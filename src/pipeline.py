from __future__ import annotations

import itertools
import json
import logging
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

from src.classconfig import ClassConfig
from src.classify import UNKNOWN, classify, classify_by_hints
from src.deadline import document_deadline
from src.extract import Extraction, Mode, extract
from src.llm import LLM, LLMError
from src.settings import Settings
from src.textextract import DocText, read_pdf

log = logging.getLogger(__name__)


@dataclass
class DocResult:
    path: Path | None
    class_name: str
    data: dict | None = None
    extraction: Extraction | None = None
    error: str | None = None
    ocr_used: bool = False
    # Czas w sekundach: całość dokumentu oraz sam odczyt tekstu (z OCR, jeśli był).
    seconds: float = 0.0
    read_seconds: float = 0.0


def process_text(
    doc: DocText,
    classes: dict[str, ClassConfig],
    llm: LLM,
    mode: Mode,
    threshold: float,
) -> DocResult:
    try:
        class_name = classify(doc, classes, llm)
    except LLMError as exc:
        class_name = classify_by_hints(doc, classes)
        if class_name == UNKNOWN:
            # Hinty nie rozstrzygają: to awaria, nie dokument spoza klas.
            raise
        log.warning("Klasyfikacja przez LLM nieudana (%s), klasa z hintów: %s", exc, class_name)
    if class_name == UNKNOWN:
        return DocResult(path=None, class_name=UNKNOWN, ocr_used=doc.ocr_used)
    extraction = extract(doc, classes[class_name], llm, mode, threshold)
    return DocResult(
        path=None,
        class_name=class_name,
        data=extraction.data,
        extraction=extraction,
        ocr_used=doc.ocr_used,
    )


def process_pdf(
    path: Path, classes: dict[str, ClassConfig], llm: LLM, settings: Settings
) -> DocResult:
    start = time.perf_counter()
    with document_deadline(settings.doc_timeout_s):
        result, read_seconds = _process_pdf(path, classes, llm, settings, start)
    result.path = path
    result.seconds = time.perf_counter() - start
    result.read_seconds = read_seconds
    return result


def _process_pdf(
    path: Path, classes: dict[str, ClassConfig], llm: LLM, settings: Settings, start: float
) -> tuple[DocResult, float]:
    read_seconds = 0.0
    try:
        doc = read_pdf(path, settings)
        read_seconds = time.perf_counter() - start
        if not doc.text.strip():
            log.warning("Pominięto %s: brak czytelnego tekstu", path)
            return DocResult(path, UNKNOWN, error="brak czytelnego tekstu w PDF"), read_seconds
        result = process_text(
            doc, classes, llm, settings.extraction_mode, settings.citation_threshold
        )
    except Exception as exc:
        log.warning("Błąd przetwarzania %s: %s", path, exc)
        return DocResult(path, UNKNOWN, error=str(exc)), read_seconds
    if result.class_name == UNKNOWN:
        log.info("Dokument nieznany (poza klasami), zapisuję pusty JSON: %s", path)
    return result, read_seconds


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _trace(result: DocResult, rel: Path) -> dict:
    ex = result.extraction
    assert ex is not None
    return {
        "source": rel.as_posix(),
        "class": result.class_name,
        "ocr_used": result.ocr_used,
        "quotes": ex.quotes,
        "citation_ok": ex.citation_ok,
        "nulled": ex.nulled,
        "warnings": ex.warnings,
        "retries": ex.retries,
        "truncated": ex.truncated,
        "seconds": round(result.seconds, 2),
        "read_seconds": round(result.read_seconds, 2),
    }


def find_pdfs(input_dir: Path) -> list[Path]:
    if not input_dir.is_dir():
        return []
    return sorted(p for p in input_dir.rglob("*") if p.is_file() and p.suffix.lower() == ".pdf")


def run_batch(
    input_dir: Path,
    output_dir: Path,
    trace_dir: Path,
    classes: dict[str, ClassConfig],
    llm: LLM,
    settings: Settings,
    workers: int = 4,
) -> list[DocResult]:
    pdfs = find_pdfs(input_dir)
    done = itertools.count(1)

    def work(pdf: Path) -> DocResult:
        result = process_pdf(pdf, classes, llm, settings)
        status = "błąd" if result.error else (result.class_name or "?")
        print(
            f"[{next(done)}/{len(pdfs)}] {pdf.relative_to(input_dir).as_posix()}: {status}",
            file=sys.stderr,
            flush=True,
        )
        return result

    with ThreadPoolExecutor(max_workers=max(workers, 1)) as pool:
        results = list(pool.map(work, pdfs))
    for pdf, result in zip(pdfs, results, strict=True):
        rel = pdf.relative_to(input_dir).with_suffix(".json")
        if result.data is not None:
            _write_json(output_dir / rel, result.data)
            _write_json(trace_dir / rel, _trace(result, rel))
        else:
            # Obcy dokument albo awaria: pusty JSON pod nazwą pliku, żeby skaner zawsze
            # znalazł plik. Awaria zostaje w `result.error`, logu i podsumowaniu CLI.
            _write_json(output_dir / rel, {})
    return results

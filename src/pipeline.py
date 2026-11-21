from __future__ import annotations

import json
import logging
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

from src.classconfig import ClassConfig
from src.classify import UNKNOWN, classify, classify_by_hints
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
    try:
        doc = read_pdf(path, settings)
        if not doc.text.strip():
            log.warning("Pominięto %s: brak czytelnego tekstu", path)
            return DocResult(path, UNKNOWN, error="brak czytelnego tekstu w PDF")
        result = process_text(
            doc, classes, llm, settings.extraction_mode, settings.citation_threshold
        )
    except Exception as exc:
        log.warning("Błąd przetwarzania %s: %s", path, exc)
        return DocResult(path, UNKNOWN, error=str(exc))
    result.path = path
    if result.class_name == UNKNOWN:
        log.info("Dokument nieznany (poza klasami), zapisuję pusty JSON: %s", path)
    return result


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
        "retries": ex.retries,
        "truncated": ex.truncated,
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
    with ThreadPoolExecutor(max_workers=max(workers, 1)) as pool:
        results = list(pool.map(lambda p: process_pdf(p, classes, llm, settings), pdfs))
    for pdf, result in zip(pdfs, results, strict=True):
        rel = pdf.relative_to(input_dir).with_suffix(".json")
        if result.data is not None:
            _write_json(output_dir / rel, result.data)
            _write_json(trace_dir / rel, _trace(result, rel))
        elif result.class_name == UNKNOWN and not result.error:
            _write_json(output_dir / rel, {})  # obcy dokument: pusty JSON pod nazwą pliku
    return results

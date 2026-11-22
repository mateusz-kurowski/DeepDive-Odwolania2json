"""Dokumenty użytkowników: PDF-y i wyniki w object storage, przetwarzanie w tle."""

from __future__ import annotations

import copy
import csv
import io
import json
import logging
import re
import tempfile
import time
import uuid
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from src.api import highlight
from src.api.storage import NotFound, Storage
from src.classconfig import ClassConfig, FieldSpec, load_classes
from src.llm import LLM
from src.pipeline import process_pdf
from src.settings import Settings

log = logging.getLogger(__name__)

PREFIX = "documents/"
STATUSES = ("ai", "edited", "approved")
_PATH_PART = re.compile(r"([^.\[\]]+)|\[(\d+)\]")


class DocumentError(Exception):
    """Błąd do pokazania użytkownikowi (kod HTTP w `status`)."""

    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _humanize(name: str) -> str:
    text = name.replace("_", " ").replace("-", " ")
    return text[:1].upper() + text[1:]


def _walk(
    data: Any,
    fields: list[FieldSpec],
    prefix: str,
    section: str | None,
    label_prefix: str,
):
    """(ścieżka, etykieta, sekcja, wartość) dla liści schematu (pola `derive` pomijamy)."""
    for spec in fields:
        if spec.derive is not None:
            continue
        value = data.get(spec.name) if isinstance(data, dict) else None
        path = f"{prefix}{spec.name}"
        label = spec.label or _humanize(spec.name)
        if spec.type == "object":
            # obiekt najwyższego poziomu to sekcja; zagnieżdżony dokleja nazwę do etykiet
            nested = f"{label_prefix}{label}: " if section else ""
            yield from _walk(value or {}, spec.fields, f"{path}.", section or label, nested)
        elif spec.type == "array":
            for i, item in enumerate(value or []):
                yield from _walk(
                    item,
                    spec.fields,
                    f"{path}[{i}].",
                    section or label,
                    f"{label_prefix}{label} {i + 1}: ",
                )
        else:
            yield path, f"{label_prefix}{label}", section, value


def build_fields(
    data: dict, quotes: dict[str, str | None], citation_ok: dict[str, bool], cfg: ClassConfig
) -> list[dict]:
    return [
        {
            "path": path,
            "label": label,
            "section": section,
            "value": value,
            "quote": quotes.get(path),
            "citation_ok": citation_ok.get(path) if value is not None else None,
            "original": value,
            "edited": False,
            "approved": False,
        }
        for path, label, section, value in _walk(data, cfg.fields, "", None, "")
    ]


def view(field: dict) -> dict:
    """Pole w postaci z kontraktu API: `status` wynika z flag `approved` i `edited`."""
    out = {k: v for k, v in field.items() if k not in ("original", "edited", "approved")}
    out["status"] = "approved" if field["approved"] else "edited" if field["edited"] else "ai"
    return out


def set_path(data: dict, path: str, value: Any) -> None:
    node: Any = data
    parts = [(m.group(1), m.group(2)) for m in _PATH_PART.finditer(path)]
    for i, (key, idx) in enumerate(parts):
        last = i == len(parts) - 1
        try:
            if key is not None:
                if last:
                    node[key] = value
                else:
                    node = node[key]
            else:
                if last:
                    node[int(idx)] = value
                else:
                    node = node[int(idx)]
        except (KeyError, IndexError, TypeError):
            raise DocumentError(f"Nieznana ścieżka pola: {path}", 404) from None


def _coerce(original: Any, value: Any) -> Any:
    if isinstance(value, str):
        value = value.strip()
        if value == "":
            return None
        if isinstance(original, bool):
            return value
        if isinstance(original, int | float):
            try:
                number = float(value.replace(",", ".").replace(" ", ""))
            except ValueError:
                return value
            return int(number) if isinstance(original, int) and number.is_integer() else number
    return value


class DocumentService:
    def __init__(
        self,
        storage: Storage,
        settings: Settings,
        llm_factory: Callable[[Settings], LLM],
        max_upload_mb: int = 25,
        workers: int = 2,
    ):
        self.storage = storage
        self.settings = settings
        self.llm_factory = llm_factory
        self.max_upload_bytes = max_upload_mb * 1024 * 1024
        self._pool = ThreadPoolExecutor(max_workers=max(workers, 1), thread_name_prefix="doc")
        self._llm: LLM | None = None

    # --- klucze -----------------------------------------------------------------------------
    @staticmethod
    def _key(doc_id: str, name: str) -> str:
        if not re.fullmatch(r"[0-9a-f]{32}", doc_id):
            raise DocumentError("Nie znaleziono dokumentu.", 404)
        return f"{PREFIX}{doc_id}/{name}"

    def _read_json(self, doc_id: str, name: str) -> dict:
        try:
            return json.loads(self.storage.get(self._key(doc_id, name)))
        except NotFound:
            raise DocumentError("Nie znaleziono dokumentu.", 404) from None

    def _write_json(self, doc_id: str, name: str, payload: dict) -> None:
        self.storage.put(
            self._key(doc_id, name),
            json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            "application/json",
        )

    def _meta(self, doc_id: str) -> dict:
        return self._read_json(doc_id, "meta.json")

    def _result(self, doc_id: str) -> dict | None:
        try:
            return self._read_json(doc_id, "result.json")
        except DocumentError:
            return None

    # --- wysyłanie i przetwarzanie ------------------------------------------------------------
    def validate_upload(self, filename: str, content: bytes) -> str:
        name = Path(filename or "dokument.pdf").name
        if not name.lower().endswith(".pdf"):
            raise DocumentError(f"{name}: dozwolone są tylko pliki PDF.", 415)
        if not content.startswith(b"%PDF"):
            raise DocumentError(f"{name}: to nie jest poprawny plik PDF.", 415)
        if len(content) > self.max_upload_bytes:
            raise DocumentError(
                f"{name}: plik większy niż {self.max_upload_bytes // 1024 // 1024} MB.", 413
            )
        return name

    def add(self, filename: str, content: bytes) -> dict:
        name = self.validate_upload(filename, content)
        doc_id = uuid.uuid4().hex
        self.storage.put(self._key(doc_id, "source.pdf"), content, "application/pdf")
        self._write_json(
            doc_id,
            "meta.json",
            {"id": doc_id, "filename": name, "status": "queued", "created_at": _now()},
        )
        self._pool.submit(self._process, doc_id)
        return {"id": doc_id, "filename": name, "status": "queued"}

    def resume(self) -> None:
        """Po restarcie: dokumenty `queued`/`processing` wracają do kolejki."""
        for key in self.storage.list(PREFIX):
            if key.endswith("/meta.json"):
                meta = json.loads(self.storage.get(key))
                if meta.get("status") in ("queued", "processing"):
                    self._pool.submit(self._process, meta["id"])

    def reprocess(self, doc_id: str) -> dict:
        meta = self._meta(doc_id)
        meta.update(status="queued", error=None)
        self._write_json(doc_id, "meta.json", meta)
        self.storage.delete(self._key(doc_id, "result.json"))
        self.storage.delete(self._key(doc_id, "highlights.json"))
        self._pool.submit(self._process, doc_id)
        return self.summary(doc_id)

    def _get_llm(self) -> LLM:
        if self._llm is None:
            self._llm = self.llm_factory(self.settings)
        return self._llm

    def _process(self, doc_id: str) -> None:
        started = time.monotonic()
        try:
            meta = self._meta(doc_id)
            meta["status"] = "processing"
            self._write_json(doc_id, "meta.json", meta)
            classes = load_classes(self.settings.classes_dir)
            pdf = self.storage.get(self._key(doc_id, "source.pdf"))
            with tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / "source.pdf"
                path.write_bytes(pdf)
                result = process_pdf(path, classes, self._get_llm(), self.settings)
            meta.update(
                duration_s=round(time.monotonic() - started, 1),
                class_name=result.class_name,
                ocr_used=result.ocr_used,
                model=self.settings.llm_model,
                pages=highlight.page_count(pdf),
                error=result.error,
            )
            if result.error:
                meta["status"] = "error"
            else:
                fields: list[dict] = []
                data: dict = {}
                if result.extraction is not None:
                    ex = result.extraction
                    data = ex.data
                    fields = build_fields(
                        data, ex.quotes, ex.citation_ok, classes[result.class_name]
                    )
                self._write_json(
                    doc_id,
                    "result.json",
                    {"class_name": result.class_name, "data": data, "fields": fields},
                )
                meta["status"] = "done"
            self._write_json(doc_id, "meta.json", meta)
        except Exception as exc:  # awaria jednego dokumentu nie zatrzymuje reszty
            log.exception("Przetwarzanie %s nieudane", doc_id)
            try:
                meta = self._meta(doc_id)
                meta.update(status="error", error=f"{type(exc).__name__}: {exc}")
                self._write_json(doc_id, "meta.json", meta)
            except Exception:
                log.exception("Nie zapisano statusu błędu dla %s", doc_id)

    # --- odczyt ------------------------------------------------------------------------------
    def summary(self, doc_id: str) -> dict:
        meta = self._meta(doc_id)
        result = self._result(doc_id) if meta.get("status") == "done" else None
        fields = [view(f) for f in (result or {}).get("fields", []) if f["value"] is not None]
        cited = [f for f in fields if f["citation_ok"] is not None]
        return {
            "id": meta["id"],
            "filename": meta["filename"],
            "status": meta["status"],
            "class_name": meta.get("class_name"),
            "label": meta["filename"],
            "created_at": meta["created_at"],
            "duration_s": meta.get("duration_s"),
            "citation_ok_rate": (sum(f["citation_ok"] for f in cited) / len(cited))
            if cited
            else None,
            "needs_review": any(f["citation_ok"] is False and f["status"] == "ai" for f in fields),
            "approved_count": sum(f["status"] == "approved" for f in fields),
            "field_count": len(fields),
            "error": meta.get("error"),
        }

    def list(self, q: str = "", status: str = "", needs_review: bool | None = None) -> dict:
        items = []
        for key in self.storage.list(PREFIX):
            if key.endswith("/meta.json"):
                try:
                    items.append(self.summary(key.split("/")[1]))
                except DocumentError:
                    continue
        items.sort(key=lambda s: s["created_at"], reverse=True)
        total = len(items)
        done = [s for s in items if s["status"] == "done"]
        summary = {
            "total": total,
            "processed": len(done),
            "needs_review_rate": (sum(s["needs_review"] for s in done) / len(done))
            if done
            else None,
            "avg_citation_ok_rate": _mean([s["citation_ok_rate"] for s in done]),
            "avg_duration_s": _mean([s["duration_s"] for s in done]),
        }
        q = q.strip().casefold()
        if q:
            items = [s for s in items if q in s["filename"].casefold()]
        if status:
            items = [s for s in items if s["status"] == status]
        if needs_review is not None:
            items = [s for s in items if s["needs_review"] == needs_review]
        return {"items": items, "summary": summary}

    def get(self, doc_id: str) -> dict:
        meta = self._meta(doc_id)
        out = self.summary(doc_id)
        result = self._result(doc_id)
        out.update(
            ocr_used=meta.get("ocr_used", False),
            model=meta.get("model", ""),
            pages=meta.get("pages", 0),
            fields=[],
            data={},
        )
        if result:
            marks = self._highlights(doc_id, meta, result["fields"])
            names = self._labels(result)
            fields = [
                {**view(f), **names.get(f["path"], {}), "highlights": marks.get(f["path"], [])}
                for f in result["fields"]
            ]
            out.update(fields=fields, data=self._current_data(result))
        return out

    def _labels(self, result: dict) -> dict[str, dict]:
        """Etykiety i sekcje z bieżącego YAML-a klasy (zmiana `label` działa bez reprocessingu)."""
        try:
            cfg = load_classes(self.settings.classes_dir).get(result.get("class_name") or "")
        except Exception:  # zepsuty YAML nie może blokować podglądu dokumentu
            return {}
        if cfg is None:
            return {}
        return {
            path: {"label": label, "section": section}
            for path, label, section, _ in _walk(result.get("data") or {}, cfg.fields, "", None, "")
        }

    def _highlights(self, doc_id: str, meta: dict, fields: list[dict]) -> dict[str, list[dict]]:
        try:
            return self._read_json(doc_id, "highlights.json")
        except DocumentError:
            pass
        if meta.get("ocr_used"):
            marks: dict[str, list[dict]] = {}
        else:
            marks = highlight.locate_quotes(
                self.pdf(doc_id), {f["path"]: f["quote"] for f in fields if f["quote"]}
            )
        self._write_json(doc_id, "highlights.json", marks)
        return marks

    def pdf(self, doc_id: str) -> bytes:
        try:
            return self.storage.get(self._key(doc_id, "source.pdf"))
        except NotFound:
            raise DocumentError("Nie znaleziono dokumentu.", 404) from None

    def page_png(self, doc_id: str, number: int, width: int) -> bytes:
        try:
            return highlight.render_page(self.pdf(doc_id), number, width)
        except IndexError:
            raise DocumentError("Nie ma takiej strony.", 404) from None
        except highlight.DocumentTooLarge as exc:
            raise DocumentError(f"Nie można wyrenderować strony: {exc}.", 422) from None

    # --- korekty -----------------------------------------------------------------------------
    @staticmethod
    def _current_data(result: dict) -> dict:
        data = copy.deepcopy(result["data"])
        for f in result["fields"]:
            if f["edited"]:
                set_path(data, f["path"], f["value"])
        return data

    def update_field(
        self,
        doc_id: str,
        path: str,
        value: Any = None,
        status: str | None = None,
        has_value: bool = False,
        revert: bool = False,
    ) -> dict:
        if status is not None and status not in STATUSES:
            raise DocumentError("Niepoprawny status pola.", 422)
        result = self._result(doc_id)
        if result is None:
            raise DocumentError("Dokument nie jest jeszcze przetworzony.", 409)
        field = next((f for f in result["fields"] if f["path"] == path), None)
        if field is None:
            raise DocumentError(f"Nieznane pole: {path}", 404)
        if revert:  # wartość z modelu, bez zatwierdzenia
            field.update(value=field["original"], edited=False, approved=False)
        if has_value:
            field["value"] = _coerce(field["original"], value)
            field["edited"] = field["value"] != field["original"]
            field["approved"] = False
        if status is not None and not revert:
            field["approved"] = status == "approved"
        self._write_json(doc_id, "result.json", result)
        marks = self._highlights(doc_id, self._meta(doc_id), result["fields"])
        return {**view(field), "highlights": marks.get(path, [])}

    def approve_all(self, doc_id: str) -> dict:
        result = self._result(doc_id)
        if result is None:
            raise DocumentError("Dokument nie jest jeszcze przetworzony.", 409)
        for f in result["fields"]:
            if f["value"] is not None:
                f["approved"] = True
        self._write_json(doc_id, "result.json", result)
        return self.summary(doc_id)

    def delete(self, doc_id: str) -> None:
        self._meta(doc_id)
        for key in self.storage.list(f"{PREFIX}{doc_id}/"):
            self.storage.delete(key)

    def delete_all(self) -> None:
        for key in self.storage.list(PREFIX):
            self.storage.delete(key)

    # --- eksport -----------------------------------------------------------------------------
    def export_data(self, doc_id: str) -> tuple[str, dict]:
        meta = self._meta(doc_id)
        result = self._result(doc_id)
        if result is None:
            raise DocumentError(f"{meta['filename']}: brak wyniku do eksportu.", 409)
        return meta["filename"], self._current_data(result)

    def export(self, ids: list[str], fmt: str) -> tuple[bytes, str, str]:
        rows = []
        for doc_id in ids:
            filename, data = self.export_data(doc_id)
            rows.append(
                {"file": filename, "class": self._meta(doc_id).get("class_name"), "data": data}
            )
        if fmt == "json":
            body = json.dumps(rows, ensure_ascii=False, indent=2).encode("utf-8")
            return body, "application/json", "dokumenty.json"
        if fmt == "jsonl":
            body = "\n".join(json.dumps(r, ensure_ascii=False) for r in rows).encode("utf-8")
            return body, "application/x-ndjson", "dokumenty.jsonl"
        if fmt == "csv":
            buf = io.StringIO()
            writer = csv.writer(buf)
            writer.writerow(["file", "class", "path", "value"])
            for row in rows:
                for path, value in _flat(row["data"]):
                    cells = (row["file"], row["class"], path, "" if value is None else value)
                    writer.writerow([_csv_safe(c) for c in cells])
            return buf.getvalue().encode("utf-8-sig"), "text/csv", "dokumenty.csv"
        raise DocumentError("Format eksportu: json, jsonl lub csv.", 422)


def _csv_safe(cell: Any) -> Any:
    """Komórka zaczynająca się od = + - @ (lub tab/CR) byłaby formułą w arkuszu."""
    if isinstance(cell, str) and cell[:1] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + cell
    return cell


def _mean(values: list[float | None]) -> float | None:
    nums = [v for v in values if v is not None]
    return sum(nums) / len(nums) if nums else None


def _flat(data: Any, prefix: str = ""):
    if isinstance(data, dict):
        for k, v in data.items():
            yield from _flat(v, f"{prefix}{k}." if isinstance(v, dict) else f"{prefix}{k}")
    elif isinstance(data, list):
        for i, v in enumerate(data):
            yield from _flat(v, f"{prefix}[{i}]." if isinstance(v, dict) else f"{prefix}[{i}]")
    else:
        yield prefix.rstrip("."), data

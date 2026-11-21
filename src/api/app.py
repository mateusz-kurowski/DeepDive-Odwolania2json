"""FastAPI: dokumenty (object storage), schematy (YAML), ewaluacja. Kontrakt: docs/api.md."""

from __future__ import annotations

import json
import logging
import os
import re
from collections.abc import Callable, Mapping
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, Any, Literal
from urllib.parse import quote

from fastapi import APIRouter, FastAPI, File, Request, UploadFile
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel

from src.api.classes import ClassesError, ClassStore
from src.api.documents import DocumentError, DocumentService
from src.api.evaluation import EvaluationError, EvaluationService
from src.api.storage import Storage, make_storage
from src.llm import LLM, OpenAICompatLLM
from src.pipeline import find_pdfs
from src.settings import Settings

log = logging.getLogger(__name__)


class FieldPatch(BaseModel):
    path: str
    value: Any = None
    status: Literal["ai", "edited", "approved"] | None = None
    revert: bool = False  # przywróć wartość z modelu (cofnięcie edycji)


class ExportRequest(BaseModel):
    ids: list[str]
    format: Literal["json", "jsonl", "csv"] = "json"


class ClassBody(BaseModel):
    yaml: str


class RunRequest(BaseModel):
    dataset: str
    model: str | None = None
    mode: Literal["hybrid", "llm_only"] | None = None
    limit: int | None = None


def _download(body: bytes, media_type: str, filename: str) -> Response:
    ascii_name = re.sub(r"[^A-Za-z0-9._-]", "_", filename) or "plik"
    disposition = (
        f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(filename, safe='')}"
    )
    return Response(body, media_type=media_type, headers={"Content-Disposition": disposition})


MAX_FILES = 50


async def _read_limited(file: UploadFile, limit: int) -> bytes:
    """Czyta plik kawałkami i przerywa po przekroczeniu limitu (bez alokacji całości)."""
    chunks, size = [], 0
    while chunk := await file.read(1024 * 1024):
        size += len(chunk)
        if size > limit:
            raise DocumentError(
                f"{file.filename}: plik większy niż {limit // 1024 // 1024} MB.", 413
            )
        chunks.append(chunk)
    return b"".join(chunks)


def create_app(
    settings: Settings | None = None,
    storage: Storage | None = None,
    llm_factory: Callable[[Settings], LLM] | None = None,
    env: Mapping[str, str] | None = None,
) -> FastAPI:
    env = os.environ if env is None else env
    settings = settings or Settings.from_env(env if env is not os.environ else None)
    storage = storage or make_storage(env)
    llm_factory = llm_factory or OpenAICompatLLM
    max_upload_mb = int(env.get("MAX_UPLOAD_MB") or 25)
    samples_dir = Path(env.get("SAMPLES_DIR") or "data/szablon-aplikacja/input")

    documents = DocumentService(
        storage, settings, llm_factory, max_upload_mb, int(env.get("DOC_WORKERS") or 2)
    )
    evaluations = EvaluationService(
        storage,
        settings,
        llm_factory,
        Path(env.get("EVAL_DATASETS") or "config/eval-datasets.yaml"),
        Path(env.get("RESULTS_DIR") or "results"),
    )
    class_store = ClassStore(settings.classes_dir)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        documents.resume()
        evaluations.resume()
        yield

    app = FastAPI(title="Odwołania2JSON API", lifespan=lifespan)

    @app.exception_handler(DocumentError)
    @app.exception_handler(EvaluationError)
    @app.exception_handler(ClassesError)
    async def _domain_error(_: Request, exc: Exception) -> JSONResponse:
        return JSONResponse({"detail": str(exc)}, status_code=getattr(exc, "status", 400))

    api = APIRouter(prefix="/api")

    @api.get("/health")
    def health() -> dict:
        return {"status": "ok", "storage": storage.backend, "model": settings.llm_model}

    @api.get("/settings")
    def get_settings() -> dict:
        return {
            "llm_model": settings.llm_model,
            "extraction_mode": settings.extraction_mode,
            "ocr_backend": settings.ocr_backend,
            "vlm_model": settings.vlm_model,
            "openai_base_url": settings.openai_base_url,
            "storage_backend": storage.backend,
            "bucket": storage.bucket,
            "max_upload_mb": max_upload_mb,
            "classes": [c["name"] for c in class_store.list()],
        }

    # --- dokumenty ---------------------------------------------------------------------------
    @api.post("/documents", status_code=201)
    async def upload(files: Annotated[list[UploadFile], File()]) -> list[dict]:
        if len(files) > MAX_FILES:
            raise DocumentError(f"Najwyżej {MAX_FILES} plików naraz.", 413)
        contents = [
            (f.filename or "", await _read_limited(f, documents.max_upload_bytes)) for f in files
        ]
        for name, content in contents:  # walidacja wszystkiego przed zapisem czegokolwiek
            documents.validate_upload(name, content)
        return [documents.add(name, content) for name, content in contents]

    @api.post("/documents/samples", status_code=201)
    def samples() -> list[dict]:
        pdfs = find_pdfs(samples_dir)
        if not pdfs:
            raise DocumentError("Brak przykładowych dokumentów na serwerze.", 404)
        return [documents.add(p.name, p.read_bytes()) for p in pdfs]

    @api.get("/documents")
    def list_documents(q: str = "", status: str = "", needs_review: bool | None = None) -> dict:
        return documents.list(q, status, needs_review)

    @api.delete("/documents", status_code=204)
    def delete_all() -> Response:
        documents.delete_all()
        return Response(status_code=204)

    @api.post("/documents/export")
    def export_many(body: ExportRequest) -> Response:
        return _download(*documents.export(body.ids, body.format))

    @api.get("/documents/{doc_id}")
    def get_document(doc_id: str) -> dict:
        return documents.get(doc_id)

    @api.get("/documents/{doc_id}/pdf")
    def get_pdf(doc_id: str) -> Response:
        return Response(documents.pdf(doc_id), media_type="application/pdf")

    @api.get("/documents/{doc_id}/pages/{number}.png")
    def get_page(doc_id: str, number: int, width: int = 900) -> Response:
        width = min(max(width, 200), 2400)
        return Response(documents.page_png(doc_id, number, width), media_type="image/png")

    @api.patch("/documents/{doc_id}/fields")
    def patch_field(doc_id: str, body: FieldPatch) -> dict:
        return documents.update_field(
            doc_id,
            body.path,
            body.value,
            body.status,
            "value" in body.model_fields_set,
            body.revert,
        )

    @api.post("/documents/{doc_id}/approve-all")
    def approve_all(doc_id: str) -> dict:
        return documents.approve_all(doc_id)

    @api.post("/documents/{doc_id}/reprocess", status_code=202)
    def reprocess(doc_id: str) -> dict:
        return documents.reprocess(doc_id)

    @api.delete("/documents/{doc_id}", status_code=204)
    def delete_document(doc_id: str) -> Response:
        documents.delete(doc_id)
        return Response(status_code=204)

    @api.get("/documents/{doc_id}/export")
    def export_one(doc_id: str) -> Response:
        filename, data = documents.export_data(doc_id)
        stem = Path(filename).stem
        return _download(
            json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8"),
            "application/json",
            f"{stem}.json",
        )

    # --- schematy ----------------------------------------------------------------------------
    @api.get("/classes")
    def list_classes() -> list[dict]:
        return class_store.list()

    @api.get("/classes/{name}")
    def get_class(name: str) -> dict:
        return class_store.get(name)

    @api.put("/classes/{name}")
    def put_class(name: str, body: ClassBody) -> dict:
        return class_store.put(name, body.yaml)

    @api.delete("/classes/{name}", status_code=204)
    def delete_class(name: str) -> Response:
        class_store.delete(name)
        return Response(status_code=204)

    # --- ewaluacja ---------------------------------------------------------------------------
    @api.get("/evaluation/datasets")
    def eval_datasets() -> list[dict]:
        return evaluations.datasets()

    @api.get("/evaluation/runs")
    def eval_runs() -> list[dict]:
        return evaluations.list_runs()

    @api.post("/evaluation/runs", status_code=202)
    def eval_start(body: RunRequest) -> dict:
        return evaluations.start(body.dataset, body.model, body.mode, body.limit)

    @api.get("/evaluation/runs/{run_id}")
    def eval_run(run_id: str) -> dict:
        return evaluations.get_run(run_id)

    @api.get("/evaluation/runs/{run_id}/documents")
    def eval_documents(run_id: str) -> list[dict]:
        return evaluations.documents(run_id)

    @api.get("/evaluation/runs/{run_id}/documents/{label}/{stem}")
    def eval_document(run_id: str, label: str, stem: str) -> dict:
        return evaluations.read_document(run_id, label, stem)

    app.include_router(api)
    return app

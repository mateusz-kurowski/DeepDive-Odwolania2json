from __future__ import annotations

import time
from pathlib import Path

import pytest
from conftest import DEMO_TEXT, classification, extraction
from fastapi.testclient import TestClient

from src import pipeline
from src.api.app import create_app
from src.api.storage import LocalStorage
from src.settings import Settings
from src.textextract import DocText

SAMPLE_PDF = Path("data/dane/przyklad_01/przelew.pdf")


@pytest.fixture
def pdf_bytes() -> bytes:
    if not SAMPLE_PDF.is_file():
        pytest.skip("brak przykładowego PDF w data/dane")
    return SAMPLE_PDF.read_bytes()


@pytest.fixture
def make_client(tmp_path, demo_classes, fake_llm, monkeypatch):
    monkeypatch.setattr(
        pipeline, "read_pdf", lambda path, settings=None: DocText(DEMO_TEXT, 1, False)
    )

    def make(responses=None, env=None, **kw) -> TestClient:
        responses = responses if responses is not None else [classification(), extraction()] * 5
        llm = fake_llm(responses)
        settings = Settings(llm_model="m", classes_dir=demo_classes[0])
        app = create_app(
            settings=settings,
            storage=LocalStorage(tmp_path / "storage"),
            llm_factory=lambda s: llm,
            env={
                "RESULTS_DIR": str(tmp_path / "results"),
                "EVAL_DATASETS": str(tmp_path / "datasets.yaml"),
                "DOC_WORKERS": "1",
                **(env or {}),
            },
            **kw,
        )
        client = TestClient(app)
        client.llm = llm
        return client

    return make


@pytest.fixture
def client(make_client):
    with make_client() as c:
        yield c


def wait_for(client: TestClient, doc_id: str, status="done", timeout=10.0) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        doc = client.get(f"/api/documents/{doc_id}").json()
        if doc["status"] in (status, "error"):
            return doc
        time.sleep(0.05)
    raise AssertionError(f"dokument {doc_id} nie osiągnął statusu {status}")

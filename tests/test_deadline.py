import json
import time

import pytest
from conftest import DEMO_TEXT, classification, extraction
from test_llm import SCHEMA, make, rate_limit

from src import deadline, pipeline
from src.evaluate import evaluate
from src.llm import LLMError
from src.settings import Settings
from src.textextract import DocText


def test_no_deadline_by_default():
    assert deadline.remaining() is None
    assert deadline.request_timeout(180) == 180


def test_deadline_caps_request_timeout_and_restores():
    with deadline.document_deadline(10):
        assert 9 < deadline.request_timeout(180) <= 10
        with deadline.document_deadline(None):
            assert deadline.remaining() is None
        assert deadline.remaining() is not None
    assert deadline.remaining() is None


def test_expired_deadline_raises():
    with deadline.document_deadline(0.5), pytest.raises(deadline.DeadlineExceeded):
        deadline.check()


def test_llm_sends_timeout_only_with_deadline():
    llm, client, _ = make(['{"a": 1}', '{"a": 1}'])
    llm.complete_json("s", "u", SCHEMA, "demo")
    assert "timeout" not in client.kwargs[0]
    with deadline.document_deadline(30):
        llm.complete_json("s", "u", SCHEMA, "demo")
    assert 0 < client.kwargs[1]["timeout"] <= 30


def test_llm_stops_retrying_after_deadline():
    llm, client, _ = make([rate_limit(), '{"a": 1}'])
    # Sztuczne „zużycie” czasu przez sleep: po pierwszej próbie limit jest przekroczony.
    llm.sleep = lambda s: time.sleep(1.2)
    with deadline.document_deadline(2), pytest.raises(LLMError, match="limit czasu"):
        llm.complete_json("s", "u", SCHEMA, "demo")
    assert len(client.kwargs) == 1


def test_process_pdf_records_time(tmp_path, demo_classes, fake_llm, monkeypatch):
    monkeypatch.setattr(
        pipeline, "read_pdf", lambda path, settings=None: DocText(DEMO_TEXT, 1, False)
    )
    pdf = tmp_path / "a.pdf"
    pdf.write_bytes(b"%PDF")
    result = pipeline.process_pdf(
        pdf, demo_classes[1], fake_llm([classification(), extraction()]), Settings(llm_model="m")
    )
    assert result.seconds >= result.read_seconds >= 0
    assert result.path == pdf


def test_eval_counts_negatives(tmp_path, demo_classes, fake_llm, monkeypatch):
    monkeypatch.setattr(
        pipeline, "read_pdf", lambda path, settings=None: DocText(DEMO_TEXT, 1, False)
    )
    neg = tmp_path / "dane" / "negatywne"
    neg.mkdir(parents=True)
    (neg / "obcy1.pdf").write_bytes(b"%PDF")
    (neg / "obcy2.pdf").write_bytes(b"%PDF")
    # obcy1 odrzucony (nieznany), obcy2 błędnie przyjęty jako `demo`.
    llm = fake_llm([classification("nieznany"), classification(), extraction()])
    report = evaluate(tmp_path / "dane", demo_classes[1], llm, Settings(llm_model="m"), workers=1)
    d = report.to_dict()
    assert d["negatives_total"] == 2
    assert d["negatives_accepted"] == 1
    assert d["negatives_rejected_rate"] == 0.5
    assert d["accepted_files"] == ["negatywne/obcy2.pdf → demo"]
    assert d["timing"]["pdfs"] == 2
    assert "negatywy odrzucone" in report.render()


def test_eval_negative_inside_example(tmp_path, demo_classes, fake_llm, monkeypatch):
    monkeypatch.setattr(
        pipeline, "read_pdf", lambda path, settings=None: DocText(DEMO_TEXT, 1, False)
    )
    ex = tmp_path / "dane" / "przyklad_01"
    ex.mkdir(parents=True)
    (ex / "a_demo.pdf").write_bytes(b"%PDF")
    (ex / "b_obcy.pdf").write_bytes(b"%PDF")
    (ex / "demo.json").write_text(
        json.dumps({"nip": "5270000000", "tytul": "Budowa drogi"}), encoding="utf-8"
    )
    llm = fake_llm([classification(), extraction(), classification("nieznany")])
    report = evaluate(tmp_path / "dane", demo_classes[1], llm, Settings(llm_model="m"), workers=1)
    assert report.negatives_total == 1 and report.negatives_accepted == 0
    assert report.micro_f1 == 1.0

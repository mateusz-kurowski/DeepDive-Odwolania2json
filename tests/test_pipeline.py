import json
import logging

import pytest
from conftest import DEMO_TEXT, classification, extraction

from src import pipeline
from src.llm import LLMError
from src.settings import Settings
from src.textextract import DocText

SETTINGS = Settings(openai_api_key="k", llm_model="m")


@pytest.fixture(autouse=True)
def fake_pdf_reader(monkeypatch):
    def read(path, settings=None):
        if "pusty" in path.stem:
            return DocText(text="", pages=1, ocr_used=False)
        return DocText(text=DEMO_TEXT, pages=1, ocr_used=False)

    monkeypatch.setattr(pipeline, "read_pdf", read)


def touch(base, *relative):
    path = base.joinpath(*relative)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"%PDF-1.4")
    return path


def batch(tmp_path, classes, llm, settings=SETTINGS):
    return pipeline.run_batch(
        tmp_path / "input",
        tmp_path / "output",
        tmp_path / "trace",
        classes,
        llm,
        settings,
        workers=1,
    )


def test_writes_json_with_same_stem_and_structure(tmp_path, demo_classes, fake_llm):
    touch(tmp_path / "input", "case1", "Mój plik ąę.PDF")
    llm = fake_llm([classification(), extraction()])
    results = batch(tmp_path, demo_classes[1], llm)
    out = tmp_path / "output" / "case1" / "Mój plik ąę.json"
    assert out.exists()
    assert json.loads(out.read_text(encoding="utf-8")) == {
        "nip": "5270000000",
        "tytul": "Budowa drogi",
    }
    assert results[0].class_name == "demo" and results[0].error is None


def test_unknown_writes_empty_json_with_same_name_and_logs(
    tmp_path, demo_classes, fake_llm, caplog
):
    touch(tmp_path / "input", "case1", "Obcy plik.pdf")
    with caplog.at_level(logging.INFO):
        results = batch(tmp_path, demo_classes[1], fake_llm([classification("nieznany")]))
    out = tmp_path / "output" / "case1" / "Obcy plik.json"
    assert json.loads(out.read_text(encoding="utf-8")) == {}
    assert not (tmp_path / "trace" / "case1" / "Obcy plik.json").exists()
    assert "nieznany" in caplog.text
    assert results[0].class_name == "nieznany" and results[0].error is None


def test_failed_document_writes_empty_json(tmp_path, demo_classes, fake_llm):
    touch(tmp_path / "input", "case1", "a.pdf")
    from src.llm import LLMError

    class Boom:
        def complete_json(self, *a, **k):
            raise LLMError("model niedostępny")

    results = batch(tmp_path, demo_classes[1], Boom())
    assert results[0].error
    out = tmp_path / "output" / "case1" / "a.json"
    assert json.loads(out.read_text(encoding="utf-8")) == {}
    assert not (tmp_path / "trace" / "case1" / "a.json").exists()


def test_non_pdf_ignored(tmp_path, demo_classes, fake_llm):
    touch(tmp_path / "input", "case1", "a.pdf")
    (tmp_path / "input" / "case1" / "notatki.txt").write_text("x")
    results = batch(tmp_path, demo_classes[1], fake_llm([classification(), extraction()]))
    assert len(results) == 1
    assert [p.name for p in (tmp_path / "output" / "case1").iterdir()] == ["a.json"]


def test_llm_failure_on_one_file_does_not_stop_batch(tmp_path, demo_classes, fake_llm):
    touch(tmp_path / "input", "case1", "a.pdf")
    touch(tmp_path / "input", "case1", "b.pdf")
    llm = fake_llm([classification(), LLMError("429"), classification(), extraction()])
    results = batch(tmp_path, demo_classes[1], llm)
    assert results[0].error is not None and "429" in results[0].error
    assert results[1].error is None
    assert (tmp_path / "output" / "case1" / "b.json").exists()
    assert json.loads((tmp_path / "output" / "case1" / "a.json").read_text("utf-8")) == {}


def test_unreadable_pdf_skipped_with_log(tmp_path, demo_classes, fake_llm, caplog):
    touch(tmp_path / "input", "case1", "pusty.pdf")
    touch(tmp_path / "input", "case1", "b.pdf")
    with caplog.at_level(logging.WARNING):
        results = batch(tmp_path, demo_classes[1], fake_llm([classification(), extraction()]))
    by_name = {r.path.name: r for r in results}
    assert by_name["pusty.pdf"].error and "tekst" in by_name["pusty.pdf"].error
    assert by_name["b.pdf"].error is None
    assert "pusty.pdf" in caplog.text
    assert (tmp_path / "output" / "case1" / "pusty.json").read_text("utf-8").strip() == "{}"
    assert (tmp_path / "output" / "case1" / "b.json").exists()


def test_trace_written_outside_output(tmp_path, demo_classes, fake_llm):
    touch(tmp_path / "input", "case1", "a.pdf")
    batch(tmp_path, demo_classes[1], fake_llm([classification(), extraction()]))
    trace = json.loads((tmp_path / "trace" / "case1" / "a.json").read_text(encoding="utf-8"))
    assert trace["class"] == "demo"
    assert trace["quotes"]["nip"] == "527-000-00-00"
    assert trace["citation_ok"]["nip"] is True
    assert {"nulled", "retries", "truncated"} <= set(trace)
    assert all(p.suffix == ".json" for p in (tmp_path / "output").rglob("*") if p.is_file())
    assert not (tmp_path / "output" / "case1" / "a.trace.json").exists()


def test_rerun_is_idempotent(tmp_path, demo_classes, fake_llm):
    touch(tmp_path / "input", "case1", "a.pdf")
    llm = fake_llm([classification(), extraction(), classification(), extraction()])
    batch(tmp_path, demo_classes[1], llm)
    batch(tmp_path, demo_classes[1], llm)
    assert json.loads((tmp_path / "output" / "case1" / "a.json").read_text())["nip"] == "5270000000"


def test_same_stem_in_two_cases_does_not_collide(tmp_path, demo_classes, fake_llm):
    touch(tmp_path / "input", "case1", "a.pdf")
    touch(tmp_path / "input", "case2", "a.pdf")
    batch(
        tmp_path,
        demo_classes[1],
        fake_llm([classification(), extraction(), classification(), extraction()]),
    )
    assert (tmp_path / "output" / "case1" / "a.json").exists()
    assert (tmp_path / "output" / "case2" / "a.json").exists()


def test_llm_only_mode_leaves_raw_value(tmp_path, demo_classes, fake_llm):
    touch(tmp_path / "input", "case1", "a.pdf")
    settings = SETTINGS.model_copy(update={"extraction_mode": "llm_only"})
    batch(tmp_path, demo_classes[1], fake_llm([classification(), extraction()]), settings)
    assert (
        json.loads((tmp_path / "output" / "case1" / "a.json").read_text())["nip"] == "527-000-00-00"
    )


def test_write_json_keeps_polish_characters(tmp_path):
    target = tmp_path / "x" / "a.json"
    pipeline._write_json(target, {"nazwa": "Zażółć gęślą jaźń"})
    assert "Zażółć gęślą jaźń" in target.read_text(encoding="utf-8")


HINTED_CLASSES_YAML = {
    "alfa": "name: alfa\ndescription: Dokument alfa\nhints: [ALFA]\nfields:\n  - {name: nip, type: text}\n",
    "beta": "name: beta\ndescription: Dokument beta\nhints: [BETA]\nfields:\n  - {name: nip, type: text}\n",
}


def hinted_classes(tmp_path):
    from src.classconfig import load_classes

    directory = tmp_path / "hinted"
    directory.mkdir()
    for name, body in HINTED_CLASSES_YAML.items():
        (directory / f"{name}.yaml").write_text(body, encoding="utf-8")
    return load_classes(directory)


def test_classification_failure_falls_back_to_hints(tmp_path, fake_llm):
    classes = hinted_classes(tmp_path)
    doc = DocText(text="ALFA dokument, NIP 527-000-00-00", pages=1, ocr_used=False)
    llm = fake_llm([LLMError("pusta odpowiedź"), {"nip": {"value": None, "quote": None}}])
    result = pipeline.process_text(doc, classes, llm, "hybrid", 85)
    assert result.class_name == "alfa"
    assert result.error is None
    assert len(llm.calls) == 2


def test_classification_failure_with_ambiguous_hints_stays_an_error(tmp_path, fake_llm):
    classes = hinted_classes(tmp_path)
    doc = DocText(text="ALFA i BETA naraz", pages=1, ocr_used=False)
    with pytest.raises(LLMError):
        pipeline.process_text(doc, classes, fake_llm([LLMError("x")]), "hybrid", 85)

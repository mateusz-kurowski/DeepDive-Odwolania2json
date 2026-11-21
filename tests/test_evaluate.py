import json

import pytest

from odwolania2json import evaluate as ev
from odwolania2json.classconfig import ClassConfig
from odwolania2json.evaluate import Counts, Report, evaluate, flatten, score_document
from odwolania2json.settings import Settings

from conftest import classification

CFG = ClassConfig.model_validate(
    {
        "name": "demo",
        "description": "d",
        "fields": [
            {"name": "tytul", "type": "text"},
            {"name": "data", "type": "text", "validator": "date"},
            {"name": "kwota", "type": "number"},
            {
                "name": "osoby",
                "type": "array",
                "key": ["krs", "dane.nip"],
                "fields": [
                    {"name": "krs", "type": "text"},
                    {"name": "nazwa", "type": "text"},
                    {"name": "dane", "type": "object", "fields": [{"name": "nip", "type": "text"}]},
                ],
            },
        ],
    }
)

REF = {
    "tytul": "Budowa drogi",
    "data": "2025-10-13",
    "kwota": 10000.0,
    "osoby": [
        {"krs": "0000000001", "nazwa": "Alfa", "dane": {"nip": None}},
        {"krs": None, "nazwa": "Beta", "dane": {"nip": "5270000000"}},
    ],
}


def total(counts: dict[str, Counts]) -> Counts:
    out = Counts()
    for c in counts.values():
        out = out + c
    return out


def test_flatten_arrays_by_key():
    flat = flatten(REF, CFG)
    assert flat["osoby[krs=0000000001].nazwa"] == "alfa"
    assert flat["osoby[dane.nip=5270000000].nazwa"] == "beta"


def test_flatten_arrays_fallback_to_index():
    data = {"osoby": [{"krs": None, "nazwa": "X", "dane": {"nip": None}}]}
    assert flatten(data, CFG)["osoby[0].nazwa"] == "x"


def test_perfect_prediction_f1_1():
    counts = total(score_document(REF, REF, CFG))
    assert counts.fp == 0 and counts.fn == 0 and counts.tp > 0
    assert counts.f1 == 1.0


def test_wrong_value_counts_fp_and_fn():
    pred = {**REF, "tytul": "Inna droga"}
    c = score_document(pred, REF, CFG)["tytul"]
    assert (c.tp, c.fp, c.fn, c.wrong) == (0, 1, 1, 1)


def test_null_vs_missing_equivalent():
    ref = {"tytul": None}
    assert total(score_document({}, ref, CFG)) == Counts()
    assert total(score_document({"tytul": None}, {}, CFG)) == Counts()


def test_pred_null_ref_value_is_fn():
    pred = {**REF, "kwota": None}
    c = score_document(pred, REF, CFG)["kwota"]
    assert (c.tp, c.fp, c.fn, c.nulled) == (0, 0, 1, 1)


def test_pred_value_ref_null_is_fp():
    ref = {**REF, "kwota": None}
    c = score_document(REF, ref, CFG)["kwota"]
    assert (c.tp, c.fp, c.fn) == (0, 1, 0)


def test_misclassified_doc_all_fn():
    counts = score_document(None, REF, CFG)
    assert total(counts).tp == 0 and total(counts).fp == 0
    assert total(counts).fn == len([v for v in flatten(REF, CFG).values() if v is not None])


def test_normalization_case_and_whitespace():
    pred = {**REF, "tytul": "  BUDOWA   drogi "}
    assert score_document(pred, REF, CFG)["tytul"].tp == 1


def test_date_format_normalized():
    pred = {**REF, "data": "13.10.2025"}
    assert score_document(pred, REF, CFG)["data"].tp == 1


def test_numbers_compared_numerically():
    pred = {**REF, "kwota": 10000}
    assert score_document(pred, REF, CFG)["kwota"].tp == 1


def test_array_order_irrelevant_when_key_matches():
    pred = {**REF, "osoby": list(reversed(REF["osoby"]))}
    counts = total(score_document(pred, REF, CFG))
    assert counts.fp == 0 and counts.fn == 0


def test_per_field_uses_schema_paths():
    assert "osoby[].nazwa" in score_document(REF, REF, CFG)
    assert "osoby[].dane.nip" in score_document(REF, REF, CFG)


def test_report_aggregates_micro_f1():
    report = Report()
    report.add_document(score_document(REF, REF, CFG))
    report.add_document(score_document({**REF, "tytul": "x"}, REF, CFG))
    assert report.docs == 2 and report.doc_exact == 1
    assert 0 < report.micro_f1 < 1
    assert report.precision == report.tp_total / (report.tp_total + report.fp_total)
    assert "tytul" in report.render()
    assert report.to_dict()["docs"] == 2


def test_evaluate_end_to_end(tmp_path, demo_classes, fake_llm, monkeypatch):
    from odwolania2json import pipeline
    from odwolania2json.textextract import DocText

    from conftest import DEMO_TEXT, extraction

    monkeypatch.setattr(pipeline, "read_pdf", lambda path: DocText(DEMO_TEXT, 1, False))
    example = tmp_path / "dane" / "przyklad_01"
    example.mkdir(parents=True)
    (example / "cokolwiek.pdf").write_bytes(b"%PDF")
    (example / "demo.json").write_text(
        json.dumps({"nip": "5270000000", "tytul": "Budowa drogi"}), encoding="utf-8"
    )
    llm = fake_llm([classification(), extraction()])
    report = evaluate(tmp_path / "dane", demo_classes[1], llm, Settings(llm_model="m"), workers=1)
    assert report.docs == 1 and report.doc_exact == 1
    assert report.micro_f1 == 1.0
    assert report.classification_accuracy == 1.0
    assert report.citation_ok_rate == 1.0


def test_evaluate_misclassified_counts_all_fn(tmp_path, demo_classes, fake_llm, monkeypatch):
    from odwolania2json import pipeline
    from odwolania2json.textextract import DocText

    from conftest import DEMO_TEXT

    monkeypatch.setattr(pipeline, "read_pdf", lambda path: DocText(DEMO_TEXT, 1, False))
    example = tmp_path / "dane" / "przyklad_01"
    example.mkdir(parents=True)
    (example / "a.pdf").write_bytes(b"%PDF")
    (example / "demo.json").write_text(json.dumps({"nip": "5270000000", "tytul": "T"}), encoding="utf-8")
    report = evaluate(
        tmp_path / "dane", demo_classes[1], fake_llm([classification("nieznany")]),
        Settings(llm_model="m"), workers=1,
    )
    assert report.classification_accuracy == 0.0
    assert report.micro_f1 == 0.0
    assert report.fn_total == 2

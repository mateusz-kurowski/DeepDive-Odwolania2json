import json

from conftest import classification

from src.classconfig import ClassConfig
from src.evaluate import Counts, Report, evaluate, flatten, score_document
from src.settings import Settings

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
    from conftest import DEMO_TEXT, extraction

    from src import pipeline
    from src.textextract import DocText

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
    from conftest import DEMO_TEXT

    from src import pipeline
    from src.textextract import DocText

    monkeypatch.setattr(pipeline, "read_pdf", lambda path: DocText(DEMO_TEXT, 1, False))
    example = tmp_path / "dane" / "przyklad_01"
    example.mkdir(parents=True)
    (example / "a.pdf").write_bytes(b"%PDF")
    (example / "demo.json").write_text(
        json.dumps({"nip": "5270000000", "tytul": "T"}), encoding="utf-8"
    )
    report = evaluate(
        tmp_path / "dane",
        demo_classes[1],
        fake_llm([classification("nieznany")]),
        Settings(llm_model="m"),
        workers=1,
    )
    assert report.classification_accuracy == 0.0
    assert report.micro_f1 == 0.0
    assert report.fn_total == 2


def test_numeric_string_equals_number_for_numeric_fields():
    ref = {**REF, "kwota": "10000"}
    assert score_document(REF, ref, CFG)["kwota"].tp == 1


def _person(krs, nip, nazwa="Alfa"):
    return {"krs": krs, "nazwa": nazwa, "dane": {"nip": nip}}


def test_missing_key_still_pairs_item_by_other_key():
    ref = {"osoby": [_person("0000000001", "5270000000")]}
    pred = {"osoby": [_person(None, "5270000000")]}
    counts = score_document(pred, ref, CFG)
    assert counts["osoby[].krs"].fn == 1 and counts["osoby[].krs"].fp == 0
    assert counts["osoby[].nazwa"].tp == 1
    assert counts["osoby[].dane.nip"].tp == 1
    assert total(counts).fp == 0 and total(counts).fn == 1


def test_items_with_no_shared_key_paired_by_order():
    ref = {"osoby": [_person("0000000001", None)]}
    pred = {"osoby": [_person("0000000009", None)]}
    counts = score_document(pred, ref, CFG)
    assert counts["osoby[].krs"].wrong == 1
    assert counts["osoby[].nazwa"].tp == 1


def test_extra_predicted_item_counts_fp_only():
    ref = {"osoby": [_person("0000000001", None)]}
    pred = {"osoby": [_person("0000000001", None), _person("0000000002", None, "Gamma")]}
    counts = score_document(pred, ref, CFG)
    assert counts["osoby[].nazwa"].tp == 1 and counts["osoby[].nazwa"].fp == 1
    assert total(counts).fn == 0


def _demo_example(tmp_path, monkeypatch, ref):
    from conftest import DEMO_TEXT

    from src import pipeline
    from src.textextract import DocText

    monkeypatch.setattr(pipeline, "read_pdf", lambda path: DocText(DEMO_TEXT, 1, False))
    example = tmp_path / "dane" / "przyklad_01"
    example.mkdir(parents=True)
    (example / "cokolwiek.pdf").write_bytes(b"%PDF")
    (example / "demo.json").write_text(json.dumps(ref), encoding="utf-8")
    return tmp_path / "dane"


def test_evaluate_dump_writes_prediction_reference_and_diffs(
    tmp_path, demo_classes, fake_llm, monkeypatch
):
    from conftest import extraction

    data = _demo_example(tmp_path, monkeypatch, {"nip": "5270000000", "tytul": "Inny tytuł"})
    dump = tmp_path / "dump"
    evaluate(
        data,
        demo_classes[1],
        fake_llm([classification(), extraction()]),
        Settings(llm_model="m"),
        workers=1,
        dump_dir=dump,
    )
    doc = json.loads((dump / "przyklad_01" / "cokolwiek.json").read_text(encoding="utf-8"))
    assert doc["class"] == "demo" and doc["error"] is None
    assert doc["prediction"]["tytul"] == "Budowa drogi"
    assert doc["reference"] == {"nip": "5270000000", "tytul": "Inny tytuł"}
    assert doc["trace"]["citation_ok"]
    assert doc["diffs"] == [
        {"field": "tytul", "predicted": "budowa drogi", "expected": "inny tytuł", "status": "wrong"}
    ]


def test_evaluate_dump_records_unknown_and_missed_reference(
    tmp_path, demo_classes, fake_llm, monkeypatch
):
    data = _demo_example(tmp_path, monkeypatch, {"nip": "5270000000", "tytul": "T"})
    dump = tmp_path / "dump"
    evaluate(
        data,
        demo_classes[1],
        fake_llm([classification("nieznany")]),
        Settings(llm_model="m"),
        workers=1,
        dump_dir=dump,
    )
    doc = json.loads((dump / "przyklad_01" / "cokolwiek.json").read_text(encoding="utf-8"))
    assert doc["class"] == "nieznany" and doc["prediction"] is None
    missed = json.loads((dump / "przyklad_01" / "_missed.json").read_text(encoding="utf-8"))
    assert missed["demo"]["reason"] == "brak dokumentu tej klasy"
    assert {d["status"] for d in missed["demo"]["diffs"]} == {"missing"}


def test_report_separates_errors_from_quality():
    report = Report()
    report.add_document(score_document(REF, REF, CFG))
    report.add_document(score_document(None, REF, CFG), clean=False)
    report.errors = 1
    data = report.to_dict()
    assert data["errors"] == 1
    assert data["docs_lost_to_errors"] == 1
    assert data["micro_f1_without_errors"] == 1.0
    assert data["micro_f1"] < 1.0
    assert "bez dokumentów z błędem" in report.render()


def test_merge_keeps_clean_counts_and_errors():
    part = Report()
    part.add_document(score_document(REF, REF, CFG))
    part.add_document(score_document(None, REF, CFG), clean=False)
    part.errors = 2
    total = Report()
    total.merge(part)
    total.merge(part)
    assert total.errors == 4
    assert total.docs_lost_to_errors == 2
    assert total.totals_clean.f1 == 1.0
    assert total.totals.fn > 0


def test_evaluate_document_lost_to_error_excluded_from_clean_f1(
    tmp_path, demo_classes, fake_llm, monkeypatch
):
    from conftest import DEMO_TEXT

    from src import pipeline
    from src.llm import LLMError
    from src.textextract import DocText

    monkeypatch.setattr(pipeline, "read_pdf", lambda path: DocText(DEMO_TEXT, 1, False))
    example = tmp_path / "dane" / "przyklad_01"
    example.mkdir(parents=True)
    (example / "a.pdf").write_bytes(b"%PDF")
    (example / "demo.json").write_text(
        json.dumps({"nip": "5270000000", "tytul": "Budowa drogi"}), encoding="utf-8"
    )
    llm = fake_llm([classification(), LLMError("pusta odpowiedź")])
    report = evaluate(tmp_path / "dane", demo_classes[1], llm, Settings(llm_model="m"), workers=1)
    assert report.errors == 1
    assert report.docs_lost_to_errors == 1
    assert report.micro_f1 == 0.0
    assert report.totals_clean.tp + report.totals_clean.fn == 0


def test_example_name_accepts_number_or_name():
    from src.evaluate import example_name

    assert example_name("1") == "przyklad_01"
    assert example_name("13") == "przyklad_13"
    assert example_name("przyklad_02") == "przyklad_02"


def test_evaluate_only_selected_examples(tmp_path, demo_classes, fake_llm, monkeypatch):
    from conftest import DEMO_TEXT, extraction

    from src import pipeline
    from src.textextract import DocText

    monkeypatch.setattr(pipeline, "read_pdf", lambda path: DocText(DEMO_TEXT, 1, False))
    for n in ("01", "02", "03"):
        example = tmp_path / "dane" / f"przyklad_{n}"
        example.mkdir(parents=True)
        (example / "a.pdf").write_bytes(b"%PDF")
        (example / "demo.json").write_text(
            json.dumps({"nip": "5270000000", "tytul": "Budowa drogi"}), encoding="utf-8"
        )
    llm = fake_llm([classification(), extraction()])
    report = evaluate(
        tmp_path / "dane", demo_classes[1], llm, Settings(llm_model="m"), workers=1, only=["2"]
    )
    assert report.docs == 1
    assert len(llm.calls) == 2


def test_evaluate_scan_layout_resolves_reference_class_by_keys(
    tmp_path, demo_classes, fake_llm, monkeypatch
):
    from conftest import DEMO_TEXT, extraction

    from src import pipeline
    from src.textextract import DocText

    monkeypatch.setattr(pipeline, "read_pdf", lambda path: DocText(DEMO_TEXT, 1, False))
    case = tmp_path / "skany" / "demo_kind" / "0001"
    case.mkdir(parents=True)
    (case / "0001.pdf").write_bytes(b"%PDF")
    (case / "0001.json").write_text(
        json.dumps({"nip": "5270000000", "tytul": "Budowa drogi"}), encoding="utf-8"
    )
    llm = fake_llm([classification(), extraction()])
    report = evaluate(tmp_path / "skany", demo_classes[1], llm, Settings(llm_model="m"), workers=1)
    assert report.classified_total == 1 and report.classified_ok == 1
    assert report.micro_f1 == 1.0

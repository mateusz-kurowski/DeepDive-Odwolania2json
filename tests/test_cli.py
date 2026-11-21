import json

import pytest
from conftest import DEMO_TEXT, classification, extraction

from src import pipeline
from src.cli import main
from src.textextract import DocText


@pytest.fixture(autouse=True)
def fake_pdf_reader(monkeypatch):
    monkeypatch.setattr(pipeline, "read_pdf", lambda path: DocText(DEMO_TEXT, 1, False))


def args(tmp_path, classes_dir, *extra):
    return [
        "run",
        "--input",
        str(tmp_path / "input"),
        "--output",
        str(tmp_path / "output"),
        "--trace",
        str(tmp_path / "trace"),
        "--classes",
        str(classes_dir),
        "--workers",
        "1",
        *extra,
    ]


ENV = {"OPENAI_API_KEY": "k", "LLM_MODEL": "m"}


def make_input(tmp_path):
    path = tmp_path / "input" / "case1" / "a.pdf"
    path.parent.mkdir(parents=True)
    path.write_bytes(b"%PDF-1.4")


def test_empty_input_dir_exit_0_with_message(tmp_path, demo_classes, fake_llm, capsys):
    (tmp_path / "input").mkdir()
    assert main(args(tmp_path, demo_classes[0]), llm=fake_llm([]), env=ENV) == 0
    assert "Brak plików PDF" in capsys.readouterr().out


def test_missing_input_dir_exit_0_with_message(tmp_path, demo_classes, fake_llm, capsys):
    assert main(args(tmp_path, demo_classes[0]), llm=fake_llm([]), env=ENV) == 0
    assert "Brak plików PDF" in capsys.readouterr().out


def test_run_exit_0_on_success(tmp_path, demo_classes, fake_llm):
    make_input(tmp_path)
    code = main(
        args(tmp_path, demo_classes[0]), llm=fake_llm([classification(), extraction()]), env=ENV
    )
    assert code == 0
    assert (tmp_path / "output" / "case1" / "a.json").exists()


def test_exit_1_when_a_document_failed(tmp_path, demo_classes, fake_llm):
    from src.llm import LLMError

    make_input(tmp_path)
    code = main(args(tmp_path, demo_classes[0]), llm=fake_llm([LLMError("x")]), env=ENV)
    assert code == 1


def test_unknown_document_exit_0(tmp_path, demo_classes, fake_llm):
    make_input(tmp_path)
    code = main(
        args(tmp_path, demo_classes[0]), llm=fake_llm([classification("nieznany")]), env=ENV
    )
    assert code == 0


def test_mode_flag_overrides_env(tmp_path, demo_classes, fake_llm):
    make_input(tmp_path)
    env = {**ENV, "EXTRACTION_MODE": "llm_only"}
    main(
        args(tmp_path, demo_classes[0], "--mode", "hybrid"),
        llm=fake_llm([classification(), extraction()]),
        env=env,
    )
    assert json.loads((tmp_path / "output" / "case1" / "a.json").read_text())["nip"] == "5270000000"


def test_env_mode_used_without_flag(tmp_path, demo_classes, fake_llm):
    make_input(tmp_path)
    env = {**ENV, "EXTRACTION_MODE": "llm_only"}
    main(args(tmp_path, demo_classes[0]), llm=fake_llm([classification(), extraction()]), env=env)
    assert (
        json.loads((tmp_path / "output" / "case1" / "a.json").read_text())["nip"] == "527-000-00-00"
    )


def test_classes_command_lists_loaded_classes(tmp_path, demo_classes, capsys):
    assert main(["classes", "--classes", str(demo_classes[0])], env=ENV) == 0
    assert "demo" in capsys.readouterr().out


def test_eval_command_prints_report_and_writes_json(tmp_path, demo_classes, fake_llm, capsys):
    example = tmp_path / "dane" / "przyklad_01"
    example.mkdir(parents=True)
    (example / "a.pdf").write_bytes(b"%PDF")
    (example / "demo.json").write_text(
        json.dumps({"nip": "5270000000", "tytul": "Budowa drogi"}), encoding="utf-8"
    )
    out = tmp_path / "wynik.json"
    code = main(
        [
            "eval",
            "--data",
            str(tmp_path / "dane"),
            "--classes",
            str(demo_classes[0]),
            "--workers",
            "1",
            "--limit",
            "1",
            "--model",
            "inny-model",
            "--out-json",
            str(out),
        ],
        llm=fake_llm([classification(), extraction()]),
        env=ENV,
    )
    assert code == 0
    assert "F1 (micro)" in capsys.readouterr().out
    assert json.loads(out.read_text())["micro_f1"] == 1.0


def test_model_flag_overrides_env_model():
    from src.cli import _parser, _settings

    args = _parser().parse_args(["eval", "--model", "inny-model"])
    assert _settings(args, ENV).llm_model == "inny-model"


def test_empty_classes_dir_fails_fast(tmp_path, fake_llm, capsys):
    make_input(tmp_path)
    empty = tmp_path / "puste"
    empty.mkdir()
    assert main(args(tmp_path, empty), llm=fake_llm([]), env=ENV) == 2
    assert "klas" in capsys.readouterr().err


def test_missing_classes_dir_fails_fast(tmp_path, fake_llm):
    make_input(tmp_path)
    assert main(args(tmp_path, tmp_path / "nie-ma"), llm=fake_llm([]), env=ENV) == 2


def test_broken_class_yaml_reports_readable_error(tmp_path, fake_llm, capsys):
    make_input(tmp_path)
    broken = tmp_path / "zle"
    broken.mkdir()
    (broken / "x.yaml").write_text("name: x\nfields: [", encoding="utf-8")
    assert main(args(tmp_path, broken), llm=fake_llm([]), env=ENV) == 2
    assert "x.yaml" in capsys.readouterr().err


def test_missing_model_name_fails_fast(tmp_path, demo_classes, capsys):
    make_input(tmp_path)
    assert main(args(tmp_path, demo_classes[0]), env={"OPENAI_API_KEY": "k"}) == 2
    assert "LLM_MODEL" in capsys.readouterr().err


def test_eval_dump_flag_writes_files(tmp_path, demo_classes, fake_llm, monkeypatch):
    from conftest import DEMO_TEXT

    from src import pipeline
    from src.textextract import DocText

    monkeypatch.setattr(pipeline, "read_pdf", lambda path: DocText(DEMO_TEXT, 1, False))
    example = tmp_path / "dane" / "przyklad_01"
    example.mkdir(parents=True)
    (example / "a.pdf").write_bytes(b"%PDF")
    (example / "demo.json").write_text(json.dumps({"tytul": "Budowa drogi"}), encoding="utf-8")
    dump = tmp_path / "dump"
    code = main(
        [
            "eval",
            "--data",
            str(tmp_path / "dane"),
            "--classes",
            str(demo_classes[0]),
            "--workers",
            "1",
            "--dump",
            str(dump),
        ],
        llm=fake_llm([classification(), extraction()]),
        env=ENV,
    )
    assert code == 0
    assert (dump / "przyklad_01" / "a.json").exists()


def test_run_writes_summary_with_unknown_and_errors(tmp_path, demo_classes, fake_llm):
    inp = tmp_path / "input" / "case1"
    inp.mkdir(parents=True)
    (inp / "a.pdf").write_bytes(b"%PDF")
    trace = tmp_path / "trace"
    main(
        [
            "run",
            "--input",
            str(tmp_path / "input"),
            "--output",
            str(tmp_path / "out"),
            "--trace",
            str(trace),
            "--classes",
            str(demo_classes[0]),
            "--workers",
            "1",
        ],
        llm=fake_llm([classification("nieznany")]),
        env=ENV,
    )
    summary = json.loads((trace / "_summary.json").read_text(encoding="utf-8"))
    assert summary["files"][0]["source"] == "case1/a.pdf"
    assert summary["files"][0]["class"] == "nieznany"
    assert summary["files"][0]["output"] is None

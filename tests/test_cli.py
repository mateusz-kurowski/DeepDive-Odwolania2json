import json

import pytest

from odwolania2json import pipeline
from odwolania2json.cli import main
from odwolania2json.textextract import DocText

from conftest import DEMO_TEXT, classification, extraction


@pytest.fixture(autouse=True)
def fake_pdf_reader(monkeypatch):
    monkeypatch.setattr(pipeline, "read_pdf", lambda path: DocText(DEMO_TEXT, 1, False))


def args(tmp_path, classes_dir, *extra):
    return [
        "run",
        "--input", str(tmp_path / "input"),
        "--output", str(tmp_path / "output"),
        "--trace", str(tmp_path / "trace"),
        "--classes", str(classes_dir),
        "--workers", "1",
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
    code = main(args(tmp_path, demo_classes[0]), llm=fake_llm([classification(), extraction()]), env=ENV)
    assert code == 0
    assert (tmp_path / "output" / "case1" / "a.json").exists()


def test_exit_1_when_a_document_failed(tmp_path, demo_classes, fake_llm):
    from odwolania2json.llm import LLMError

    make_input(tmp_path)
    code = main(args(tmp_path, demo_classes[0]), llm=fake_llm([LLMError("x")]), env=ENV)
    assert code == 1


def test_unknown_document_exit_0(tmp_path, demo_classes, fake_llm):
    make_input(tmp_path)
    code = main(args(tmp_path, demo_classes[0]), llm=fake_llm([classification("nieznany")]), env=ENV)
    assert code == 0


def test_mode_flag_overrides_env(tmp_path, demo_classes, fake_llm):
    make_input(tmp_path)
    env = {**ENV, "EXTRACTION_MODE": "llm_only"}
    main(args(tmp_path, demo_classes[0], "--mode", "hybrid"),
         llm=fake_llm([classification(), extraction()]), env=env)
    assert json.loads((tmp_path / "output" / "case1" / "a.json").read_text())["nip"] == "5270000000"


def test_env_mode_used_without_flag(tmp_path, demo_classes, fake_llm):
    make_input(tmp_path)
    env = {**ENV, "EXTRACTION_MODE": "llm_only"}
    main(args(tmp_path, demo_classes[0]), llm=fake_llm([classification(), extraction()]), env=env)
    assert json.loads((tmp_path / "output" / "case1" / "a.json").read_text())["nip"] == "527-000-00-00"


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
        ["eval", "--data", str(tmp_path / "dane"), "--classes", str(demo_classes[0]),
         "--workers", "1", "--limit", "1", "--model", "inny-model", "--out-json", str(out)],
        llm=fake_llm([classification(), extraction()]),
        env=ENV,
    )
    assert code == 0
    assert "F1 (micro)" in capsys.readouterr().out
    assert json.loads(out.read_text())["micro_f1"] == 1.0


def test_model_flag_overrides_env_model():
    from odwolania2json.cli import _parser, _settings

    args = _parser().parse_args(["eval", "--model", "inny-model"])
    assert _settings(args, ENV).llm_model == "inny-model"

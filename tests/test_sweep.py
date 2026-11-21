import json

import pytest
import yaml
from conftest import DEMO_TEXT, FakeLLM, classification, extraction

from src import pipeline
from src.cli import main
from src.sweep import SweepConfigError, load_sweep, run_sweep
from src.textextract import DocText

ENV = {"OPENAI_API_KEY": "k", "LLM_MODEL": "domyslny"}


@pytest.fixture(autouse=True)
def fake_pdf_reader(monkeypatch):
    monkeypatch.setattr(
        pipeline, "read_pdf", lambda path, settings=None: DocText(DEMO_TEXT, 1, False)
    )


@pytest.fixture
def data_dir(tmp_path):
    example = tmp_path / "dane" / "przyklad_01"
    example.mkdir(parents=True)
    (example / "a.pdf").write_bytes(b"%PDF")
    (example / "demo.json").write_text(
        json.dumps({"nip": "5270000000", "tytul": "Budowa drogi"}), encoding="utf-8"
    )
    return tmp_path / "dane"


def write_config(tmp_path, data_dir, classes_dir, **overrides):
    cfg = {
        "out_dir": str(tmp_path / "wyniki"),
        "data": str(data_dir),
        "classes": str(classes_dir),
        "workers": 1,
        "variants": [
            {"name": "a", "model": "model-a"},
            {"name": "b", "model": "model-b", "mode": "llm_only"},
        ],
        **overrides,
    }
    path = tmp_path / "sweep.yaml"
    path.write_text(yaml.safe_dump(cfg), encoding="utf-8")
    return path


def factory(responses_per_model: dict):
    made: dict[str, FakeLLM] = {}

    def make(settings):
        llm = FakeLLM(responses_per_model[settings.llm_model])
        made[settings.llm_model] = llm
        return llm

    make.made = made
    return make


OK = [classification(), extraction()]


def test_runs_every_variant_and_writes_full_results(tmp_path, data_dir, demo_classes):
    cfg = write_config(tmp_path, data_dir, demo_classes[0])
    make = factory({"model-a": OK, "model-b": OK})
    results = run_sweep(cfg, env=ENV, llm_factory=make)
    out = tmp_path / "wyniki"
    assert [r["name"] for r in results] == ["a", "b"]
    for name, model, mode in [("a", "model-a", "hybrid"), ("b", "model-b", "llm_only")]:
        report = json.loads((out / name / "report.json").read_text())
        assert report["model"] == model and report["mode"] == mode
        assert report["micro_f1"] == 1.0
        assert (out / name / "dump").is_dir()
    summary = json.loads((out / "summary.json").read_text())
    assert [s["name"] for s in summary] == ["a", "b"]
    assert summary[0]["micro_f1"] == 1.0 and summary[0]["error"] is None
    md = (out / "summary.md").read_text()
    assert "model-a" in md and "model-b" in md
    assert (out / "sweep.yaml").exists()


def test_failing_variant_does_not_stop_others(tmp_path, data_dir, demo_classes):
    cfg = write_config(tmp_path, data_dir, demo_classes[0])

    def make(settings):
        if settings.llm_model == "model-a":
            raise RuntimeError("brak dostępu do modelu")
        return FakeLLM(OK)

    results = run_sweep(cfg, env=ENV, llm_factory=make)
    assert "brak dostępu" in results[0]["error"]
    assert results[1]["error"] is None and results[1]["micro_f1"] == 1.0
    summary = json.loads((tmp_path / "wyniki" / "summary.json").read_text())
    assert summary[0]["error"]


def test_top_level_defaults_overridden_by_variant(tmp_path, data_dir, demo_classes):
    cfg = write_config(
        tmp_path,
        data_dir,
        demo_classes[0],
        mode="llm_only",
        variants=[
            {"name": "a", "model": "model-a"},
            {"name": "b", "model": "model-b", "mode": "hybrid"},
        ],
    )
    results = run_sweep(cfg, env=ENV, llm_factory=factory({"model-a": OK, "model-b": OK}))
    assert [r["mode"] for r in results] == ["llm_only", "hybrid"]


def test_vlm_and_ocr_overrides_reach_settings(tmp_path, data_dir, demo_classes):
    cfg = write_config(
        tmp_path,
        data_dir,
        demo_classes[0],
        variants=[{"name": "a", "model": "m", "vlm_model": "vision-x", "ocr_backend": "tesseract"}],
    )
    seen = []

    def make(settings):
        seen.append(settings)
        return FakeLLM(OK)

    run_sweep(cfg, env=ENV, llm_factory=make)
    assert seen[0].vlm_model == "vision-x" and seen[0].ocr_backend == "tesseract"


def test_examples_and_limit_are_passed(tmp_path, data_dir, demo_classes):
    cfg = write_config(
        tmp_path, data_dir, demo_classes[0], examples=["01"], variants=[{"name": "a", "model": "m"}]
    )
    results = run_sweep(cfg, env=ENV, llm_factory=factory({"m": OK}))
    assert results[0]["docs"] == 1


@pytest.mark.parametrize(
    "variants,msg",
    [
        ([], "variants"),
        ([{"name": "a", "model": "m"}, {"name": "a", "model": "n"}], "powtarza"),
        ([{"name": "../x", "model": "m"}], "nazwa"),
        ([{"name": "a"}], "model"),
        ([{"name": "a", "model": "m", "nieznane": 1}], "nieznane"),
    ],
)
def test_invalid_config_rejected(tmp_path, data_dir, demo_classes, variants, msg):
    cfg = write_config(tmp_path, data_dir, demo_classes[0], variants=variants)
    with pytest.raises(SweepConfigError, match=msg):
        load_sweep(cfg)


def test_cli_sweep_command_exit_codes(tmp_path, data_dir, demo_classes, capsys):
    cfg = write_config(tmp_path, data_dir, demo_classes[0])
    assert main(["sweep", str(cfg)], llm=FakeLLM(OK + OK), env=ENV) == 0
    assert "model-a" in capsys.readouterr().out

    bad = tmp_path / "zly.yaml"
    bad.write_text("variants: []\nout_dir: x\n", encoding="utf-8")
    assert main(["sweep", str(bad)], env=ENV) == 2


def test_llm_config_override_reaches_settings(tmp_path, data_dir, demo_classes):
    cfg = write_config(
        tmp_path,
        data_dir,
        demo_classes[0],
        variants=[
            {"name": "a", "model": "m", "llm_config": "config/llm-mistral.json"},
            {"name": "b", "model": "n"},
        ],
    )
    seen = []

    def make(settings):
        seen.append(settings.llm_config)
        return FakeLLM(OK)

    run_sweep(cfg, env=ENV, llm_factory=make)
    assert str(seen[0]) == "config/llm-mistral.json"
    assert str(seen[1]) == "config/llm.json"

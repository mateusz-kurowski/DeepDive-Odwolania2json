"""`python -m src check`: diagnostyka konfiguracji, bez prawdziwego API."""

from src.check import run_check
from src.settings import Settings


class _Client:
    def __init__(self, fail: set[str] = frozenset()):
        self.fail = fail
        self.chat = self
        self.completions = self

    def create(self, model, **_):
        if model in self.fail:
            raise RuntimeError("model not found")


def _settings(demo_classes, **kw):
    return Settings(
        openai_api_key="k", llm_model="m", vlm_model="v", classes_dir=demo_classes[0], **kw
    )


def test_all_ok(demo_classes, tmp_path, capsys):
    (tmp_path / "input").mkdir()
    code = run_check(_settings(demo_classes), {}, lambda u, k: _Client(), root=tmp_path)
    out = capsys.readouterr().out
    assert code == 0
    assert "model m" in out and "model v" in out and "Gotowe" in out


def test_failing_model_and_missing_key(demo_classes, tmp_path, capsys):
    settings = _settings(demo_classes).model_copy(update={"openai_api_key": ""})
    code = run_check(settings, {}, lambda u, k: _Client({"m"}), root=tmp_path)
    out = capsys.readouterr().out
    assert code == 1
    assert "OPENAI_API_KEY" in out and "model not found" in out


def test_missing_env_file_is_reported(demo_classes, tmp_path, capsys):
    code = run_check(_settings(demo_classes), None, lambda u, k: _Client(), root=tmp_path)
    assert code == 1
    assert "cp .env.example .env" in capsys.readouterr().out

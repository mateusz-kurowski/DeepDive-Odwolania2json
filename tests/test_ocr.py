from pathlib import Path
from types import SimpleNamespace

import pytest

from src import ocr
from src.settings import Settings

ROOT = Path(__file__).resolve().parent.parent
SCAN_PDF = ROOT / "data/szablon-aplikacja/input/case1/przyklad odwolanie.pdf"


class FakeVision:
    """Udaje klienta OpenAI: zapisuje wywołania, zwraca kolejne odpowiedzi tekstowe."""

    def __init__(self, answers):
        self.answers = list(answers)
        self.calls = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        self.calls.append(kwargs)
        item = self.answers.pop(0) if len(self.answers) > 1 else self.answers[0]
        if isinstance(item, Exception):
            raise item
        message = SimpleNamespace(content=item)
        return SimpleNamespace(choices=[SimpleNamespace(message=message)], usage=None)


def settings(**kw):
    return Settings(openai_api_key="k", vlm_model="vision-x", **kw)


def test_settings_ocr_defaults_to_vlm_without_model():
    s = Settings.from_env({})
    assert s.ocr_backend == "vlm"
    assert s.vlm_model == ""


def test_settings_ocr_from_env():
    s = Settings.from_env(
        {"OCR_BACKEND": "tesseract", "VLM_MODEL": "m", "VLM_BASE_URL": "http://v"}
    )
    assert (s.ocr_backend, s.vlm_model, s.vlm_base_url) == ("tesseract", "m", "http://v")


def test_vlm_ocr_sends_every_page_as_image_and_joins_text():
    client = FakeVision(["Strona tekst"])
    text = ocr.vlm_ocr(SCAN_PDF, settings(), client=client)
    assert len(client.calls) == 7
    assert text == "\n".join(["Strona tekst"] * 7)
    call = client.calls[0]
    assert call["model"] == "vision-x"
    content = call["messages"][-1]["content"]
    image = next(part for part in content if part["type"] == "image_url")
    assert image["image_url"]["url"].startswith("data:image/jpeg;base64,")


def test_vlm_ocr_requires_model_name():
    with pytest.raises(ocr.OcrUnavailable, match="VLM_MODEL"):
        ocr.vlm_ocr(SCAN_PDF, Settings(openai_api_key="k"), client=FakeVision(["x"]))


def test_vlm_ocr_empty_answer_is_error():
    with pytest.raises(ocr.OcrUnavailable, match="pusta"):
        ocr.vlm_ocr(SCAN_PDF, settings(), client=FakeVision([None]))


def test_ocr_pdf_falls_back_to_tesseract_when_vlm_fails(monkeypatch):
    monkeypatch.setattr(ocr, "tesseract_available", lambda: True)
    monkeypatch.setattr(ocr, "tesseract_ocr", lambda path: "z tesseracta")
    client = FakeVision([RuntimeError("model bez wizji")])
    assert ocr.ocr_pdf(SCAN_PDF, settings(), client=client) == "z tesseracta"


def test_ocr_pdf_raises_when_vlm_fails_and_no_tesseract(monkeypatch):
    monkeypatch.setattr(ocr, "tesseract_available", lambda: False)
    with pytest.raises(RuntimeError, match="model bez wizji"):
        ocr.ocr_pdf(SCAN_PDF, settings(), client=FakeVision([RuntimeError("model bez wizji")]))


def test_ocr_pdf_tesseract_backend_never_calls_vlm(monkeypatch):
    monkeypatch.setattr(ocr, "tesseract_available", lambda: True)
    monkeypatch.setattr(ocr, "tesseract_ocr", lambda path: "lokalnie")
    client = FakeVision(["nie wołać"])
    assert ocr.ocr_pdf(SCAN_PDF, settings(ocr_backend="tesseract"), client=client) == "lokalnie"
    assert client.calls == []


def test_tesseract_backend_without_tesseract_explains_install(monkeypatch):
    monkeypatch.setattr(ocr, "tesseract_available", lambda: False)
    with pytest.raises(ocr.OcrUnavailable, match="README"):
        ocr.ocr_pdf(SCAN_PDF, settings(ocr_backend="tesseract"))

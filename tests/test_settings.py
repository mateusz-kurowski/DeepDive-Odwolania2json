from pathlib import Path

import pytest
from pydantic import ValidationError

from src.settings import Settings


def test_defaults():
    s = Settings.from_env({"OPENAI_API_KEY": "k"})
    assert s.extraction_mode == "hybrid"
    assert s.classes_dir == Path("classes")
    assert s.citation_threshold == 85


def test_mode_from_env():
    s = Settings.from_env({"OPENAI_API_KEY": "k", "EXTRACTION_MODE": "llm_only"})
    assert s.extraction_mode == "llm_only"


def test_invalid_mode_rejected():
    with pytest.raises(ValidationError):
        Settings.from_env({"OPENAI_API_KEY": "k", "EXTRACTION_MODE": "foo"})


def test_model_routing_defaults_to_llm_model():
    s = Settings.from_env({"LLM_MODEL": "m", "CLASSIFY_MODEL": "small"})
    assert s.model_for("classification") == "small"
    assert s.model_for("odwolanie") == "m"


def test_models_used_distinct_and_skips_tesseract():
    s = Settings(llm_model="a", classify_model="b", vlm_model="a")
    assert s.models_used() == ["b", "a"]
    assert Settings(llm_model="a", ocr_backend="tesseract", vlm_model="z").models_used() == ["a"]

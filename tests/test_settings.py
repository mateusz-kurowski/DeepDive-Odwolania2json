from pathlib import Path

import pytest
from pydantic import ValidationError

from odwolania2json.settings import Settings


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

from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path
from typing import Literal

from pydantic import BaseModel


class Settings(BaseModel):
    openai_api_key: str = ""
    openai_base_url: str = "http://localhost:4000/v1"
    llm_model: str = ""
    extraction_mode: Literal["hybrid", "llm_only"] = "hybrid"
    classes_dir: Path = Path("classes")
    citation_threshold: float = 85

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> Settings:
        if env is None:
            from dotenv import load_dotenv

            load_dotenv()
            env = os.environ
        values = {
            "openai_api_key": env.get("OPENAI_API_KEY"),
            "openai_base_url": env.get("OPENAI_BASE_URL"),
            "llm_model": env.get("LLM_MODEL"),
            "extraction_mode": env.get("EXTRACTION_MODE"),
            "classes_dir": env.get("CLASSES_DIR"),
            "citation_threshold": env.get("CITATION_THRESHOLD"),
        }
        return cls(**{k: v for k, v in values.items() if v not in (None, "")})

from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

CLASSIFY_TASK = "classification"


class Settings(BaseModel):
    openai_api_key: str = ""
    openai_base_url: str = "http://localhost:4000/v1"
    llm_model: str = ""
    # Opcjonalne modele per zadanie; puste = llm_model.
    classify_model: str = ""
    extract_model: str = ""
    extraction_mode: Literal["hybrid", "llm_only"] = "hybrid"
    classes_dir: Path = Path("classes")
    citation_threshold: float = 85
    llm_config: Path = Path("config/llm.json")
    ocr_backend: Literal["vlm", "tesseract"] = "vlm"
    vlm_model: str = ""
    vlm_base_url: str = ""
    vlm_api_key: str = ""
    # Limit czasu na dokument w sekundach (OCR + klasyfikacja + ekstrakcja); 0 = bez limitu.
    doc_timeout_s: float = 240

    def model_for(self, task: str) -> str:
        """Model dla zadania: "classification" albo ekstrakcja (nazwa klasy dokumentu)."""
        specific = self.classify_model if task == CLASSIFY_TASK else self.extract_model
        return specific or self.llm_model

    def models_used(self) -> list[str]:
        """Różne modele LLM użyte w rozwiązaniu (do średniej liczby parametrów).
        OCR przez Tesseract nie jest LLM-em, więc nie wchodzi do listy."""
        names = [self.model_for(CLASSIFY_TASK), self.model_for("extraction")]
        if self.ocr_backend == "vlm":
            names.append(self.vlm_model)
        return list(dict.fromkeys(n for n in names if n))

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
            "classify_model": env.get("CLASSIFY_MODEL"),
            "extract_model": env.get("EXTRACT_MODEL"),
            "extraction_mode": env.get("EXTRACTION_MODE"),
            "classes_dir": env.get("CLASSES_DIR"),
            "citation_threshold": env.get("CITATION_THRESHOLD"),
            "llm_config": env.get("LLM_CONFIG"),
            "ocr_backend": env.get("OCR_BACKEND"),
            "vlm_model": env.get("VLM_MODEL"),
            "vlm_base_url": env.get("VLM_BASE_URL"),
            "vlm_api_key": env.get("VLM_API_KEY"),
            "doc_timeout_s": env.get("DOC_TIMEOUT_S"),
        }
        return cls(**{k: v for k, v in values.items() if v not in (None, "")})

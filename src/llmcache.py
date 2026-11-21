from __future__ import annotations

import hashlib
import json
import logging
import threading
from pathlib import Path
from typing import Any

from src.llm import LLM

log = logging.getLogger(__name__)


class DiskCachedLLM:
    """Cache odpowiedzi LLM na dysku (włączany flagą --cache, domyślnie wyłączony).

    Klucz: hash modelu, parametrów zapytania, promptu systemowego, treści, schematu i nazwy.
    Zapisywane są tylko poprawne odpowiedzi (obiekt JSON); błędy i puste odpowiedzi nie.
    Zmiana YAML klasy zmienia prompt lub schemat, więc unieważnia odpowiedni wpis.
    """

    def __init__(self, inner: LLM, directory: Path, model: str = "", params: Any = None):
        self.inner = inner
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.model = model
        self.params = params if params is not None else getattr(inner, "params", {})
        self.hits = 0
        self.misses = 0
        self._lock = threading.Lock()

    @property
    def usage(self) -> Any:
        return getattr(self.inner, "usage", None)

    def key(self, system: str, user: str, schema: dict, name: str) -> str:
        payload = json.dumps(
            {
                "model": self.model,
                "params": self.params,
                "system": system,
                "user": user,
                "schema": schema,
                "name": name,
            },
            ensure_ascii=False,
            sort_keys=True,
            default=str,
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def complete_json(self, system: str, user: str, schema: dict, name: str) -> dict:
        path = self.directory / f"{self.key(system, user, schema, name)}.json"
        if path.is_file():
            try:
                cached = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                cached = None
            if isinstance(cached, dict) and cached:
                with self._lock:
                    self.hits += 1
                return cached
        result = self.inner.complete_json(system, user, schema, name)
        with self._lock:
            self.misses += 1
        if isinstance(result, dict) and result:
            tmp = path.with_name(f"{path.stem}.{threading.get_ident()}.tmp")
            tmp.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
            tmp.replace(path)
        return result

    def stats(self) -> dict:
        return {"hits": self.hits, "misses": self.misses}

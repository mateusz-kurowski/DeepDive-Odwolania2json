from __future__ import annotations

import json
import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

import openai

from src import deadline
from src.settings import Settings

log = logging.getLogger(__name__)

_RETRIABLE = (
    openai.RateLimitError,
    openai.APITimeoutError,
    openai.APIConnectionError,
    openai.InternalServerError,
)


class LLM(Protocol):
    def complete_json(self, system: str, user: str, schema: dict, name: str) -> dict: ...


class Usage:
    """Licznik wywołań i tokenów (bezpieczny wątkowo)."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.calls = 0
        self.prompt_tokens = 0
        self.completion_tokens = 0
        self.by_model: dict[str, dict[str, int]] = {}

    def add(self, response: Any, model: str = "") -> None:
        u = getattr(response, "usage", None)
        prompt = getattr(u, "prompt_tokens", 0) or 0
        completion = getattr(u, "completion_tokens", 0) or 0
        with self._lock:
            self.calls += 1
            self.prompt_tokens += prompt
            self.completion_tokens += completion
            if model:
                row = self.by_model.setdefault(
                    model, {"calls": 0, "prompt_tokens": 0, "completion_tokens": 0}
                )
                row["calls"] += 1
                row["prompt_tokens"] += prompt
                row["completion_tokens"] += completion

    def to_dict(self) -> dict:
        return {
            "calls": self.calls,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.prompt_tokens + self.completion_tokens,
            **(
                {"by_model": {k: dict(v) for k, v in self.by_model.items()}}
                if self.by_model
                else {}
            ),
        }


class LLMError(Exception):
    """Model nie zwrócił poprawnej odpowiedzi mimo ponowień."""


def _schema_unsupported(exc: Exception) -> bool:
    text = str(exc).lower()
    return any(word in text for word in ("response_format", "json_schema", "schema"))


class _BadResponse(Exception):
    pass


REQUEST_TIMEOUT_S = 180.0
BACKOFF_BASE = 3.0
BACKOFF_MAX = 30.0
RETRY_TEMPERATURE = 0.2
NO_CACHE = {"no-cache": True, "no-store": True}


def load_llm_params(path: Path | None) -> dict:
    """Wczytuje parametry zapytania z config/llm.json (sekcja "extraction").

    Zwraca tylko klucze przekazywane do API: temperature, max_tokens, extra_body.
    Brak pliku = parametry domyślne backendu.
    """
    if path is None or not Path(path).is_file():
        log.info("Brak pliku konfiguracji LLM (%s), używam parametrów domyślnych", path)
        return {}
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    section = raw.get("extraction", raw) if isinstance(raw, dict) else {}
    params: dict = {}
    for key in ("temperature", "max_tokens"):
        if section.get(key) is not None:
            params[key] = section[key]
    if isinstance(section.get("extra_body"), dict) and section["extra_body"]:
        params["extra_body"] = dict(section["extra_body"])
    return params


@dataclass(frozen=True)
class Attempt:
    """Wariant zapytania dla danej próby; każda ponowna próba różni się od poprzedniej."""

    temperature: float
    no_cache: bool
    json_object: bool


def attempt_plan(index: int, total: int, base_temperature: float) -> Attempt:
    """Próba 1: parametry z konfiguracji. Kolejne: bez cache LiteLLM i z temperature>0
    (identyczne zapytanie dawało identyczną pustą odpowiedź). Ostatnia: json_object
    ze schematem w prompcie (omija ewentualny problem z constrained decoding)."""
    if index == 0:
        return Attempt(base_temperature, no_cache=False, json_object=False)
    last = index == total - 1 and total > 2
    return Attempt(max(base_temperature, RETRY_TEMPERATURE), no_cache=True, json_object=last)


class OpenAICompatLLM:
    def __init__(
        self,
        settings: Settings,
        max_attempts: int = 4,
        sleep: Callable[[float], None] = time.sleep,
        client: Any = None,
        params: dict | None = None,
    ):
        self.settings = settings
        self.max_attempts = max_attempts
        self.sleep = sleep
        self._client = client
        self._json_object_mode = False
        self.params = dict(params) if params is not None else load_llm_params(settings.llm_config)
        self.usage = Usage()

    @property
    def client(self) -> Any:
        if self._client is None:
            self._client = openai.OpenAI(
                api_key=self.settings.openai_api_key or "none",
                base_url=self.settings.openai_base_url,
                timeout=REQUEST_TIMEOUT_S,
                max_retries=0,
            )
        return self._client

    def model_for(self, name: str) -> str:
        """Model dla zadania (name: "classification" albo nazwa klasy przy ekstrakcji)."""
        return self.settings.model_for(name)

    def complete_json(self, system: str, user: str, schema: dict, name: str) -> dict:
        last: Exception | None = None
        base_temperature = float(self.params.get("temperature", 0) or 0)
        for index in range(self.max_attempts):
            attempt = attempt_plan(index, self.max_attempts, base_temperature)
            try:
                deadline.check()
                return self._call(system, user, schema, name, attempt)
            except deadline.DeadlineExceeded as exc:
                raise LLMError(f"{exc} (próba {index + 1}, ostatni błąd: {last})") from exc
            except (*_RETRIABLE, _BadResponse) as exc:
                last = exc
                log.warning("Próba %d/%d nieudana: %s", index + 1, self.max_attempts, exc)
                if index < self.max_attempts - 1:
                    pause = min(BACKOFF_BASE * 2.0**index, BACKOFF_MAX)
                    left = deadline.remaining()
                    self.sleep(pause if left is None else max(min(pause, left), 0))
            except openai.OpenAIError as exc:
                raise LLMError(f"Błąd modelu: {exc}") from exc
        raise LLMError(f"Model niedostępny po {self.max_attempts} próbach: {last}") from last

    def _call(self, system: str, user: str, schema: dict, name: str, attempt: Attempt) -> dict:
        if not self._json_object_mode and not attempt.json_object:
            try:
                return self._request(
                    system,
                    user,
                    {
                        "type": "json_schema",
                        "json_schema": {"name": name, "schema": schema, "strict": True},
                    },
                    attempt,
                    name,
                )
            except openai.BadRequestError as exc:
                if not _schema_unsupported(exc):
                    raise
                log.warning("Backend nie obsługuje json_schema, przechodzę na json_object: %s", exc)
                self._json_object_mode = True
        schema_text = json.dumps(schema, ensure_ascii=False)
        return self._request(
            f"{system}\n\nOdpowiadaj wyłącznie obiektem JSON zgodnym z tym schematem JSON Schema:\n{schema_text}",
            user,
            {"type": "json_object"},
            attempt,
            name,
        )

    def _request(
        self, system: str, user: str, response_format: dict, attempt: Attempt, name: str = ""
    ) -> dict:
        model = self.model_for(name)
        kwargs: dict[str, Any] = {
            "model": model,
            "temperature": attempt.temperature,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "response_format": response_format,
        }
        if self.params.get("max_tokens"):
            kwargs["max_tokens"] = self.params["max_tokens"]
        extra_body = dict(self.params.get("extra_body") or {})
        if attempt.no_cache:
            extra_body["cache"] = dict(NO_CACHE)
        if extra_body:
            kwargs["extra_body"] = extra_body
        if deadline.remaining() is not None:
            kwargs["timeout"] = deadline.request_timeout(REQUEST_TIMEOUT_S)
        try:
            response = self.client.chat.completions.create(**kwargs)
        except openai.BadRequestError as exc:
            config_body = self.params.get("extra_body") or {}
            mentioned = any(str(key).lower() in str(exc).lower() for key in config_body)
            if not mentioned or _schema_unsupported(exc):
                raise
            # Backend odrzucił parametry dostawcy z config/llm.json: działamy dalej bez nich.
            log.warning("Backend odrzucił extra_body z konfiguracji, pomijam je: %s", exc)
            self.params.pop("extra_body", None)
            if attempt.no_cache:
                kwargs["extra_body"] = {"cache": dict(NO_CACHE)}
            else:
                kwargs.pop("extra_body", None)
            response = self.client.chat.completions.create(**kwargs)
        self.usage.add(response, model)
        content = response.choices[0].message.content
        try:
            parsed = json.loads(content or "")
        except json.JSONDecodeError as exc:
            log.warning("Niepoprawna odpowiedź modelu: %s", describe_response(response))
            raise _BadResponse(f"niepoprawny JSON: {exc}") from exc
        if not isinstance(parsed, dict):
            log.warning("Odpowiedź nie jest obiektem JSON: %s", describe_response(response))
            raise _BadResponse("odpowiedź nie jest obiektem JSON")
        return parsed


def describe_response(response: Any) -> dict:
    """Diagnostyka pustej lub niepoprawnej odpowiedzi (bez treści dokumentu)."""
    choices = getattr(response, "choices", None) or [None]
    choice = choices[0]
    message = getattr(choice, "message", None)
    content = getattr(message, "content", None)
    reasoning = getattr(message, "reasoning_content", None) or getattr(message, "reasoning", None)
    usage = getattr(response, "usage", None)
    details = getattr(usage, "completion_tokens_details", None)
    return {
        "finish_reason": getattr(choice, "finish_reason", None),
        "content_len": len(content) if isinstance(content, str) else None,
        "content_head": content[:80] if isinstance(content, str) else None,
        "reasoning_len": len(reasoning) if isinstance(reasoning, str) else None,
        "refusal": getattr(message, "refusal", None),
        "prompt_tokens": getattr(usage, "prompt_tokens", None),
        "completion_tokens": getattr(usage, "completion_tokens", None),
        "reasoning_tokens": getattr(details, "reasoning_tokens", None),
        "cache_hit": _cache_hit(response),
    }


def _cache_hit(response: Any) -> Any:
    hidden = getattr(response, "_hidden_params", None)
    if isinstance(hidden, dict) and "cache_hit" in hidden:
        return hidden["cache_hit"]
    extra = getattr(response, "model_extra", None)
    if isinstance(extra, dict):
        return extra.get("cache_hit")
    return None

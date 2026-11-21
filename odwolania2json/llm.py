from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable
from typing import Any, Protocol

import openai

from odwolania2json.settings import Settings

log = logging.getLogger(__name__)

_RETRIABLE = (
    openai.RateLimitError,
    openai.APITimeoutError,
    openai.APIConnectionError,
    openai.InternalServerError,
)


class LLM(Protocol):
    def complete_json(self, system: str, user: str, schema: dict, name: str) -> dict: ...


class LLMError(Exception):
    """Model nie zwrócił poprawnej odpowiedzi mimo ponowień."""


def _schema_unsupported(exc: Exception) -> bool:
    text = str(exc).lower()
    return any(word in text for word in ("response_format", "json_schema", "schema"))


class _BadResponse(Exception):
    pass


class OpenAICompatLLM:
    def __init__(
        self,
        settings: Settings,
        max_attempts: int = 4,
        sleep: Callable[[float], None] = time.sleep,
        client: Any = None,
    ):
        self.settings = settings
        self.max_attempts = max_attempts
        self.sleep = sleep
        self._client = client
        self._json_object_mode = False

    @property
    def client(self) -> Any:
        if self._client is None:
            self._client = openai.OpenAI(
                api_key=self.settings.openai_api_key or "none",
                base_url=self.settings.openai_base_url,
                timeout=180,
                max_retries=0,
            )
        return self._client

    def complete_json(self, system: str, user: str, schema: dict, name: str) -> dict:
        last: Exception | None = None
        for attempt in range(self.max_attempts):
            try:
                return self._call(system, user, schema, name)
            except (*_RETRIABLE, _BadResponse) as exc:
                last = exc
                log.warning("Próba %d/%d nieudana: %s", attempt + 1, self.max_attempts, exc)
                if attempt < self.max_attempts - 1:
                    self.sleep(min(2.0**attempt, 30.0))
            except openai.OpenAIError as exc:
                raise LLMError(f"Błąd modelu: {exc}") from exc
        raise LLMError(f"Model niedostępny po {self.max_attempts} próbach: {last}") from last

    def _call(self, system: str, user: str, schema: dict, name: str) -> dict:
        if not self._json_object_mode:
            try:
                return self._request(
                    system,
                    user,
                    {
                        "type": "json_schema",
                        "json_schema": {"name": name, "schema": schema, "strict": True},
                    },
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
        )

    def _request(self, system: str, user: str, response_format: dict) -> dict:
        response = self.client.chat.completions.create(
            model=self.settings.llm_model,
            temperature=0,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            response_format=response_format,
        )
        content = response.choices[0].message.content
        try:
            parsed = json.loads(content or "")
        except json.JSONDecodeError as exc:
            raise _BadResponse(f"niepoprawny JSON: {exc}") from exc
        if not isinstance(parsed, dict):
            raise _BadResponse("odpowiedź nie jest obiektem JSON")
        return parsed

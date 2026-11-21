from __future__ import annotations

import pytest


class FakeLLM:
    """Zwraca kolejne odpowiedzi z listy; wyjątki są rzucane. Zapisuje wywołania."""

    def __init__(self, responses: list):
        self.responses = list(responses)
        self.calls: list[dict] = []

    def complete_json(self, system: str, user: str, schema: dict, name: str) -> dict:
        self.calls.append({"system": system, "user": user, "schema": schema, "name": name})
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


@pytest.fixture
def fake_llm():
    def make(responses: list) -> FakeLLM:
        return FakeLLM(responses)

    return make

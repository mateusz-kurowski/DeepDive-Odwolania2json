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


DEMO_CLASS_YAML = """
name: demo
description: Dokument demonstracyjny
fields:
  - {name: nip, type: text, validator: nip}
  - {name: tytul, type: text}
"""

DEMO_TEXT = "Wykonawca ma NIP 527-000-00-00 oraz tytuł Budowa drogi."


@pytest.fixture
def demo_classes(tmp_path):
    from odwolania2json.classconfig import load_classes

    directory = tmp_path / "classes"
    directory.mkdir()
    (directory / "demo.yaml").write_text(DEMO_CLASS_YAML, encoding="utf-8")
    return directory, load_classes(directory)


def classification(name="demo"):
    return {"class": name}


def extraction(nip="527-000-00-00"):
    return {
        "nip": {"value": nip, "quote": "527-000-00-00"},
        "tytul": {"value": "Budowa drogi", "quote": "tytuł Budowa drogi"},
    }

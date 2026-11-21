import pytest

from src.classconfig import ClassConfig
from src.schema import build_response_schema, unwrap


@pytest.fixture
def cfg():
    return ClassConfig.model_validate(
        {
            "name": "demo",
            "description": "d",
            "fields": [
                {"name": "tytul", "type": "text"},
                {"name": "powod", "type": "enum", "options": {1: "a", 4: "b"}},
                {
                    "name": "powod_opis",
                    "type": "text",
                    "derive": {"from": "powod", "map": {1: "Pierwszy", 4: "Czwarty"}},
                },
                {"name": "flaga", "type": "flag"},
                {
                    "name": "osoby",
                    "type": "array",
                    "key": ["krs"],
                    "fields": [
                        {"name": "krs", "type": "text"},
                        {
                            "name": "pelnomocnik",
                            "type": "object",
                            "fields": [{"name": "mail", "type": "text"}],
                        },
                    ],
                },
            ],
        }
    )


def leaf(value, quote="q"):
    return {"value": value, "quote": quote}


RAW = {
    "tytul": leaf("T"),
    "powod": leaf(4),
    "flaga": leaf(1),
    "osoby": [{"krs": leaf("0000000001"), "pelnomocnik": {"mail": leaf("a@b.pl", "mail: a@b.pl")}}],
}


def test_leaf_has_value_and_quote(cfg):
    leaf_schema = build_response_schema(cfg)["properties"]["tytul"]
    assert set(leaf_schema["properties"]) == {"value", "quote"}
    assert leaf_schema["required"] == ["value", "quote"]
    assert leaf_schema["additionalProperties"] is False


def test_derived_field_not_in_schema(cfg):
    schema = build_response_schema(cfg)
    assert "powod_opis" not in schema["properties"]
    assert "powod_opis" not in schema["required"]


def test_enum_includes_null_and_options(cfg):
    value = build_response_schema(cfg)["properties"]["powod"]["properties"]["value"]
    assert set(value["enum"]) == {1, 4, None}
    flag = build_response_schema(cfg)["properties"]["flaga"]["properties"]["value"]
    assert set(flag["enum"]) == {1, 0, None}


def test_array_items_schema(cfg):
    arr = build_response_schema(cfg)["properties"]["osoby"]
    assert arr["type"] == "array"
    assert set(arr["items"]["properties"]) == {"krs", "pelnomocnik"}
    assert "mail" in arr["items"]["properties"]["pelnomocnik"]["properties"]


def test_unwrap_shapes_output_like_uzp(cfg):
    data, _ = unwrap(RAW, cfg)
    assert data["tytul"] == "T"
    assert data["osoby"] == [{"krs": "0000000001", "pelnomocnik": {"mail": "a@b.pl"}}]


def test_unwrap_applies_derive(cfg):
    data, _ = unwrap(RAW, cfg)
    assert data["powod_opis"] == "Czwarty"
    assert list(data) == ["tytul", "powod", "powod_opis", "flaga", "osoby"]


def test_unwrap_derive_null_when_source_null(cfg):
    raw = {**RAW, "powod": leaf(None, None)}
    data, _ = unwrap(raw, cfg)
    assert data["powod"] is None
    assert data["powod_opis"] is None


def test_unwrap_collects_quotes_by_path(cfg):
    _, quotes = unwrap(RAW, cfg)
    assert quotes["tytul"] == "q"
    assert quotes["osoby[0].pelnomocnik.mail"] == "mail: a@b.pl"

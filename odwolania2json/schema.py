from __future__ import annotations

from typing import Any

from odwolania2json.classconfig import ClassConfig, FieldSpec

_SCALAR_TYPES = {"text": "string", "number": "number", "integer": "integer"}


def _value_schema(spec: FieldSpec) -> dict:
    if spec.type == "flag":
        values: list[Any] = [1, 0]
    elif spec.type == "enum":
        values = list(spec.options or {})
    else:
        base = _SCALAR_TYPES[spec.type]
        return {"type": [base, "null"] if spec.nullable else base}
    return {"enum": values + [None] if spec.nullable else values}


def _fields_schema(fields: list[FieldSpec]) -> dict:
    active = [f for f in fields if f.derive is None]
    return {
        "type": "object",
        "properties": {f.name: _field_schema(f) for f in active},
        "required": [f.name for f in active],
        "additionalProperties": False,
    }


def _field_schema(spec: FieldSpec) -> dict:
    if spec.type == "object":
        return _fields_schema(spec.fields)
    if spec.type == "array":
        return {"type": "array", "items": _fields_schema(spec.fields)}
    return {
        "type": "object",
        "properties": {
            "value": _value_schema(spec),
            "quote": {"type": ["string", "null"]},
        },
        "required": ["value", "quote"],
        "additionalProperties": False,
    }


def build_response_schema(cfg: ClassConfig) -> dict:
    return _fields_schema(cfg.fields)


def _unwrap_fields(
    raw: dict, fields: list[FieldSpec], prefix: str, quotes: dict[str, str | None]
) -> dict:
    out: dict[str, Any] = {}
    for spec in fields:
        path = f"{prefix}{spec.name}"
        if spec.derive is not None:
            source = out.get(spec.derive.from_field)
            out[spec.name] = None if source is None else spec.derive.map.get(source)
        elif spec.type == "object":
            out[spec.name] = _unwrap_fields(
                raw.get(spec.name) or {}, spec.fields, f"{path}.", quotes
            )
        elif spec.type == "array":
            items = raw.get(spec.name) or []
            out[spec.name] = [
                _unwrap_fields(item, spec.fields, f"{path}[{i}].", quotes)
                for i, item in enumerate(items)
            ]
        else:
            cell = raw.get(spec.name) or {}
            out[spec.name] = cell.get("value")
            quotes[path] = cell.get("quote")
    return out


def unwrap(raw: dict, cfg: ClassConfig) -> tuple[dict, dict[str, str | None]]:
    quotes: dict[str, str | None] = {}
    return _unwrap_fields(raw, cfg.fields, "", quotes), quotes

from __future__ import annotations

import json
import logging
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Literal

from src.citations import citation_ok
from src.classconfig import ClassConfig, FieldSpec
from src.llm import LLM, LLMError
from src.schema import build_response_schema, unwrap
from src.textextract import DocText
from src.validators import checksum_ok, grounded_in_quote, validate_value

log = logging.getLogger(__name__)

MAX_CHARS = 60_000
HEAD_RATIO = 0.7
Mode = Literal["hybrid", "llm_only"]


@dataclass
class Extraction:
    data: dict
    quotes: dict[str, str | None]
    citation_ok: dict[str, bool]
    nulled: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    retries: int = 0
    truncated: bool = False


def truncate(text: str) -> tuple[str, bool]:
    if len(text) <= MAX_CHARS:
        return text, False
    head_len = int(MAX_CHARS * HEAD_RATIO)
    tail_len = MAX_CHARS - head_len
    omitted = len(text) - head_len - tail_len
    marker = f"\n[...pominięto {omitted} znaków...]\n"
    return text[:head_len] + marker + text[-tail_len:], True


def _describe_fields(fields: list[FieldSpec], indent: int = 0) -> list[str]:
    pad = "  " * indent
    lines: list[str] = []
    for spec in fields:
        if spec.derive is not None:
            continue
        head = f"{pad}- {spec.name} ({spec.type})"
        if spec.description:
            head += f": {spec.description}"
        lines.append(head)
        if spec.options:
            lines += [f"{pad}    {value} = {label}" for value, label in spec.options.items()]
        if spec.type in ("object", "array"):
            lines += _describe_fields(spec.fields, indent + 1)
    return lines


def _system_prompt(cfg: ClassConfig, truncated: bool) -> str:
    parts = [
        f"Wyodrębniasz dane z dokumentu klasy '{cfg.name}': {cfg.description}",
        "Dla każdego pola zwróć obiekt {value, quote}: value to wartość, quote to "
        "dosłowny fragment tekstu dokumentu, z którego ją odczytano.",
        "Gdy nie jesteś pewien albo informacji nie ma w tekście, zwróć value=null i quote=null. "
        "Nie zgaduj.",
        "Pola:",
        *_describe_fields(cfg.fields),
    ]
    if cfg.rules:
        parts += ["Reguły:", *[f"- {rule}" for rule in cfg.rules]]
    if cfg.examples:
        parts.append(
            "Przykłady poprawnych wartości (w odpowiedzi opakuj każdą wartość jako {value, quote}):"
        )
        for ex in cfg.examples:
            parts.append(
                f"TEKST:\n{ex.text}\nWARTOŚCI:\n{json.dumps(ex.output, ensure_ascii=False)}"
            )
    if truncated:
        parts.append(
            "Tekst jest niepełny (środek pominięto). "
            "Dla pól bez dowodu w widocznym tekście zwracaj null."
        )
    return "\n".join(parts)


def _cells(
    raw: dict, fields: list[FieldSpec], prefix: str = ""
) -> Iterator[tuple[dict, FieldSpec, str]]:
    for spec in fields:
        if spec.derive is not None:
            continue
        path = f"{prefix}{spec.name}"
        value = raw.get(spec.name)
        if spec.type == "object":
            yield from _cells(value or {}, spec.fields, f"{path}.")
        elif spec.type == "array":
            for i, item in enumerate(value or []):
                yield from _cells(item, spec.fields, f"{path}[{i}].")
        elif isinstance(value, dict):
            yield value, spec, path


def _raw_value(raw: dict, dotted: str) -> object:
    node: object = raw
    for part in dotted.split("."):
        if not isinstance(node, dict):
            return None
        node = node.get(part)
    return node.get("value") if isinstance(node, dict) else None


def _consistency_problems(raw: dict, cfg: ClassConfig) -> list[str]:
    problems = []
    for req in cfg.requires:
        if _raw_value(raw, req.when) is None:
            continue
        for path in req.then:
            if _raw_value(raw, path) is None:
                hint = f" {req.message}" if req.message else ""
                problems.append(
                    f"{path}: brak wartości, choć {req.when} jest wypełnione; "
                    f"sprawdź tekst ponownie (null tylko gdy naprawdę brak).{hint}"
                )
    return problems


def _problems(
    raw: dict, cfg: ClassConfig, text: str, mode: Mode, threshold: float, ocr_used: bool = False
) -> list[str]:
    problems = _consistency_problems(raw, cfg) if mode == "hybrid" else []
    for cell, spec, path in _cells(raw, cfg.fields):
        value = cell.get("value")
        if value is None:
            continue
        if mode == "hybrid":
            try:
                value = validate_value(spec, value)
            except ValueError as exc:
                problems.append(f"{path}: {exc}")
                continue
        if not citation_ok(cell.get("quote"), text, threshold):
            problems.append(
                f"{path}: cytat nie występuje w tekście; podaj dosłowny fragment albo null"
            )
        elif not grounded_in_quote(spec.validator, value, cell.get("quote")):
            problems.append(
                f"{path}: wartość {value!r} nie wynika z podanego cytatu; "
                "popraw wartość albo cytat, albo zwróć null"
            )
        elif mode == "hybrid" and ocr_used and checksum_ok(spec.validator, value) is False:
            problems.append(
                f"{path}: {value!r} ma niepoprawną sumę kontrolną (możliwy błąd odczytu skanu); "
                "sprawdź cyfry ponownie"
            )
    return problems


def extract(doc: DocText, cfg: ClassConfig, llm: LLM, mode: Mode, threshold: float) -> Extraction:
    text, truncated = truncate(doc.text)
    system = _system_prompt(cfg, truncated)
    schema = build_response_schema(cfg)
    raw = llm.complete_json(system, text, schema, cfg.name)
    retries = 0

    problems = _problems(raw, cfg, text, mode, threshold, doc.ocr_used)
    if problems:
        retries = 1
        feedback = f"{text}\n\nPoprzednia odpowiedź miała problemy, popraw je:\n" + "\n".join(
            f"- {p}" for p in problems
        )
        try:
            raw = llm.complete_json(system, feedback, schema, cfg.name)
        except LLMError as exc:
            log.warning("Ponowna próba nieudana, zostaje pierwsza odpowiedź: %s", exc)

    nulled: list[str] = []
    if mode == "hybrid":
        for cell, spec, path in _cells(raw, cfg.fields):
            try:
                cell["value"] = validate_value(spec, cell.get("value"))
            except ValueError:
                cell["value"] = None
                nulled.append(path)

    warnings: list[str] = []
    cited: dict[str, bool] = {}
    for cell, spec, path in _cells(raw, cfg.fields):
        value = cell.get("value")
        if value is None:
            continue
        quote = cell.get("quote")
        cited[path] = citation_ok(quote, text, threshold) and grounded_in_quote(
            spec.validator, value, quote
        )
        if checksum_ok(spec.validator, value) is False:
            warnings.append(f"{path}: niepoprawna suma kontrolna")
    data, quotes = unwrap(raw, cfg)
    return Extraction(
        data=data,
        quotes=quotes,
        citation_ok=cited,
        nulled=nulled,
        warnings=warnings,
        retries=retries,
        truncated=truncated,
    )

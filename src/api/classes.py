"""Typy dokumentów jako YAML w classes/: odczyt, walidacja, zapis (config only)."""

from __future__ import annotations

import re
from pathlib import Path

import yaml
from pydantic import ValidationError

from src.classconfig import ClassConfig, FieldSpec

NAME = re.compile(r"[a-z][a-z0-9_]*")


class ClassesError(Exception):
    def __init__(self, message: str, status: int = 422):
        super().__init__(message)
        self.status = status


def _field(spec: FieldSpec) -> dict:
    return {
        "name": spec.name,
        "type": spec.type,
        "label": spec.label,
        "description": spec.description,
        "validator": spec.validator,
        "options": {str(k): v for k, v in spec.options.items()} if spec.options else None,
        "nullable": spec.nullable,
        "fields": [_field(f) for f in spec.fields],
    }


def _count(fields: list[FieldSpec]) -> int:
    return sum(1 if f.type not in ("object", "array") else _count(f.fields) for f in fields)


class ClassStore:
    def __init__(self, directory: Path):
        self.directory = Path(directory)

    def _path(self, name: str) -> Path:
        if not NAME.fullmatch(name):
            raise ClassesError("Nazwa: małe litery, cyfry i _, zaczynając od litery.", 422)
        return self.directory / f"{name}.yaml"

    def _load(self, path: Path) -> ClassConfig:
        return ClassConfig.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))

    def list(self) -> list[dict]:
        out = []
        for path in sorted(self.directory.glob("*.yaml")):
            try:
                cfg = self._load(path)
            except (yaml.YAMLError, ValidationError, TypeError):
                out.append(
                    {
                        "name": path.stem,
                        "description": "Niepoprawny schemat (popraw YAML).",
                        "field_count": 0,
                        "hints": [],
                    }
                )
                continue
            out.append(
                {
                    "name": cfg.name,
                    "description": cfg.description,
                    "field_count": _count(cfg.fields),
                    "hints": cfg.hints,
                }
            )
        return out

    def get(self, name: str) -> dict:
        path = self._path(name)
        if not path.is_file():
            raise ClassesError("Nie znaleziono typu dokumentu.", 404)
        text = path.read_text(encoding="utf-8")
        try:
            cfg = self._load(path)
        except (yaml.YAMLError, ValidationError, TypeError):
            return {"name": name, "description": "", "yaml": text, "fields": [], "example_count": 0}
        return {
            "name": cfg.name,
            "description": cfg.description,
            "yaml": text,
            "fields": [_field(f) for f in cfg.fields],
            "example_count": len(cfg.examples),
        }

    def put(self, name: str, text: str) -> dict:
        path = self._path(name)
        try:
            raw = yaml.safe_load(text)
            cfg = ClassConfig.model_validate(raw)
        except yaml.YAMLError as exc:
            raise ClassesError(f"Niepoprawny YAML: {exc}") from exc
        except (ValidationError, TypeError) as exc:
            raise ClassesError(f"Niepoprawny schemat: {exc}") from exc
        if cfg.name != name:
            raise ClassesError(f"Pole name ('{cfg.name}') musi równać się nazwie typu '{name}'.")
        self.directory.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".yaml.tmp")
        tmp.write_text(text, encoding="utf-8")
        tmp.replace(path)
        return self.get(name)

    def delete(self, name: str) -> None:
        path = self._path(name)
        if not path.is_file():
            raise ClassesError("Nie znaleziono typu dokumentu.", 404)
        path.unlink()

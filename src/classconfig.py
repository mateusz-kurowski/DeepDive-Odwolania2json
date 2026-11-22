from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

FieldType = Literal["text", "number", "integer", "flag", "enum", "object", "array"]


class ClassConfigError(Exception):
    def __init__(self, path: Path, message: str):
        super().__init__(f"{path}: {message}")
        self.path = path
        self.message = message


class Derive(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    from_field: str = Field(alias="from")
    map: dict[int | str, str]


class FieldSpec(BaseModel):
    name: str
    type: FieldType
    description: str = ""
    validator: str | None = None
    options: dict[int | str, str] | None = None
    fields: list[FieldSpec] = []
    key: list[str] = []
    derive: Derive | None = None
    nullable: bool = True

    @model_validator(mode="after")
    def _check_shape(self) -> FieldSpec:
        if self.type in ("object", "array") and not self.fields:
            raise ValueError(f"pole '{self.name}' typu {self.type} wymaga 'fields'")
        if self.type == "enum" and not self.options:
            raise ValueError(f"pole '{self.name}' typu enum wymaga 'options'")
        _check_derive(self.fields)
        return self


class Requirement(BaseModel):
    """Kontrola spójności: gdy pole `when` ma wartość, pola z `then` też powinny ją mieć.

    Ścieżki z kropkami przez obiekty (bez tablic), np. Sekcja.pole. Naruszenie nie zeruje
    wartości: trafia do listy problemów i wywołuje jedną ponowną próbę ekstrakcji.
    """

    when: str
    then: list[str]
    message: str = ""


class Example(BaseModel):
    text: str
    output: dict


class ClassConfig(BaseModel):
    name: str
    description: str
    hints: list[str] = []
    # Kiedy brak hintu w tekście unieważnia wybór modelu:
    # always (domyślnie): zawsze; other_class: tylko gdy pasują hinty innej klasy; never.
    hint_veto: Literal["always", "other_class", "never"] = "always"
    # Słowa wykluczające: gdy którekolwiek występuje na początku dokumentu, to nie ta klasa
    # (np. wyrok KIO cytuje odwołanie, ale zaczyna się od „Sygn. akt”, „orzeka”).
    exclude_hints: list[str] = []
    rules: list[str] = []
    examples: list[Example] = []
    requires: list[Requirement] = []
    fields: list[FieldSpec]

    @model_validator(mode="after")
    def _check_derive(self) -> ClassConfig:
        _check_derive(self.fields)
        for req in self.requires:
            for path in (req.when, *req.then):
                if field_at(self.fields, path) is None:
                    raise ValueError(f"requires: pole '{path}' nie istnieje (lub jest w tablicy)")
        return self


def field_at(fields: list[FieldSpec], dotted: str) -> FieldSpec | None:
    """Pole liścia pod ścieżką z kropkami przez obiekty; None, gdy brak lub tablica po drodze."""
    parts = dotted.split(".")
    current = fields
    for i, part in enumerate(parts):
        spec = next((f for f in current if f.name == part), None)
        if spec is None:
            return None
        if i == len(parts) - 1:
            return spec if spec.type not in ("object", "array") else None
        if spec.type != "object":
            return None
        current = spec.fields
    return None


def _check_derive(fields: list[FieldSpec]) -> None:
    names = {f.name for f in fields}
    for f in fields:
        if f.derive and f.derive.from_field not in names:
            raise ValueError(f"pole '{f.name}': derive.from '{f.derive.from_field}' nie istnieje")


def load_classes(directory: Path) -> dict[str, ClassConfig]:
    classes: dict[str, ClassConfig] = {}
    for path in sorted(Path(directory).glob("*.yaml")):
        try:
            raw = yaml.safe_load(path.read_text(encoding="utf-8"))
            cfg = ClassConfig.model_validate(raw)
        except (yaml.YAMLError, ValidationError, TypeError) as exc:
            raise ClassConfigError(path, str(exc)) from exc
        if cfg.name != path.stem:
            raise ClassConfigError(
                path, f"name '{cfg.name}' musi równać się nazwie pliku '{path.stem}'"
            )
        classes[cfg.name] = cfg
    return classes

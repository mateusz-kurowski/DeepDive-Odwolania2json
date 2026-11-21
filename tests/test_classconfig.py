from pathlib import Path

import pytest

from src.classconfig import ClassConfigError, load_classes

VALID = """
name: demo
description: Dokument demonstracyjny
hints: [demo]
rules: ["Zwracaj null gdy brak"]
fields:
  - name: tytul
    type: text
    description: Tytuł
  - name: powod
    type: enum
    options: {1: "pierwszy", 4: "czwarty"}
  - name: powod_opis
    type: text
    derive: {from: powod, map: {1: "Pierwszy", 4: "Czwarty"}}
  - name: osoby
    type: array
    key: [krs]
    fields:
      - {name: krs, type: text, validator: krs}
      - {name: nazwa, type: text}
"""


def write(tmp_path: Path, name: str, body: str) -> Path:
    (tmp_path / f"{name}.yaml").write_text(body, encoding="utf-8")
    return tmp_path


def test_loads_valid_class(tmp_path):
    classes = load_classes(write(tmp_path, "demo", VALID))
    cfg = classes["demo"]
    assert cfg.fields[1].options[4] == "czwarty"
    assert cfg.fields[2].derive.from_field == "powod"
    assert cfg.fields[3].key == ["krs"]
    assert cfg.hints == ["demo"]


def test_name_must_match_filename(tmp_path):
    with pytest.raises(ClassConfigError):
        load_classes(write(tmp_path, "inna", VALID))


def test_unknown_field_type_rejected(tmp_path):
    body = "name: x\ndescription: d\nfields:\n  - {name: a, type: blob}\n"
    with pytest.raises(ClassConfigError):
        load_classes(write(tmp_path, "x", body))


def test_array_requires_fields(tmp_path):
    body = "name: x\ndescription: d\nfields:\n  - {name: a, type: array}\n"
    with pytest.raises(ClassConfigError):
        load_classes(write(tmp_path, "x", body))


def test_derive_must_reference_sibling(tmp_path):
    body = (
        "name: x\ndescription: d\nfields:\n"
        "  - {name: a, type: text, derive: {from: nie_ma, map: {1: 'a'}}}\n"
    )
    with pytest.raises(ClassConfigError):
        load_classes(write(tmp_path, "x", body))


def test_empty_dir_returns_empty_dict(tmp_path):
    assert load_classes(tmp_path) == {}

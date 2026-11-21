from pathlib import Path

import pytest

from odwolania2json.classconfig import ClassConfig, FieldSpec, load_classes
from odwolania2json.validators import REGISTRY

CLASSES_DIR = Path(__file__).resolve().parent.parent / "classes"
CLASSES = load_classes(CLASSES_DIR)


def walk(fields: list[FieldSpec]):
    for spec in fields:
        yield spec
        yield from walk(spec.fields)


def field_map(cfg: ClassConfig) -> dict[str, FieldSpec]:
    return {spec.name: spec for spec in walk(cfg.fields)}


def test_shipped_validators_and_derive_references_exist():
    assert CLASSES, "brak klas w classes/"
    for cfg in CLASSES.values():
        for spec in walk(cfg.fields):
            if spec.validator:
                assert spec.validator in REGISTRY, f"{cfg.name}.{spec.name}: {spec.validator}"


def test_przelew_structure():
    cfg = CLASSES["przelew"]
    root = cfg.fields[0]
    assert root.name == "przelew_bankowy" and root.type == "object"
    fields = {f.name: f for f in root.fields}
    assert set(fields) == {
        "data_operacji", "kwota", "na_rachunek", "numer_transakcji", "tytul", "z_rachunku"
    }
    assert fields["data_operacji"].validator == "date"
    assert fields["kwota"].validator == "amount"
    assert fields["na_rachunek"].validator == "iban"
    assert fields["z_rachunku"].validator == "iban"
    assert cfg.hints and cfg.rules and cfg.examples


DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "dane"


def _leaves(data, fields, path=""):
    for spec in fields:
        value = data.get(spec.name) if isinstance(data, dict) else None
        here = f"{path}{spec.name}"
        if spec.type == "object":
            yield from _leaves(value or {}, spec.fields, f"{here}.")
        elif spec.type == "array":
            for i, item in enumerate(value or []):
                yield from _leaves(item, spec.fields, f"{here}[{i}].")
        else:
            yield here, spec, value


@pytest.mark.parametrize("class_name", sorted(CLASSES))
def test_reference_values_survive_validators_unchanged(class_name):
    """Walidatory nie mogą odrzucać ani zmieniać wartości referencyjnych organizatora."""
    from odwolania2json.validators import validate_value

    cfg = CLASSES[class_name]
    refs = sorted(DATA_DIR.glob(f"przyklad_*/{class_name}.json"))
    assert refs, "brak referencji w data/dane"
    problems = []
    for ref in refs:
        import json

        data = json.loads(ref.read_text(encoding="utf-8"))
        for path, spec, value in _leaves(data, cfg.fields):
            if spec.derive is not None or value is None:
                continue
            try:
                out = validate_value(spec, value)
            except ValueError as exc:
                problems.append(f"{ref.parent.name}:{path}: {exc}")
                continue
            if out != value:
                problems.append(f"{ref.parent.name}:{path}: {value!r} -> {out!r}")
    assert problems == []

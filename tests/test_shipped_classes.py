from pathlib import Path

import pytest

from src.classconfig import ClassConfig, FieldSpec, load_classes
from src.validators import REGISTRY

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
    from src.validators import validate_value

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
            if out != value and str(out) != str(value):
                problems.append(f"{ref.parent.name}:{path}: {value!r} -> {out!r}")
    assert problems == []


def test_pelnomocnictwo_structure():
    cfg = CLASSES["pelnomocnictwo"]
    top = {f.name: f for f in cfg.fields}
    assert set(top) == {"mocodawca", "pelnomocnicy"}
    assert top["mocodawca"].type == "array" and top["mocodawca"].key == ["data.krs", "data.nip"]
    assert top["pelnomocnicy"].type == "array" and top["pelnomocnicy"].key == ["imie_nazwisko"]
    moc = {f.name: f for f in top["mocodawca"].fields}
    assert set(moc) == {"data", "podpisujacy"}
    assert moc["podpisujacy"].type == "array" and moc["podpisujacy"].key == ["imie_nazwisko"]
    data = {f.name: f for f in moc["data"].fields}
    assert set(data) == {"imie_nazwisko", "krs", "nazwa", "nip", "typ"}
    assert data["typ"].type == "enum"
    assert set(data["typ"].options) == {"osoba_prawna", "osoba_fizyczna"}
    assert data["krs"].validator == "krs" and data["nip"].validator == "nip"
    pel = {f.name: f for f in top["pelnomocnicy"].fields}
    assert set(pel) == {"imie_nazwisko", "pesel"}
    assert pel["pesel"].validator == "pesel"
    assert cfg.hints and cfg.rules and cfg.examples


def test_odwolanie_structure():
    from src.schema import build_response_schema

    cfg = CLASSES["odwolanie"]
    top = {f.name: f for f in cfg.fields}
    assert set(top) == {"OdwolanieKIO", "Odwolujacy", "Zamawiajacy", "ZamowieniePubliczne"}
    info = {f.name: f for f in top["OdwolanieKIO"].fields}
    assert set(info) == {"data", "czynnosc_dzien", "czynnosc_powod_id", "czynnosc_opis", "miejscowosc"}
    assert set(info["czynnosc_powod_id"].options) == set(range(1, 12))
    assert info["czynnosc_opis"].derive.from_field == "czynnosc_powod_id"
    assert set(info["czynnosc_opis"].derive.map) == set(range(1, 12))
    assert info["data"].validator == "date" and info["czynnosc_dzien"].validator == "date"

    odw = {f.name: f for f in top["Odwolujacy"].fields}
    assert top["Odwolujacy"].key == ["krs", "nip"] and top["Zamawiajacy"].key == ["krs", "nip"]
    assert odw["przez-pelnomocnika"].type == "flag" and odw["przez-pelnomocnika"].nullable is False
    pel = {f.name: f for f in odw["pelnomocnik"].fields}
    assert set(pel) == {"imie_nazwisko", "nazwa", "mail"} and pel["mail"].validator == "email"
    zam = {f.name: f for f in top["Zamawiajacy"].fields}
    assert zam["prowadzacy_postepowanie"].type == "flag" and zam["prowadzacy_postepowanie"].nullable
    zp = {f.name: f for f in top["ZamowieniePubliczne"].fields}
    assert zp["numer_bzp"].validator == "bzp" and zp["numer_ted"].validator == "ted"
    assert {"krs", "nip", "regon"} <= {n for n, f in odw.items() if f.validator} | {
        n for n, f in zam.items() if f.validator
    }

    schema = build_response_schema(cfg)
    assert "czynnosc_opis" not in schema["properties"]["OdwolanieKIO"]["properties"]
    assert cfg.hints and cfg.rules and cfg.examples


def _wrap(data, fields):
    out = {}
    for spec in fields:
        if spec.derive is not None:
            continue
        value = data.get(spec.name) if isinstance(data, dict) else None
        if spec.type == "object":
            out[spec.name] = _wrap(value or {}, spec.fields)
        elif spec.type == "array":
            out[spec.name] = [_wrap(item, spec.fields) for item in value or []]
        else:
            out[spec.name] = {"value": value, "quote": None}
    return out


@pytest.mark.parametrize("class_name", sorted(CLASSES))
def test_unwrap_of_perfect_model_answer_reproduces_reference(class_name):
    """Schemat + unwrap + derive dla prawdziwych klas odtwarzają referencje (60 przykładów)."""
    import json

    from src.schema import unwrap

    cfg = CLASSES[class_name]
    for ref in sorted(DATA_DIR.glob(f"przyklad_*/{class_name}.json")):
        expected = json.loads(ref.read_text(encoding="utf-8"))
        data, _ = unwrap(_wrap(expected, cfg.fields), cfg)
        assert data == expected, ref.parent.name

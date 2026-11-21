import pytest

from src.classconfig import FieldSpec
from src.validators import REGISTRY, validate_value


@pytest.mark.parametrize(
    "name,raw,expected",
    [
        ("nip", "527-000-00-00", "5270000000"),
        ("nip", "NIP: 5270000000", "5270000000"),
        ("krs", "54588", "0000054588"),
        ("krs", "KRS 0000054588", "0000054588"),
        ("regon", "000279077", "000279077"),
        ("regon", "12345678901234", "12345678901234"),
        ("iban", "PL 60 1010 1010 0081 3622 3100 0000", "60101010100081362231000000"),
        ("iban", "60101010100081362231000000", "60101010100081362231000000"),
        ("ted", "2025/S 123-456789", "456789-2025"),
        ("ted", "641651-2025", "641651-2025"),
        ("bzp", "2026/BZP 00999778", "2026/BZP00999778"),
        ("bzp", "2026/BZP00999778/01", "2026/BZP00999778/01"),
        ("date", "13.10.2025", "2025-10-13"),
        ("date", "2025-10-13", "2025-10-13"),
        ("date", "13 października 2025 r.", "2025-10-13"),
        ("amount", "10 000,00", 10000.0),
        ("amount", "10000.00", 10000.0),
        ("amount", "10.000,00 zł", 10000.0),
        ("email", "Biuro@Poczta.example", "biuro@poczta.example"),
        ("pesel", "85120133547", 85120133547),
    ],
)
def test_normalizes(name, raw, expected):
    assert REGISTRY[name](raw) == expected


@pytest.mark.parametrize(
    "name,raw",
    [
        ("nip", "123"),
        ("krs", "abc"),
        ("regon", "12345"),
        ("iban", "123"),
        ("ted", "abc"),
        ("bzp", "2026/XYZ1"),
        ("date", "2025-13-45"),
        ("amount", "dużo"),
        ("email", "bez-malpy"),
        ("pesel", "123"),
    ],
)
def test_rejects(name, raw):
    with pytest.raises(ValueError):
        REGISTRY[name](raw)


def test_validate_value_none_passes():
    assert validate_value(FieldSpec(name="a", type="text", validator="nip"), None) is None


def test_validate_value_uses_registry():
    spec = FieldSpec(name="a", type="text", validator="nip")
    assert validate_value(spec, "527-000-00-00") == "5270000000"


def test_validate_value_unknown_validator_is_config_error():
    with pytest.raises(KeyError):
        validate_value(FieldSpec(name="a", type="text", validator="nie-ma"), "x")


def test_flag_rejects_out_of_range():
    spec = FieldSpec(name="f", type="flag")
    assert validate_value(spec, 1) == 1
    assert validate_value(spec, 0) == 0
    with pytest.raises(ValueError):
        validate_value(spec, 2)


def test_enum_rejects_unknown_option():
    spec = FieldSpec(name="e", type="enum", options={1: "a", 4: "b"})
    assert validate_value(spec, 4) == 4
    with pytest.raises(ValueError):
        validate_value(spec, 7)

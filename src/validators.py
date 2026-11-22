from __future__ import annotations

import re
from collections.abc import Callable
from datetime import date as _date
from typing import Any

from src.classconfig import FieldSpec

_MONTHS = {
    "stycznia": 1, "lutego": 2, "marca": 3, "kwietnia": 4, "maja": 5, "czerwca": 6,
    "lipca": 7, "sierpnia": 8, "września": 9, "wrzesnia": 9, "października": 10,
    "pazdziernika": 10, "listopada": 11, "grudnia": 12,
}  # fmt: skip


def _digits(value: Any) -> str:
    return re.sub(r"\D", "", str(value))


def nip(value: Any) -> str:
    d = _digits(value)
    if len(d) != 10:
        raise ValueError(f"NIP musi mieć 10 cyfr: {value!r}")
    return d


def krs(value: Any) -> str:
    d = _digits(value)
    if not 1 <= len(d) <= 10:
        raise ValueError(f"KRS musi mieć do 10 cyfr: {value!r}")
    return d.zfill(10)


def regon(value: Any) -> str:
    d = _digits(value)
    if len(d) not in (9, 14):
        raise ValueError(f"REGON musi mieć 9 lub 14 cyfr: {value!r}")
    return d


def iban(value: Any) -> str:
    s = re.sub(r"\s+", "", str(value))
    s = re.sub(r"^PL", "", s, flags=re.IGNORECASE)
    if not re.fullmatch(r"\d{26}", s):
        raise ValueError(f"IBAN musi mieć 26 cyfr: {value!r}")
    return s


def ted(value: Any) -> str:
    s = str(value).strip()
    if m := re.fullmatch(r"(\d{6})-(\d{4})", s):
        return s
    if m := re.fullmatch(r"(\d{4})\s*/\s*S\s*\d{1,3}\s*-\s*(\d{6})", s, re.IGNORECASE):
        return f"{m.group(2)}-{m.group(1)}"
    raise ValueError(f"niepoprawny numer TED: {value!r}")


def bzp(value: Any) -> str:
    s = re.sub(r"\s+", "", str(value)).upper()
    if not re.fullmatch(r"\d{4}/BZP\d{8}(/\d{2})?", s):
        raise ValueError(f"niepoprawny numer BZP: {value!r}")
    return s


def date(value: Any) -> str:
    s = str(value).strip()
    s = re.sub(r"\s*r\.?$", "", s)
    if m := re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", s):
        y, mo, d = map(int, m.groups())
    elif m := re.fullmatch(r"(\d{1,2})[./-](\d{1,2})[./-](\d{4})", s):
        d, mo, y = map(int, m.groups())
    elif m := re.fullmatch(r"(\d{1,2})\s+([^\W\d]+)\s+(\d{4})", s):
        d, y = int(m.group(1)), int(m.group(3))
        mo = _MONTHS.get(m.group(2).lower(), 0)
    else:
        raise ValueError(f"niepoprawna data: {value!r}")
    try:
        return _date(y, mo, d).isoformat()
    except ValueError as exc:
        raise ValueError(f"niepoprawna data: {value!r}") from exc


def amount(value: Any) -> float:
    if isinstance(value, bool):
        raise ValueError(f"niepoprawna kwota: {value!r}")
    if isinstance(value, (int, float)):
        return float(value)
    s = re.sub(r"(zł|pln)", "", str(value), flags=re.IGNORECASE)
    s = re.sub(r"[\s ]", "", s)
    if "," in s and "." in s:
        decimal = "," if s.rfind(",") > s.rfind(".") else "."
        thousands = "." if decimal == "," else ","
        s = s.replace(thousands, "").replace(decimal, ".")
    elif "," in s:
        s = s.replace(",", ".")
    elif re.fullmatch(r"\d{1,3}(\.\d{3})+", s):
        s = s.replace(".", "")
    if not re.fullmatch(r"\d+(\.\d+)?", s):
        raise ValueError(f"niepoprawna kwota: {value!r}")
    return float(s)


def email(value: Any) -> str:
    s = str(value).strip().lower()
    if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", s):
        raise ValueError(f"niepoprawny adres e-mail: {value!r}")
    return s


def pesel(value: Any) -> int:
    d = _digits(value)
    if len(d) != 11:
        raise ValueError(f"PESEL musi mieć 11 cyfr: {value!r}")
    return int(d)


def _nip_sum(d: str) -> bool:
    w = (6, 5, 7, 2, 3, 4, 5, 6, 7)
    return sum(int(a) * b for a, b in zip(d, w, strict=False)) % 11 == int(d[9])


def _regon_sum(d: str) -> bool:
    w = (8, 9, 2, 3, 4, 5, 6, 7) if len(d) == 9 else (2, 4, 8, 5, 0, 9, 7, 3, 6, 1, 2, 4, 8)
    return sum(int(a) * b for a, b in zip(d, w, strict=False)) % 11 % 10 == int(d[-1])


def _pesel_sum(d: str) -> bool:
    w = (1, 3, 7, 9, 1, 3, 7, 9, 1, 3)
    return (10 - sum(int(a) * b for a, b in zip(d, w, strict=False)) % 10) % 10 == int(d[10])


def _iban_sum(d: str) -> bool:
    return int(d[2:] + "2521" + d[:2]) % 97 == 1


_CHECKSUMS: dict[str, tuple[int | tuple[int, ...], Callable[[str], bool]]] = {
    "nip": (10, _nip_sum),
    "regon": ((9, 14), _regon_sum),
    "pesel": (11, _pesel_sum),
    "iban": (26, _iban_sum),
}


def checksum_ok(validator: str | None, value: Any) -> bool | None:
    """Suma kontrolna znormalizowanej wartości; None gdy brak reguły albo wartość nie pasuje.

    Dane treningowe są syntetyczne i część numerów ma zły checksum, więc to jest sygnał
    (ponowna próba, ostrzeżenie), nie powód do zerowania wartości.
    """
    rule = _CHECKSUMS.get(validator or "")
    if rule is None or value is None:
        return None
    lengths, fn = rule
    d = _digits(value)
    if validator == "pesel":
        d = d.zfill(11)
    if len(d) not in ((lengths,) if isinstance(lengths, int) else lengths):
        return None
    return fn(d)


_GROUNDED = {"nip", "krs", "regon", "iban", "pesel", "amount"}


def grounded_in_quote(validator: str | None, value: Any, quote: str | None) -> bool:
    """Czy cyfry wartości występują w cytacie (prawdziwy cytat nie uzasadnia innej liczby)."""
    if validator not in _GROUNDED or value is None:
        return True
    if validator == "amount":
        try:
            needle = str(int(float(value)))
        except (TypeError, ValueError):
            return True
        needle = needle if needle != "0" else ""
    else:
        needle = _digits(value).lstrip("0")
    if not needle:
        return True
    return needle in _digits(quote or "")


REGISTRY: dict[str, Callable[[Any], Any]] = {
    "nip": nip, "krs": krs, "regon": regon, "iban": iban, "ted": ted, "bzp": bzp,
    "date": date, "amount": amount, "email": email, "pesel": pesel,
}  # fmt: skip


def validate_value(spec: FieldSpec, value: Any) -> Any:
    if value is None:
        return None
    if spec.type == "flag" and value not in (1, 0):
        raise ValueError(f"flaga musi być 1 lub 0: {value!r}")
    if spec.type == "enum" and value not in (spec.options or {}):
        raise ValueError(f"wartość spoza listy opcji: {value!r}")
    if spec.validator is not None:
        return REGISTRY[spec.validator](value)
    return value

"""Rozmiary modeli i punktacja za średnią liczbę parametrów (reguła zadania UZP)."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

import yaml

# (górna granica w mld parametrów włącznie, punkty)
SIZE_POINTS = ((8, 20), (14, 18), (32, 12), (70, 8), (150, 4))


def load_model_sizes(path: Path | str = "config/models.yaml") -> dict[str, float]:
    p = Path(path)
    if not p.is_file():
        return {}
    raw = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    return {str(k): float(v) for k, v in raw.items()}


def average_params(models: Iterable[str], sizes: dict[str, float]) -> float | None:
    """Średnia z różnych modeli; None, gdy któregoś nie ma w tabeli (nie zgadujemy)."""
    distinct = list(dict.fromkeys(models))
    if not distinct or any(m not in sizes for m in distinct):
        return None
    return sum(sizes[m] for m in distinct) / len(distinct)


def size_points(avg_b: float | None) -> int | None:
    if avg_b is None:
        return None
    for limit, points in SIZE_POINTS:
        if avg_b <= limit:
            return points
    return 0

"""Limit czasu na jeden dokument (per wątek).

Wątku nie da się przerwać z zewnątrz, więc limit działa od środka: każde wywołanie
API dostaje timeout nie dłuższy niż pozostały czas, a po jego upływie kolejne
próby nie startują (LLMError → dokument dostaje `{}` i wpis w logu).
"""

from __future__ import annotations

import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager

_local = threading.local()

# Minimalny sensowny timeout pojedynczego żądania; poniżej tego lepiej nie startować.
MIN_REQUEST_S = 1.0


class DeadlineExceeded(TimeoutError):
    pass


@contextmanager
def document_deadline(seconds: float | None) -> Iterator[None]:
    """Ustaw limit czasu dla bieżącego wątku; `None` albo `<= 0` = bez limitu."""
    previous = getattr(_local, "deadline", None)
    _local.deadline = time.monotonic() + seconds if seconds and seconds > 0 else None
    try:
        yield
    finally:
        _local.deadline = previous


def remaining() -> float | None:
    """Pozostały czas w sekundach albo `None`, gdy limit nie jest ustawiony."""
    deadline = getattr(_local, "deadline", None)
    return None if deadline is None else deadline - time.monotonic()


def request_timeout(default: float) -> float:
    """Timeout pojedynczego żądania: `default` przycięty do pozostałego czasu."""
    left = remaining()
    if left is None:
        return default
    if left < MIN_REQUEST_S:
        raise DeadlineExceeded("Przekroczono limit czasu dokumentu")
    return min(default, left)


def check() -> None:
    left = remaining()
    if left is not None and left < MIN_REQUEST_S:
        raise DeadlineExceeded("Przekroczono limit czasu dokumentu")

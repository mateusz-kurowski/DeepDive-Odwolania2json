from __future__ import annotations

import re

from rapidfuzz import fuzz


def _normalize(text: str) -> str:
    text = re.sub(r"-\s*\n\s*", "", text)
    return re.sub(r"\s+", " ", text).strip().casefold()


def citation_score(quote: str | None, text: str) -> float:
    if not quote or not quote.strip():
        return 0.0
    q, t = _normalize(quote), _normalize(text)
    if not q or not t:
        return 0.0
    if q in t:
        return 100.0
    return float(fuzz.partial_ratio(q, t))


def citation_ok(quote: str | None, text: str, threshold: float) -> bool:
    return citation_score(quote, text) >= threshold

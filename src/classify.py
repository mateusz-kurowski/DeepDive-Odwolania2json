from __future__ import annotations

import re
import unicodedata

from src.classconfig import ClassConfig
from src.llm import LLM
from src.settings import CLASSIFY_TASK
from src.textextract import DocText

UNKNOWN = "nieznany"
HEAD_CHARS = 3000


def _system_prompt(classes: dict[str, ClassConfig]) -> str:
    lines = [
        "Rozpoznajesz rodzaj dokumentu na podstawie początku jego tekstu.",
        "Wybierz dokładnie jedną z poniższych klas albo "
        f"'{UNKNOWN}', jeśli dokument nie pasuje do żadnej z nich:",
    ]
    lines += [f"- {name}: {cfg.description}" for name, cfg in classes.items()]
    return "\n".join(lines)


_LETTER = r"[^\W\d_]"
_SPACED_LETTERS = re.compile(rf"(?<!\w){_LETTER}(?: {_LETTER}(?!\w)){{2,}}")


def normalize_for_hints(text: str) -> str:
    """Tekst do dopasowania hintów: sklejone rozstrzelone litery („P E Ł N O” → „PEŁNO”),
    bez polskich znaków, casefold."""
    text = _SPACED_LETTERS.sub(lambda m: m.group(0).replace(" ", ""), text)
    text = text.replace("ł", "l").replace("Ł", "L")
    text = "".join(
        ch for ch in unicodedata.normalize("NFKD", text) if not unicodedata.combining(ch)
    )
    return text.casefold()


def _hints(cfg: ClassConfig) -> set[str]:
    return {normalize_for_hints(h) for h in cfg.hints if h.strip()}


def _hint_present(cfg: ClassConfig, text: str) -> bool:
    normalized = normalize_for_hints(text)
    return any(hint in normalized for hint in _hints(cfg))


def _hint_count(cfg: ClassConfig, text: str) -> int:
    normalized = normalize_for_hints(text)
    return sum(hint in normalized for hint in _hints(cfg))


def classify_by_hints(doc: DocText, classes: dict[str, ClassConfig]) -> str:
    """Klasyfikacja awaryjna bez modelu (gdy LLM zawiódł): hinty z YAML na początku tekstu.

    Wygrywa klasa z największą liczbą różnych dopasowanych hintów; remis albo brak
    dopasowań daje UNKNOWN (nie zgadujemy). Hinty różnych klas się nakładają
    (dokument jednej klasy cytuje tytuł innej), stąd liczenie, a nie
    wymóg dopasowania tylko jednej klasy.
    """
    head = doc.text[:HEAD_CHARS]
    counts = {name: _hint_count(cfg, head) for name, cfg in classes.items() if cfg.hints}
    best = max(counts.values(), default=0)
    if best == 0:
        return UNKNOWN
    winners = [name for name, n in counts.items() if n == best]
    return winners[0] if len(winners) == 1 else UNKNOWN


def classify(doc: DocText, classes: dict[str, ClassConfig], llm: LLM) -> str:
    if not classes or not doc.text.strip():
        return UNKNOWN
    schema = {
        "type": "object",
        "properties": {"class": {"enum": [*classes, UNKNOWN]}},
        "required": ["class"],
        "additionalProperties": False,
    }
    answer = llm.complete_json(
        _system_prompt(classes), doc.text[:HEAD_CHARS], schema, CLASSIFY_TASK
    )
    chosen = answer.get("class", UNKNOWN)
    cfg = classes.get(chosen)
    if cfg is None:
        return UNKNOWN
    if _vetoed(chosen, cfg, classes, doc.text):
        return UNKNOWN
    return chosen


def _vetoed(chosen: str, cfg: ClassConfig, classes: dict[str, ClassConfig], text: str) -> bool:
    """Kontrola wyboru modelu hintami z YAML (sterowana polem hint_veto klasy)."""
    if not cfg.hints or cfg.hint_veto == "never" or _hint_present(cfg, text):
        return False
    if cfg.hint_veto == "other_class":
        return any(_hint_present(other, text) for name, other in classes.items() if name != chosen)
    return True

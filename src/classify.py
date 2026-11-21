from __future__ import annotations

from src.classconfig import ClassConfig
from src.llm import LLM
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


def _hint_present(cfg: ClassConfig, text: str) -> bool:
    lowered = text.casefold()
    return any(hint.casefold() in lowered for hint in cfg.hints)


def _hint_count(cfg: ClassConfig, text: str) -> int:
    lowered = text.casefold()
    return sum(hint.casefold() in lowered for hint in set(cfg.hints))


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
        _system_prompt(classes), doc.text[:HEAD_CHARS], schema, "classification"
    )
    chosen = answer.get("class", UNKNOWN)
    cfg = classes.get(chosen)
    if cfg is None:
        return UNKNOWN
    if cfg.hints and not _hint_present(cfg, doc.text):
        return UNKNOWN
    return chosen

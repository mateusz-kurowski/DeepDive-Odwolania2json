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

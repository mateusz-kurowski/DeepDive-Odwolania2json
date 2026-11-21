from odwolania2json.classconfig import ClassConfig
from odwolania2json.classify import UNKNOWN, classify
from odwolania2json.textextract import DocText


def cls(name, description, hints=()):
    return ClassConfig.model_validate(
        {
            "name": name,
            "description": description,
            "hints": list(hints),
            "fields": [{"name": "a", "type": "text"}],
        }
    )


CLASSES = {
    "alfa": cls("alfa", "Dokument alfa", hints=["ALFA-marker"]),
    "beta": cls("beta", "Dokument beta bez wskazówek"),
}


def doc(text):
    return DocText(text=text, pages=1, ocr_used=False)


def test_returns_model_class_when_hint_present(fake_llm):
    llm = fake_llm([{"class": "alfa"}])
    assert classify(doc("to jest alfa-MARKER w tekście"), CLASSES, llm) == "alfa"


def test_hint_control_downgrades_to_unknown(fake_llm):
    llm = fake_llm([{"class": "alfa"}])
    assert classify(doc("zupełnie inny dokument"), CLASSES, llm) == UNKNOWN


def test_class_without_hints_trusted(fake_llm):
    llm = fake_llm([{"class": "beta"}])
    assert classify(doc("dowolny tekst"), CLASSES, llm) == "beta"


def test_model_can_say_unknown(fake_llm):
    llm = fake_llm([{"class": UNKNOWN}])
    assert classify(doc("ogłoszenie TED"), CLASSES, llm) == UNKNOWN


def test_empty_text_unknown_without_llm_call(fake_llm):
    llm = fake_llm([])
    assert classify(doc("   "), CLASSES, llm) == UNKNOWN
    assert llm.calls == []


def test_prompt_lists_all_classes_from_config(fake_llm):
    llm = fake_llm([{"class": "beta"}])
    classify(doc("tekst"), CLASSES, llm)
    call = llm.calls[0]
    assert "alfa" in call["system"] and "Dokument alfa" in call["system"]
    assert "beta" in call["system"]
    assert set(call["schema"]["properties"]["class"]["enum"]) == {"alfa", "beta", UNKNOWN}


def test_only_head_of_text_is_sent(fake_llm):
    llm = fake_llm([{"class": "beta"}])
    classify(doc("A" * 3000 + "KONIEC"), CLASSES, llm)
    assert "KONIEC" not in llm.calls[0]["user"]


def test_no_classes_unknown(fake_llm):
    llm = fake_llm([])
    assert classify(doc("tekst"), {}, llm) == UNKNOWN
    assert llm.calls == []

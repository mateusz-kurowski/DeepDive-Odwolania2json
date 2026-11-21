import pytest

from src.classconfig import ClassConfig
from src.extract import HEAD_RATIO, MAX_CHARS, extract, truncate
from src.llm import LLMError
from src.textextract import DocText

CFG = ClassConfig.model_validate(
    {
        "name": "demo",
        "description": "Dokument demonstracyjny",
        "rules": ["REGUŁA-TESTOWA: bierz dane Lidera"],
        "examples": [{"text": "PRZYKŁAD-TEKST", "output": {"nip": "1234567890", "tytul": "X"}}],
        "fields": [
            {"name": "nip", "type": "text", "validator": "nip", "description": "NIP firmy"},
            {"name": "tytul", "type": "text"},
        ],
    }
)
TEXT = "Wykonawca ma NIP 527-000-00-00 oraz tytuł Budowa drogi."


def doc(text=TEXT):
    return DocText(text=text, pages=1, ocr_used=False)


def raw(nip, nip_quote="527-000-00-00", tytul="Budowa drogi", tytul_quote="tytuł Budowa drogi"):
    return {
        "nip": {"value": nip, "quote": nip_quote},
        "tytul": {"value": tytul, "quote": tytul_quote},
    }


def run(llm, mode="hybrid", text=TEXT):
    return extract(doc(text), CFG, llm, mode, 85)


def test_hybrid_normalizes_value(fake_llm):
    result = run(fake_llm([raw("527-000-00-00")]))
    assert result.data["nip"] == "5270000000"
    assert result.retries == 0
    assert result.nulled == []


def test_llm_only_leaves_value_raw(fake_llm):
    result = run(fake_llm([raw("527-000-00-00")]), mode="llm_only")
    assert result.data["nip"] == "527-000-00-00"
    assert result.nulled == []


def test_llm_only_does_not_retry_for_format(fake_llm):
    llm = fake_llm([raw("123", nip_quote="527-000-00-00")])
    result = run(llm, mode="llm_only")
    assert len(llm.calls) == 1
    assert result.data["nip"] == "123"


def test_invalid_format_retried_once_then_nulled(fake_llm):
    llm = fake_llm([raw("123"), raw("123")])
    result = run(llm)
    assert len(llm.calls) == 2
    assert result.retries == 1
    assert result.data["nip"] is None
    assert "nip" in result.nulled
    assert "nip" in llm.calls[1]["user"]


def test_retry_fixes_value(fake_llm):
    result = run(fake_llm([raw("123"), raw("527-000-00-00")]))
    assert result.data["nip"] == "5270000000"
    assert result.nulled == []
    assert result.retries == 1


def test_bad_citation_flagged_not_nulled(fake_llm):
    bad = raw("527-000-00-00", tytul="T", tytul_quote="tego cytatu nie ma w dokumencie wcale")
    result = run(fake_llm([bad, bad]))
    assert result.data["tytul"] == "T"
    assert result.citation_ok["tytul"] is False
    assert result.citation_ok["nip"] is True
    assert result.retries == 1


def test_good_citation_ok(fake_llm):
    result = run(fake_llm([raw("527-000-00-00")]))
    assert result.citation_ok == {"nip": True, "tytul": True}
    assert result.quotes["nip"] == "527-000-00-00"


def test_null_value_has_no_citation_entry(fake_llm):
    result = run(fake_llm([raw(None, None, None, None)]))
    assert result.data == {"nip": None, "tytul": None}
    assert result.citation_ok == {}
    assert result.retries == 0


def test_retry_failure_keeps_first_result(fake_llm):
    llm = fake_llm([raw("527-000-00-00", tytul="T", tytul_quote="brak w tekście zupełnie"), LLMError("x")])
    result = run(llm)
    assert result.data["tytul"] == "T"
    assert result.retries == 1


def test_rules_and_examples_in_prompt(fake_llm):
    llm = fake_llm([raw("527-000-00-00")])
    run(llm)
    system = llm.calls[0]["system"]
    assert "REGUŁA-TESTOWA" in system
    assert "PRZYKŁAD-TEKST" in system
    assert "NIP firmy" in system
    assert llm.calls[0]["user"].startswith("Wykonawca")


def test_truncate_short_text_unchanged():
    assert truncate("krótki") == ("krótki", False)


def test_truncate_keeps_head_and_tail_with_marker():
    text = "H" * 100_000 + "S" * 100_000 + "T" * 100_000
    out, truncated = truncate(text)
    assert truncated is True
    assert len(out) <= MAX_CHARS + 100
    assert out.startswith("H" * int(MAX_CHARS * HEAD_RATIO))
    assert out.endswith("T" * 1000)
    assert "pominięto" in out


def test_truncated_prompt_tells_model_text_incomplete(fake_llm):
    llm = fake_llm([raw(None, None, None, None)])
    result = run(llm, text="x" * 200_000)
    assert result.truncated is True
    assert "niepełny" in llm.calls[0]["system"]
    assert len(llm.calls[0]["user"]) <= MAX_CHARS + 100


def test_extract_long_doc_sets_truncated_and_no_exception(fake_llm):
    result = run(fake_llm([raw(None, None, None, None)]), text="y" * 500_000)
    assert result.truncated is True


def test_short_doc_not_truncated(fake_llm):
    result = run(fake_llm([raw("527-000-00-00")]))
    assert result.truncated is False

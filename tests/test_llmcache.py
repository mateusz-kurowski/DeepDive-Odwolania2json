from src.llm import LLMError
from src.llmcache import DiskCachedLLM

SCHEMA = {"type": "object"}


def test_second_identical_call_served_from_disk(tmp_path, fake_llm):
    inner = fake_llm([{"a": 1}])
    llm = DiskCachedLLM(inner, tmp_path / "cache", model="m", params={})
    assert llm.complete_json("s", "u", SCHEMA, "n") == {"a": 1}
    assert llm.complete_json("s", "u", SCHEMA, "n") == {"a": 1}
    assert len(inner.calls) == 1
    assert llm.stats() == {"hits": 1, "misses": 1}


def test_cache_survives_new_instance(tmp_path, fake_llm):
    DiskCachedLLM(fake_llm([{"a": 1}]), tmp_path, model="m", params={}).complete_json(
        "s", "u", SCHEMA, "n"
    )
    inner = fake_llm([])
    assert DiskCachedLLM(inner, tmp_path, model="m", params={}).complete_json(
        "s", "u", SCHEMA, "n"
    ) == {"a": 1}
    assert inner.calls == []


def test_key_depends_on_model_prompt_and_schema(tmp_path, fake_llm):
    llm = DiskCachedLLM(fake_llm([]), tmp_path, model="m", params={})
    base = llm.key("s", "u", SCHEMA, "n")
    assert base != llm.key("s2", "u", SCHEMA, "n")
    assert base != llm.key("s", "u2", SCHEMA, "n")
    assert base != llm.key("s", "u", {"type": "array"}, "n")
    other = DiskCachedLLM(fake_llm([]), tmp_path, model="m2", params={})
    assert base != other.key("s", "u", SCHEMA, "n")


def test_empty_and_failed_responses_not_stored(tmp_path, fake_llm):
    import pytest

    inner = fake_llm([{}, LLMError("pusta"), {"a": 2}])
    llm = DiskCachedLLM(inner, tmp_path, model="m", params={})
    assert llm.complete_json("s", "u", SCHEMA, "n") == {}
    with pytest.raises(LLMError):
        llm.complete_json("s", "u", SCHEMA, "n")
    assert llm.complete_json("s", "u", SCHEMA, "n") == {"a": 2}
    assert len(inner.calls) == 3
    assert list(tmp_path.glob("*.tmp")) == []

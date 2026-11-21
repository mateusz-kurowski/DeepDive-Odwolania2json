from types import SimpleNamespace

import openai
import pytest

from src.llm import LLMError, OpenAICompatLLM
from src.settings import Settings

SCHEMA = {"type": "object", "properties": {}, "additionalProperties": False}


def completion(content):
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))])


class FakeClient:
    def __init__(self, items):
        self.items = list(items)
        self.kwargs: list[dict] = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        self.kwargs.append(kwargs)
        item = self.items.pop(0)
        if isinstance(item, Exception):
            raise item
        return completion(item)


def fake_response(status: int):
    return SimpleNamespace(status_code=status, headers={}, request=SimpleNamespace())


def rate_limit():
    return openai.RateLimitError("limit", response=fake_response(429), body=None)


def make(items, **kw):
    sleeps: list[float] = []
    client = FakeClient(items)
    llm = OpenAICompatLLM(Settings(llm_model="m"), client=client, sleep=sleeps.append, **kw)
    return llm, client, sleeps


def test_returns_parsed_json():
    llm, _, _ = make(['{"a": 1}'])
    assert llm.complete_json("sys", "usr", SCHEMA, "demo") == {"a": 1}


def test_retries_on_429_then_succeeds():
    llm, client, sleeps = make([rate_limit(), '{"a": 1}'])
    assert llm.complete_json("s", "u", SCHEMA, "demo") == {"a": 1}
    assert len(client.kwargs) == 2
    assert len(sleeps) == 1


def test_retries_on_invalid_json():
    llm, client, _ = make(["to nie json", '{"a": 2}'])
    assert llm.complete_json("s", "u", SCHEMA, "demo") == {"a": 2}
    assert len(client.kwargs) == 2


def test_raises_llmerror_after_max_attempts():
    llm, client, sleeps = make([rate_limit()] * 3, max_attempts=3)
    with pytest.raises(LLMError):
        llm.complete_json("s", "u", SCHEMA, "demo")
    assert len(client.kwargs) == 3
    assert len(sleeps) == 2


def test_non_retriable_error_raises_immediately():
    err = openai.AuthenticationError("bad key", response=fake_response(401), body=None)
    llm, client, _ = make([err, '{"a": 1}'])
    with pytest.raises(LLMError):
        llm.complete_json("s", "u", SCHEMA, "demo")
    assert len(client.kwargs) == 1


def test_sends_json_schema_response_format():
    llm, client, _ = make(['{"a": 1}'])
    llm.complete_json("sys", "usr", SCHEMA, "demo")
    kw = client.kwargs[0]
    assert kw["model"] == "m"
    assert kw["temperature"] == 0
    assert kw["response_format"] == {
        "type": "json_schema",
        "json_schema": {"name": "demo", "schema": SCHEMA, "strict": True},
    }
    assert kw["messages"] == [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "usr"},
    ]


def bad_request(message):
    return openai.BadRequestError(message, response=fake_response(400), body=None)


def test_falls_back_to_json_object_when_json_schema_unsupported():
    llm, client, _ = make(
        [bad_request("response_format json_schema is not supported"), '{"a": 1}', '{"a": 2}']
    )
    assert llm.complete_json("sys", "usr", SCHEMA, "demo") == {"a": 1}
    fallback = client.kwargs[1]
    assert fallback["response_format"] == {"type": "json_object"}
    assert '"additionalProperties"' in fallback["messages"][0]["content"]
    assert fallback["messages"][0]["content"].startswith("sys")
    # kolejne wywołania od razu w trybie json_object
    assert llm.complete_json("sys", "usr", SCHEMA, "demo") == {"a": 2}
    assert client.kwargs[2]["response_format"] == {"type": "json_object"}


def test_unrelated_bad_request_is_not_swallowed():
    llm, client, _ = make([bad_request("context length exceeded"), '{"a": 1}'])
    with pytest.raises(LLMError):
        llm.complete_json("s", "u", SCHEMA, "demo")
    assert len(client.kwargs) == 1


def test_describe_response_reports_empty_content_diagnostics():
    from src.llm import describe_response

    response = SimpleNamespace(
        choices=[
            SimpleNamespace(
                finish_reason="length",
                message=SimpleNamespace(content="", reasoning_content="myślę...", refusal=None),
            )
        ],
        usage=SimpleNamespace(
            prompt_tokens=100,
            completion_tokens=8192,
            completion_tokens_details=SimpleNamespace(reasoning_tokens=8192),
        ),
    )
    info = describe_response(response)
    assert info["finish_reason"] == "length"
    assert info["content_len"] == 0
    assert info["reasoning_len"] == len("myślę...")
    assert info["completion_tokens"] == 8192
    assert info["reasoning_tokens"] == 8192


def test_empty_response_logs_diagnostics(caplog):
    llm, _, _ = make(["", '{"a": 1}'])
    with caplog.at_level("WARNING"):
        assert llm.complete_json("s", "u", SCHEMA, "demo") == {"a": 1}
    assert "finish_reason" in caplog.text

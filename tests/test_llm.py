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


def make(items, params=None, **kw):
    sleeps: list[float] = []
    client = FakeClient(items)
    llm = OpenAICompatLLM(
        Settings(llm_model="m"),
        client=client,
        sleep=sleeps.append,
        params={} if params is None else params,
        **kw,
    )
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


def test_empty_response_then_valid_succeeds_with_different_request():
    llm, client, sleeps = make(["", '{"a": 1}'])
    assert llm.complete_json("s", "u", SCHEMA, "demo") == {"a": 1}
    first, second = client.kwargs
    assert first["temperature"] == 0
    assert "extra_body" not in first
    assert second["temperature"] > 0
    assert second["extra_body"]["cache"] == {"no-cache": True, "no-store": True}
    assert second["response_format"]["type"] == "json_schema"
    assert sleeps == [3.0]


def test_attempts_vary_and_last_uses_json_object():
    llm, client, sleeps = make(["", "", "", '{"a": 1}'])
    assert llm.complete_json("sys", "u", SCHEMA, "demo") == {"a": 1}
    formats = [kw["response_format"]["type"] for kw in client.kwargs]
    assert formats == ["json_schema", "json_schema", "json_schema", "json_object"]
    assert '"additionalProperties"' in client.kwargs[3]["messages"][0]["content"]
    assert all("cache" in kw["extra_body"] for kw in client.kwargs[1:])
    assert sleeps == [3.0, 6.0, 12.0]


def test_attempt_plan():
    from src.llm import attempt_plan

    first = attempt_plan(0, 4, 0.0)
    assert (first.temperature, first.no_cache, first.json_object) == (0.0, False, False)
    second = attempt_plan(1, 4, 0.0)
    assert second.temperature == 0.2 and second.no_cache and not second.json_object
    assert attempt_plan(3, 4, 0.0).json_object
    assert not attempt_plan(1, 2, 0.0).json_object


def test_config_params_are_sent():
    params = {"temperature": 0, "max_tokens": 8192, "extra_body": {"reasoning": {"enabled": False}}}
    llm, client, _ = make(['{"a": 1}'], params=params)
    llm.complete_json("s", "u", SCHEMA, "demo")
    kw = client.kwargs[0]
    assert kw["max_tokens"] == 8192
    assert kw["extra_body"] == {"reasoning": {"enabled": False}}


def test_retry_keeps_config_extra_body_and_adds_no_cache():
    params = {"extra_body": {"reasoning": {"enabled": False}}}
    llm, client, _ = make(["", '{"a": 1}'], params=params)
    llm.complete_json("s", "u", SCHEMA, "demo")
    assert client.kwargs[1]["extra_body"] == {
        "reasoning": {"enabled": False},
        "cache": {"no-cache": True, "no-store": True},
    }
    assert params == {"extra_body": {"reasoning": {"enabled": False}}}


def test_rejected_config_extra_body_is_dropped():
    params = {"extra_body": {"provider": {"require_parameters": True}}}
    llm, client, _ = make(
        [bad_request("Unrecognized request argument: provider"), '{"a": 1}'], params=params
    )
    assert llm.complete_json("s", "u", SCHEMA, "demo") == {"a": 1}
    assert "extra_body" not in client.kwargs[1]
    assert "extra_body" not in llm.params


def test_load_llm_params_reads_extraction_section(tmp_path):
    from src.llm import load_llm_params

    path = tmp_path / "llm.json"
    path.write_text(
        '{"extraction": {"temperature": 0, "max_tokens": 4096, "response_format": {}, '
        '"extra_body": {"reasoning": {"enabled": false}}, "validation": {}}}',
        encoding="utf-8",
    )
    assert load_llm_params(path) == {
        "temperature": 0,
        "max_tokens": 4096,
        "extra_body": {"reasoning": {"enabled": False}},
    }


def test_load_llm_params_missing_file_gives_defaults(tmp_path):
    from src.llm import load_llm_params

    assert load_llm_params(tmp_path / "brak.json") == {}


def test_llm_config_path_from_env():
    settings = Settings.from_env({"LLM_CONFIG": "inny/llm.json"})
    assert str(settings.llm_config) == "inny/llm.json"


def test_unrelated_bad_request_keeps_config_extra_body():
    params = {"extra_body": {"reasoning": {"enabled": False}}}
    llm, client, _ = make([bad_request("context length exceeded")], params=params)
    with pytest.raises(LLMError):
        llm.complete_json("s", "u", SCHEMA, "demo")
    assert llm.params["extra_body"] == {"reasoning": {"enabled": False}}
    assert len(client.kwargs) == 1

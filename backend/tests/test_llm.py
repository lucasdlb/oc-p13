import json

import httpx
import pytest

from backend.app.core.settings import LLMSettings
from backend.app.services.llm import (
    FakeLLMProvider,
    LLMProviderEmptyError,
    LLMProviderError,
    LLMProviderLengthError,
    LLMProviderTimeoutError,
    OpenAICompatLLMProvider,
    OllamaLLMProvider,
)


def _provider(handler, **overrides: object) -> OllamaLLMProvider:
    client = httpx.Client(transport=httpx.MockTransport(handler))
    return OllamaLLMProvider(LLMSettings(**overrides), client=client)  # type: ignore[arg-type]


def _openai_provider(handler, **overrides: object) -> OpenAICompatLLMProvider:
    client = httpx.Client(transport=httpx.MockTransport(handler))
    settings = LLMSettings(
            provider="mistral",
        base_url="https://api.mistral.ai/v1",
        api_key="mistral-test-key",
        **overrides,
    )
    return OpenAICompatLLMProvider(settings, client=client)


def test_generate_posts_prompt_and_returns_text() -> None:
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content))
        return httpx.Response(200, json={"response": "Explication."})

    provider = _provider(handler)
    result = provider.generate("Explique l'Espagnole.", system="Coach contraint.")

    assert result == "Explication."
    assert captured["model"] == "qwen2.5:7b-instruct"
    assert captured["prompt"] == "Explique l'Espagnole."
    assert captured["system"] == "Coach contraint."
    assert captured["stream"] is False
    assert captured["options"]["temperature"] == 0.2
    assert captured["options"]["num_predict"] == 512
    assert captured["options"]["num_ctx"] == 4096
    assert "seed" not in captured["options"]
    assert captured["think"] is False
    assert captured["keep_alive"] == "5m"


def test_warmup_loads_model_without_streaming_completion() -> None:
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content))
        return httpx.Response(200, json={"response": " "})

    _provider(handler).warmup()

    assert captured["model"] == "qwen2.5:7b-instruct"
    assert captured["prompt"] == " "
    assert captured["stream"] is False
    assert captured["options"] == {"num_predict": 1, "num_ctx": 4096}
    assert captured["keep_alive"] == "5m"


def test_generate_posts_optional_seed_and_thinking_mode() -> None:
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content))
        return httpx.Response(200, json={"response": "Explication."})

    _provider(handler, think=True, seed=123).generate("prompt")

    assert captured["think"] is True
    assert captured["options"]["seed"] == 123


def test_generate_raises_on_http_error() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text="unavailable")

    with pytest.raises(LLMProviderError):
        _provider(handler).generate("hi")


def test_generate_raises_on_empty_response() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"response": "   "})

    with pytest.raises(LLMProviderEmptyError):
        _provider(handler).generate("hi")


def test_generate_raises_when_ollama_stops_for_length() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"response": "Texte tronque", "done_reason": "length"})

    with pytest.raises(LLMProviderLengthError, match="length"):
        _provider(handler).generate("hi")


def test_fake_provider_returns_canned_response_and_records_prompts() -> None:
    provider = FakeLLMProvider(response="Reponse sourcee.")

    assert provider.generate("prompt 1") == "Reponse sourcee."
    assert provider.generate("prompt 2", system="sys") == "Reponse sourcee."
    assert provider.prompts == ["prompt 1", "prompt 2"]
    assert provider.systems == [None, "sys"]


def test_fake_provider_can_queue_responses_and_errors() -> None:
    provider = FakeLLMProvider(responses=["premiere", LLMProviderError("boom"), "troisieme"])

    assert provider.generate("prompt 1") == "premiere"
    with pytest.raises(LLMProviderError, match="boom"):
        provider.generate("prompt 2")
    assert provider.generate("prompt 3") == "troisieme"


def test_generate_raises_on_timeout() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        raise httpx.TimeoutException("timed out", request=None)

    with pytest.raises(LLMProviderTimeoutError, match="timed out"):
        _provider(handler).generate("hi")


def test_generate_raises_on_malformed_json() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="not json")

    with pytest.raises(LLMProviderError):
        _provider(handler).generate("hi")


def test_openai_compat_generate_posts_chat_completion() -> None:
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content))
        assert request.url.path == "/v1/chat/completions"
        assert request.headers["authorization"] == "Bearer mistral-test-key"
        return httpx.Response(
            200,
            json={
                "choices": [
                    {"message": {"content": "Explication Mistral."}, "finish_reason": "stop"}
                ]
            },
        )

    result = _openai_provider(handler).generate("Explique l'Espagnole.", system="Coach contraint.")

    assert result == "Explication Mistral."
    assert captured == {
        "model": "mistral-large-latest",
        "messages": [
            {"role": "system", "content": "Coach contraint."},
            {"role": "user", "content": "Explique l'Espagnole."},
        ],
        "temperature": 0.2,
        "max_tokens": 512,
        "stream": False,
    }


def test_openai_compat_can_disable_thinking() -> None:
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content))
        return httpx.Response(200, json={"choices": [{"message": {"content": "Rapide."}}]})

    _openai_provider(handler, thinking=False).generate("prompt")

    assert captured["thinking"] == {"type": "disabled"}
    assert "reasoning_effort" not in captured


def test_openai_compat_can_set_reasoning_effort() -> None:
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content))
        return httpx.Response(200, json={"choices": [{"message": {"content": "Analyse."}}]})

    _openai_provider(handler, reasoning_effort="low").generate("prompt")

    assert captured["reasoning_effort"] == "low"
    assert "thinking" not in captured


def test_openai_compat_can_disable_deepseek_reasoning() -> None:
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content))
        return httpx.Response(200, json={"choices": [{"message": {"content": "API_OK"}}]})

    _openai_provider(handler, reasoning_effort="none").generate("prompt")

    assert captured["reasoning_effort"] == "none"
    assert "thinking" not in captured


def test_openai_compat_can_disable_nemotron_thinking() -> None:
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content))
        return httpx.Response(200, json={"choices": [{"message": {"content": "API_OK"}}]})

    _openai_provider(handler, enable_thinking=False).generate("prompt")

    assert captured["chat_template_kwargs"] == {"enable_thinking": False}
    assert "thinking" not in captured
    assert "reasoning_effort" not in captured


def test_openai_compat_retries_transient_status_errors() -> None:
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(429, json={"error": "busy"})
        return httpx.Response(200, json={"choices": [{"message": {"content": "Reponse."}}]})

    provider = _openai_provider(handler, retry_backoff_seconds=0.001)

    assert provider.generate("prompt") == "Reponse."
    assert calls == 2


def test_openai_compat_does_not_retry_client_errors() -> None:
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(400, json={"error": "invalid"})

    with pytest.raises(LLMProviderError):
        _openai_provider(handler, retry_backoff_seconds=0.001).generate("prompt")

    assert calls == 1


def test_openai_compat_stream_retries_before_first_token() -> None:
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(503, json={"error": "busy"})
        body = 'data: {"choices":[{"delta":{"content":"Reponse."}}]}\n\ndata: [DONE]\n\n'
        return httpx.Response(200, text=body, headers={"content-type": "text/event-stream"})

    chunks = list(_openai_provider(handler, retry_backoff_seconds=0.001).generate_stream("prompt"))

    assert chunks == ["Reponse."]
    assert calls == 2


def test_openai_compat_rejects_conflicting_reasoning_controls() -> None:
    with pytest.raises(ValueError, match="mutually exclusive"):
        _openai_provider(handler=lambda _request: httpx.Response(200), thinking=False, reasoning_effort="low")


def test_openai_compat_stream_yields_sse_content() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        body = (
            'data: {"choices":[{"delta":{"content":"Premiere "},"finish_reason":null}]}\n\n'
            'data: {"choices":[{"delta":{"content":"phrase."},"finish_reason":"stop"}]}\n\n'
            "data: [DONE]\n\n"
        )
        return httpx.Response(200, text=body, headers={"content-type": "text/event-stream"})

    chunks = list(_openai_provider(handler).generate_stream("prompt"))

    assert chunks == ["Premiere ", "phrase."]


def test_openai_compat_stream_ignores_empty_choices_usage_chunk() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        body = (
            'data: {"choices":[{"delta":{"content":"Premiere "}}]}\n\n'
            'data: {"choices":[{"delta":{"content":"phrase."}}]}\n\n'
            'data: {"choices":[],"usage":{"completion_tokens":2}}\n\n'
            "data: [DONE]\n\n"
        )
        return httpx.Response(200, text=body, headers={"content-type": "text/event-stream"})

    chunks = list(_openai_provider(handler).generate_stream("prompt"))

    assert chunks == ["Premiere ", "phrase."]


def test_openai_compat_keeps_nonempty_text_when_generation_stops_for_length() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [
                    {"message": {"content": "Texte tronque"}, "finish_reason": "length"}
                ]
            },
        )

    assert _openai_provider(handler).generate("hi") == "Texte tronque"


def test_openai_compat_raises_on_empty_completion() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"choices": [{"message": {"content": "   "}}]})

    with pytest.raises(LLMProviderEmptyError):
        _openai_provider(handler).generate("hi")


def test_openai_compat_raises_on_timeout() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        raise httpx.TimeoutException("timed out", request=None)

    with pytest.raises(LLMProviderTimeoutError, match="timed out"):
        _openai_provider(handler).generate("hi")

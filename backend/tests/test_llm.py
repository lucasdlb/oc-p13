import json

import httpx
import pytest

from backend.app.core.settings import LLMSettings
from backend.app.services.llm import (
    FakeLLMProvider,
    LLMProviderError,
    OllamaLLMProvider,
)


def _provider(handler, **overrides: object) -> OllamaLLMProvider:
    client = httpx.Client(transport=httpx.MockTransport(handler))
    return OllamaLLMProvider(LLMSettings(**overrides), client=client)  # type: ignore[arg-type]


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

    with pytest.raises(LLMProviderError):
        _provider(handler).generate("hi")


def test_generate_raises_when_ollama_stops_for_length() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"response": "Texte tronque", "done_reason": "length"})

    with pytest.raises(LLMProviderError, match="length"):
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

    with pytest.raises(LLMProviderError, match="timed out"):
        _provider(handler).generate("hi")


def test_generate_raises_on_malformed_json() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="not json")

    with pytest.raises(LLMProviderError):
        _provider(handler).generate("hi")

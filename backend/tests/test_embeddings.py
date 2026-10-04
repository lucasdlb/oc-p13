import json

import httpx
import pytest

from backend.app.core.settings import EmbeddingsSettings
from backend.app.services.embeddings import (
    EmbeddingProviderError,
    FakeEmbeddingProvider,
    OllamaEmbeddingProvider,
)


def _settings(**overrides: object) -> EmbeddingsSettings:
    return EmbeddingsSettings(**overrides)  # type: ignore[arg-type]


def _provider(handler, **overrides: object) -> OllamaEmbeddingProvider:
    client = httpx.Client(transport=httpx.MockTransport(handler))
    return OllamaEmbeddingProvider(_settings(**overrides), client=client)


def test_embed_documents_batches_requests() -> None:
    requests: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        requests.append(payload)
        return httpx.Response(200, json={"embeddings": [[0.1] * 1024 for _ in payload["input"]]})

    provider = _provider(handler, batch_size=2)
    vectors = provider.embed_documents(["a", "b", "c", "d", "e"])

    assert len(vectors) == 5
    assert [len(payload["input"]) for payload in requests] == [2, 2, 1]
    assert requests[0]["model"] == "qwen3-embedding:0.6b"
    assert requests[0]["dimensions"] == 1024
    assert requests[0]["keep_alive"] == "5m"
    assert requests[0]["truncate"] is False


def test_embed_query_applies_english_instruction_prefix() -> None:
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content))
        return httpx.Response(200, json={"embeddings": [[0.0] * 1024]})

    provider = _provider(handler)
    provider.embed_query("defense sicilienne najdorf")

    assert captured["input"] == [
        "Instruct: Given a web search query, retrieve relevant passages "
        "that answer the query\nQuery: defense sicilienne najdorf"
    ]


def test_embed_documents_do_not_apply_query_instruction_prefix() -> None:
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content))
        return httpx.Response(200, json={"embeddings": [[0.0] * 1024]})

    provider = _provider(handler)
    provider.embed_documents(["defense sicilienne najdorf"])

    assert captured["input"] == ["defense sicilienne najdorf"]


def test_embed_raises_on_http_error() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="boom")

    provider = _provider(handler)

    with pytest.raises(EmbeddingProviderError):
        provider.embed_documents(["a"])


def test_embed_raises_on_wrong_dimension() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"embeddings": [[0.0, 0.0]]})

    provider = _provider(handler)

    with pytest.raises(EmbeddingProviderError):
        provider.embed_documents(["a"])


@pytest.mark.parametrize(
    "element",
    ["nan", None, True, "0.5"],
)
def test_embed_raises_on_malformed_vector_element(element: object) -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        vector = [0.0] * 1023 + [element]
        return httpx.Response(200, json={"embeddings": [vector]})

    provider = _provider(handler)

    with pytest.raises(EmbeddingProviderError):
        provider.embed_documents(["a"])


def test_embed_raises_on_non_finite_element() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        vector = [0.0] * 1023 + [float("inf")]
        return httpx.Response(200, json={"embeddings": [vector]})

    provider = _provider(handler)

    with pytest.raises(EmbeddingProviderError):
        provider.embed_documents(["a"])


def test_embed_coerces_integer_elements_to_float() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"embeddings": [[0] * 1024]})

    provider = _provider(handler)
    vector = provider.embed_documents(["a"])[0]

    assert all(isinstance(value, float) for value in vector)


def test_model_digest_reads_the_tag_revision() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "models": [
                    {"name": "other:latest", "digest": "abc"},
                    {"name": "qwen3-embedding:0.6b", "digest": "sha256:deadbeef"},
                ]
            },
        )

    provider = _provider(handler)

    assert provider.model_digest() == "sha256:deadbeef"


def test_model_digest_matches_untagged_configured_model_to_latest() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"models": [{"name": "qwen3-embedding:latest", "digest": "sha256:latest"}]},
        )

    provider = _provider(handler, model="qwen3-embedding")

    assert provider.model_digest() == "sha256:latest"


def test_model_digest_is_none_when_unavailable() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="boom")

    assert _provider(handler).model_digest() is None


@pytest.mark.parametrize(
    ("size", "size_vram", "processor"),
    [
        (1_000, 0, "cpu"),
        (1_000, 1_000, "gpu"),
        (1_000, 600, "mixed"),
    ],
)
def test_runtime_info_detects_loaded_model_processor(
    size: int,
    size_vram: int,
    processor: str,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/tags":
            return httpx.Response(
                200,
                json={
                    "models": [
                        {"name": "qwen3-embedding:0.6b", "digest": "sha256:deadbeef"}
                    ]
                },
            )
        if request.url.path == "/api/ps":
            return httpx.Response(
                200,
                json={
                    "models": [
                        {
                            "name": "qwen3-embedding:0.6b",
                            "size": size,
                            "size_vram": size_vram,
                        }
                    ]
                },
            )
        if request.url.path == "/api/version":
            return httpx.Response(200, json={"version": "0.35.0"})
        raise AssertionError(request.url.path)

    runtime = _provider(handler).runtime_info()

    assert runtime.processor == processor
    assert runtime.model_digest == "sha256:deadbeef"
    assert runtime.vram_bytes == size_vram
    assert runtime.ollama_version == "0.35.0"


def test_runtime_info_matches_untagged_configured_model_to_latest() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/tags":
            return httpx.Response(
                200,
                json={"models": [{"name": "qwen3-embedding:latest", "digest": "sha256:latest"}]},
            )
        if request.url.path == "/api/ps":
            return httpx.Response(
                200,
                json={"models": [{"name": "qwen3-embedding:latest", "size": 100, "size_vram": 100}]},
            )
        if request.url.path == "/api/version":
            return httpx.Response(200, json={"version": "0.35.0"})
        raise AssertionError(request.url.path)

    runtime = _provider(handler, model="qwen3-embedding").runtime_info()

    assert runtime.processor == "gpu"
    assert runtime.model_digest == "sha256:latest"


def test_runtime_info_is_unknown_for_malformed_responses() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/tags":
            return httpx.Response(200, json={"models": "invalid"})
        if request.url.path == "/api/ps":
            return httpx.Response(200, json={"models": [{"name": 42, "size": -1}]})
        if request.url.path == "/api/version":
            return httpx.Response(200, json={"version": 35})
        raise AssertionError(request.url.path)

    runtime = _provider(handler).runtime_info()

    assert runtime.processor == "unknown"
    assert runtime.model_digest is None
    assert runtime.vram_bytes is None
    assert runtime.ollama_version is None


def test_runtime_info_is_unknown_when_ollama_is_unavailable() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text="unavailable")

    runtime = _provider(handler).runtime_info()

    assert runtime.processor == "unknown"
    assert runtime.model_digest is None
    assert runtime.vram_bytes is None
    assert runtime.ollama_version is None


def test_fake_provider_is_deterministic_normalized_and_distinct() -> None:
    provider = FakeEmbeddingProvider(dimension=16)

    first = provider.embed_documents(["ruy lopez opening"])[0]
    again = provider.embed_documents(["ruy lopez opening"])[0]
    other = provider.embed_documents(["sicilian defence"])[0]

    assert first == again
    assert first != other
    assert len(first) == 16
    assert pytest.approx(sum(value * value for value in first) ** 0.5, abs=1e-9) == 1.0


def test_fake_provider_scores_shared_tokens_higher() -> None:
    provider = FakeEmbeddingProvider(dimension=64)
    query = provider.embed_query("sicilian defence najdorf")
    near = provider.embed_documents(["the sicilian defence najdorf variation"])[0]
    far = provider.embed_documents(["ruy lopez spanish opening"])[0]

    assert _cosine(query, near) > _cosine(query, far)


def _cosine(left: list[float], right: list[float]) -> float:
    return sum(a * b for a, b in zip(left, right))

"""Embedding provider seam.

`EmbeddingProvider` is the interface callers and tests depend on. The Ollama
adapter talks to `/api/embed`; `FakeEmbeddingProvider` is a deterministic,
dependency-free adapter for tests and offline runs. Qwen3 is instruction-aware,
so the query instruction prefix is applied to queries only, never to documents.
"""

import hashlib
import math
import re
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Literal, Protocol, runtime_checkable

import httpx

from backend.app.core.settings import EmbeddingsSettings


class EmbeddingProviderError(RuntimeError):
    """Raised when an embedding provider cannot return usable vectors."""


@dataclass(frozen=True)
class EmbeddingRuntime:
    """Best-effort execution provenance reported by the embedding runtime."""

    processor: Literal["cpu", "gpu", "mixed", "unknown"]
    model_digest: str | None
    vram_bytes: int | None
    ollama_version: str | None


@runtime_checkable
class EmbeddingProvider(Protocol):
    dimension: int

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """Embed documents for indexing. Documents are embedded plain."""

    def embed_query(self, text: str) -> list[float]:
        """Embed a single query, with the provider's query instruction applied."""

    def model_digest(self) -> str | None:
        """Return the model revision when available for provenance."""

    def runtime_info(self) -> EmbeddingRuntime:
        """Return best-effort runtime provenance."""

    def close(self) -> None:
        """Release provider resources."""


class OllamaEmbeddingProvider:
    """`EmbeddingProvider` backed by an Ollama server (`/api/embed`)."""

    def __init__(
        self,
        settings: EmbeddingsSettings,
        client: httpx.Client | None = None,
    ) -> None:
        self._settings = settings
        self.dimension = settings.dimension
        self._owns_client = client is None
        self._client = client or httpx.Client(timeout=settings.timeout_seconds)

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        for batch in _batched(texts, self._settings.batch_size):
            vectors.extend(self._embed(batch))
        return vectors

    def embed_query(self, text: str) -> list[float]:
        prompt = f"Instruct: {self._settings.query_instruction}\nQuery: {text}"
        return self._embed([prompt])[0]

    def available(self) -> bool:
        try:
            response = self._client.get(f"{self._base_url()}/api/tags")
            response.raise_for_status()
        except httpx.HTTPError:
            return False
        return True

    def model_digest(self) -> str | None:
        """Immutable revision of the configured model, for run provenance.

        Ollama tags are mutable; the digest identifies the exact weights that
        produced a benchmark run. Returns `None` when the server or tag is
        unavailable (provenance then records the failure rather than a lie).
        """

        payload = self._get_json("/api/tags")
        models = payload.get("models") if payload is not None else None
        if not isinstance(models, list):
            return None

        for entry in models:
            if not isinstance(entry, dict):
                continue
            if self._matches_model(entry):
                digest = entry.get("digest")
                return digest if isinstance(digest, str) else None
        return None

    def runtime_info(self) -> EmbeddingRuntime:
        """Inspect Ollama's loaded-model state without making it a runtime requirement."""

        processor: Literal["cpu", "gpu", "mixed", "unknown"] = "unknown"
        vram_bytes: int | None = None
        payload = self._get_json("/api/ps")
        models = payload.get("models") if payload is not None else None
        if isinstance(models, list):
            for entry in models:
                if not isinstance(entry, dict) or not self._matches_model(entry):
                    continue
                size = entry.get("size")
                size_vram = entry.get("size_vram")
                if (
                    isinstance(size, int)
                    and not isinstance(size, bool)
                    and size > 0
                    and isinstance(size_vram, int)
                    and not isinstance(size_vram, bool)
                    and 0 <= size_vram <= size
                ):
                    vram_bytes = size_vram
                    if size_vram == 0:
                        processor = "cpu"
                    elif size_vram == size:
                        processor = "gpu"
                    else:
                        processor = "mixed"
                break

        version_payload = self._get_json("/api/version")
        version = version_payload.get("version") if version_payload is not None else None
        return EmbeddingRuntime(
            processor=processor,
            model_digest=self.model_digest(),
            vram_bytes=vram_bytes,
            ollama_version=version if isinstance(version, str) and version else None,
        )

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> "OllamaEmbeddingProvider":
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def _embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []

        try:
            response = self._client.post(
                f"{self._base_url()}/api/embed",
                json={
                    "model": self._settings.model,
                    "input": texts,
                    "dimensions": self._settings.dimension,
                    "keep_alive": self._settings.keep_alive,
                    "truncate": False,
                },
            )
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise EmbeddingProviderError(f"Ollama embedding request failed: {exc}") from exc

        embeddings = payload.get("embeddings") if isinstance(payload, dict) else None
        if not isinstance(embeddings, list) or len(embeddings) != len(texts):
            raise EmbeddingProviderError("Ollama embedding response does not match request size")

        return [_validate_vector(vector, self._settings.dimension) for vector in embeddings]

    def _base_url(self) -> str:
        return self._settings.base_url.rstrip("/")

    def _get_json(self, path: str) -> dict | None:
        try:
            response = self._client.get(f"{self._base_url()}{path}")
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError):
            return None
        return payload if isinstance(payload, dict) else None

    def _matches_model(self, entry: dict[str, object]) -> bool:
        wanted = self._settings.model
        if ":" not in wanted:
            wanted += ":latest"
        return wanted in (entry.get("name"), entry.get("model"))


class FakeEmbeddingProvider:
    """Deterministic hashed bag-of-words embeddings for tests and offline runs.

    Cosine similarity reflects token overlap, so retrieval can be exercised
    without a live model. Vectors are L2-normalized like Ollama's.
    """

    def __init__(self, dimension: int = 1024) -> None:
        self.dimension = dimension

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._vector(text) for text in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._vector(text)

    def model_digest(self) -> str:
        return "fake"

    def runtime_info(self) -> EmbeddingRuntime:
        return EmbeddingRuntime(
            processor="unknown",
            model_digest=self.model_digest(),
            vram_bytes=None,
            ollama_version=None,
        )

    def close(self) -> None:
        pass

    def __enter__(self) -> "FakeEmbeddingProvider":
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def _vector(self, text: str) -> list[float]:
        vector = [0.0] * self.dimension
        for token in _tokenize(text):
            digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
            vector[int.from_bytes(digest, "big") % self.dimension] += 1.0

        norm = math.sqrt(sum(value * value for value in vector))
        if norm == 0.0:
            return vector
        return [value / norm for value in vector]


def _validate_vector(vector: object, dimension: int) -> list[float]:
    if not isinstance(vector, list) or len(vector) != dimension:
        raise EmbeddingProviderError("Ollama returned a vector of unexpected dimension")

    validated: list[float] = []
    for value in vector:
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise EmbeddingProviderError(
                "Ollama returned a non-numeric or non-finite vector element"
            )
        validated.append(float(value))
    return validated


def _batched(items: list[str], size: int) -> Iterator[list[str]]:
    for start in range(0, len(items), size):
        yield items[start : start + size]


def _tokenize(text: str) -> list[str]:
    return [token for token in re.split(r"\W+", text.lower()) if token]

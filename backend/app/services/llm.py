"""LLM provider seam.

`LLMProvider` is the interface the coach depends on. The Ollama adapter talks
to `/api/generate`; `FakeLLMProvider` returns canned text for tests. The model
choice stays behind this seam so a cloud provider can be added later by ADR.
"""

from collections.abc import Sequence
from typing import Protocol, runtime_checkable

import httpx

from backend.app.core.settings import LLMSettings


class LLMProviderError(RuntimeError):
    """Raised when an LLM provider cannot produce a completion."""


@runtime_checkable
class LLMProvider(Protocol):
    def generate(self, prompt: str, *, system: str | None = None) -> str:
        """Return a completion for `prompt`, optionally constrained by `system`."""


class OllamaLLMProvider:
    """`LLMProvider` backed by an Ollama server (`/api/generate`)."""

    def __init__(
        self,
        settings: LLMSettings,
        client: httpx.Client | None = None,
    ) -> None:
        self._settings = settings
        self._owns_client = client is None
        self._client = client or httpx.Client(timeout=settings.timeout_seconds)

    def generate(self, prompt: str, *, system: str | None = None) -> str:
        body: dict[str, object] = {
            "model": self._settings.model,
            "prompt": prompt,
            "stream": False,
            "think": self._settings.think,
            "keep_alive": self._settings.keep_alive,
            "options": {
                "temperature": self._settings.temperature,
                "num_predict": self._settings.max_tokens,
                "num_ctx": self._settings.num_ctx,
            },
        }
        if self._settings.seed is not None:
            options = body["options"]
            assert isinstance(options, dict)
            options["seed"] = self._settings.seed
        if system is not None:
            body["system"] = system

        try:
            response = self._client.post(f"{self._base_url()}/api/generate", json=body)
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise LLMProviderError(f"Ollama generation request failed: {exc}") from exc

        if isinstance(payload, dict) and payload.get("done_reason") == "length":
            raise LLMProviderError("Ollama stopped generation because num_predict length was reached")
        text = payload.get("response") if isinstance(payload, dict) else None
        if not isinstance(text, str) or not text.strip():
            raise LLMProviderError("Ollama returned an empty completion")
        return text

    def available(self) -> bool:
        try:
            response = self._client.get(f"{self._base_url()}/api/tags")
            response.raise_for_status()
        except httpx.HTTPError:
            return False
        return True

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> "OllamaLLMProvider":
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def _base_url(self) -> str:
        return self._settings.base_url.rstrip("/")


class FakeLLMProvider:
    """Deterministic `LLMProvider` for tests: returns a canned response."""

    def __init__(
        self,
        response: str = "",
        *,
        responses: Sequence[str | LLMProviderError] | None = None,
    ) -> None:
        self._response = response
        self._responses = list(responses or [])
        self.prompts: list[str] = []
        self.systems: list[str | None] = []

    def generate(self, prompt: str, *, system: str | None = None) -> str:
        self.prompts.append(prompt)
        self.systems.append(system)
        if self._responses:
            response = self._responses.pop(0)
            if isinstance(response, LLMProviderError):
                raise response
            return response
        return self._response

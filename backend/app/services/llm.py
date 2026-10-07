"""LLM provider seam.

`LLMProvider` is the interface the coach depends on. The Ollama adapter talks
to `/api/generate`, while the OpenAI-compatible adapter talks to
`/chat/completions`; `FakeLLMProvider` returns canned text for tests. The model
choice stays behind this seam.
"""

import json
import time
from collections.abc import Iterator, Sequence
from typing import Protocol, runtime_checkable

import httpx

from backend.app.core.settings import LLMSettings


class LLMProviderError(RuntimeError):
    """Raised when an LLM provider cannot produce a completion."""


class LLMProviderTimeoutError(LLMProviderError):
    """Raised when the provider does not answer before its timeout."""


class LLMProviderEmptyError(LLMProviderError):
    """Raised when the provider returns no usable text."""


class LLMProviderLengthError(LLMProviderError):
    """Raised when the provider stops because its output limit was reached."""


@runtime_checkable
class LLMProvider(Protocol):
    def warmup(self) -> None:
        """Load or validate the configured model before serving requests."""

    def generate(self, prompt: str, *, system: str | None = None) -> str:
        """Return a completion for `prompt`, optionally constrained by `system`."""

    def generate_stream(self, prompt: str, *, system: str | None = None) -> Iterator[str]:
        """Yield completion chunks for `prompt`."""


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

    def warmup(self) -> None:
        """Load the configured model without waiting for a real completion."""
        try:
            response = self._client.post(
                f"{self._base_url()}/api/generate",
                json={
                    "model": self._settings.model,
                    "prompt": " ",
                    "stream": False,
                    "think": self._settings.think,
                    "keep_alive": self._settings.keep_alive,
                    "options": {
                        "num_predict": 1,
                        "num_ctx": self._settings.num_ctx,
                    },
                },
            )
            response.raise_for_status()
        except httpx.TimeoutException as exc:
            raise LLMProviderTimeoutError(f"Ollama warmup timed out: {exc}") from exc
        except httpx.HTTPError as exc:
            raise LLMProviderError(f"Ollama warmup request failed: {exc}") from exc

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
        except httpx.TimeoutException as exc:
            raise LLMProviderTimeoutError(f"Ollama generation timed out: {exc}") from exc
        except (httpx.HTTPError, ValueError) as exc:
            raise LLMProviderError(f"Ollama generation request failed: {exc}") from exc

        if isinstance(payload, dict) and payload.get("done_reason") == "length":
            raise LLMProviderLengthError("Ollama stopped generation because num_predict length was reached")
        text = payload.get("response") if isinstance(payload, dict) else None
        if not isinstance(text, str) or not text.strip():
            raise LLMProviderEmptyError("Ollama returned an empty completion")
        return text

    def generate_stream(self, prompt: str, *, system: str | None = None) -> Iterator[str]:
        body: dict[str, object] = {
            "model": self._settings.model,
            "prompt": prompt,
            "stream": True,
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
            with self._client.stream("POST", f"{self._base_url()}/api/generate", json=body) as response:
                response.raise_for_status()
                yielded = False
                for line in response.iter_lines():
                    if not line:
                        continue
                    payload = json.loads(line)
                    if payload.get("done_reason") == "length":
                        raise LLMProviderLengthError(
                            "Ollama stopped generation because num_predict length was reached"
                        )
                    text = payload.get("response")
                    if isinstance(text, str) and text:
                        yielded = True
                        yield text
        except httpx.TimeoutException as exc:
            raise LLMProviderTimeoutError(f"Ollama streaming request timed out: {exc}") from exc
        except (httpx.HTTPError, ValueError, json.JSONDecodeError) as exc:
            raise LLMProviderError(f"Ollama streaming request failed: {exc}") from exc
        if not yielded:
            raise LLMProviderEmptyError("Ollama returned an empty streamed completion")

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


class OpenAICompatLLMProvider:
    """`LLMProvider` backed by an OpenAI-compatible chat completions API."""

    def __init__(
        self,
        settings: LLMSettings,
        client: httpx.Client | None = None,
    ) -> None:
        if not settings.api_key:
            raise ValueError(f"{settings.provider.upper()}_API_KEY is required for the configured provider")
        self._settings = settings
        self._owns_client = client is None
        self._client = client or httpx.Client(timeout=settings.timeout_seconds)

    def warmup(self) -> None:
        """Cloud providers load models on demand, so no startup call is needed."""

    def generate(self, prompt: str, *, system: str | None = None) -> str:
        try:
            response = self._post_with_retry(prompt, system=system)
            payload = response.json()
        except httpx.TimeoutException as exc:
            raise LLMProviderTimeoutError(f"OpenAI-compatible generation timed out: {exc}") from exc
        except (httpx.HTTPError, ValueError) as exc:
            raise LLMProviderError(f"OpenAI-compatible generation request failed: {exc}") from exc

        return self._completion_text(payload)

    def generate_stream(self, prompt: str, *, system: str | None = None) -> Iterator[str]:
        try:
            yielded = False
            for attempt in range(self._settings.retries + 1):
                try:
                    with self._client.stream(
                        "POST",
                        f"{self._base_url()}/chat/completions",
                        headers=self._headers(),
                        json=self._body(prompt, system=system, stream=True),
                    ) as response:
                        response.raise_for_status()
                        for line in response.iter_lines():
                            if not line or not line.startswith("data:"):
                                continue
                            data = line[len("data:") :].strip()
                            if data == "[DONE]":
                                break
                            payload = json.loads(data)
                            choices = payload.get("choices") if isinstance(payload, dict) else None
                            # NIM emits a final usage chunk with an empty choices list.
                            if not isinstance(choices, list) or not choices:
                                continue
                            if not isinstance(choices[0], dict):
                                raise LLMProviderError("OpenAI-compatible stream returned invalid choices")
                            choice = choices[0]
                            delta = choice.get("delta")
                            text = delta.get("content") if isinstance(delta, dict) else None
                            if isinstance(text, str) and text:
                                yielded = True
                                yield text
                    break
                except httpx.HTTPStatusError as exc:
                    if yielded or not self._should_retry(exc, attempt):
                        raise
                    time.sleep(self._settings.retry_backoff_seconds)
        except httpx.TimeoutException as exc:
            raise LLMProviderTimeoutError(f"OpenAI-compatible streaming request timed out: {exc}") from exc
        except (httpx.HTTPError, ValueError) as exc:
            raise LLMProviderError(f"OpenAI-compatible streaming request failed: {exc}") from exc
        if not yielded:
            raise LLMProviderEmptyError("OpenAI-compatible provider returned an empty streamed completion")

    def available(self) -> bool:
        try:
            response = self._client.get(f"{self._base_url()}/models", headers=self._headers())
            response.raise_for_status()
        except httpx.HTTPError:
            return False
        return True

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> "OpenAICompatLLMProvider":
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def _base_url(self) -> str:
        return self._settings.base_url.rstrip("/")

    def _headers(self) -> dict[str, str]:
        assert self._settings.api_key is not None
        return {"Authorization": f"Bearer {self._settings.api_key.get_secret_value()}"}

    def _post_with_retry(self, prompt: str, *, system: str | None) -> httpx.Response:
        for attempt in range(self._settings.retries + 1):
            try:
                response = self._client.post(
                    f"{self._base_url()}/chat/completions",
                    headers=self._headers(),
                    json=self._body(prompt, system=system, stream=False),
                )
                response.raise_for_status()
                return response
            except httpx.HTTPStatusError as exc:
                if not self._should_retry(exc, attempt):
                    raise
                time.sleep(self._retry_delay(exc.response))
        raise AssertionError("retry loop did not return or raise")

    def _should_retry(self, error: httpx.HTTPStatusError, attempt: int) -> bool:
        return attempt < self._settings.retries and error.response.status_code in {429, 500, 502, 503, 504}

    def _retry_delay(self, response: httpx.Response) -> float:
        retry_after = response.headers.get("Retry-After")
        if retry_after:
            try:
                return max(0.0, float(retry_after))
            except ValueError:
                pass
        return self._settings.retry_backoff_seconds

    def _body(self, prompt: str, *, system: str | None, stream: bool) -> dict[str, object]:
        messages: list[dict[str, str]] = []
        if system is not None:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        body: dict[str, object] = {
            "model": self._settings.model,
            "messages": messages,
            "temperature": self._settings.temperature,
            "max_tokens": self._settings.max_tokens,
            "stream": stream,
        }
        if self._settings.thinking is not None:
            body["thinking"] = {"type": "enabled" if self._settings.thinking else "disabled"}
        if self._settings.enable_thinking is not None:
            body["chat_template_kwargs"] = {"enable_thinking": self._settings.enable_thinking}
        if self._settings.reasoning_effort is not None:
            body["reasoning_effort"] = self._settings.reasoning_effort
        return body

    def _completion_text(self, payload: object) -> str:
        if not isinstance(payload, dict):
            raise LLMProviderError("OpenAI-compatible provider returned an invalid response")
        choices = payload.get("choices")
        if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
            raise LLMProviderEmptyError("OpenAI-compatible provider returned no choices")
        choice = choices[0]
        message = choice.get("message")
        text = message.get("content") if isinstance(message, dict) else None
        if not isinstance(text, str) or not text.strip():
            raise LLMProviderEmptyError("OpenAI-compatible provider returned an empty completion")
        return text


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

    def warmup(self) -> None:
        """Keep the fake compatible with the runtime provider protocol."""

    def generate(self, prompt: str, *, system: str | None = None) -> str:
        self.prompts.append(prompt)
        self.systems.append(system)
        if self._responses:
            response = self._responses.pop(0)
            if isinstance(response, LLMProviderError):
                raise response
            return response
        return self._response

    def generate_stream(self, prompt: str, *, system: str | None = None) -> Iterator[str]:
        self.prompts.append(prompt)
        self.systems.append(system)
        if self._responses:
            response = self._responses.pop(0)
            if isinstance(response, LLMProviderError):
                raise response
            text = response
        else:
            text = self._response
        if not text.strip():
            raise LLMProviderEmptyError("Fake provider returned an empty completion")
        words = text.split(" ")
        for index, word in enumerate(words):
            yield word + (" " if index < len(words) - 1 else "")

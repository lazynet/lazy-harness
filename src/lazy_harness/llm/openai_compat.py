"""OpenAICompatibleBackend — any /v1/chat/completions endpoint (ADR-033).

Covers Ollama, Apple MLX serve, LM Studio, OpenRouter, and any other
provider exposing the OpenAI wire format.
"""

from __future__ import annotations

import httpx

from lazy_harness.llm.base import LLMBackendError, LLMTimeoutError


class OpenAICompatibleBackend:
    def __init__(self, base_url: str, api_key: str = "none") -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key

    @property
    def name(self) -> str:
        return "openai-compatible"

    def default_model(self) -> str:
        # Sensible Ollama default; override via [compound_loop].model.
        return "llama3.2:3b"

    def complete(self, prompt: str, model: str, timeout: int, *, schema: dict | None = None) -> str:
        payload: dict = {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
        }
        if schema is not None:
            # Ollama, MLX and LM Studio all honour this. Verified against a
            # live Ollama: without it a 7B model answers outside a declared
            # enum while still emitting well-formed JSON.
            payload["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": "response", "strict": True, "schema": schema},
            }
        try:
            resp = httpx.post(
                f"{self._base_url}/v1/chat/completions",
                json=payload,
                headers={"Authorization": f"Bearer {self._api_key}"},
                timeout=timeout,
            )
            resp.raise_for_status()
        except httpx.TimeoutException as e:
            raise LLMTimeoutError(str(e) or f"timed out after {timeout}s") from e
        except httpx.HTTPError as e:
            raise LLMBackendError(str(e)) from e
        try:
            content = resp.json()["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError, ValueError) as e:
            raise LLMBackendError(f"unexpected response shape: {e!r}") from e
        if not isinstance(content, str):
            raise LLMBackendError("unexpected response shape: content is not a string")
        return content

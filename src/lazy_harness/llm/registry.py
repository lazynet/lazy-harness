"""LLM backend discovery and resolution (ADR-033)."""

from __future__ import annotations

from lazy_harness.core.config import CompoundLoopConfig
from lazy_harness.llm.base import LLMBackend, LLMBackendError
from lazy_harness.llm.claude import ClaudeBackend
from lazy_harness.llm.openai_compat import OpenAICompatibleBackend


class LLMBackendNotFoundError(Exception):
    """Raised when the configured backend name is not registered."""


_DEFAULT_URLS: dict[str, str] = {
    "ollama": "http://localhost:11434",
    "mlx": "http://localhost:8080",
}

_AVAILABLE = ("claude", "ollama", "mlx", "openai-compatible")


def get_backend(cfg: CompoundLoopConfig) -> LLMBackend:
    """Instantiate the LLM backend configured in [compound_loop].backend."""
    name = cfg.backend
    options = cfg.backend_options

    if name == "claude":
        return ClaudeBackend()
    if name in ("ollama", "mlx", "openai-compatible"):
        base_url = options.get("base_url") or _DEFAULT_URLS.get(name)
        if not base_url:
            raise LLMBackendError(
                f"backend '{name}' requires [compound_loop.backend_options] base_url"
            )
        api_key = options.get("api_key", "none")
        return OpenAICompatibleBackend(base_url=base_url, api_key=api_key)

    raise LLMBackendNotFoundError(
        f"LLM backend '{name}' not found. Available: {', '.join(_AVAILABLE)}"
    )

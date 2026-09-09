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


def build_backend(*, type: str, base_url: str = "", api_key: str = "") -> LLMBackend:
    """Instantiate a backend from its type and options.

    The one place that maps a type name to an implementation. `get_backend`
    and the role-routed seam both come through here so a new provider is added
    once rather than in every caller — the accumulation ADR-033 set out to
    prevent.
    """
    if type == "claude":
        return ClaudeBackend()
    if type in ("ollama", "mlx", "openai-compatible"):
        resolved_url = base_url or _DEFAULT_URLS.get(type, "")
        if not resolved_url:
            raise LLMBackendError(f"backend '{type}' requires a base_url")
        return OpenAICompatibleBackend(base_url=resolved_url, api_key=api_key or "none")

    raise LLMBackendNotFoundError(
        f"LLM backend '{type}' not found. Available: {', '.join(_AVAILABLE)}"
    )


def get_backend(cfg: CompoundLoopConfig) -> LLMBackend:
    """Instantiate the LLM backend configured in [compound_loop].backend.

    The ADR-033 entry point. Retained for the deprecated config form; new
    callers resolve a role and go through `build_backend`.
    """
    options = cfg.backend_options
    try:
        return build_backend(
            type=cfg.backend,
            base_url=options.get("base_url", ""),
            api_key=options.get("api_key", ""),
        )
    except LLMBackendError as e:
        if "requires a base_url" in str(e):
            raise LLMBackendError(
                f"backend '{cfg.backend}' requires [compound_loop.backend_options] base_url"
            ) from e
        raise

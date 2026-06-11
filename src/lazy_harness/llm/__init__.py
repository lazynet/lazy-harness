"""LLM backend abstraction (ADR-033) — provider-agnostic inference."""

from lazy_harness.llm.base import LLMBackend, LLMBackendError
from lazy_harness.llm.registry import LLMBackendNotFoundError, get_backend

__all__ = [
    "LLMBackend",
    "LLMBackendError",
    "LLMBackendNotFoundError",
    "get_backend",
]

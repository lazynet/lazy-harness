"""LLMBackend Protocol — how the framework calls a model (ADR-033).

Structurally parallel to AgentAdapter (ADR-004): the agent is the CLI the
user talks to; the LLM backend is the inference provider the framework uses
internally (compound-loop, grading, memory consolidation).
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


class LLMBackendError(Exception):
    """Raised by a backend on any completion failure (connection, timeout, refusal)."""


class LLMTimeoutError(LLMBackendError):
    """The call exceeded its budget.

    A subclass so every ADR-033 caller catching `LLMBackendError` keeps
    working. It exists because the kind cannot be recovered from the message:
    `str(httpx.ReadTimeout(""))` is empty, and a timeout misreported as
    unreachable takes exit 70 where the contract promises 124.
    """


@runtime_checkable
class LLMBackend(Protocol):
    @property
    def name(self) -> str:
        """Unique identifier, matches the config.toml value."""
        ...

    def default_model(self) -> str:
        """Model identifier to use when the config does not specify one."""
        ...

    def complete(self, prompt: str, model: str, timeout: int, *, schema: dict | None = None) -> str:
        """Run a single-turn completion and return the response text.

        `schema` is a JSON Schema the provider should constrain the answer to.
        A backend that cannot express the constraint accepts and ignores it —
        the caller cannot know which, so it validates the result either way.

        Raises `LLMBackendError` on any failure (connection, timeout,
        content refusal). The caller is responsible for retry logic.
        """
        ...

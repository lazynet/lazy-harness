"""LLMBackend Protocol — how the framework calls a model (ADR-033).

Structurally parallel to AgentAdapter (ADR-004): the agent is the CLI the
user talks to; the LLM backend is the inference provider the framework uses
internally (compound-loop, grading, memory consolidation).
"""

from __future__ import annotations

from dataclasses import dataclass
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


@dataclass(frozen=True)
class ModelUsage:
    """What one model spent on one completion, as the provider reported it.

    The two cache-write TTLs are siblings, not a total and a share: they bill
    at different rates (ADR-065), the same split the transcript reader keeps.
    """

    model: str
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int
    cache_creation_tokens: int
    cache_creation_1h_tokens: int
    #: The provider's own figure, kept for comparison; never the stored cost.
    cost_usd: float | None = None


@dataclass(frozen=True)
class Completion:
    text: str
    #: The provider's id for this one call, or None when it reported none.
    session_id: str | None = None
    service_tier: str | None = None
    usage: tuple[ModelUsage, ...] = ()


@runtime_checkable
class UsageReportingBackend(Protocol):
    """A backend that can say what a completion spent (ADR-033 Evolution).

    Optional: `run_inference` prefers it when present and falls back to
    `LLMBackend.complete`, recording nothing, when it is not.
    """

    def complete_with_usage(
        self, prompt: str, model: str, timeout: int, *, schema: dict | None = None
    ) -> Completion: ...

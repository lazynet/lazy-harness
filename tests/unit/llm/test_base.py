"""Protocol conformance for LLMBackend (ADR-033) — mirrors test_agent_protocol.py."""

from __future__ import annotations


class _StubBackend:
    """Minimal structural implementation of the LLMBackend Protocol."""

    @property
    def name(self) -> str:
        return "stub"

    def default_model(self) -> str:
        return "stub-model"

    def complete(self, prompt: str, model: str, timeout: int) -> str:
        return f"echo:{prompt}"


class _IncompleteBackend:
    """Missing complete() — must NOT satisfy the Protocol."""

    @property
    def name(self) -> str:
        return "incomplete"

    def default_model(self) -> str:
        return "none"


def test_stub_backend_satisfies_protocol() -> None:
    from lazy_harness.llm.base import LLMBackend

    assert isinstance(_StubBackend(), LLMBackend)


def test_incomplete_backend_does_not_satisfy_protocol() -> None:
    from lazy_harness.llm.base import LLMBackend

    assert not isinstance(_IncompleteBackend(), LLMBackend)


def test_llm_backend_error_is_exception() -> None:
    from lazy_harness.llm.base import LLMBackendError

    assert issubclass(LLMBackendError, Exception)

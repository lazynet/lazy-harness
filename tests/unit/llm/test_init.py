"""Public API of the lazy_harness.llm package (ADR-033)."""

from __future__ import annotations


def test_package_reexports_public_api() -> None:
    import lazy_harness.llm as llm
    from lazy_harness.llm import (
        LLMBackend,
        LLMBackendError,
        LLMBackendNotFoundError,
        get_backend,
    )
    from lazy_harness.llm.base import LLMBackend as base_LLMBackend
    from lazy_harness.llm.base import LLMBackendError as base_LLMBackendError
    from lazy_harness.llm.registry import LLMBackendNotFoundError as reg_NotFound
    from lazy_harness.llm.registry import get_backend as reg_get_backend

    assert LLMBackend is base_LLMBackend
    assert LLMBackendError is base_LLMBackendError
    assert LLMBackendNotFoundError is reg_NotFound
    assert get_backend is reg_get_backend
    assert set(llm.__all__) == {
        "LLMBackend",
        "LLMBackendError",
        "LLMBackendNotFoundError",
        "get_backend",
    }

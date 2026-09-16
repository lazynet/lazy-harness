"""Unit tests for `hooks.loader.builtin_operations`."""

from __future__ import annotations

from lazy_harness.agents.base import Operation
from lazy_harness.hooks.loader import builtin_operations


def test_builtin_declaring_operations_returns_them() -> None:
    assert builtin_operations("pre-tool-use-read-size") == frozenset({Operation.READ_FILE})


def test_builtin_declaring_several_operations_returns_all_of_them() -> None:
    assert builtin_operations("pre-tool-use-security") == frozenset(
        {Operation.RUN_COMMAND, Operation.READ_FILE, Operation.MODIFY_FILE}
    )


def test_builtin_declaring_none_returns_the_empty_set() -> None:
    """`compound-loop` never reasons about a tool call at all."""
    assert builtin_operations("compound-loop") == frozenset()


def test_unregistered_name_returns_the_empty_set_rather_than_raising() -> None:
    """A user hook declares no operations; the caller wants that, not an error."""
    assert builtin_operations("a-user-hook-that-is-not-a-builtin") == frozenset()

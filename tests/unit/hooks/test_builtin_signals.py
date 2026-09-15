"""Unit tests for `hooks.loader.builtin_signals`."""

from __future__ import annotations

from lazy_harness.agents.base import Signal
from lazy_harness.hooks.loader import builtin_signals


def test_builtin_declaring_signals_returns_them() -> None:
    assert builtin_signals("stop-verify-guard") == frozenset({Signal.GOAL_STATUS})


def test_builtin_declaring_none_returns_the_empty_set() -> None:
    """`compound-loop` and `session-export` are the deliberate contrast.

    Both run on `session_stop` and both reach a transcript, but only
    `session-export` reads message *text* in its own process. `compound-loop`
    enqueues the path and its worker reads it later, out of process — so
    declaring a signal for it would make `deploy` omit a working hook on any
    agent whose reader cannot supply one it never touches.
    """
    assert builtin_signals("compound-loop") == frozenset()
    assert builtin_signals("session-export") == frozenset({Signal.MESSAGES})


def test_unregistered_name_returns_the_empty_set_rather_than_raising() -> None:
    """A user hook declares no signals; the caller wants that, not an error."""
    assert builtin_signals("a-user-hook-that-is-not-a-builtin") == frozenset()

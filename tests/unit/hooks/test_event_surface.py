"""Unit tests for the per-profile `hook_events()` surface (design step 10).

Mirrors `test_signal_gaps.py`'s shape: a collector per profile, a `collect_*`
wrapper over every selected profile, and `NullAdapter` subclasses standing in
for agents whose `hook_events()` differs from the two real adapters.
"""

from __future__ import annotations

import pytest

from lazy_harness.agents.base import HookSupport, Operation
from lazy_harness.agents.registry import NullAdapter
from lazy_harness.core.config import Config, HookEventConfig, ProfileEntry
from lazy_harness.hooks.event_surface import (
    UncarriedEventHook,
    collect_hook_operation_gaps,
    collect_uncarried_events,
    operation_gaps_for_profile,
    uncarried_events_for_profile,
)


class _NoStopEventAdapter(NullAdapter):
    """Delivers `session_start` only — the event a deployed hook needs is absent."""

    @property
    def name(self) -> str:
        return "no-stop-event"

    def hook_events(self) -> dict[str, HookSupport]:
        return {"session_start": HookSupport(native_name="SessionStart")}


def _cfg(agent: str, hooks: dict[str, HookEventConfig]) -> Config:
    cfg = Config()
    cfg.agent.type = agent
    cfg.profiles.default = "p1"
    cfg.profiles.items = {"p1": ProfileEntry(config_dir="~/.agent-p1", agent=agent)}
    cfg.hooks = hooks
    return cfg


def _register(monkeypatch: pytest.MonkeyPatch, name: str, cls: type) -> None:
    from lazy_harness.agents import registry

    monkeypatch.setitem(registry._AGENTS, name, cls)


def test_claude_code_default_hooks_have_no_operation_gap() -> None:
    """Claude Code's tool map produces every `Operation` a builtin declares."""
    assert operation_gaps_for_profile(_cfg("claude-code", {}), "p1") == []
    assert collect_hook_operation_gaps(_cfg("claude-code", {})) == []


def test_claude_code_default_hooks_have_no_uncarried_event() -> None:
    """Every event a default builtin is wired to is one Claude Code carries."""
    assert uncarried_events_for_profile(_cfg("claude-code", {}), "p1") == []
    assert collect_uncarried_events(_cfg("claude-code", {})) == []


def test_codex_cannot_produce_read_file_so_the_security_hook_is_partially_inert() -> None:
    """Codex's `_TOOL_OPERATIONS` maps no native tool to `READ_FILE` at all.

    `pre-tool-use-security` still gates `RUN_COMMAND` (Bash) and `MODIFY_FILE`
    (`apply_patch`) on Codex — only its read-guarding half never sees a call.
    """
    gaps = operation_gaps_for_profile(_cfg("codex", {}), "p1")
    gap = next(g for g in gaps if g.hook == "pre-tool-use-security")
    assert gap.event == "pre_tool_use"
    assert gap.inert == (Operation.READ_FILE,)
    assert gap.fully_inert is False


def test_codex_cannot_produce_read_file_so_read_size_guard_is_fully_inert() -> None:
    """`pre-tool-use-read-size` declares only `READ_FILE` — its whole reason to
    run — so on Codex it installs, is wired to a tool call that never arrives,
    and passes every time."""
    gaps = operation_gaps_for_profile(_cfg("codex", {}), "p1")
    gap = next(g for g in gaps if g.hook == "pre-tool-use-read-size")
    assert gap.inert == (Operation.READ_FILE,)
    assert gap.fully_inert is True


def test_codex_has_no_operation_gap_for_a_hook_it_fully_covers() -> None:
    gaps = operation_gaps_for_profile(_cfg("codex", {}), "p1")
    assert all(g.hook != "pre-tool-use-git-scope" for g in gaps)
    assert all(g.hook != "post-tool-use-format" for g in gaps)


def test_hook_wired_to_an_event_the_adapter_does_not_deliver_is_uncarried(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _register(monkeypatch, "no-stop-event", _NoStopEventAdapter)
    cfg = _cfg("no-stop-event", {"session_stop": HookEventConfig(scripts=["stop-verify-guard"])})

    gaps = uncarried_events_for_profile(cfg, "p1")

    assert (
        UncarriedEventHook(
            profile="p1", agent="no-stop-event", event="session_stop", hook="stop-verify-guard"
        )
        in gaps
    )


def test_uncarried_events_never_overlap_with_operation_gaps(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The two are the two distinct unsupported states the design refuses to collapse."""
    _register(monkeypatch, "no-stop-event", _NoStopEventAdapter)
    cfg = _cfg("no-stop-event", {"session_stop": HookEventConfig(scripts=["stop-verify-guard"])})

    assert operation_gaps_for_profile(cfg, "p1") == []


def test_collect_functions_are_silent_for_a_profile_with_no_hooks_configured() -> None:
    cfg = _cfg("claude-code", {event: HookEventConfig(scripts=[]) for event in ("session_stop",)})
    assert collect_hook_operation_gaps(cfg) == []
    assert collect_uncarried_events(cfg) == []

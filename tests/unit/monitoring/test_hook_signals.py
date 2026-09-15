"""Unit tests for the per-profile hook signal gap collector."""

from __future__ import annotations

from pathlib import Path

import pytest

from lazy_harness.agents.base import HookSupport, Signal, Verdict
from lazy_harness.agents.registry import NullAdapter
from lazy_harness.core.config import Config, HookEventConfig, ProfileEntry

_STOP = {"session_stop": HookSupport(native_name="Stop", verdicts=frozenset({Verdict.BLOCK}))}


class _NoReaderAdapter(NullAdapter):
    """Delivers the Stop event and implements no `TranscriptReader` at all."""

    @property
    def name(self) -> str:
        return "no-reader"

    def hook_events(self) -> dict[str, HookSupport]:
        return dict(_STOP)


class _PartialReaderAdapter(NullAdapter):
    """Reads transcripts, but its vocabulary has no explicit goal marker."""

    @property
    def name(self) -> str:
        return "partial-reader"

    def hook_events(self) -> dict[str, HookSupport]:
        return dict(_STOP)

    def signals(self) -> set[Signal]:
        return {Signal.MESSAGES, Signal.TOOL_CALLS}

    def locate_sessions(self, config_dir: Path, since: object) -> object:
        return iter(())

    def read(self, path: Path) -> object:
        return iter(())


class _NoStopEventAdapter(NullAdapter):
    """Reads nothing and does not deliver Stop — the *other* unsupported state."""

    @property
    def name(self) -> str:
        return "no-stop-event"

    def hook_events(self) -> dict[str, HookSupport]:
        return {"session_start": HookSupport(native_name="SessionStart")}


def _cfg(agent: str) -> Config:
    cfg = Config()
    cfg.agent.type = agent
    cfg.profiles.default = "p1"
    cfg.profiles.items = {"p1": ProfileEntry(config_dir="~/.agent-p1", agent=agent)}
    cfg.hooks = {"session_stop": HookEventConfig(scripts=["stop-verify-guard"])}
    return cfg


def _register(monkeypatch: pytest.MonkeyPatch, name: str, cls: type) -> None:
    from lazy_harness.agents import registry

    monkeypatch.setitem(registry._AGENTS, name, cls)


def test_adapter_delivering_every_signal_reports_no_gap() -> None:
    from lazy_harness.monitoring.hook_signals import collect_hook_signal_gaps

    assert collect_hook_signal_gaps(_cfg("claude-code")) == []


def test_adapter_without_a_transcript_reader_is_missing_every_declared_signal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from lazy_harness.monitoring.hook_signals import collect_hook_signal_gaps

    _register(monkeypatch, "no-reader", _NoReaderAdapter)
    gaps = collect_hook_signal_gaps(_cfg("no-reader"))

    assert len(gaps) == 1
    gap = gaps[0]
    assert gap.profile == "p1"
    assert gap.agent == "no-reader"
    assert gap.hook == "stop-verify-guard"
    assert gap.event == "session_stop"
    assert gap.missing == (Signal.GOAL_STATUS,)
    assert gap.has_reader is False


def test_reader_delivering_other_signals_still_reports_the_one_it_lacks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from lazy_harness.monitoring.hook_signals import collect_hook_signal_gaps

    _register(monkeypatch, "partial-reader", _PartialReaderAdapter)
    gaps = collect_hook_signal_gaps(_cfg("partial-reader"))

    assert len(gaps) == 1
    assert gaps[0].missing == (Signal.GOAL_STATUS,)
    assert gaps[0].has_reader is True


def test_hook_whose_event_the_agent_lacks_is_not_reported_as_a_missing_signal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The two unsupported states must not collapse into one line.

    `session_stop` absent from `hook_events()` means nothing is installed and
    nothing runs; that waits on the agent's event vocabulary, not on a
    `TranscriptReader`, so this collector does not speak for it.
    """
    from lazy_harness.monitoring.hook_signals import collect_hook_signal_gaps

    _register(monkeypatch, "no-stop-event", _NoStopEventAdapter)
    assert collect_hook_signal_gaps(_cfg("no-stop-event")) == []


def test_hook_declaring_no_signals_reports_no_gap(monkeypatch: pytest.MonkeyPatch) -> None:
    from lazy_harness.monitoring.hook_signals import collect_hook_signal_gaps

    _register(monkeypatch, "no-reader", _NoReaderAdapter)
    cfg = _cfg("no-reader")
    cfg.hooks = {"session_stop": HookEventConfig(scripts=["session-export"])}

    assert collect_hook_signal_gaps(cfg) == []


def test_each_profile_is_resolved_against_its_own_agent(monkeypatch: pytest.MonkeyPatch) -> None:
    from lazy_harness.monitoring.hook_signals import collect_hook_signal_gaps

    _register(monkeypatch, "no-reader", _NoReaderAdapter)
    cfg = _cfg("claude-code")
    cfg.profiles.items["p2"] = ProfileEntry(config_dir="~/.agent-p2", agent="no-reader")

    gaps = collect_hook_signal_gaps(cfg)

    assert [(g.profile, g.hook) for g in gaps] == [("p2", "stop-verify-guard")]

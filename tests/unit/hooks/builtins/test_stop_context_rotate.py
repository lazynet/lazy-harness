"""Tests for the non-blocking context-rotation notice.

The gauge already computes a session's context and paints the pane red at
400k, but nothing acts on it: measured over 72h across both profiles, nine
interactive sessions crossed that threshold and none were rotated. This hook
turns the existing signal into a message the operator actually sees, without
blocking the Stop it rides on.

Since the migration onto the event contract, `main` takes a `HookEvent` and
returns a `HookDecision`: the runner parses the payload and the adapter
serialises the decision, so what is asserted here is the decision rather than
the bytes. The bytes have their own file — `test_stop_context_rotate_goldens.py`
— captured against the pre-migration hook.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from lazy_harness.agents.base import HookEvent, Signal
from lazy_harness.hooks.builtins import stop_context_rotate as hook


def _transcript(tmp_path: Path, *context_totals: int) -> Path:
    """Write a transcript whose assistant turns carry the given context sizes."""
    path = tmp_path / "transcript.jsonl"
    lines = []
    for total in context_totals:
        lines.append(
            json.dumps(
                {
                    "type": "assistant",
                    "message": {
                        "usage": {
                            "input_tokens": total,
                            "cache_read_input_tokens": 0,
                            "cache_creation_input_tokens": 0,
                        }
                    },
                }
            )
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _event(transcript: Path | None, session_id: str = "s") -> HookEvent:
    """A Stop event as the runner hands it over.

    `cwd` is `Path("")` — what `parse_hook_input` yields when the payload names
    none — rather than a plausible directory: this hook reads no cwd, and a
    fixture that supplied one would hide a migration that started to.
    """
    return HookEvent(
        event="session_stop",
        profile="p",
        session_id=session_id,
        cwd=Path(""),
        transcript_path=transcript,
    )


@pytest.fixture(autouse=True)
def _isolated_stamps(tmp_path, monkeypatch):
    """Keep the once-per-session stamp inside the test's own tmp_path.

    Without this the hook writes into the real temp dir, so a stamp left by one
    run silences the notice in the next one — the suite passed alone and failed
    in full, which is the failure this fixture removes.
    """
    monkeypatch.setattr(hook, "stamp_dir", lambda: tmp_path / "stamps")


def test_quiet_below_the_rotate_threshold(tmp_path) -> None:
    """A session under 400k gets no message at all."""
    t = _transcript(tmp_path, 150_000, 380_000)

    decision = hook.main(_event(t, "s-under"))

    assert decision.system_message == ""
    assert decision.verdict is None


def test_warns_above_the_rotate_threshold(tmp_path) -> None:
    """At or above 400k the hook returns a non-blocking system message."""
    t = _transcript(tmp_path, 150_000, 437_000)

    decision = hook.main(_event(t, "s-over"))

    # Non-blocking: the Stop decision must not be touched. `stop` is the
    # decision-level spelling of the same mistake as a `decision: block` body.
    assert decision.verdict is None
    assert decision.stop is False
    assert decision.additional_context == ""

    msg = decision.system_message
    assert "437k" in msg
    assert "/compact" in msg and "/clear" in msg


def test_notice_fires_once_per_session(tmp_path) -> None:
    """Stop runs every turn; the notice must not repeat all the way down.

    Without this the hook shouts on each of the dozens of Stops a long session
    emits, which is how a warning gets tuned out.
    """
    t = _transcript(tmp_path, 437_000)
    event = _event(t, "s-once")

    first = hook.main(event)
    second = hook.main(event)

    assert first.system_message != ""
    assert second.system_message == ""


def test_returns_an_empty_decision_on_a_missing_transcript(tmp_path) -> None:
    """A gauge must never take down the turn it measures.

    The path is *declared* and absent from disk, which is the state
    `existing_transcript` exists to absorb: `HookEvent.transcript_path` is what
    the payload named, not what is there.
    """
    decision = hook.main(_event(tmp_path / "nope.jsonl", "s-gone"))

    assert decision.system_message == ""


def test_returns_an_empty_decision_when_no_transcript_was_declared() -> None:
    """`transcript_path` is `None` whenever the payload named none, or named
    something that was not a non-empty string."""
    decision = hook.main(_event(None, "s-none"))

    assert decision.system_message == ""


def test_returns_an_empty_decision_on_a_transcript_that_is_a_directory(tmp_path) -> None:
    """The blanket fail-open, exercised rather than asserted about.

    `existing_transcript` already rejects a directory, so this is the branch
    below it: whatever `context_tokens` raises on, the hook answers with an
    empty decision rather than with an exception the runner has to catch.
    """
    empty = tmp_path / "empty.jsonl"
    empty.write_text("", encoding="utf-8")

    decision = hook.main(_event(empty, "s-empty"))

    assert decision.system_message == ""


def test_a_session_id_that_is_empty_still_gets_a_stamp(tmp_path) -> None:
    """An absent `session_id` arrives as `""`, which `_stamp_for` names "unknown".

    The notice still goes out — losing the id is no reason to withhold it — but
    it must still fire only once.
    """
    t = _transcript(tmp_path, 437_000)

    first = hook.main(_event(t, ""))
    second = hook.main(_event(t, ""))

    assert first.system_message != ""
    assert second.system_message == ""


def test_registered_as_a_builtin_hook() -> None:
    """An implemented hook does not run until it is wired."""
    from lazy_harness.hooks.loader import list_builtin_hooks

    assert "stop-context-rotate" in list_builtin_hooks()


def test_declares_the_signal_it_reads_and_nothing_more() -> None:
    """`TOKEN_USAGE` alone, and declared as a plain frozenset.

    `deploy` refuses to install a hook whose declared signals the profile's
    agent does not supply, and `signal_gaps.gaps_for_profile` reads the field
    regardless of `migrated` — so a signal this hook does not read in its own
    process would silently undeploy a working hook. It reads exactly one:
    `context_tokens` sums the last assistant turn's usage counters.
    """
    from lazy_harness.hooks.loader import _BUILTIN_HOOKS, builtin_signals

    spec = _BUILTIN_HOOKS["stop-context-rotate"]

    assert builtin_signals("stop-context-rotate") == frozenset({Signal.TOKEN_USAGE})
    assert spec.signals == frozenset({Signal.TOKEN_USAGE})
    assert spec.migrated is True
    assert spec.blocking is False
    assert spec.operations == frozenset()


def test_threshold_is_the_gauge_threshold() -> None:
    """Two readers of one question must resolve it the same way.

    The pane turns red at the gauge's ROTATE_TOKENS; a notice that fired at a
    different number would contradict the colour the operator is looking at.
    """
    from lazy_harness.hooks.builtins.herdr_context_gauge import ROTATE_TOKENS

    assert hook.ROTATE_TOKENS is ROTATE_TOKENS


def test_the_module_compares_against_no_wire_event_name() -> None:
    """Trap 2, pinned rather than checked once by hand.

    `HookEvent.event` carries the canonical `session_stop`; the payload's
    `hook_event_name` carries Claude Code's `Stop`. A comparison left behind
    against the wire name would be permanently false and nothing would fail.
    """
    source = Path(hook.__file__).read_text(encoding="utf-8")

    assert "hook_event_name" not in source
    assert '"Stop"' not in source

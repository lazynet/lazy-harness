"""Tests for the Stop soft-enforcement guard (verify-before-close).

See specs/designs/2026-08-16-loop-engineering-design.md, "Soft enforcement on
`Stop`". The guard fires once per session: if the session declared a goal
(via the native `/goal` command) and no `verify_ran` event exists for it, the
first Stop attempt blocks with a reminder; the second closes regardless. The
event is recorded either way.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from lazy_harness.hooks.builtins.stop_verify_guard import _goal_declared


def _reader():
    """The real Claude Code reader — the guard's collaborator, not a stub."""
    from lazy_harness.agents.claude_code import ClaudeCodeAdapter

    return ClaudeCodeAdapter()


def _write_transcript(path: Path, lines: list[dict[str, object]]) -> Path:
    import json

    path.write_text("\n".join(json.dumps(line) for line in lines) + "\n")
    return path


def test_true_when_a_goal_status_attachment_is_present(tmp_path: Path) -> None:
    transcript = _write_transcript(
        tmp_path / "session.jsonl",
        [
            {"type": "user", "message": {"role": "user", "content": "hola"}},
            {
                "type": "attachment",
                "attachment": {
                    "type": "goal_status",
                    "met": False,
                    "sentinel": True,
                    "condition": "tests pass",
                },
            },
        ],
    )

    assert _goal_declared(transcript, _reader()) is True


def test_false_when_no_goal_status_attachment_exists(tmp_path: Path) -> None:
    transcript = _write_transcript(
        tmp_path / "session.jsonl",
        [
            {"type": "user", "message": {"role": "user", "content": "hola"}},
            {"type": "assistant", "message": {"role": "assistant", "content": "hola"}},
        ],
    )

    assert _goal_declared(transcript, _reader()) is False


def test_false_for_an_empty_transcript(tmp_path: Path) -> None:
    transcript = tmp_path / "session.jsonl"
    transcript.write_text("")

    assert _goal_declared(transcript, _reader()) is False


def test_false_when_the_transcript_file_does_not_exist(tmp_path: Path) -> None:
    assert _goal_declared(tmp_path / "missing.jsonl", _reader()) is False


def test_skips_malformed_lines_and_still_finds_the_marker(tmp_path: Path) -> None:
    transcript = tmp_path / "session.jsonl"
    transcript.write_text(
        "{not json at all\n"
        '{"type": "attachment", "attachment": {"type": "goal_status", "condition": "x"}}\n'
    )

    assert _goal_declared(transcript, _reader()) is True


@pytest.mark.parametrize(
    "attachment",
    [None, 42, ["a"], "a string"],
)
def test_ignores_a_wrong_type_attachment_field(tmp_path: Path, attachment: object) -> None:
    import json

    transcript = tmp_path / "session.jsonl"
    transcript.write_text(json.dumps({"type": "attachment", "attachment": attachment}) + "\n")

    assert _goal_declared(transcript, _reader()) is False


def test_ignores_an_attachment_of_a_different_type(tmp_path: Path) -> None:
    transcript = _write_transcript(
        tmp_path / "session.jsonl",
        [{"type": "attachment", "attachment": {"type": "something_else"}}],
    )

    assert _goal_declared(transcript, _reader()) is False


def test_a_reader_that_delivers_no_goal_signal_reports_no_goal(tmp_path: Path) -> None:
    """The marker is in the file and the guard still says no.

    This is what proves the guard *consumes* `GOAL_STATUS` rather than declaring
    it: with the hand-rolled scan this replaced, the bytes were read directly
    and no reader was ever asked, so the assertion below could not fail. An
    agent that has a transcript but no concept of an explicit goal is exactly
    the case decision 11 refuses to let pass silently.
    """
    transcript = _write_transcript(
        tmp_path / "session.jsonl",
        [{"type": "attachment", "attachment": {"type": "goal_status", "condition": "x"}}],
    )

    class _NoGoalSignal:
        """A reader that delivers messages and tokens, and no goal."""

        def locate_sessions(self, config_dir, since):
            return iter(())

        def read(self, path):
            return iter(())

        def signals(self):
            from lazy_harness.agents.base import Signal

            return {Signal.MESSAGES, Signal.TOKEN_USAGE}

    assert _goal_declared(transcript, _NoGoalSignal()) is False


def test_no_reader_at_all_reports_no_goal(tmp_path: Path) -> None:
    """`None` is the answer `transcript_reader` gives for an unreadable agent."""
    transcript = _write_transcript(
        tmp_path / "session.jsonl",
        [{"type": "attachment", "attachment": {"type": "goal_status"}}],
    )

    assert _goal_declared(transcript, None) is False


def test_it_stops_at_the_first_goal_marker_instead_of_reading_on(tmp_path: Path) -> None:
    """Short-circuiting is why `read()` is an iterator rather than a list.

    A session transcript runs to hundreds of megabytes by the time a `Stop`
    hook sees it, and the guard needs one bit out of it.
    """
    from lazy_harness.agents.base import GoalStatus, Signal, TranscriptEvent

    consumed = []

    class _Counting:
        def locate_sessions(self, config_dir, since):
            return iter(())

        def read(self, path):
            for index in range(100):
                consumed.append(index)
                yield TranscriptEvent(signal=Signal.GOAL_STATUS, goal=GoalStatus())

        def signals(self):
            return {Signal.GOAL_STATUS}

    assert _goal_declared(tmp_path / "anything.jsonl", _Counting()) is True
    assert consumed == [0], "the guard read past the marker it was looking for"


# --- main() -----------------------------------------------------------------


def _goal_transcript(tmp_path: Path, name: str = "session.jsonl") -> Path:
    return _write_transcript(
        tmp_path / name,
        [{"type": "attachment", "attachment": {"type": "goal_status", "condition": "x"}}],
    )


def _no_goal_transcript(tmp_path: Path, name: str = "session.jsonl") -> Path:
    return _write_transcript(
        tmp_path / name,
        [{"type": "assistant", "message": {"role": "assistant", "content": "hola"}}],
    )


def _run(monkeypatch, payload: dict[str, object]) -> str:
    """Payload -> adapter -> guard -> adapter, and back to the bytes on stdout.

    The guard returns a `HookDecision` now, but what the agent reads is what
    the adapter makes of it, so the assertions below stay about stdout. The
    profile resolves the way `run_hook` resolves it, which is what carries the
    scope into the metrics row.
    """
    from lazy_harness.agents.claude_code import ClaudeCodeAdapter
    from lazy_harness.hooks.builtins import stop_verify_guard as mod
    from lazy_harness.hooks.runner import resolve_profile

    adapter = ClaudeCodeAdapter()
    event = adapter.parse_hook_input("session_stop", payload, profile=resolve_profile(None))
    return adapter.format_hook_output(event, mod.main(event)).stdout or ""


def _recorded(db_path: Path) -> list[tuple[str, str, str]]:
    """(kind, session, project) per row."""
    with sqlite3.connect(db_path) as conn:
        return conn.execute("SELECT kind, session, project FROM loop_events").fetchall()


def test_blocks_the_first_stop_attempt_when_goal_declared_and_unverified(
    monkeypatch, tmp_path: Path
) -> None:
    from lazy_harness.hooks.builtins import stop_verify_guard as mod

    db_path = tmp_path / "m.db"
    monkeypatch.setattr(mod, "_db_path", lambda: db_path)
    monkeypatch.setattr(mod, "_injection_enabled", lambda: True)
    transcript = _goal_transcript(tmp_path)

    out = _run(
        monkeypatch,
        {"session_id": "s1", "transcript_path": str(transcript)},
    )

    payload = json.loads(out)
    assert payload["decision"] == "block"
    assert isinstance(payload["reason"], str) and payload["reason"]
    assert _recorded(db_path) == [("verify_block", "s1", "")]


@pytest.mark.parametrize("kind", [[], {}])
def test_still_blocks_when_an_unhashable_type_precedes_the_goal_marker(
    monkeypatch, tmp_path: Path, kind: object
) -> None:
    """A regression the `!=` scan on `main` could not have: `kind not in` hashes.

    The old scan compared `entry.get("type") != "attachment"`, which is safe
    for any JSON value. The reader tests membership against a frozenset, so a
    `"type"` of `[]` or `{}` raised `TypeError` out of the generator, ended the
    iteration before the marker, and left the guard silently off — no block and
    no `verify_block` row, so the metric did not even count the failure.
    """
    from lazy_harness.hooks.builtins import stop_verify_guard as mod

    db_path = tmp_path / "m.db"
    monkeypatch.setattr(mod, "_db_path", lambda: db_path)
    monkeypatch.setattr(mod, "_injection_enabled", lambda: True)
    transcript = _write_transcript(
        tmp_path / "session.jsonl",
        [
            {"type": kind, "message": {"role": "user", "content": "hola"}},
            {"type": "attachment", "attachment": {"type": "goal_status", "condition": "x"}},
        ],
    )

    out = _run(monkeypatch, {"session_id": "s1", "transcript_path": str(transcript)})

    assert json.loads(out)["decision"] == "block"
    assert _recorded(db_path) == [("verify_block", "s1", "")]


def test_lets_the_second_stop_attempt_close_without_blocking(
    monkeypatch, tmp_path: Path
) -> None:
    from lazy_harness.hooks.builtins import stop_verify_guard as mod
    from lazy_harness.monitoring.db import MetricsDB

    db_path = tmp_path / "m.db"
    monkeypatch.setattr(mod, "_db_path", lambda: db_path)
    monkeypatch.setattr(mod, "_injection_enabled", lambda: True)
    transcript = _goal_transcript(tmp_path)
    payload = {"session_id": "s1", "cwd": "/tmp", "transcript_path": str(transcript)}

    first = _run(monkeypatch, payload)
    second = _run(monkeypatch, payload)

    assert json.loads(first)["decision"] == "block"
    assert second == "", "the second attempt must close silently, not block again"
    assert MetricsDB(db_path).loop_event_counts() == {"verify_block": 1, "verify_skipped": 1}


def test_never_blocks_a_third_time_either(monkeypatch, tmp_path: Path) -> None:
    from lazy_harness.hooks.builtins import stop_verify_guard as mod
    from lazy_harness.monitoring.db import MetricsDB

    db_path = tmp_path / "m.db"
    monkeypatch.setattr(mod, "_db_path", lambda: db_path)
    monkeypatch.setattr(mod, "_injection_enabled", lambda: True)
    transcript = _goal_transcript(tmp_path)
    payload = {"session_id": "s1", "cwd": "/tmp", "transcript_path": str(transcript)}

    _run(monkeypatch, payload)
    _run(monkeypatch, payload)
    third = _run(monkeypatch, payload)

    assert third == ""
    assert MetricsDB(db_path).loop_event_counts() == {"verify_block": 1, "verify_skipped": 2}


def test_stays_silent_when_verify_ran_is_already_recorded(
    monkeypatch, tmp_path: Path
) -> None:
    from lazy_harness.hooks.builtins import stop_verify_guard as mod
    from lazy_harness.monitoring.db import MetricsDB

    db_path = tmp_path / "m.db"
    MetricsDB(db_path).record_loop_event(session="s1", kind="verify_ran")
    monkeypatch.setattr(mod, "_db_path", lambda: db_path)
    monkeypatch.setattr(mod, "_injection_enabled", lambda: True)
    transcript = _goal_transcript(tmp_path)

    out = _run(
        monkeypatch,
        {"session_id": "s1", "cwd": "/tmp", "transcript_path": str(transcript)},
    )

    assert out == ""
    assert MetricsDB(db_path).loop_event_counts() == {"verify_ran": 1}


def test_stays_silent_when_no_goal_was_declared(monkeypatch, tmp_path: Path) -> None:
    from lazy_harness.hooks.builtins import stop_verify_guard as mod
    from lazy_harness.monitoring.db import MetricsDB

    db_path = tmp_path / "m.db"
    monkeypatch.setattr(mod, "_db_path", lambda: db_path)
    monkeypatch.setattr(mod, "_injection_enabled", lambda: True)
    transcript = _no_goal_transcript(tmp_path)

    out = _run(
        monkeypatch,
        {"session_id": "s1", "cwd": "/tmp", "transcript_path": str(transcript)},
    )

    assert out == ""
    assert MetricsDB(db_path).loop_event_counts() == {}


def test_stays_silent_when_the_transcript_is_unresolvable(
    monkeypatch, tmp_path: Path
) -> None:
    """No transcript_path/transcriptPath/input key, or one pointing nowhere."""
    from lazy_harness.hooks.builtins import stop_verify_guard as mod
    from lazy_harness.monitoring.db import MetricsDB

    db_path = tmp_path / "m.db"
    monkeypatch.setattr(mod, "_db_path", lambda: db_path)
    monkeypatch.setattr(mod, "_injection_enabled", lambda: True)

    out = _run(monkeypatch, {"session_id": "s1", "cwd": "/tmp"})

    assert out == ""
    assert MetricsDB(db_path).loop_event_counts() == {}


def test_stays_silent_when_the_flag_is_off(monkeypatch, tmp_path: Path) -> None:
    from lazy_harness.hooks.builtins import stop_verify_guard as mod
    from lazy_harness.monitoring.db import MetricsDB

    db_path = tmp_path / "m.db"
    monkeypatch.setattr(mod, "_db_path", lambda: db_path)
    monkeypatch.setattr(mod, "_injection_enabled", lambda: False)
    transcript = _goal_transcript(tmp_path)

    out = _run(
        monkeypatch,
        {"session_id": "s1", "cwd": "/tmp", "transcript_path": str(transcript)},
    )

    assert out == "", "inject_goal_prompt=false must never block"
    assert MetricsDB(db_path).loop_event_counts() == {}


def test_records_the_repo_root_when_launched_from_an_artifact_subdirectory(
    monkeypatch, tmp_path: Path, git_checkout
) -> None:
    from lazy_harness.hooks.builtins import stop_verify_guard as mod

    db_path = tmp_path / "m.db"
    monkeypatch.setattr(mod, "_db_path", lambda: db_path)
    monkeypatch.setattr(mod, "_injection_enabled", lambda: True)
    transcript = _goal_transcript(tmp_path)

    _run(
        monkeypatch,
        {
            "session_id": "s1",
            "cwd": str(git_checkout.subdir),
            "transcript_path": str(transcript),
        },
    )

    assert _recorded(db_path) == [("verify_block", "s1", str(git_checkout.repo))]


def test_records_the_profile_the_agent_runs_under(
    monkeypatch, tmp_path: Path, active_profile: str
) -> None:
    from lazy_harness.hooks.builtins import stop_verify_guard as mod

    db_path = tmp_path / "m.db"
    monkeypatch.setattr(mod, "_db_path", lambda: db_path)
    monkeypatch.setattr(mod, "_injection_enabled", lambda: True)
    transcript = _goal_transcript(tmp_path)

    _run(
        monkeypatch,
        {"session_id": "s1", "cwd": "/tmp", "transcript_path": str(transcript)},
    )

    with sqlite3.connect(db_path) as conn:
        assert conn.execute("SELECT profile FROM loop_events").fetchall() == [(active_profile,)]


@pytest.mark.parametrize("session_id", [None, 42, ["s1"], {"nested": "dict"}])
def test_stays_silent_on_a_session_id_that_is_not_a_string(
    monkeypatch, tmp_path: Path, session_id: object
) -> None:
    """A non-string session id arrives absent, never coerced.

    `str(42)` would be a session key that looks real, and the guard would then
    record a `verify_block` against it and block a session it cannot track.
    """
    from lazy_harness.hooks.builtins import stop_verify_guard as mod
    from lazy_harness.monitoring.db import MetricsDB

    db_path = tmp_path / "m.db"
    monkeypatch.setattr(mod, "_db_path", lambda: db_path)
    monkeypatch.setattr(mod, "_injection_enabled", lambda: True)
    transcript = _goal_transcript(tmp_path)

    out = _run(
        monkeypatch,
        {"session_id": session_id, "cwd": "/tmp", "transcript_path": str(transcript)},
    )

    assert out == ""
    assert MetricsDB(db_path).loop_event_counts() == {}


def test_exits_zero_when_the_database_is_unwritable(monkeypatch, tmp_path: Path) -> None:
    """A broken metrics store must never take down the session."""
    from lazy_harness.hooks.builtins import stop_verify_guard as mod

    blocked = tmp_path / "file-not-a-dir"
    blocked.write_text("x")
    monkeypatch.setattr(mod, "_db_path", lambda: blocked / "m.db")
    monkeypatch.setattr(mod, "_injection_enabled", lambda: True)
    transcript = _goal_transcript(tmp_path)

    _run(
        monkeypatch,
        {"session_id": "s1", "cwd": "/tmp", "transcript_path": str(transcript)},
    )


def test_injection_enabled_returns_false_when_config_read_fails(monkeypatch) -> None:
    """An unreadable or missing config must never crash the hook; stay silent."""
    from lazy_harness.hooks.builtins import stop_verify_guard as mod

    def _boom() -> Path:
        raise OSError("config unreadable")

    monkeypatch.setattr("lazy_harness.core.paths.config_file", _boom)

    assert mod._injection_enabled() is False

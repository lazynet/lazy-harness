"""Tests for the Stop soft-enforcement guard (verify-before-close).

See specs/designs/2026-08-16-loop-engineering-design.md, "Soft enforcement on
`Stop`". The guard fires once per session: if the session declared a goal
(via the native `/goal` command) and no `verify_ran` event exists for it, the
first Stop attempt blocks with a reminder; the second closes regardless. The
event is recorded either way.
"""

from __future__ import annotations

import io
import json
import sqlite3
from pathlib import Path

import pytest

from lazy_harness.hooks.builtins.stop_verify_guard import _goal_declared


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

    assert _goal_declared(transcript) is True


def test_false_when_no_goal_status_attachment_exists(tmp_path: Path) -> None:
    transcript = _write_transcript(
        tmp_path / "session.jsonl",
        [
            {"type": "user", "message": {"role": "user", "content": "hola"}},
            {"type": "assistant", "message": {"role": "assistant", "content": "hola"}},
        ],
    )

    assert _goal_declared(transcript) is False


def test_false_for_an_empty_transcript(tmp_path: Path) -> None:
    transcript = tmp_path / "session.jsonl"
    transcript.write_text("")

    assert _goal_declared(transcript) is False


def test_false_when_the_transcript_file_does_not_exist(tmp_path: Path) -> None:
    assert _goal_declared(tmp_path / "missing.jsonl") is False


def test_skips_malformed_lines_and_still_finds_the_marker(tmp_path: Path) -> None:
    transcript = tmp_path / "session.jsonl"
    transcript.write_text(
        "{not json at all\n"
        '{"type": "attachment", "attachment": {"type": "goal_status", "condition": "x"}}\n'
    )

    assert _goal_declared(transcript) is True


@pytest.mark.parametrize(
    "attachment",
    [None, 42, ["a"], "a string"],
)
def test_ignores_a_wrong_type_attachment_field(tmp_path: Path, attachment: object) -> None:
    import json

    transcript = tmp_path / "session.jsonl"
    transcript.write_text(json.dumps({"type": "attachment", "attachment": attachment}) + "\n")

    assert _goal_declared(transcript) is False


def test_ignores_an_attachment_of_a_different_type(tmp_path: Path) -> None:
    transcript = _write_transcript(
        tmp_path / "session.jsonl",
        [{"type": "attachment", "attachment": {"type": "something_else"}}],
    )

    assert _goal_declared(transcript) is False


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


def _run(monkeypatch, payload: object, capsys) -> str:
    from lazy_harness.hooks.builtins import stop_verify_guard as mod

    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(payload)))
    with pytest.raises(SystemExit) as exc:
        mod.main()
    assert exc.value.code == 0
    return capsys.readouterr().out


def _recorded(db_path: Path) -> list[tuple[str, str, str]]:
    """(kind, session, project) per row."""
    with sqlite3.connect(db_path) as conn:
        return conn.execute("SELECT kind, session, project FROM loop_events").fetchall()


def test_blocks_the_first_stop_attempt_when_goal_declared_and_unverified(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    from lazy_harness.hooks.builtins import stop_verify_guard as mod

    db_path = tmp_path / "m.db"
    monkeypatch.setattr(mod, "_db_path", lambda: db_path)
    monkeypatch.setattr(mod, "_injection_enabled", lambda: True)
    transcript = _goal_transcript(tmp_path)

    out = _run(
        monkeypatch,
        {"session_id": "s1", "transcript_path": str(transcript)},
        capsys,
    )

    payload = json.loads(out)
    assert payload["decision"] == "block"
    assert isinstance(payload["reason"], str) and payload["reason"]
    assert _recorded(db_path) == [("verify_block", "s1", "")]


def test_lets_the_second_stop_attempt_close_without_blocking(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    from lazy_harness.hooks.builtins import stop_verify_guard as mod
    from lazy_harness.monitoring.db import MetricsDB

    db_path = tmp_path / "m.db"
    monkeypatch.setattr(mod, "_db_path", lambda: db_path)
    monkeypatch.setattr(mod, "_injection_enabled", lambda: True)
    transcript = _goal_transcript(tmp_path)
    payload = {"session_id": "s1", "cwd": "/tmp", "transcript_path": str(transcript)}

    first = _run(monkeypatch, payload, capsys)
    second = _run(monkeypatch, payload, capsys)

    assert json.loads(first)["decision"] == "block"
    assert second == "", "the second attempt must close silently, not block again"
    assert MetricsDB(db_path).loop_event_counts() == {"verify_block": 1, "verify_skipped": 1}


def test_never_blocks_a_third_time_either(monkeypatch, tmp_path: Path, capsys) -> None:
    from lazy_harness.hooks.builtins import stop_verify_guard as mod
    from lazy_harness.monitoring.db import MetricsDB

    db_path = tmp_path / "m.db"
    monkeypatch.setattr(mod, "_db_path", lambda: db_path)
    monkeypatch.setattr(mod, "_injection_enabled", lambda: True)
    transcript = _goal_transcript(tmp_path)
    payload = {"session_id": "s1", "cwd": "/tmp", "transcript_path": str(transcript)}

    _run(monkeypatch, payload, capsys)
    _run(monkeypatch, payload, capsys)
    third = _run(monkeypatch, payload, capsys)

    assert third == ""
    assert MetricsDB(db_path).loop_event_counts() == {"verify_block": 1, "verify_skipped": 2}


def test_stays_silent_when_verify_ran_is_already_recorded(
    monkeypatch, tmp_path: Path, capsys
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
        capsys,
    )

    assert out == ""
    assert MetricsDB(db_path).loop_event_counts() == {"verify_ran": 1}


def test_stays_silent_when_no_goal_was_declared(monkeypatch, tmp_path: Path, capsys) -> None:
    from lazy_harness.hooks.builtins import stop_verify_guard as mod
    from lazy_harness.monitoring.db import MetricsDB

    db_path = tmp_path / "m.db"
    monkeypatch.setattr(mod, "_db_path", lambda: db_path)
    monkeypatch.setattr(mod, "_injection_enabled", lambda: True)
    transcript = _no_goal_transcript(tmp_path)

    out = _run(
        monkeypatch,
        {"session_id": "s1", "cwd": "/tmp", "transcript_path": str(transcript)},
        capsys,
    )

    assert out == ""
    assert MetricsDB(db_path).loop_event_counts() == {}


def test_stays_silent_when_the_transcript_is_unresolvable(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    """No transcript_path/transcriptPath/input key, or one pointing nowhere."""
    from lazy_harness.hooks.builtins import stop_verify_guard as mod
    from lazy_harness.monitoring.db import MetricsDB

    db_path = tmp_path / "m.db"
    monkeypatch.setattr(mod, "_db_path", lambda: db_path)
    monkeypatch.setattr(mod, "_injection_enabled", lambda: True)

    out = _run(monkeypatch, {"session_id": "s1", "cwd": "/tmp"}, capsys)

    assert out == ""
    assert MetricsDB(db_path).loop_event_counts() == {}


def test_stays_silent_when_the_flag_is_off(monkeypatch, tmp_path: Path, capsys) -> None:
    from lazy_harness.hooks.builtins import stop_verify_guard as mod
    from lazy_harness.monitoring.db import MetricsDB

    db_path = tmp_path / "m.db"
    monkeypatch.setattr(mod, "_db_path", lambda: db_path)
    monkeypatch.setattr(mod, "_injection_enabled", lambda: False)
    transcript = _goal_transcript(tmp_path)

    out = _run(
        monkeypatch,
        {"session_id": "s1", "cwd": "/tmp", "transcript_path": str(transcript)},
        capsys,
    )

    assert out == "", "inject_goal_prompt=false must never block"
    assert MetricsDB(db_path).loop_event_counts() == {}


def test_records_the_repo_root_when_launched_from_an_artifact_subdirectory(
    monkeypatch, tmp_path: Path, capsys, git_checkout
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
        capsys,
    )

    assert _recorded(db_path) == [("verify_block", "s1", str(git_checkout.repo))]


def test_records_the_profile_the_agent_runs_under(
    monkeypatch, tmp_path: Path, capsys, active_profile: str
) -> None:
    from lazy_harness.hooks.builtins import stop_verify_guard as mod

    db_path = tmp_path / "m.db"
    monkeypatch.setattr(mod, "_db_path", lambda: db_path)
    monkeypatch.setattr(mod, "_injection_enabled", lambda: True)
    transcript = _goal_transcript(tmp_path)

    _run(
        monkeypatch,
        {"session_id": "s1", "cwd": "/tmp", "transcript_path": str(transcript)},
        capsys,
    )

    with sqlite3.connect(db_path) as conn:
        assert conn.execute("SELECT profile FROM loop_events").fetchall() == [(active_profile,)]


@pytest.mark.parametrize("session_id", [None, 42, ["s1"], {"nested": "dict"}])
def test_exits_zero_on_valid_json_wrong_type_session_id(
    monkeypatch, tmp_path: Path, capsys, session_id: object
) -> None:
    from lazy_harness.hooks.builtins import stop_verify_guard as mod
    from lazy_harness.monitoring.db import MetricsDB

    db_path = tmp_path / "m.db"
    monkeypatch.setattr(mod, "_db_path", lambda: db_path)
    monkeypatch.setattr(mod, "_injection_enabled", lambda: True)
    transcript = _goal_transcript(tmp_path)

    out = _run(
        monkeypatch,
        {"session_id": session_id, "cwd": "/tmp", "transcript_path": str(transcript)},
        capsys,
    )

    assert out == ""
    assert MetricsDB(db_path).loop_event_counts() == {}


@pytest.mark.parametrize("payload", [None, 42, ["a"], "a string"])
def test_exits_zero_on_valid_json_wrong_type_payload(
    monkeypatch, tmp_path: Path, capsys, payload: object
) -> None:
    from lazy_harness.hooks.builtins import stop_verify_guard as mod

    monkeypatch.setattr(mod, "_db_path", lambda: tmp_path / "m.db")
    monkeypatch.setattr(mod, "_injection_enabled", lambda: True)

    _run(monkeypatch, payload, capsys)


def test_exits_zero_on_malformed_json(monkeypatch, tmp_path: Path, capsys) -> None:
    from lazy_harness.hooks.builtins import stop_verify_guard as mod

    monkeypatch.setattr(mod, "_db_path", lambda: tmp_path / "m.db")
    monkeypatch.setattr(mod, "_injection_enabled", lambda: True)
    monkeypatch.setattr("sys.stdin", io.StringIO("{not json at all"))

    with pytest.raises(SystemExit) as exc:
        mod.main()
    assert exc.value.code == 0


def test_exits_zero_when_the_database_is_unwritable(monkeypatch, tmp_path: Path, capsys) -> None:
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
        capsys,
    )


def test_injection_enabled_returns_false_when_config_read_fails(monkeypatch) -> None:
    """An unreadable or missing config must never crash the hook; stay silent."""
    from lazy_harness.hooks.builtins import stop_verify_guard as mod

    def _boom() -> Path:
        raise OSError("config unreadable")

    monkeypatch.setattr("lazy_harness.core.paths.config_file", _boom)

    assert mod._injection_enabled() is False

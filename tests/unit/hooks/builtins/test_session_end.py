"""Tests for the SessionEnd hook's loop-event record.

`_enqueue_compound_loop` is exercised elsewhere; these cover the metrics row
it writes first, which shipped with no test file at all.

Every event here is built by `ClaudeCodeAdapter.parse_hook_input` from the same
raw payload the pre-runner tests fed `_record_session_closed` directly. The
`isinstance` narrowing that turns a wrong-type `cwd` or `session_id` into an
absent one moved into the adapter with the migration, so asserting against a
hand-built `HookEvent` would assert against a normalisation nothing ran — and
the guard these cases exist for would be untested on both sides.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from lazy_harness.agents.base import HookEvent


def _event(payload: object, *, profile: str = "") -> HookEvent:
    from lazy_harness.agents.claude_code import ClaudeCodeAdapter

    assert isinstance(payload, dict)
    return ClaudeCodeAdapter().parse_hook_input("session_end", payload, profile=profile)


def _recorded(db_path: Path) -> list[tuple[str, str, str]]:
    """(kind, session, project) per row."""
    with sqlite3.connect(db_path) as conn:
        return conn.execute("SELECT kind, session, project FROM loop_events").fetchall()


def test_records_the_repo_root_when_the_session_ran_in_a_subdirectory(
    monkeypatch, tmp_path: Path, git_checkout
) -> None:
    """`session_closed` carried no project at all, so nothing could group it."""
    from lazy_harness.hooks.builtins import session_end as mod

    db_path = tmp_path / "m.db"
    monkeypatch.setattr(mod, "_loop_db_path", lambda: db_path)

    mod._record_session_closed(_event({"session_id": "s1", "cwd": str(git_checkout.subdir)}))

    assert _recorded(db_path) == [("session_closed", "s1", str(git_checkout.repo))]


def test_records_the_main_repo_when_the_session_ran_in_a_worktree(
    monkeypatch, tmp_path: Path, git_checkout
) -> None:
    from lazy_harness.hooks.builtins import session_end as mod

    db_path = tmp_path / "m.db"
    monkeypatch.setattr(mod, "_loop_db_path", lambda: db_path)

    mod._record_session_closed(_event({"session_id": "s1", "cwd": str(git_checkout.worktree)}))

    assert _recorded(db_path) == [("session_closed", "s1", str(git_checkout.repo.resolve()))]


def test_records_the_profile_the_hook_was_invoked_under(monkeypatch, tmp_path: Path) -> None:
    """`event.profile`, not the ambient `CLAUDE_CONFIG_DIR`.

    `profile_name()` answered from the environment, so a hook invoked with an
    explicit `--profile` recorded whatever the environment happened to say —
    `""` whenever the variable is unset, which is every hook subprocess that
    reaches the runner through the deployed command.
    """
    from lazy_harness.hooks.builtins import session_end as mod

    db_path = tmp_path / "m.db"
    monkeypatch.setattr(mod, "_loop_db_path", lambda: db_path)

    mod._record_session_closed(_event({"session_id": "s1", "cwd": "/tmp"}, profile="gate"))

    with sqlite3.connect(db_path) as conn:
        assert conn.execute("SELECT profile FROM loop_events").fetchall() == [("gate",)]


def test_records_an_empty_project_when_the_payload_omits_cwd(monkeypatch, tmp_path: Path) -> None:
    """A missing cwd must not resolve against the hook's own process cwd.

    The other half of trap 1, and the reason this row does *not* take the
    `Path.cwd()` fallback the enqueue takes: a metrics label that guesses is
    worse than one that admits it does not know, while a queued task that
    guesses points at the wrong project's memory.
    """
    from lazy_harness.hooks.builtins import session_end as mod

    db_path = tmp_path / "m.db"
    monkeypatch.setattr(mod, "_loop_db_path", lambda: db_path)

    mod._record_session_closed(_event({"session_id": "s1"}))

    assert _recorded(db_path) == [("session_closed", "s1", "")]


@pytest.mark.parametrize("session_id", [None, 42, ["a"], {"a": 1}])
def test_records_an_empty_session_for_a_wrong_type_session_id(
    monkeypatch, tmp_path: Path, session_id: object
) -> None:
    """Shutdown must not be blocked by a payload shape the hook did not expect."""
    from lazy_harness.hooks.builtins import session_end as mod

    db_path = tmp_path / "m.db"
    monkeypatch.setattr(mod, "_loop_db_path", lambda: db_path)

    mod._record_session_closed(_event({"session_id": session_id, "cwd": "/tmp"}))

    assert _recorded(db_path)[0][:2] == ("session_closed", "")


@pytest.mark.parametrize("cwd", [None, 42, ["/tmp"], {"path": "/tmp"}])
def test_records_an_empty_project_for_a_wrong_type_cwd(
    monkeypatch, tmp_path: Path, cwd: object
) -> None:
    from lazy_harness.hooks.builtins import session_end as mod

    db_path = tmp_path / "m.db"
    monkeypatch.setattr(mod, "_loop_db_path", lambda: db_path)

    mod._record_session_closed(_event({"session_id": "s1", "cwd": cwd}))

    assert _recorded(db_path) == [("session_closed", "s1", "")]


def test_never_raises_when_the_database_is_unwritable(monkeypatch, tmp_path: Path) -> None:
    from lazy_harness.hooks.builtins import session_end as mod

    blocked = tmp_path / "file-not-a-dir"
    blocked.write_text("x")
    monkeypatch.setattr(mod, "_loop_db_path", lambda: blocked / "m.db")

    mod._record_session_closed(_event({"session_id": "s1", "cwd": "/tmp"}))

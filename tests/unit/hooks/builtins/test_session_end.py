"""Tests for the SessionEnd hook's loop-event record.

`_enqueue_compound_loop` is exercised elsewhere; these cover the metrics row
it writes first, which shipped with no test file at all.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest


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

    mod._record_session_closed({"session_id": "s1", "cwd": str(git_checkout.subdir)})

    assert _recorded(db_path) == [("session_closed", "s1", str(git_checkout.repo))]


def test_records_the_main_repo_when_the_session_ran_in_a_worktree(
    monkeypatch, tmp_path: Path, git_checkout
) -> None:
    from lazy_harness.hooks.builtins import session_end as mod

    db_path = tmp_path / "m.db"
    monkeypatch.setattr(mod, "_loop_db_path", lambda: db_path)

    mod._record_session_closed({"session_id": "s1", "cwd": str(git_checkout.worktree)})

    assert _recorded(db_path) == [("session_closed", "s1", str(git_checkout.repo.resolve()))]


def test_records_an_empty_project_when_the_payload_omits_cwd(monkeypatch, tmp_path: Path) -> None:
    """A missing cwd must not resolve against the hook's own process cwd."""
    from lazy_harness.hooks.builtins import session_end as mod

    db_path = tmp_path / "m.db"
    monkeypatch.setattr(mod, "_loop_db_path", lambda: db_path)

    mod._record_session_closed({"session_id": "s1"})

    assert _recorded(db_path) == [("session_closed", "s1", "")]


@pytest.mark.parametrize("payload", [None, 42, ["a"], "a string"])
def test_never_raises_on_valid_json_wrong_type(
    monkeypatch, tmp_path: Path, payload: object
) -> None:
    """Shutdown must not be blocked by a payload shape the hook did not expect."""
    from lazy_harness.hooks.builtins import session_end as mod

    db_path = tmp_path / "m.db"
    monkeypatch.setattr(mod, "_loop_db_path", lambda: db_path)

    mod._record_session_closed(payload)

    assert _recorded(db_path) == [("session_closed", "", "")]


@pytest.mark.parametrize("cwd", [None, 42, ["/tmp"]])
def test_records_an_empty_project_for_a_wrong_type_cwd(
    monkeypatch, tmp_path: Path, cwd: object
) -> None:
    from lazy_harness.hooks.builtins import session_end as mod

    db_path = tmp_path / "m.db"
    monkeypatch.setattr(mod, "_loop_db_path", lambda: db_path)

    mod._record_session_closed({"session_id": "s1", "cwd": cwd})

    assert _recorded(db_path) == [("session_closed", "s1", "")]


def test_never_raises_when_the_database_is_unwritable(monkeypatch, tmp_path: Path) -> None:
    from lazy_harness.hooks.builtins import session_end as mod

    blocked = tmp_path / "file-not-a-dir"
    blocked.write_text("x")
    monkeypatch.setattr(mod, "_loop_db_path", lambda: blocked / "m.db")

    mod._record_session_closed({"session_id": "s1", "cwd": "/tmp"})

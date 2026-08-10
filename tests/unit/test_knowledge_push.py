"""Tests for the knowledge store push cycle."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest


def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True)


@pytest.fixture
def store(tmp_path: Path) -> Path:
    root = tmp_path / "store"
    root.mkdir()
    (root / "knowledge.toml").write_text(
        '[knowledge]\nversion = 1\nsessions = "sessions"\nlearnings = "learnings"\n',
        encoding="utf-8",
    )
    _git(root, "init", "-q", "-b", "main")
    _git(root, "config", "user.email", "test@example.invalid")
    _git(root, "config", "user.name", "test")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "init")
    return root


def test_clean_store_is_a_noop(store: Path) -> None:
    from lazy_harness.knowledge.git_push import push_once

    result = push_once(store, host="test-host")
    assert result.status == "clean"


def test_new_files_are_committed(store: Path) -> None:
    from lazy_harness.knowledge.git_push import push_once

    (store / "learnings").mkdir()
    (store / "learnings" / "a.md").write_text("x", encoding="utf-8")
    result = push_once(store, host="test-host")
    assert result.status in {"committed", "pushed"}
    log = subprocess.run(
        ["git", "-C", str(store), "log", "-1", "--format=%s"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    assert "test-host" in log


def test_commit_subject_counts_sessions_and_learnings(store: Path) -> None:
    from lazy_harness.knowledge.git_push import push_once

    for kind in ("sessions", "learnings"):
        (store / kind).mkdir()
    (store / "sessions" / "a.md").write_text("x", encoding="utf-8")
    (store / "learnings" / "b.md").write_text("x", encoding="utf-8")
    (store / "learnings" / "c.md").write_text("x", encoding="utf-8")
    push_once(store, host="test-host")
    log = subprocess.run(
        ["git", "-C", str(store), "log", "-1", "--format=%s"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    assert "1 sessions" in log
    assert "2 learnings" in log


def test_invalid_marker_stops_before_touching_git(store: Path) -> None:
    from lazy_harness.knowledge.git_push import push_once

    (store / "knowledge.toml").write_text(
        '[knowledge]\nversion = 99\nsessions = "s"\nlearnings = "l"\n', encoding="utf-8"
    )
    (store / "dirty.md").write_text("x", encoding="utf-8")
    result = push_once(store, host="test-host")
    assert result.status == "invalid"
    status = subprocess.run(
        ["git", "-C", str(store), "status", "--porcelain"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    assert "dirty.md" in status


def test_held_lock_is_a_silent_noop(store: Path) -> None:
    import fcntl
    import os

    from lazy_harness.knowledge.git_push import push_once

    lock = store / ".git" / ".push.lock"
    fd = os.open(str(lock), os.O_CREAT | os.O_WRONLY, 0o600)
    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    try:
        (store / "learnings.md").write_text("x", encoding="utf-8")
        assert push_once(store, host="test-host").status == "locked"
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


def test_no_remote_leaves_commits_local(store: Path) -> None:
    from lazy_harness.knowledge.git_push import push_once

    (store / "a.md").write_text("x", encoding="utf-8")
    result = push_once(store, host="test-host")
    assert result.status == "committed"
    count = subprocess.run(
        ["git", "-C", str(store), "rev-list", "--count", "HEAD"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    assert count == "2"


def test_rebase_conflict_aborts_and_reports(tmp_path: Path, store: Path) -> None:
    """A genuine add/add conflict must abort the rebase, never auto-resolve."""
    from lazy_harness.knowledge.git_push import push_once

    remote = tmp_path / "remote.git"
    subprocess.run(
        ["git", "init", "-q", "--bare", "-b", "main", str(remote)], check=True, capture_output=True
    )
    _git(store, "remote", "add", "origin", str(remote))
    _git(store, "push", "-q", "-u", "origin", "main")

    # Another writer lands a file at the same path with different content.
    other = tmp_path / "other"
    subprocess.run(["git", "clone", "-q", str(remote), str(other)], check=True, capture_output=True)
    _git(other, "config", "user.email", "other@example.invalid")
    _git(other, "config", "user.name", "other")
    (other / "clash.md").write_text("theirs", encoding="utf-8")
    _git(other, "add", "-A")
    _git(other, "commit", "-qm", "theirs")
    _git(other, "push", "-q")

    (store / "clash.md").write_text("ours", encoding="utf-8")
    result = push_once(store, host="test-host")
    assert result.status == "conflict"
    # The abort left no rebase in progress and the local commit survived.
    assert not (store / ".git" / "rebase-merge").exists()
    assert not (store / ".git" / "rebase-apply").exists()
    assert (store / "clash.md").read_text(encoding="utf-8") == "ours"

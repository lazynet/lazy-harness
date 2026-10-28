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


def _read(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(root), *args], capture_output=True, text=True, check=True
    ).stdout


def _commit_all(root: Path, msg: str) -> None:
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", msg)


@pytest.fixture
def pair(tmp_path: Path, store: Path) -> tuple[Path, Path]:
    """`store` and a second clone, both tracking one bare remote."""
    remote = tmp_path / "remote.git"
    subprocess.run(
        ["git", "init", "-q", "--bare", "-b", "main", str(remote)], check=True, capture_output=True
    )
    _git(store, "remote", "add", "origin", str(remote))
    _git(store, "push", "-q", "-u", "origin", "main")
    other = tmp_path / "other"
    subprocess.run(["git", "clone", "-q", str(remote), str(other)], check=True, capture_output=True)
    _git(other, "config", "user.email", "other@example.invalid")
    _git(other, "config", "user.name", "other")
    return store, other


def _land_remote(other: Path, rel: str, text: str, *, append: bool = False) -> None:
    path = other / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    if append and path.exists():
        text = path.read_text(encoding="utf-8") + text
    path.write_text(text, encoding="utf-8")
    _commit_all(other, f"remote {rel}")
    _git(other, "push", "-q")


HANDOFF = "memory/h/o/r/handoff.md"


def _frontmatter(ts: str, body: str) -> str:
    return f"---\nwritten_at: {ts}\n---\n{body}\n"


def _bodyline(ts: str, body: str) -> str:
    return f"# Handoff\n\n- Written at: {ts}\n\n{body}\n"


def _diverge_handoff(store: Path, other: Path, local: str, remote: str) -> None:
    (store / HANDOFF).parent.mkdir(parents=True)
    (store / HANDOFF).write_text("base\n", encoding="utf-8")
    _commit_all(store, "base")
    _git(store, "push", "-q")
    _git(other, "pull", "-q")
    _land_remote(other, HANDOFF, remote)
    (store / HANDOFF).write_text(local, encoding="utf-8")


@pytest.mark.parametrize(
    ("local", "remote", "winner"),
    [
        (
            _frontmatter("2026-10-26T22:13:46-03:00", "local"),
            _bodyline("2026-10-27T18:34:58+00:00", "remote"),
            "remote",
        ),
        (
            _bodyline("2026-10-27T18:34:58+00:00", "local"),
            _frontmatter("2026-10-26T22:13:46-03:00", "remote"),
            "local",
        ),
        # 21:00-03:00 is 00:00Z next day: later than 23:00Z despite the smaller clock reading.
        (
            _frontmatter("2026-10-27T21:00:00-03:00", "local"),
            _bodyline("2026-10-27T23:00:00+00:00", "remote"),
            "local",
        ),
    ],
)
def test_diverged_handoff_newest_wins(
    pair: tuple[Path, Path], local: str, remote: str, winner: str
) -> None:
    from lazy_harness.knowledge.git_push import push_once

    store, other = pair
    _diverge_handoff(store, other, local, remote)
    result = push_once(store, host="test-host")
    assert result.status == "pushed", result.detail
    assert winner in (store / HANDOFF).read_text(encoding="utf-8")
    assert not (store / ".git" / "MERGE_HEAD").exists()
    assert _read(store, "rev-parse", "HEAD") == _read(store, "rev-parse", "origin/main")


def test_diverged_appends_are_unioned(pair: tuple[Path, Path]) -> None:
    from lazy_harness.knowledge.git_push import push_once

    store, other = pair
    (store / "memory").mkdir()
    for name in ("decisions.jsonl", "claude-md.proposal.md"):
        (store / "memory" / name).write_text("base\n", encoding="utf-8")
    _commit_all(store, "base")
    _git(store, "push", "-q")
    _git(other, "pull", "-q")
    for name in ("decisions.jsonl", "claude-md.proposal.md"):
        _land_remote(other, f"memory/{name}", "remote line\n", append=True)
        with (store / "memory" / name).open("a", encoding="utf-8") as f:
            f.write("local line\n")

    result = push_once(store, host="test-host")
    assert result.status == "pushed", result.detail
    for name in ("decisions.jsonl", "claude-md.proposal.md"):
        lines = (store / "memory" / name).read_text(encoding="utf-8").splitlines()
        assert {"base", "remote line", "local line"} <= set(lines)


def test_behind_only_clean_clone_is_fast_forwarded(pair: tuple[Path, Path]) -> None:
    from lazy_harness.knowledge.git_push import push_once

    store, other = pair
    # The attributes file lands first so the receive-only clone is genuinely clean.
    assert push_once(store, host="test-host").status in {"pushed", "committed"}
    _git(other, "pull", "-q")
    _land_remote(other, "learnings/x.md", "x")

    result = push_once(store, host="test-host")
    assert result.status == "updated", result.detail
    assert (store / "learnings" / "x.md").exists()


def test_non_handoff_conflict_aborts_and_reports(pair: tuple[Path, Path]) -> None:
    from lazy_harness.knowledge.git_push import push_once

    store, other = pair
    _land_remote(other, "clash.md", "theirs")
    (store / "clash.md").write_text("ours", encoding="utf-8")
    result = push_once(store, host="test-host")
    assert result.status == "conflict"
    assert "clash.md" in result.detail
    assert not (store / ".git" / "MERGE_HEAD").exists()
    assert (store / "clash.md").read_text(encoding="utf-8") == "ours"


def test_handoff_conflict_next_to_other_conflict_aborts_whole_merge(
    pair: tuple[Path, Path],
) -> None:
    from lazy_harness.knowledge.git_push import push_once

    store, other = pair
    _land_remote(other, "clash.md", "theirs")
    _land_remote(other, HANDOFF, _frontmatter("2026-10-27T00:00:00+00:00", "remote"))
    (store / "clash.md").write_text("ours", encoding="utf-8")
    (store / HANDOFF).parent.mkdir(parents=True)
    (store / HANDOFF).write_text(_frontmatter("2026-10-26T00:00:00+00:00", "local"))
    result = push_once(store, host="test-host")
    assert result.status == "conflict"
    assert not (store / ".git" / "MERGE_HEAD").exists()
    assert "local" in (store / HANDOFF).read_text(encoding="utf-8")


def test_timestamped_non_handoff_file_is_never_auto_resolved(pair: tuple[Path, Path]) -> None:
    """A parseable timestamp is not enough: only handoff.md paths get newest-wins."""
    from lazy_harness.knowledge.git_push import push_once

    store, other = pair
    notes = "memory/h/o/r/notes.md"
    _land_remote(other, notes, _frontmatter("2026-10-27T00:00:00+00:00", "remote"))
    (store / notes).parent.mkdir(parents=True)
    (store / notes).write_text(_frontmatter("2026-10-26T00:00:00+00:00", "local"))
    result = push_once(store, host="test-host")
    assert result.status == "conflict"
    assert notes in result.detail
    assert not (store / ".git" / "MERGE_HEAD").exists()
    assert "local" in (store / notes).read_text(encoding="utf-8")


@pytest.mark.parametrize("side", ["local", "remote"])
def test_handoff_without_timestamp_aborts(pair: tuple[Path, Path], side: str) -> None:
    from lazy_harness.knowledge.git_push import push_once

    store, other = pair
    stamped = _frontmatter("2026-10-27T00:00:00+00:00", "x")
    bare = "no timestamp here\n"
    local, remote = (bare, stamped) if side == "local" else (stamped, bare)
    _diverge_handoff(store, other, local, remote)
    result = push_once(store, host="test-host")
    assert result.status == "conflict"
    assert "handoff.md" in result.detail
    assert not (store / ".git" / "MERGE_HEAD").exists()


def test_naive_timestamp_is_not_comparable(pair: tuple[Path, Path]) -> None:
    from lazy_harness.knowledge.git_push import push_once

    store, other = pair
    _diverge_handoff(
        store,
        other,
        _frontmatter("2026-10-26T00:00:00", "local"),
        _frontmatter("2026-10-27T00:00:00+00:00", "remote"),
    )
    assert push_once(store, host="test-host").status == "conflict"


def test_gitattributes_created_and_not_clobbered(pair: tuple[Path, Path]) -> None:
    from lazy_harness.knowledge.git_push import push_once

    store, _ = pair
    (store / ".gitattributes").write_text("*.png binary\n*.jsonl merge=union\n", encoding="utf-8")
    _commit_all(store, "attrs")
    assert push_once(store, host="test-host").status == "pushed"
    lines = (store / ".gitattributes").read_text(encoding="utf-8").splitlines()
    assert lines.count("*.png binary") == 1
    assert lines.count("*.jsonl merge=union") == 1
    assert "claude-md.proposal.md merge=union" in lines
    assert "claude-md.proposal.md" in _read(store, "show", "HEAD:.gitattributes")


def test_gitattributes_is_created_in_a_fresh_store(pair: tuple[Path, Path]) -> None:
    from lazy_harness.knowledge.git_push import push_once

    store, _ = pair
    assert push_once(store, host="test-host").status == "pushed"
    assert "*.jsonl merge=union" in _read(store, "show", "origin/main:.gitattributes")


def test_long_divergence_merges_once_without_replaying(pair: tuple[Path, Path]) -> None:
    from lazy_harness.knowledge.git_push import push_once

    store, other = pair
    _land_remote(other, HANDOFF, _frontmatter("2026-10-27T00:00:00+00:00", "remote"))
    # Several local commits, the first of which would conflict on a replay.
    (store / HANDOFF).parent.mkdir(parents=True)
    (store / HANDOFF).write_text(_frontmatter("2026-10-26T00:00:00+00:00", "local"))
    _commit_all(store, "local 0")
    for i in range(1, 6):
        (store / f"n{i}.md").write_text(str(i), encoding="utf-8")
        _commit_all(store, f"local {i}")

    result = push_once(store, host="test-host")
    assert result.status == "pushed", result.detail
    assert [(store / f"n{i}.md").exists() for i in range(1, 6)] == [True] * 5
    assert "remote" in (store / HANDOFF).read_text(encoding="utf-8")
    merges = _read(store, "rev-list", "--merges", "--count", "HEAD").strip()
    assert merges == "1"

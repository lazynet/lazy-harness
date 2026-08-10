"""One commit/rebase/push cycle for the knowledge store.

Producers never call this — the Stop hook and the compound-loop worker only
write files. Keeping git on a scheduler cycle means a broken transport (no
network, dead remote, bad credentials) cannot stall a session or lose a write:
the files are on disk and the next cycle picks them up.
"""

from __future__ import annotations

import fcntl
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

from lazy_harness.knowledge.marker import MarkerError, read_marker

LOCK_FILENAME = ".push.lock"


def _lock_path(root: Path) -> Path:
    """Where the cycle lock lives.

    Inside `.git/` when there is one: a lock in the work tree would make the
    store permanently dirty and end up committed as knowledge.
    """
    git_dir = root / ".git"
    return git_dir / LOCK_FILENAME if git_dir.is_dir() else root / LOCK_FILENAME


@dataclass(frozen=True)
class PushResult:
    status: str
    detail: str = ""


def _git(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True)


def _has_remote(root: Path) -> bool:
    return bool(_git(root, "remote").stdout.strip())


def _status(root: Path) -> list[str]:
    """Porcelain status with every untracked file listed individually.

    Without `-uall` git collapses an untracked directory to a single entry, so
    a fresh `learnings/YYYY-MM/` with twenty files would be counted as one.
    """
    return _git(root, "status", "--porcelain", "-uall").stdout.splitlines()


def _summarise(root: Path, marker_sessions: str, marker_learnings: str) -> str:
    paths = [line[3:] for line in _status(root)]
    sessions = sum(1 for p in paths if p.startswith(f"{marker_sessions}/"))
    learnings = sum(1 for p in paths if p.startswith(f"{marker_learnings}/"))
    return f"{sessions} sessions, {learnings} learnings"


def push_once(root: Path, host: str) -> PushResult:
    """Run one cycle. Expected failures are returned, not raised."""
    try:
        marker = read_marker(root)
    except MarkerError as e:
        return PushResult("invalid", str(e))

    lock_fd = os.open(str(_lock_path(root)), os.O_CREAT | os.O_WRONLY, 0o600)
    try:
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return PushResult("locked", "another cycle is running")

        dirty = bool(_status(root))
        # Only meaningful with a remote: `--not --remotes` on a remoteless repo
        # reports every commit ever made, so the cycle would never read clean.
        has_remote = _has_remote(root)
        ahead = has_remote and bool(
            _git(root, "log", "--branches", "--not", "--remotes", "--oneline").stdout.strip()
        )
        if not dirty and not ahead:
            return PushResult("clean")

        if dirty:
            summary = _summarise(root, marker.sessions, marker.learnings)
            _git(root, "add", "-A")
            commit = _git(root, "commit", "-m", f"knowledge: {summary} ({host})")
            if commit.returncode != 0:
                return PushResult("invalid", commit.stderr.strip())

        if not has_remote:
            return PushResult("committed", "no remote configured")

        rebase = _git(root, "pull", "--rebase")
        if rebase.returncode != 0:
            _git(root, "rebase", "--abort")
            return PushResult("conflict", rebase.stderr.strip())

        pushed = _git(root, "push")
        if pushed.returncode != 0:
            return PushResult("committed", pushed.stderr.strip())

        return PushResult("pushed")
    finally:
        fcntl.flock(lock_fd, fcntl.LOCK_UN)
        os.close(lock_fd)

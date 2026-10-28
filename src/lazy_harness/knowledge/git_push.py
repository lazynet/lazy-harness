"""One commit/merge/push cycle for the knowledge store.

Producers never call this — the Stop hook and the compound-loop worker only
write files. Keeping git on a scheduler cycle means a broken transport (no
network, dead remote, bad credentials) cannot stall a session or lose a write:
the files are on disk and the next cycle picks them up.
"""

from __future__ import annotations

import fcntl
import os
import re
import subprocess
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path, PurePosixPath

from lazy_harness.knowledge.marker import MarkerError, read_marker

LOCK_FILENAME = ".push.lock"

# Files that two hosts append to: a union merge keeps both sides' lines.
UNION_PATTERNS = ("*.jsonl", "claude-md.proposal.md")
_UNION_LINES = tuple(f"{pattern} merge=union" for pattern in UNION_PATTERNS)

# Two formats exist in the wild: YAML frontmatter and a body bullet.
_WRITTEN_AT = re.compile(r"^(?:written_at:|- Written at:)[ \t]*(\S+)[ \t]*$", re.MULTILINE)


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


def _ensure_gitattributes(root: Path) -> None:
    """Add the union-merge lines the file is missing, keeping everything else."""
    path = root / ".gitattributes"
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    present = {line.strip() for line in existing.splitlines()}
    missing = [line for line in _UNION_LINES if line not in present]
    if not missing:
        return
    if existing and not existing.endswith("\n"):
        existing += "\n"
    path.write_text(existing + "\n".join(missing) + "\n", encoding="utf-8")


def _is_handoff(path: str) -> bool:
    p = PurePosixPath(path)
    return p.name == "handoff.md" and p.parts[0] == "memory"


def _written_at(text: str) -> datetime | None:
    """The handoff's timestamp, or None when absent or without an offset."""
    match = _WRITTEN_AT.search(text)
    if match is None:
        return None
    try:
        stamp = datetime.fromisoformat(match.group(1).strip("'\""))
    except ValueError:
        return None
    return stamp if stamp.tzinfo is not None else None


def _resolve_handoffs(root: Path, conflicted: list[str]) -> bool:
    """Newest-wins on every conflicted handoff; False leaves the merge untouched."""
    picks: dict[str, str] = {}
    for path in conflicted:
        ours = _git(root, "show", f":2:{path}")
        theirs = _git(root, "show", f":3:{path}")
        if ours.returncode != 0 or theirs.returncode != 0:
            return False
        ours_at, theirs_at = _written_at(ours.stdout), _written_at(theirs.stdout)
        if ours_at is None or theirs_at is None:
            return False
        picks[path] = "--theirs" if theirs_at > ours_at else "--ours"
    for path, side in picks.items():
        if _git(root, "checkout", side, "--", path).returncode != 0:
            return False
        if _git(root, "add", "--", path).returncode != 0:
            return False
    return True


def _merge_upstream(root: Path) -> PushResult | None:
    """Merge the upstream into HEAD; a PushResult means the cycle must stop."""
    merge = _git(root, "merge", "--no-edit", "@{u}")
    if merge.returncode == 0:
        return None
    conflicted = _git(root, "diff", "--name-only", "--diff-filter=U").stdout.split()
    if (
        conflicted
        and all(_is_handoff(p) for p in conflicted)
        and _resolve_handoffs(root, conflicted)
        and _git(root, "commit", "--no-edit").returncode == 0
    ):
        return None
    _git(root, "merge", "--abort")
    detail = ", ".join(conflicted) if conflicted else merge.stderr.strip()
    return PushResult("conflict", detail)


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

        # Only meaningful with a remote: `--not --remotes` on a remoteless repo
        # reports every commit ever made, so the cycle would never read clean.
        has_remote = _has_remote(root)
        if has_remote:
            _ensure_gitattributes(root)
        dirty = bool(_status(root))
        ahead = has_remote and bool(
            _git(root, "log", "--branches", "--not", "--remotes", "--oneline").stdout.strip()
        )

        if dirty:
            summary = _summarise(root, marker.sessions, marker.learnings)
            _git(root, "add", "-A")
            commit = _git(root, "commit", "-m", f"knowledge: {summary} ({host})")
            if commit.returncode != 0:
                return PushResult("invalid", commit.stderr.strip())

        if not has_remote:
            return PushResult("committed", "no remote configured") if dirty else PushResult("clean")

        head_before = _git(root, "rev-parse", "HEAD").stdout.strip()
        fetched = _git(root, "fetch")
        if fetched.returncode != 0:
            if dirty or ahead:
                return PushResult("committed", fetched.stderr.strip())
            return PushResult("clean", fetched.stderr.strip())

        stopped = _merge_upstream(root)
        if stopped is not None:
            return stopped
        updated = _git(root, "rev-parse", "HEAD").stdout.strip() != head_before
        if not dirty and not ahead:
            return PushResult("updated" if updated else "clean")

        pushed = _git(root, "push")
        if pushed.returncode != 0:
            return PushResult("committed", pushed.stderr.strip())

        return PushResult("pushed")
    finally:
        fcntl.flock(lock_fd, fcntl.LOCK_UN)
        os.close(lock_fd)

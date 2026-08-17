"""Shared rendering / parsing helpers for `lh status` views.

These are pure functions — no I/O, no rich. The views import from here for
formatting (time_ago, format_size, decode_project_name, etc.) and for the
`StatusContext` dataclass that carries the resolved Config + paths into each
view function.
"""

from __future__ import annotations

import os
import re
import subprocess
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from pathlib import Path

from lazy_harness.core.config import Config
from lazy_harness.core.profiles import ProfileInfo, list_profiles
from lazy_harness.knowledge.directory import learnings_dir as knowledge_learnings_dir
from lazy_harness.knowledge.marker import MarkerError, resolve_root
from lazy_harness.scheduler.base import SchedulerBackend

HOOK_NAMES_DEFAULT = (
    "context-inject",
    "session-context",
    "session-export",
    "compound-loop",
    "pre-compact",
)


@dataclass
class StatusContext:
    """Everything a view needs to render. Built once per CLI invocation."""

    cfg: Config
    profiles: list[ProfileInfo] = field(default_factory=list)
    knowledge_path: Path | None = None
    learnings_dir: Path | None = None
    scheduler_backend: SchedulerBackend | None = None

    @classmethod
    def build(cls, cfg: Config) -> StatusContext:
        knowledge_path = resolve_root(cfg.knowledge.root or None)
        learnings_dir: Path | None
        try:
            learnings_dir = knowledge_learnings_dir(knowledge_path)
        except MarkerError:
            learnings_dir = None
        from lazy_harness.scheduler.manager import detect_backend

        return cls(
            cfg=cfg,
            profiles=list_profiles(cfg),
            knowledge_path=knowledge_path,
            learnings_dir=learnings_dir,
            # The views ask the backend what exists; they used to glob
            # ~/Library/LaunchAgents themselves, which made them macOS-only
            # regardless of which backend was actually active.
            scheduler_backend=detect_backend(cfg.scheduler.backend),
        )

    def logs_dir(self, profile: ProfileInfo) -> Path:
        return profile.config_dir / "logs"

    def queue_dir(self, profile: ProfileInfo) -> Path:
        return profile.config_dir / "queue"


def format_tokens(n: int | float) -> str:
    n = int(n)
    if n >= 1_000_000_000:
        return f"{n / 1_000_000_000:.1f}G"
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n / 1_000:.1f}K"
    return str(n)


def format_size(path: Path) -> str:
    try:
        size = path.stat().st_size
    except OSError:
        return "?"
    if size >= 1_048_576:
        return f"{size / 1_048_576:.1f}M"
    if size >= 1024:
        return f"{size / 1024:.0f}K"
    return f"{size}B"


_TS_FORMATS = (
    "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%dT%H:%M",
    "%Y-%m-%d",
)


def time_ago(ts: str) -> str:
    """Render an ISO-ish timestamp as 'just now', '5m ago', '3d ago', etc.

    Tolerates trailing timezone offsets and several common formats. Returns
    '?' on anything it cannot parse.
    """
    if not ts:
        return "—"
    clean = re.sub(r"[+-]\d{2}:?\d{2}$", "", ts.strip())
    dt: datetime | None = None
    for fmt in _TS_FORMATS:
        try:
            dt = datetime.strptime(clean, fmt)
            break
        except ValueError:
            continue
    if dt is None:
        return "?"
    diff = int((datetime.now() - dt).total_seconds())
    if diff < 0:
        return "just now"
    if diff < 60:
        return "just now"
    if diff < 3600:
        return f"{diff // 60}m ago"
    if diff < 86400:
        return f"{diff // 3600}h ago"
    if diff < 604800:
        return f"{diff // 86400}d ago"
    if diff < 2592000:
        return f"{diff // 604800}w ago"
    return f"{diff // 2592000}mo ago"


_KNOWN_CONTAINERS = frozenset({"repos", "projects", "src", "work", "dev", "code", "workspace"})


def decode_project_name(encoded: str) -> str:
    """Convert Claude Code's URL-encoded project dir name back to a readable name.

    Claude replaces '/' with '-', which is ambiguous for repos containing
    hyphens (e.g. `lazy-claudecode`). Try candidate splits against the
    filesystem; fall back to the segment after a known container.
    """
    if not encoded.startswith("-"):
        return encoded
    raw = encoded[1:]
    if not raw:
        return "(root)"
    parts = raw.split("-")

    def try_build(index: int, current_path: str) -> str | None:
        if index == len(parts):
            return current_path if os.path.exists(current_path) else None
        combined = parts[index]
        for j in range(index, len(parts)):
            if j > index:
                combined += "-" + parts[j]
            candidate = os.path.join(current_path, combined)
            r = try_build(j + 1, candidate)
            if r:
                return r
        return None

    resolved = try_build(0, "/")
    if resolved:
        return os.path.basename(resolved)
    for i, part in enumerate(parts):
        if part in _KNOWN_CONTAINERS and i + 1 < len(parts):
            return "-".join(parts[i + 1 :])
    return parts[-1] if parts else encoded


def last_hook_line(log_file: Path, hook_name: str) -> str:
    """Return the most recent hooks.log line mentioning `hook_name fired`."""
    if not log_file.is_file():
        return ""
    try:
        for line in reversed(log_file.read_text().splitlines()):
            if hook_name in line and "fired" in line:
                return line
    except OSError:
        pass
    return ""


def last_hook_ts(log_file: Path, hook_name: str) -> str:
    line = last_hook_line(log_file, hook_name)
    if not line:
        return ""
    parts = line.split()
    return parts[0] if parts else ""


def last_log_timestamp(log_file: Path) -> str:
    """Pull the most recent `[YYYY-MM-DD HH:MM:SS]` bracket-stamp from a log."""
    try:
        lines = log_file.read_text().splitlines()
    except OSError:
        return ""
    for line in reversed(lines[-50:]):
        match = re.search(r"\[([\d\- :.]+)\]", line)
        if match:
            return match.group(1).replace(" ", "T", 1)
    return ""


def count_errors_today(log_file: Path) -> int:
    if not log_file.is_file():
        return 0
    today = datetime.now().strftime("%Y-%m-%d")
    pattern = re.compile(r"parse error|failed|lockf failed|unexpected error", re.IGNORECASE)
    count = 0
    try:
        for line in log_file.read_text().splitlines():
            if today in line and pattern.search(line) and "Wrote:" not in line:
                count += 1
    except OSError:
        pass
    return count



class LockState(StrEnum):
    """Whether the worker's advisory lock is held.

    Three-valued for the same reason `JobState` is: the previous probe
    shelled out to `lsof` and read its absence as "not held", which is the
    dangerous direction — the view claims the worker is idle while it runs.
    """

    HELD = "held"
    FREE = "free"
    UNKNOWN = "unknown"


def lock_state(path: Path) -> tuple[LockState, str]:
    """Whether an advisory lock is held on `path`, without taking it.

    This must stay read-only. Probing by acquiring the lock — `flock` has no
    test mode, so acquiring is the only direct way — makes the probe race the
    worker for its own single-instance lock. Measured at 16.6% denial under
    contention, and every denial is `compound_loop_worker` logging "another
    worker is running", exiting 0, and leaving the queue undrained until the
    next scheduled run. `lsof` cannot do that; it only reads.
    """
    if not path.is_file():
        return LockState.FREE, ""
    try:
        result = subprocess.run(
            ["lsof", str(path)],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except FileNotFoundError as e:
        return LockState.UNKNOWN, f"lsof unavailable: {e}"
    except (subprocess.TimeoutExpired, OSError) as e:
        return LockState.UNKNOWN, f"lsof failed: {e}"
    return (LockState.HELD if result.returncode == 0 else LockState.FREE), ""

"""Simple append-only log file with size-based rotation.

Used by scheduled commands (knowledge sync/embed, context-gen) that need a
persistent trail without pulling in logging handlers. Rotation is best-effort:
on overflow, keep the last N lines in place (no .1/.2 backups).
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

DEFAULT_MAX_BYTES = 100 * 1024  # 100KB
DEFAULT_TAIL_LINES = 100


def default_log_dir() -> Path:
    return Path.home() / ".local" / "share" / "lazy-harness" / "logs"


def _rotate(path: Path, max_bytes: int, tail_lines: int) -> None:
    try:
        if path.stat().st_size <= max_bytes:
            return
    except OSError:
        return
    try:
        lines = path.read_text(errors="replace").splitlines()
    except OSError:
        return
    kept = lines[-tail_lines:] if len(lines) > tail_lines else lines
    tmp = path.with_name(f".{path.name}.rot")
    try:
        tmp.write_text("\n".join(kept) + "\n")
        tmp.replace(path)
    except OSError:
        try:
            tmp.unlink()
        except OSError:
            pass


def append(
    path: Path,
    message: str,
    *,
    max_bytes: int = DEFAULT_MAX_BYTES,
    tail_lines: int = DEFAULT_TAIL_LINES,
) -> None:
    """Append a timestamped line to `path`, rotating if it grows past `max_bytes`.

    Best-effort: silently swallows OSError so a failing log never crashes the
    caller (these are scheduled background jobs).
    """
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
    except OSError:
        return
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {message}\n"
    try:
        with open(path, "a") as f:
            f.write(line)
    except OSError:
        return
    _rotate(path, max_bytes, tail_lines)

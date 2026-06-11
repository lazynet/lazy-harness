"""Shared helpers for builtin hooks.

Behavior-preserving extraction of the `_log` and `_find_latest_session`
helpers that were copy-pasted across the builtin hooks. Hooks bind
`_log = make_log("<hook-name>")` at module level so call sites stay
identical to the historical per-module definitions.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from pathlib import Path


def make_log(hook_name: str) -> Callable[[Path, str], None]:
    """Build a fail-soft logger that prefixes lines with `<ts> <hook_name>:`."""

    def _log(log_file: Path, msg: str) -> None:
        try:
            log_file.parent.mkdir(parents=True, exist_ok=True)
            ts = datetime.now().astimezone().isoformat(timespec="seconds")
            with open(log_file, "a") as f:
                f.write(f"{ts} {hook_name}: {msg}\n")
        except OSError:
            pass

    return _log


def find_latest_session(sessions_dir: Path) -> Path | None:
    """Most recently modified session JSONL in `sessions_dir`, or None."""
    if not sessions_dir.is_dir():
        return None
    jsonl_files = [p for p in sessions_dir.glob("*.jsonl") if p.is_file()]
    if not jsonl_files:
        return None
    return max(jsonl_files, key=lambda f: f.stat().st_mtime)

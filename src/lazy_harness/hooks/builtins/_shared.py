"""Shared helpers for builtin hooks.

Behavior-preserving extraction of the `_log` and `_find_latest_session`
helpers that were copy-pasted across the builtin hooks. Hooks bind
`_log = make_log("<hook-name>")` at module level so call sites stay
identical to the historical per-module definitions.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import datetime
from pathlib import Path

_TRANSCRIPT_KEYS = ("transcript_path", "transcriptPath", "input")


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


def _declared_transcript(payload: object) -> Path | None:
    """Transcript path as declared in the payload, without touching the filesystem."""
    if not isinstance(payload, Mapping):
        return None
    for key in _TRANSCRIPT_KEYS:
        raw = payload.get(key)
        if isinstance(raw, str) and raw:
            return Path(raw)
    return None


def transcript_from_payload(payload: object) -> Path | None:
    """Session JSONL the agent declared on stdin, or None if absent/not yet written."""
    declared = _declared_transcript(payload)
    if declared is None:
        return None
    return declared if declared.is_file() else None


def project_dir_from_payload(payload: object) -> Path | None:
    """Agent-owned per-project session dir, read from the declared transcript.

    The agent encodes the cwd into this directory name with a scheme that has
    changed across releases, so it is read here rather than recomputed. At
    SessionStart the transcript is not written yet, so only its parent is
    required to exist.
    """
    declared = _declared_transcript(payload)
    if declared is None:
        return None
    parent = declared.parent
    return parent if parent.is_dir() else None


def resolve_project_dir(
    payload: object, *, agent_dir: Path, sessions_subdir: str, cwd: Path
) -> Path:
    """Per-project session dir: the agent's own, else one derived from `cwd`.

    Only a declared dir inside the adapter's sessions root is honoured, so
    harness artifacts never escape it (ADR-032). The cwd-derived fallback
    matches agents whose encoding is a plain slash-to-dash rewrite.
    """
    sessions_root = agent_dir / (sessions_subdir or "projects")
    declared = project_dir_from_payload(payload)
    if declared is not None and declared.parent == sessions_root:
        return declared
    encoded = "-" + str(cwd).replace("/", "-").lstrip("-")
    return sessions_root / encoded

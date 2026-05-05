"""PostToolUse hook — regenerate per-profile CLAUDE.md after segment edits.

Triggers when an Edit/Write touches a `CLAUDE.head.md`, `CLAUDE.tail.md`, or
`CLAUDE.common.md` inside a `.../profiles/<dir>/` tree, and re-runs the
segmented CLAUDE.md generator against that tree.

Fail-soft: any error is swallowed and the hook exits 0, because a sync
failure must never block the agent's progress.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from lazy_harness.core.sync_claude import sync_profiles

SEGMENT_FILES = {"CLAUDE.head.md", "CLAUDE.tail.md", "CLAUDE.common.md"}


def _read_stdin_json() -> dict[str, Any]:
    try:
        data = sys.stdin.read()
    except (OSError, ValueError):
        return {}
    if not data.strip():
        return {}
    try:
        parsed = json.loads(data)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _profiles_dir_for(path: Path) -> Path | None:
    """If `path` lives at `<profiles>/<name>/<segment>` or
    `<profiles>/_common/CLAUDE.common.md`, return `<profiles>`. Else None."""
    parts = path.parts
    for i in range(len(parts) - 2, -1, -1):
        if parts[i] == "profiles":
            return Path(*parts[: i + 1])
    return None


def main() -> None:
    payload = _read_stdin_json()
    if payload.get("tool_name") not in ("Edit", "Write"):
        sys.exit(0)
    raw_path = str(payload.get("tool_input", {}).get("file_path", ""))
    if not raw_path:
        sys.exit(0)
    path = Path(raw_path)
    if path.name not in SEGMENT_FILES:
        sys.exit(0)
    profiles_dir = _profiles_dir_for(path)
    if profiles_dir is None:
        sys.exit(0)
    try:
        sync_profiles(profiles_dir)
    except Exception:
        pass
    sys.exit(0)


if __name__ == "__main__":
    main()

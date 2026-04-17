"""PostToolUse auto-format hook — runs `ruff format` on Python edits.

Fail-soft: all errors are swallowed and exit 0, because a formatter failure
must never block the agent's progress. See spec
`specs/designs/2026-04-17-security-hooks-cluster-design.md`.
"""

from __future__ import annotations

import json
import subprocess
import sys
from typing import Any

RUFF_TIMEOUT_SECS = 10


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


def main() -> None:
    payload = _read_stdin_json()
    if payload.get("tool_name") not in ("Edit", "Write"):
        sys.exit(0)
    path = str(payload.get("tool_input", {}).get("file_path", ""))
    if not path.endswith(".py"):
        sys.exit(0)
    try:
        subprocess.run(
            ["ruff", "format", path],
            check=False,
            capture_output=True,
            timeout=RUFF_TIMEOUT_SECS,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    sys.exit(0)


if __name__ == "__main__":
    main()

"""PreToolUse hook: surface the cost of reading a large file whole.

Non-blocking. A `Read` without `offset`/`limit` pulls the entire file into
context; on large files that is the single biggest context expense in a
session. Emits `hookSpecificOutput.systemMessage` so the read still goes
through and the caller sees what it is about to spend.

Bypass with `LH_READ_SIZE_BYPASS=1`.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

MAX_LINES = 500
BYTES_PER_TOKEN = 4


def _read_stdin_json() -> dict:
    try:
        return json.loads(sys.stdin.read())
    except (json.JSONDecodeError, ValueError):
        return {}


def _measure(path: Path) -> tuple[int, int] | None:
    """Return (lines, estimated tokens), or None if the file cannot be sized."""
    try:
        raw = path.read_bytes()
    except OSError:
        return None
    if not raw:
        return None
    lines = raw.count(b"\n") + (0 if raw.endswith(b"\n") else 1)
    return lines, len(raw) // BYTES_PER_TOKEN


def _emit_warning(file_path: str, lines: int, tokens: int) -> None:
    output = {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "systemMessage": (
                f"WARN: {file_path} is {lines} lines (~{tokens} tokens) and this Read "
                "is unbounded. Pass offset/limit for the region you need, or use Grep "
                "to locate it first."
            ),
        }
    }
    print(json.dumps(output))
    _log_warning(file_path, lines, tokens)


def _log_warning(file_path: str, lines: int, tokens: int) -> None:
    """Record the warning so its frequency is auditable after the fact."""
    try:
        from lazy_harness.agents.registry import get_agent
        from lazy_harness.core.paths import agent_runtime_dir
        from lazy_harness.hooks.builtins._shared import make_log

        agent_dir = agent_runtime_dir(get_agent("claude-code"))
        log = make_log("pre-tool-use-read-size")
        log(
            agent_dir / "logs" / "hooks.log",
            f"unbounded read: {file_path} {lines} lines ~{tokens} tokens",
        )
    except Exception:
        # Auditing must never break the warning path.
        pass


def main() -> None:
    if os.environ.get("LH_READ_SIZE_BYPASS") == "1":
        sys.exit(0)

    payload = _read_stdin_json()
    if payload.get("tool_name") != "Read":
        sys.exit(0)

    tool_input = payload.get("tool_input") or {}
    if tool_input.get("offset") is not None or tool_input.get("limit") is not None:
        sys.exit(0)

    file_path = tool_input.get("file_path", "")
    if not file_path:
        sys.exit(0)

    measured = _measure(Path(file_path))
    if measured is not None and measured[0] > MAX_LINES:
        _emit_warning(file_path, measured[0], measured[1])

    sys.exit(0)


if __name__ == "__main__":
    main()

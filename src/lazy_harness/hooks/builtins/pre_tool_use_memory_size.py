"""PreToolUse hook: warn when MEMORY.md edits push past the curated ceiling.

ADR-030 G2 — non-blocking. Emits hookSpecificOutput.systemMessage as a warning
banner so the write goes through and the user sees a hint to consolidate.

Bypass with `LH_MEMORY_SIZE_BYPASS=1` (used by the consolidator pathway).
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

MAX_LINES = 200


def _read_stdin_json() -> dict:
    try:
        return json.loads(sys.stdin.read())
    except (json.JSONDecodeError, ValueError):
        return {}


def _is_memory_md_path(file_path: str) -> bool:
    if not file_path:
        return False
    normalized = file_path.replace("\\", "/")
    return normalized.endswith("/memory/MEMORY.md")


def _line_count(text: str) -> int:
    if not text:
        return 0
    return text.count("\n") + (0 if text.endswith("\n") else 1)


def _projected_line_count(tool_name: str, tool_input: dict) -> int | None:
    """Predict line count after the operation, or None if undeterminable."""
    file_path = tool_input.get("file_path", "")
    if not file_path:
        return None

    if tool_name == "Write":
        return _line_count(tool_input.get("content", ""))

    if tool_name == "Edit":
        path = Path(file_path)
        if not path.is_file():
            return None
        try:
            current = path.read_text()
        except OSError:
            return None
        old = tool_input.get("old_string", "")
        new = tool_input.get("new_string", "")
        if tool_input.get("replace_all"):
            projected = current.replace(old, new)
        else:
            projected = current.replace(old, new, 1)
        return _line_count(projected)

    return None


def _emit_warning(file_path: str, projected_lines: int) -> None:
    output = {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "systemMessage": (
                f"WARN: MEMORY.md at {file_path} would have {projected_lines} lines "
                f"(threshold {MAX_LINES}). Consider running `lh memory consolidate` "
                "to distill recent JSONL entries before adding more."
            ),
        }
    }
    print(json.dumps(output))


def main() -> None:
    if os.environ.get("LH_MEMORY_SIZE_BYPASS") == "1":
        sys.exit(0)

    payload = _read_stdin_json()
    tool_name = payload.get("tool_name", "")
    tool_input = payload.get("tool_input", {})

    if tool_name not in {"Edit", "Write"}:
        sys.exit(0)

    file_path = tool_input.get("file_path", "")
    if not _is_memory_md_path(file_path):
        sys.exit(0)

    projected = _projected_line_count(tool_name, tool_input)
    if projected is not None and projected > MAX_LINES:
        _emit_warning(file_path, projected)

    sys.exit(0)


if __name__ == "__main__":
    main()

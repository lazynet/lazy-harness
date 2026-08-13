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

# What the context window pays for is bytes, not newlines. A curated index of
# one long line per note stays far under the line ceiling while dominating the
# session's boot context: a real 67-line index measured 20KB and cost ~3.6k
# tokens on every session start. 12KB is roughly 3k tokens — enough room for a
# rich index, tight enough to complain before it silently becomes the largest
# controllable slice of the prompt prefix.
MAX_BYTES = 12_000


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


def _projected_text(tool_name: str, tool_input: dict) -> str | None:
    """The file's content after the operation, or None if undeterminable."""
    file_path = tool_input.get("file_path", "")
    if not file_path:
        return None

    if tool_name == "Write":
        return tool_input.get("content", "")

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
            return current.replace(old, new)
        return current.replace(old, new, 1)

    return None


def _emit_warning(file_path: str, breach: str) -> None:
    output = {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "systemMessage": (
                f"WARN: MEMORY.md at {file_path} would be {breach}. Consider running "
                "`lh memory consolidate` to distill recent JSONL entries, or move detail "
                "out of the index into the linked note, before adding more."
            ),
        }
    }
    print(json.dumps(output))
    _log_warning(file_path, breach)


def _log_warning(file_path: str, breach: str) -> None:
    """Record the warning so its frequency is auditable after the fact."""
    try:
        from lazy_harness.agents.registry import get_agent
        from lazy_harness.core.paths import agent_runtime_dir
        from lazy_harness.hooks.builtins._shared import make_log

        agent_dir = agent_runtime_dir(get_agent("claude-code"))
        log = make_log("pre-tool-use-memory-size")
        log(
            agent_dir / "logs" / "hooks.log",
            f"over threshold: {file_path} would be {breach}",
        )
    except Exception:
        # Auditing must never break the warning path.
        pass


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

    projected = _projected_text(tool_name, tool_input)
    if projected is None:
        sys.exit(0)

    lines = _line_count(projected)
    size = len(projected.encode("utf-8"))
    breaches = []
    if lines > MAX_LINES:
        breaches.append(f"{lines} lines (threshold {MAX_LINES})")
    if size > MAX_BYTES:
        breaches.append(f"{size / 1000:.1f}KB (threshold {MAX_BYTES / 1000:.0f}KB)")

    if breaches:
        _emit_warning(file_path, " and ".join(breaches))

    sys.exit(0)


if __name__ == "__main__":
    main()

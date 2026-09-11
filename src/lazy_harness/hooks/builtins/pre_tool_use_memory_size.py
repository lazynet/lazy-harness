"""PreToolUse hook: warn when MEMORY.md or CLAUDE.md edits push past ceiling.

ADR-030 G2 — non-blocking. Emits hookSpecificOutput.systemMessage as a warning
banner so the write goes through and the user sees a hint to trim.

CLAUDE.md gets its own threshold pair (1a of the September 2026 harness
improvements design), separate from MEMORY.md's: the two files have different
jobs — MEMORY.md is a curated index, CLAUDE.md is a contract that loads on
every session in every profile. `lh memory rightsize` surfaces the same
thresholds across every CLAUDE.md the harness can reach.

Bypass with `LH_MEMORY_SIZE_BYPASS=1` (used by the consolidator pathway).
"""

from __future__ import annotations

import json
import os
import sys
import tomllib
from pathlib import Path

# The tool names this hook inspects. `tests/unit/test_hook_matcher_coverage.py`
# asserts the matcher the registry deploys covers every one of them, so the gate
# below and the subscription declared outside cannot drift apart.
INSPECTED_TOOLS = frozenset({"Edit", "Write"})

MAX_LINES = 200

# What the context window pays for is bytes, not newlines. A curated index of
# one long line per note stays far under the line ceiling while dominating the
# session's boot context: a real 67-line index measured 20KB and cost ~3.6k
# tokens on every session start. 12KB is roughly 3k tokens — enough room for a
# rich index, tight enough to complain before it silently becomes the largest
# controllable slice of the prompt prefix.
MAX_BYTES = 12_000

# CLAUDE.md defaults match the literature ceiling for an always-loaded
# contract (~200 lines / ~12KB). Overridable per profile under
# [hooks.pre_tool_use].claude_md_max_lines / claude_md_max_bytes.
CLAUDE_MD_MAX_LINES = 200
CLAUDE_MD_MAX_BYTES = 12_000


def _read_stdin_json() -> dict:
    try:
        data = json.loads(sys.stdin.read())
    except (json.JSONDecodeError, ValueError):
        return {}
    # Valid JSON that is not an object (null, a number, a list, a bare
    # string) parses cleanly but is not the payload shape Claude Code sends —
    # treating it as empty keeps every downstream .get() safe.
    return data if isinstance(data, dict) else {}


def _is_memory_md_path(file_path: str) -> bool:
    if not file_path:
        return False
    normalized = file_path.replace("\\", "/")
    return normalized.endswith("/memory/MEMORY.md")


def _is_claude_md_path(file_path: str) -> bool:
    if not file_path:
        return False
    normalized = file_path.replace("\\", "/")
    return normalized == "CLAUDE.md" or normalized.endswith("/CLAUDE.md")


def load_claude_md_thresholds(cfg_path: Path | None = None) -> tuple[int, int]:
    """CLAUDE.md line/byte ceilings from [hooks.pre_tool_use] in config.toml.

    Same fail-soft contract as the security hook's allowlist loader: a missing
    file, malformed TOML, missing section, or wrong-typed value falls back to
    the module defaults rather than raising or blocking the write. Shared with
    `lh memory rightsize` so the hook and the audit command cannot silently
    disagree about where the ceiling is.
    """
    try:
        path = cfg_path if cfg_path is not None else _config_file()
        if path is None or not path.is_file():
            return CLAUDE_MD_MAX_LINES, CLAUDE_MD_MAX_BYTES
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return CLAUDE_MD_MAX_LINES, CLAUDE_MD_MAX_BYTES

    hooks_section = data.get("hooks", {})
    section = hooks_section.get("pre_tool_use", {}) if isinstance(hooks_section, dict) else {}
    if not isinstance(section, dict):
        return CLAUDE_MD_MAX_LINES, CLAUDE_MD_MAX_BYTES

    lines = section.get("claude_md_max_lines", CLAUDE_MD_MAX_LINES)
    if not isinstance(lines, int) or isinstance(lines, bool) or lines <= 0:
        lines = CLAUDE_MD_MAX_LINES

    max_bytes = section.get("claude_md_max_bytes", CLAUDE_MD_MAX_BYTES)
    if not isinstance(max_bytes, int) or isinstance(max_bytes, bool) or max_bytes <= 0:
        max_bytes = CLAUDE_MD_MAX_BYTES

    return lines, max_bytes


def _config_file() -> Path | None:
    try:
        from lazy_harness.core.paths import config_file

        return config_file()
    except Exception:
        return None


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


def _emit_warning(file_path: str, breach: str, kind: str) -> None:
    if kind == "MEMORY.md":
        hint = (
            "Consider running `lh memory consolidate` to distill recent JSONL "
            "entries, or move detail out of the index into the linked note, "
            "before adding more."
        )
    else:
        hint = (
            "Consider whether each line is a fact the agent needs or a "
            "procedure it would already follow. `lh memory rightsize` shows "
            "every CLAUDE.md the harness can reach and which ceiling it breaches."
        )
    output = {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "systemMessage": f"WARN: {kind} at {file_path} would be {breach}. {hint}",
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

    if tool_name not in INSPECTED_TOOLS:
        sys.exit(0)
    if not isinstance(tool_input, dict):
        sys.exit(0)

    file_path = tool_input.get("file_path", "")
    if not isinstance(file_path, str) or not file_path:
        sys.exit(0)

    if _is_memory_md_path(file_path):
        kind = "MEMORY.md"
        max_lines, max_bytes = MAX_LINES, MAX_BYTES
    elif _is_claude_md_path(file_path):
        kind = "CLAUDE.md"
        max_lines, max_bytes = load_claude_md_thresholds()
    else:
        sys.exit(0)

    projected = _projected_text(tool_name, tool_input)
    if projected is None:
        sys.exit(0)

    lines = _line_count(projected)
    size = len(projected.encode("utf-8"))
    breaches = []
    if lines > max_lines:
        breaches.append(f"{lines} lines (threshold {max_lines})")
    if size > max_bytes:
        breaches.append(f"{size / 1000:.1f}KB (threshold {max_bytes / 1000:.0f}KB)")

    if breaches:
        _emit_warning(file_path, " and ".join(breaches), kind)

    sys.exit(0)


if __name__ == "__main__":
    main()

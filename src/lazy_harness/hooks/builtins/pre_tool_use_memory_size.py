"""PreToolUse hook: warn when MEMORY.md or CLAUDE.md edits push past ceiling.

ADR-030 G2 — non-blocking. Returns a top-level `system_message` as a warning
banner so the write goes through and the user sees a hint to trim. The verdict
stays `None`: `pre_tool_use` honours `DENY`, and an abstention that reads as
approval is exactly what `HookDecision.verdict` defaults to `None` to prevent.

CLAUDE.md gets its own threshold pair (1a of the September 2026 harness
improvements design), separate from MEMORY.md's: the two files have different
jobs — MEMORY.md is a curated index, CLAUDE.md is a contract that loads on
every session in every profile. `lh memory rightsize` surfaces the same
thresholds across every CLAUDE.md the harness can reach.

Bypass with `LH_MEMORY_SIZE_BYPASS=1` (used by the consolidator pathway).
"""

from __future__ import annotations

import os
import tomllib
from pathlib import Path
from typing import NamedTuple

# Module level, not under `TYPE_CHECKING`: `test_builtin_registry` resolves the
# signature with `typing.get_type_hints`, which evaluates the annotations
# against module globals and raises `NameError` on a name that only exists for
# the type checker.
from lazy_harness.agents.base import FileEdit, HookDecision, HookEvent

# The tool names this hook inspects. `tests/unit/test_hook_matcher_coverage.py`
# asserts the matcher the registry deploys covers every one of them, so the gate
# below and the subscription declared outside cannot drift apart.
#
# It is also the gate itself, and stays so after the migration on purpose.
# `event.tool.operation is Operation.MODIFY_FILE` looks like the normalised
# spelling and is not: `_TOOL_OPERATIONS` maps `NotebookEdit` to `MODIFY_FILE`
# beside `Edit` and `Write` (`claude_code.py:97`), and `_FILE_PATH_KEYS` reads
# `notebook_path` into the same `FileEdit.path`. The filename re-checks below
# do not narrow that back — they match `MEMORY.md` and `CLAUDE.md` by *name*,
# and nothing in `ToolCall` makes a notebook's path end `.ipynb` — so a notebook
# called `CLAUDE.md` would clear them. The suffix exclusion the migration plan
# offers as an alternative is therefore a no-op here, and the native-name gate
# is the only narrowing that holds.
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


def _projected_text(tool_name: str, edit: FileEdit) -> str | None:
    """The file's content after the operation, or None if undeterminable.

    Branching on the tool name rather than on which `FileEdit` fields are
    populated, because the two disagree on one live shape: an `Edit` whose
    payload carries no `old_string` normalises to empty `replacements`, and the
    pre-migration code projected the *current* file for it — `str.replace("",
    "", 1)` returns the subject unchanged — where a "no replacements, nothing to
    project" reading would return None and go quiet. Byte identity is this
    migration's acceptance test, so the odd branch is kept rather than tidied.
    """
    if tool_name == "Write":
        # A `Write` with no `content` normalises to None and projected `""`
        # before the migration; both are silent, and `""` is the honest one.
        return edit.content if edit.content is not None else ""

    if tool_name == "Edit":
        if not edit.path.is_file():
            return None
        try:
            current = edit.path.read_text()
        except OSError:
            return None
        for old, new in edit.replacements:
            current = (
                current.replace(old, new) if edit.replace_all else current.replace(old, new, 1)
            )
        return current

    return None


class _Warning(NamedTuple):
    """The two spellings one breach gets, kept apart on purpose.

    `banner` is what the session reads and carries the remedy; `audit` is the
    `hooks.log` line, which names the file and the breach and stops there. They
    were never the same string — deriving one from the other by stripping a
    prefix would have put the whole hint into every log line.
    """

    banner: str
    audit: str


def _warning_for(edit: FileEdit, tool_name: str) -> _Warning | None:
    """The warning this edit earns, or None when it is within budget."""
    file_path = str(edit.path)
    if _is_memory_md_path(file_path):
        kind = "MEMORY.md"
        max_lines, max_bytes = MAX_LINES, MAX_BYTES
    elif _is_claude_md_path(file_path):
        kind = "CLAUDE.md"
        max_lines, max_bytes = load_claude_md_thresholds()
    else:
        return None

    projected = _projected_text(tool_name, edit)
    if projected is None:
        return None

    lines = _line_count(projected)
    size = len(projected.encode("utf-8"))
    breaches = []
    if lines > max_lines:
        breaches.append(f"{lines} lines (threshold {max_lines})")
    if size > max_bytes:
        breaches.append(f"{size / 1000:.1f}KB (threshold {max_bytes / 1000:.0f}KB)")
    if not breaches:
        return None

    breach = " and ".join(breaches)
    return _Warning(
        banner=_format_warning(file_path, breach, kind),
        audit=f"over threshold: {file_path} would be {breach}",
    )


def _format_warning(file_path: str, breach: str, kind: str) -> str:
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
    return f"WARN: {kind} at {file_path} would be {breach}. {hint}"


def main(event: HookEvent) -> HookDecision:
    if os.environ.get("LH_MEMORY_SIZE_BYPASS") == "1":
        return HookDecision()

    tool = event.tool
    # The native name rather than the operation — see `INSPECTED_TOOLS`.
    if tool is None or tool.native_name not in INSPECTED_TOOLS:
        return HookDecision()

    # `edits` is plural because Codex's `apply_patch` and Copilot's `edit` can
    # touch several files in one call. Claude Code yields at most one, so this
    # loop is a single pass there; taking `edits[0]` instead would re-introduce
    # the singular `file_path` assumption the contract exists to remove.
    warnings = [
        warning
        for edit in tool.edits
        if (warning := _warning_for(edit, tool.native_name)) is not None
    ]
    if not warnings:
        return HookDecision()

    for warning in warnings:
        _log_warning(warning.audit, event.profile)
    # No verdict: this hook warns and lets the write through. `pre_tool_use`
    # honours `DENY`, so leaving the field to its `None` default is the whole
    # difference between a banner and a refused tool call.
    return HookDecision(system_message="\n\n".join(w.banner for w in warnings))


def _log_warning(audit: str, profile: str) -> None:
    """Record the warning under the *invoked profile's* agent directory.

    This used to be `get_agent("claude-code")` plus `agent_runtime_dir(agent)`
    with no profile, so a hook running under `--profile p` appended its line to
    whatever directory the global agent named — measured under `--profile gate`
    landing in `~/.claude/logs/hooks.log` while the warning itself reached the
    session normally, which is what kept the split invisible.
    `tests/integration/test_hook_log_profile_isolation.py` holds both halves.
    """
    try:
        from lazy_harness.core.config import Config, ConfigError, load_config
        from lazy_harness.core.paths import config_file
        from lazy_harness.hooks.builtins._shared import agent_dir_for, make_log

        cf = config_file()
        cfg: Config | None = None
        if cf.is_file():
            try:
                cfg = load_config(cf)
            except ConfigError:
                cfg = None

        agent_dir = agent_dir_for(cfg, profile)[1]
        log = make_log("pre-tool-use-memory-size")
        log(agent_dir / "logs" / "hooks.log", audit)
    except Exception:  # noqa: BLE001 — auditing must never break the warning path
        pass

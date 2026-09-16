"""PreToolUse hook: surface the cost of reading a large file whole.

Non-blocking. A `Read` without `offset`/`limit` pulls the entire file into
context; on large files that is the single biggest context expense in a
session. Emits a top-level `systemMessage` so the read still goes
through and the caller sees what it is about to spend.

Bypass with `LH_READ_SIZE_BYPASS=1`.
"""

from __future__ import annotations

import os
from pathlib import Path

from lazy_harness.agents.base import HookDecision, HookEvent, Operation

# The tool names this hook inspects. `tests/unit/test_hook_matcher_coverage.py`
# asserts the matcher the registry deploys covers every one of them, so the gate
# below and the subscription declared outside cannot drift apart.
INSPECTED_TOOLS = frozenset({"Read"})

MAX_LINES = 500
BYTES_PER_TOKEN = 4


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


def _warning(file_path: str, lines: int, tokens: int) -> str:
    """The text the agent reads, as a `systemMessage` and not as context.

    `HookDecision.system_message` lands top level in the adapter's output, never
    inside `hookSpecificOutput`: that object accepts exactly additionalContext,
    permissionDecision, permissionDecisionReason and updatedInput, and discards
    anything else. Nested, this warning parsed without error and displayed
    nothing. `claude_code.format_hook_output` now owns that placement, and
    `pre_tool_use_memory_size` points here for the reason.
    """
    return (
        f"WARN: {file_path} is {lines} lines (~{tokens} tokens) and this Read "
        "is unbounded. Pass offset/limit for the region you need, or use Grep "
        "to locate it first."
    )


def _log_warning(message: str, profile: str) -> None:
    """Record the warning under the *invoked profile's* agent directory.

    This used to be `get_agent("claude-code")` plus `agent_runtime_dir(agent)`
    with no profile, so a hook running under `--profile p` appended its line to
    whatever directory the global agent named. Measured before the fix: under
    `--profile gate` the line landed in `~/.claude/logs/hooks.log`, a different
    live profile on the same machine. `docs/how/hooks.md` named this hook as one
    of the two that still resolved it globally.
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
        log = make_log("pre-tool-use-read-size")
        log(agent_dir / "logs" / "hooks.log", message)
    except Exception:  # noqa: BLE001 — auditing must never break the warning path
        pass


def main(event: HookEvent) -> HookDecision:
    """Warn about one unbounded read, without deciding anything about it.

    The return is a bare `HookDecision(system_message=...)`: `pre_tool_use` is
    the event Claude Code honours `Verdict.DENY` on, so a verdict here would turn
    a cost notice into a permission decision. `HookDecision.verdict` defaults to
    `None` for exactly that reason and this hook never sets it.
    """
    if os.environ.get("LH_READ_SIZE_BYPASS") == "1":
        return HookDecision()

    tool = event.tool
    # Both halves, deliberately. `_TOOL_OPERATIONS` maps only `Read` into
    # `READ_FILE` today, so the operation alone happens to be equivalent — but
    # `INSPECTED_TOOLS` is what the deployed matcher is held against, and a guard
    # that stopped reading it would act on a second READ_FILE tool the matcher
    # never named while that gate stayed green. Trap 3 measured the same shape on
    # `MODIFY_FILE`, where `NotebookEdit` makes the widening live already.
    if tool is None or tool.operation is not Operation.READ_FILE:
        return HookDecision()
    if tool.native_name not in INSPECTED_TOOLS:
        return HookDecision()

    # `None`, not falsy: 0 is a legitimate start offset and `ToolCall.offset`
    # documents `None` alone as unbounded.
    if tool.offset is not None or tool.limit is not None:
        return HookDecision()

    # `reads` is plural because another agent's tool can name several paths in
    # one call. Claude Code yields at most one, so this loop is a single pass
    # there; taking `reads[0]` instead would re-introduce the singular
    # `file_path` assumption the contract exists to remove.
    for path in tool.reads:
        measured = _measure(path)
        if measured is None or measured[0] <= MAX_LINES:
            continue
        message = _warning(str(path), measured[0], measured[1])
        _log_warning(
            f"unbounded read: {path} {measured[0]} lines ~{measured[1]} tokens",
            event.profile,
        )
        return HookDecision(system_message=message)

    return HookDecision()

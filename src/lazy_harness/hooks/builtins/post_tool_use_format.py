"""PostToolUse auto-format hook — runs `ruff format` on Python edits.

Fail-soft: every error is swallowed and the hook abstains, because a formatter
failure must never block the agent's progress. See spec
`specs/designs/2026-04-17-security-hooks-cluster-design.md`.
"""

from __future__ import annotations

import subprocess

from lazy_harness.agents.base import HookDecision, HookEvent, Operation

# The tool names this hook inspects. `tests/unit/test_hook_matcher_coverage.py`
# asserts the matcher the registry deploys covers every one of them, so the gate
# below and the subscription declared outside cannot drift apart.
#
# It is also the narrowing `Operation.MODIFY_FILE` does not give: the adapter
# maps `NotebookEdit` to that operation too (`claude_code.py:97`), and this hook
# carries no matcher, so it is invoked on every PostToolUse. The `.py` suffix
# check below would not catch the difference — nothing in `ToolCall` makes a
# notebook's path end in `.ipynb`, so a `NotebookEdit` naming `notebook.py`
# would get Ruff run over a file that was never Python source.
INSPECTED_TOOLS = frozenset({"Edit", "Write"})

RUFF_TIMEOUT_SECS = 10


def main(event: HookEvent) -> HookDecision:
    """Format every Python file this tool call modified. Never refuses."""
    tool = event.tool
    if tool is None or tool.operation is not Operation.MODIFY_FILE:
        return HookDecision()
    if tool.native_name not in INSPECTED_TOOLS:
        return HookDecision()
    for edit in tool.edits:
        path = str(edit.path)
        if not path.endswith(".py"):
            continue
        try:
            subprocess.run(
                ["ruff", "format", path],
                check=False,
                capture_output=True,
                timeout=RUFF_TIMEOUT_SECS,
            )
        except (OSError, subprocess.TimeoutExpired) as e:
            # Silence here made a formatter that never ran look like one that
            # always did; record the reason so the gap is visible in the log.
            _log_unavailable(event, path, e)
    return HookDecision()


def _log_unavailable(event: HookEvent, path: str, error: Exception) -> None:
    try:
        from lazy_harness.core.config import Config, ConfigError, load_config
        from lazy_harness.core.paths import config_file
        from lazy_harness.hooks.builtins import _shared

        cf = config_file()
        cfg: Config | None = None
        if cf.is_file():
            try:
                cfg = load_config(cf)
            except ConfigError:
                cfg = None

        agent_dir = _shared.agent_dir_for(cfg, event.profile)[1]
        log = _shared.make_log("post-tool-use-format")
        log(
            agent_dir / "logs" / "hooks.log",
            f"ruff unavailable ({type(error).__name__}), left {path} unformatted",
        )
    except Exception:  # noqa: BLE001 — the fail-soft branch cannot itself fail
        pass

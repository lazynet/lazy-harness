"""`post-tool-use-sync-system-doc`'s matcher, as the deploy planner produces it.

The hook shipped with a hand-authored `matcher="Edit|Write"` — correct for
Claude Code, and silently inert on Codex: `apply_patch` never matches
`Edit|Write`, so a profile running Codex never regenerated its system doc from
a segment edit. There is no per-agent matcher *derivation* anywhere in this
codebase (measured: `BuiltinHookSpec.matcher` is always a literal, and each
adapter's own config-generation method decides what an absent matcher becomes).
The fix is narrower than "derive one": drop the literal and let each adapter's
existing default take over — Claude Code's own `post_tool_use` default is
already `Edit|Write`, so nothing observable changes there, and Codex omits the
`matcher` key entirely on a falsy one, which is the only form its own hooks
fire on every tool call under (`test_the_codex_side_reaches_its_edit_tool_without_a_matcher`
in `test_hook_matcher_coverage.py`).

These tests run the actual deploy planner (`_hook_entries_for`), not the
registry, per the repo's own gate: a hook that is registered is not a hook
that runs.
"""

from __future__ import annotations

from lazy_harness.agents.base import HookEntry
from lazy_harness.agents.claude_code import ClaudeCodeAdapter
from lazy_harness.agents.codex import CodexAdapter
from lazy_harness.core.config import Config, HookEventConfig, ProfileEntry

HOOK = "post-tool-use-sync-system-doc"


def _cfg(agent: str) -> Config:
    cfg = Config()
    cfg.agent.type = agent
    cfg.profiles.default = "p1"
    cfg.profiles.items = {"p1": ProfileEntry(config_dir=f"~/.agent-{agent}", agent=agent)}
    cfg.hooks = {"post_tool_use": HookEventConfig(scripts=[HOOK])}
    return cfg


def _entry(agent: str) -> HookEntry:
    from lazy_harness.deploy.engine import _hook_entries_for

    entries = _hook_entries_for(_cfg(agent), "p1", "lh")
    return entries["post_tool_use"][0]


def test_the_claude_code_matcher_still_covers_edit_and_write() -> None:
    """No hand-authored matcher, and the same string comes out the other end:
    Claude Code's own `post_tool_use` default already is `Edit|Write`."""
    entry = _entry("claude-code")

    generated = ClaudeCodeAdapter()._generate_hook_config({"post_tool_use": [entry]})

    assert generated["PostToolUse"][0]["matcher"] == "Edit|Write"


def test_the_codex_deploy_carries_no_matcher_and_so_fires_on_apply_patch() -> None:
    """The actual fix: not a matcher that names `apply_patch`, but no matcher at
    all -- the only form Codex's own hook dispatch fires on every tool call
    under, `apply_patch` included."""
    entry = _entry("codex")

    groups = CodexAdapter()._hook_groups({"post_tool_use": [entry]})

    assert "matcher" not in groups["PostToolUse"][0]

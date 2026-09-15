"""Deploying a pre-runner builtin to an agent that is not Claude Code warns.

An unmigrated builtin's `main()` reads stdin in Claude Code's shape, writes both
channels itself and owns its exit code. Routed to another agent it is a guess
wearing a deployed hook's clothes, and a default `lh deploy` to a Codex profile
currently ships four of them without a word.

A warning, never a refusal: the remaining builtins migrate at step 5 of
`specs/designs/2026-09-13-multi-agent-harness-design.md`, and blocking now would
leave a Codex profile with almost no hooks at all.
"""

from __future__ import annotations

import pytest

from lazy_harness.core.config import Config, HookEventConfig, ProfileEntry


def _cfg(agent: str) -> Config:
    cfg = Config()
    cfg.agent.type = agent
    cfg.profiles.default = "p1"
    cfg.profiles.items = {"p1": ProfileEntry(config_dir="~/.agent-p1", agent=agent)}
    cfg.hooks = {"session_end": HookEventConfig(scripts=["session-end"])}
    return cfg


def test_unmigrated_builtin_on_a_non_claude_code_agent_is_named(
    capsys: pytest.CaptureFixture[str],
) -> None:
    from lazy_harness.deploy.engine import _hook_entries_for

    _hook_entries_for(_cfg("codex"), "p1", "lh")

    assert (
        "session-end in 'p1': not migrated to the runner, so it reads "
        "Claude Code-shaped stdin and owns its own exit code on agent 'codex'"
        in capsys.readouterr().out
    )


def test_the_warning_does_not_stop_the_hook_being_deployed() -> None:
    """A warning, not a gate. Step 5 migrates these; until then they still ship."""
    from lazy_harness.deploy.engine import _hook_entries_for

    entries = _hook_entries_for(_cfg("codex"), "p1", "lh")

    assert "lh hook session-end --profile p1" in [e.command for e in entries["session_end"]]


def test_the_same_hook_on_claude_code_is_not_warned_about(
    capsys: pytest.CaptureFixture[str],
) -> None:
    from lazy_harness.deploy.engine import _hook_entries_for

    _hook_entries_for(_cfg("claude-code"), "p1", "lh")

    assert "not migrated to the runner" not in capsys.readouterr().out


def test_a_migrated_builtin_is_not_warned_about_on_a_foreign_agent(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The warning tracks `BuiltinHookSpec.migrated`, not the agent alone."""
    from lazy_harness.deploy.engine import _hook_entries_for

    cfg = _cfg("codex")
    cfg.hooks = {"session_start": HookEventConfig(scripts=["context-inject"])}

    _hook_entries_for(cfg, "p1", "lh")

    assert "context-inject in 'p1': not migrated" not in capsys.readouterr().out

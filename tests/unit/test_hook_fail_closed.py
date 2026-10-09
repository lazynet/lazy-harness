"""A blocking builtin is deployed to Claude Code with `onFailure: "block"`.

`BuiltinHookSpec.blocking` makes the runner exit 2 when a guard cannot run, but
only once `lh` is running. The failures before that — the launcher missing from
PATH, an interpreter that dies on import, Claude Code's own timeout — exit with
some other code, and Claude Code treats any code but 2 as "no objection". Since
2.1.295 a handler's `onFailure: "block"` turns those into a refusal too; the
probe recorded in `specs/designs/claude-code-evidence.md` shows exit 1, a
missing binary and a timeout each blocking a Bash call, and exit 0 passing.
"""

from __future__ import annotations

import json
from pathlib import Path

from lazy_harness.agents.base import HookEntry
from lazy_harness.agents.claude_code import ClaudeCodeAdapter
from lazy_harness.core.config import Config, HookEventConfig, ProfileEntry
from lazy_harness.hooks.loader import builtin_name_from_command, resolve_builtin_spec

SETTINGS = Path("settings.json")
SECURITY = "lh hook pre-tool-use-security --profile p1"
READ_SIZE = "lh hook pre-tool-use-read-size --profile p1"


def _settings_hooks(ops: list) -> dict:
    (op,) = [op for op in ops if op.relative_path == SETTINGS]
    return json.loads(op.artifact.content)["hooks"]


def _plan(hooks: dict[str, list[HookEntry]], existing: dict[Path, str] | None = None) -> list:
    return ClaudeCodeAdapter().plan_config(hooks, {}, existing or {}, binary="lh")


def _cfg(*scripts: str) -> Config:
    cfg = Config()
    cfg.agent.type = "claude-code"
    cfg.profiles.default = "p1"
    cfg.profiles.items = {"p1": ProfileEntry(config_dir="~/.agent-p1", agent="claude-code")}
    cfg.hooks = {"pre_tool_use": HookEventConfig(scripts=list(scripts))}
    return cfg


def test_a_blocking_entry_is_written_with_onfailure_block() -> None:
    hooks = _settings_hooks(
        _plan({"pre_tool_use": [HookEntry(command=SECURITY, matcher="Bash", blocking=True)]})
    )

    (group,) = hooks["PreToolUse"]
    assert group["hooks"] == [{"type": "command", "command": SECURITY, "onFailure": "block"}]


def test_an_informational_entry_carries_no_failure_policy() -> None:
    hooks = _settings_hooks(_plan({"pre_tool_use": [HookEntry(command=READ_SIZE, matcher="Read")]}))

    (group,) = hooks["PreToolUse"]
    assert group["hooks"] == [{"type": "command", "command": READ_SIZE}]


def test_deploy_marks_exactly_the_builtins_whose_spec_is_blocking() -> None:
    from lazy_harness.deploy.engine import _hook_entries_for

    names = ["pre-tool-use-security", "pre-tool-use-git-scope", "pre-tool-use-read-size"]
    entries = _hook_entries_for(_cfg(*names), "p1", "lh")["pre_tool_use"]

    marked = {}
    for entry in entries:
        name = builtin_name_from_command(entry.command, binaries={"lh"})
        assert name is not None
        spec = resolve_builtin_spec(name)
        assert spec is not None
        assert entry.blocking is spec.blocking, name
        marked[name] = entry.blocking
    assert marked == {
        "pre-tool-use-security": True,
        "pre-tool-use-git-scope": True,
        "pre-tool-use-read-size": False,
    }


def test_redeploying_a_blocking_entry_keeps_one_group() -> None:
    hooks = {"pre_tool_use": [HookEntry(command=SECURITY, matcher="Bash", blocking=True)]}
    first = _plan(hooks)
    existing = {op.relative_path: op.artifact.content for op in first}

    second = _plan(hooks, existing)

    assert _settings_hooks(second) == _settings_hooks(first)
    assert len(_settings_hooks(second)["PreToolUse"]) == 1


def test_a_deploy_from_before_the_policy_is_upgraded_in_place() -> None:
    """The previous deploy wrote the handler without `onFailure`; its ledger
    still claims it, so the redeploy replaces it rather than appending."""
    old = _plan({"pre_tool_use": [HookEntry(command=SECURITY, matcher="Bash")]})
    existing = {op.relative_path: op.artifact.content for op in old}

    upgraded = _plan(
        {"pre_tool_use": [HookEntry(command=SECURITY, matcher="Bash", blocking=True)]}, existing
    )

    (group,) = _settings_hooks(upgraded)["PreToolUse"]
    assert group["hooks"][0]["onFailure"] == "block"


def test_without_a_ledger_a_fail_closed_builtin_is_still_recognised_as_ours() -> None:
    """Ledger-less adoption matches the exact shape the generator emits, which
    now includes `onFailure` on a blocking builtin."""
    group = {
        "matcher": "Bash|Read|Edit|Write|NotebookEdit",
        "hooks": [{"type": "command", "command": SECURITY, "onFailure": "block"}],
    }
    existing = {SETTINGS: json.dumps({"hooks": {"PreToolUse": [group]}})}

    assert _settings_hooks(_plan({}, existing)) == {}


def test_without_a_ledger_onfailure_on_an_informational_builtin_is_foreign() -> None:
    """The generator never writes `onFailure` on a non-blocking hook, so a group
    carrying one was edited by someone else and is left alone."""
    group = {
        "matcher": "Read",
        "hooks": [{"type": "command", "command": READ_SIZE, "onFailure": "block"}],
    }
    existing = {SETTINGS: json.dumps({"hooks": {"PreToolUse": [group]}})}
    # An empty plan writes nothing at all, so give the deploy one hook of its own.
    ours = {"session_start": [HookEntry(command="lh hook context-inject --profile p1")]}

    assert _settings_hooks(_plan(ours, existing))["PreToolUse"] == [group]

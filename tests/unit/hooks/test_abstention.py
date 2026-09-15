"""Abstention is not approval, asserted on the bytes rather than on a field.

`specs/designs/2026-09-13-multi-agent-harness-design.md` makes this a gate of
its own, separately from the byte goldens, because the regression it guards
against is invisible in an exit code:

> Claude Code's docs are explicit that these are different states: "Exit code 0
> with no output means the hook has no decision to report, so the tool call
> continues through the normal permission flow. The hook can deny the call, but
> staying silent doesn't approve it."

A hook that abstains and a hook that approves both exit 0. What separates them
is whether a `permissionDecision` reaches stdout, so that is what these tests
stand on -- not the exit code, and not an empty stdout, either of which would
still pass if the adapter started emitting `"permissionDecision": "allow"`
alongside something else. Migrating the abstain branch onto `Verdict.ALLOW`
would turn every command the security guard merely fails to recognise into an
explicit, prompt-skipping approval, which is the single most dangerous
regression this design can ship.

The goldens cover these same branches, and cover more of them -- but they cover
them as whole-output equality, which is a different assertion: re-capture the
golden and it agrees with whatever the hook now does. This one names the thing
that must never appear.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from lazy_harness.agents.claude_code import ClaudeCodeAdapter
from lazy_harness.hooks.loader import _BUILTIN_HOOKS
from lazy_harness.hooks.runner import run_hook

#: The no-objection payload for each migrated hook whose event honours a
#: verdict. `pre_tool_use` honours `DENY` and `session_stop` honours `BLOCK`;
#: a hook on an event that honours neither has no abstention to get wrong.
_NO_OBJECTION: dict[str, dict[str, object]] = {
    "pre-tool-use-security": {
        "hook_event_name": "PreToolUse",
        "session_id": "s1",
        "tool_name": "Bash",
        "tool_input": {"command": "ls -la"},
    },
    "session-export": {
        "hook_event_name": "Stop",
        "session_id": "s1",
        "cwd": "/tmp",
    },
    "stop-verify-guard": {
        "hook_event_name": "Stop",
        "session_id": "s1",
        "cwd": "/tmp",
    },
}


def _hooks_with_a_verdict() -> list[str]:
    """Migrated hooks wired to an event this agent honours a verdict on."""
    events = ClaudeCodeAdapter().hook_events()
    return sorted(
        name
        for name, spec in _BUILTIN_HOOKS.items()
        if spec.migrated
        and spec.event is not None
        and (support := events.get(spec.event)) is not None
        and support.can_block
    )


def test_every_hook_that_can_refuse_has_a_no_objection_payload() -> None:
    """The table above is derived from the registry, not maintained beside it.

    A hook that gains a blocking event and no entry here would otherwise be
    silently exempt from the gate that matters most to it.
    """
    assert _hooks_with_a_verdict() == sorted(_NO_OBJECTION)


@pytest.mark.parametrize("hook", sorted(_NO_OBJECTION))
def test_the_no_objection_branch_emits_no_permission_decision(
    hook: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("LH_CONFIG_DIR", str(tmp_path))
    monkeypatch.setenv("LH_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "agent"))

    output = run_hook(hook, profile="", stdin_text=json.dumps(_NO_OBJECTION[hook]))

    emitted = output.stdout or ""
    assert "permissionDecision" not in emitted, (
        f"{hook} reported a permission decision on a branch where it has none; "
        f"staying silent does not approve, and saying 'allow' does"
    )
    assert "allow" not in emitted


@pytest.mark.parametrize("hook", sorted(_NO_OBJECTION))
def test_the_no_objection_branch_reports_no_decision_at_all(
    hook: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`decision` is the stop-class spelling of the same mistake.

    `stop_verify_guard` refuses through `{"decision": "block"}` rather than
    through a `permissionDecision`, so a gate that watched only the latter
    would leave half the abstentions uncovered.
    """
    monkeypatch.setenv("LH_CONFIG_DIR", str(tmp_path))
    monkeypatch.setenv("LH_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "agent"))

    output = run_hook(hook, profile="", stdin_text=json.dumps(_NO_OBJECTION[hook]))

    body = json.loads(output.stdout) if output.stdout else {}
    assert "decision" not in body
    nested = body.get("hookSpecificOutput", {})
    assert isinstance(nested, dict)
    assert "permissionDecision" not in nested

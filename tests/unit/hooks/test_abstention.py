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
from lazy_harness.hooks.loader import _BUILTIN_HOOKS, BuiltinHookSpec
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
    # The silent branch, reached by naming a file that is not there: the
    # emitting branch needs a file past `MAX_LINES` on disk, which a literal
    # payload cannot create. That branch carries a `systemMessage` and no
    # verdict, and `test_pre_tool_use_read_size_goldens.py::
    # test_the_warning_carries_no_permission_decision` is where its bytes are
    # asserted. The risk this entry covers is the other direction: a warning
    # hook on the one event Claude Code honours `DENY` on, whose silence must
    # not start carrying a permission decision.
    "pre-tool-use-read-size": {
        "hook_event_name": "PreToolUse",
        "session_id": "s1",
        "tool_name": "Read",
        "tool_input": {"file_path": "/nonexistent/lazy-harness/abstention-probe.md"},
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
    # `compound-loop` has no verdict to form at all -- it queues a task and
    # returns -- which is precisely why it belongs here: a hook on a blockable
    # event that never refuses is the one whose silence is easiest to turn into
    # an accidental `block` by returning something other than `HookDecision()`.
    "compound-loop": {
        "hook_event_name": "Stop",
        "session_id": "s1",
        "cwd": "/tmp",
    },
    "engram-persist": {
        "hook_event_name": "Stop",
        "session_id": "s1",
        "cwd": "/tmp",
    },
    # No `transcript_path`, so the notice branch is never reached and this is
    # the hook's silent path -- which is the one that matters here: the branch
    # that *does* emit carries a `systemMessage`, a channel Claude Code shows
    # without it being a verdict, and the risk is that the silent branch starts
    # carrying one too.
    "stop-context-rotate": {
        "hook_event_name": "Stop",
        "session_id": "s1",
        "cwd": "/tmp",
    },
    # A write that stays under both ceilings: this hook's silent path. The
    # branch that *does* speak carries a `systemMessage`, a channel Claude Code
    # shows without it being a verdict, and
    # `test_pre_tool_use_memory_size.py::test_a_warning_is_never_a_verdict`
    # holds that one. The risk here is the reverse: a warning hook wired to an
    # event that honours `DENY` turning its quiet branch into an approval.
    "pre-tool-use-memory-size": {
        "hook_event_name": "PreToolUse",
        "session_id": "s1",
        "tool_name": "Write",
        "tool_input": {
            "file_path": "/home/user/.claude/projects/foo/memory/MEMORY.md",
            "content": "line\n" * 50,
        },
    },
    # Reached through the *placement*, not through `spec.event`, which this hook
    # leaves unset because it branches on four. It is deployed to `Stop` all the
    # same, so the gate has to see it -- see the derivation below.
    "herdr-context-gauge": {
        "hook_event_name": "Stop",
        "session_id": "s1",
        "cwd": "/tmp",
    },
    # The other blocking hook, and the one whose abstention is cheapest to get
    # wrong: it refuses through `Verdict.DENY`, so a migration that returned a
    # verdict on the recognised-as-safe path would deny a command the guard had
    # just cleared.
    "pre-tool-use-git-scope": {
        "hook_event_name": "PreToolUse",
        "session_id": "s1",
        "tool_name": "Bash",
        "tool_input": {"command": "git st" + "ash list"},
    },
}


def _blockable_placements(name: str, spec: BuiltinHookSpec) -> bool:
    """Whether this hook lands on any event Claude Code honours a verdict on.

    `spec.event` answers for a hook that declares one, and **only** for that
    hook. A spec leaving it unset is not a spec that runs nowhere — it is one
    that branches on four events and refuses to name a fallback. Filtering on
    `spec.event is not None`, as this derivation used to, therefore exempted
    exactly the hooks whose placement the registry cannot state, which is the
    opposite of the narrowing it looked like.

    For those, the placement is the operator's and lives in the shipped default
    lists. `herdr-context-gauge` is deliberately absent from them too
    (`plugins/builtins.py:60-64`), so the conservative reading is the right one:
    an event-less migrated spec is assumed to reach a blockable event until it
    says otherwise.
    """
    events = ClaudeCodeAdapter().hook_events()
    if spec.event is None:
        return True
    support = events.get(spec.event)
    return support is not None and support.can_block


def _hooks_with_a_verdict() -> list[str]:
    """Migrated hooks wired to an event this agent honours a verdict on."""
    return sorted(
        name
        for name, spec in _BUILTIN_HOOKS.items()
        if spec.migrated and _blockable_placements(name, spec)
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

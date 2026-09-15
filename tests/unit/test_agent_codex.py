"""The throwaway `CodexAdapter` — step 4's contract gate.

Every payload, envelope and config shape asserted here was *observed* against
`codex-cli 0.154.0` with `CODEX_HOME` pointed at a disposable directory. Where
the binary was not exercised the test says so rather than asserting a guess:
this adapter exists to find out what the contract cannot express, and a test
that encodes an assumption as a fact defeats that.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from lazy_harness.agents.base import (
    ConfigPlanner,
    HookDecision,
    HookEntry,
    Operation,
    Verdict,
)

HOOKS_JSON = Path("hooks.json")


def _adapter():
    from lazy_harness.agents.codex import CodexAdapter

    return CodexAdapter()


# --- event names: the silent-drop hazard ---------------------------------


def test_every_emitted_native_name_is_one_codex_accepts() -> None:
    """The load-bearing test of this adapter.

    An event name Codex does not recognise is dropped with **no diagnostic at
    all** — no warning, nothing fires — so a mis-cased name is indistinguishable
    at the console from a hook that is merely untrusted. The mapping is therefore
    checked against the accepted set rather than eyeballed.
    """
    from lazy_harness.agents.codex import CODEX_EVENT_NAMES

    emitted = {support.native_name for support in _adapter().hook_events().values()}
    assert emitted <= CODEX_EVENT_NAMES, sorted(emitted - CODEX_EVENT_NAMES)


def test_supported_hooks_is_derived_from_the_event_map() -> None:
    """One mapping, not two. A second literal is how the casing desynchronises."""
    adapter = _adapter()
    assert set(adapter.supported_hooks()) == set(adapter.hook_events())


def test_codex_event_names_are_the_twelve_the_binary_names() -> None:
    from lazy_harness.agents.codex import CODEX_EVENT_NAMES

    assert CODEX_EVENT_NAMES == frozenset(
        {
            "PreToolUse",
            "PermissionRequest",
            "PostToolUse",
            "PreCompact",
            "PostCompact",
            "SessionStart",
            "SessionEnd",
            "UserPromptSubmit",
            "SubagentStart",
            "SubagentStop",
            "Stop",
            "Interrupt",
        }
    )


def test_notification_is_absent_rather_than_declared_verdictless() -> None:
    """Codex names no `Notification` event, and an absent key is the contract's
    way of saying "not delivered at all" — a different statement from delivered
    and ignoring the verdict."""
    assert "notification" not in _adapter().hook_events()


def test_session_start_and_pre_tool_use_carry_their_observed_casing() -> None:
    events = _adapter().hook_events()
    assert events["session_start"].native_name == "SessionStart"
    assert events["pre_tool_use"].native_name == "PreToolUse"


# --- verdicts: deny only -------------------------------------------------


def test_deny_is_the_only_verdict_declared_anywhere() -> None:
    """`allow` without `updatedInput` and `ask` are both rejected by Codex as an
    unsupported `permissionDecision` — and it then **fails open**, running the
    tool. Declaring either would let deploy install a guard that approves."""
    declared = {v for support in _adapter().hook_events().values() for v in support.verdicts}
    assert declared == {Verdict.DENY}


def test_only_pre_tool_use_can_block() -> None:
    events = _adapter().hook_events()
    assert events["pre_tool_use"].verdicts == frozenset({Verdict.DENY})
    assert [name for name, s in events.items() if s.can_block] == ["pre_tool_use"]


@pytest.mark.parametrize("verdict", [Verdict.ALLOW, Verdict.ASK, Verdict.BLOCK])
def test_an_unhonoured_verdict_raises_rather_than_emitting_nothing(verdict: Verdict) -> None:
    """Emitting nothing on a blocking hook reads as approval."""
    adapter = _adapter()
    event = adapter.parse_hook_input("pre_tool_use", _PRE_TOOL_USE, profile="probe")
    with pytest.raises(ValueError, match="pre_tool_use"):
        adapter.format_hook_output(event, HookDecision(verdict=verdict, reason="no"))


def test_deny_on_an_event_that_does_not_honour_it_raises() -> None:
    adapter = _adapter()
    event = adapter.parse_hook_input("session_start", _SESSION_START, profile="probe")
    with pytest.raises(ValueError, match="session_start"):
        adapter.format_hook_output(event, HookDecision(verdict=Verdict.DENY, reason="no"))


# --- payloads: observed verbatim -----------------------------------------

_SESSION_START: dict = {
    "session_id": "01a0a300-3482-78d2-8b75-4d10359406b8",
    "transcript_path": (
        "/private/tmp/codex-step4-probe/sessions/2026/09/14/"
        "rollout-2026-09-14T23-58-14-01a0a300-3482-78d2-8b75-4d10359406b8.jsonl"
    ),
    "cwd": "/private/tmp/codex-step4-wd",
    "hook_event_name": "SessionStart",
    "model": "gpt-oss:20b",
    "permission_mode": "bypassPermissions",
    "source": "startup",
}

_PRE_TOOL_USE: dict = {
    "session_id": "01a0a301-0d88-7c91-9483-5276101d5acb",
    "turn_id": "01a0a301-0db8-70a2-89b7-7d55840aeba3",
    "transcript_path": (
        "/private/tmp/codex-step4-probe/sessions/2026/09/14/"
        "rollout-2026-09-14T23-59-10-01a0a301-0d88-7c91-9483-5276101d5acb.jsonl"
    ),
    "cwd": "/private/tmp/codex-step4-wd",
    "hook_event_name": "PreToolUse",
    "model": "gpt-oss:20b",
    "permission_mode": "bypassPermissions",
    "tool_name": "Bash",
    "tool_input": {"command": "touch /private/tmp/codex-step4-wd/MARKER_ALLOW"},
    "tool_use_id": "call_f32q6f2s",
}


def test_session_start_payload_normalises() -> None:
    event = _adapter().parse_hook_input("session_start", _SESSION_START, profile="probe")
    assert event.event == "session_start"
    assert event.profile == "probe"
    assert event.session_id == "01a0a300-3482-78d2-8b75-4d10359406b8"
    assert event.cwd == Path("/private/tmp/codex-step4-wd")
    assert event.transcript_path is not None
    assert event.transcript_path.name.startswith("rollout-")
    assert event.source == "startup"
    assert event.permission_mode == "bypassPermissions"
    assert event.tool is None


def test_pre_tool_use_normalises_the_shell_call() -> None:
    """`tool_name` arrives as `Bash`, not `exec_command`: Codex normalises the
    native tool name to Claude's on the hook wire. A builtin matching on `Bash`
    works unmodified; one matching on Codex's own name would never fire."""
    event = _adapter().parse_hook_input("pre_tool_use", _PRE_TOOL_USE, profile="probe")
    assert event.tool is not None
    assert event.tool.native_name == "Bash"
    assert event.tool.operation is Operation.RUN_COMMAND
    assert event.tool.command == "touch /private/tmp/codex-step4-wd/MARKER_ALLOW"
    assert event.tool_use_id == "call_f32q6f2s"


def test_a_tool_codex_normalisation_was_never_observed_for_parses_without_an_operation() -> None:
    """Only the shell tool was exercised. Claiming `Edit` normalises the same way
    would be a guess a path guard would then under-enforce."""
    payload = dict(_PRE_TOOL_USE, tool_name="Edit", tool_input={"file_path": "/tmp/x"})
    event = _adapter().parse_hook_input("pre_tool_use", payload, profile="probe")
    assert event.tool is not None
    assert event.tool.native_name == "Edit"
    assert event.tool.operation is None


def test_a_malformed_session_id_arrives_absent_not_plausible() -> None:
    payload = dict(_SESSION_START, session_id=["not", "a", "string"], cwd=7)
    event = _adapter().parse_hook_input("session_start", payload, profile="probe")
    assert event.session_id == ""
    assert event.cwd == Path("")


# --- the deny envelope: nested, exit 0 -----------------------------------


def test_deny_emits_the_nested_envelope_on_stdout_with_exit_zero() -> None:
    """Verified against the binary by effect: with exactly this on stdout and
    exit 0, `touch MARKER_DENY` never created the file across four attempts, and
    Codex echoed the reason back as `Command blocked by PreToolUse hook: <reason>`.
    """
    adapter = _adapter()
    event = adapter.parse_hook_input("pre_tool_use", _PRE_TOOL_USE, profile="probe")
    out = adapter.format_hook_output(
        event, HookDecision(verdict=Verdict.DENY, reason="blocked by step4 probe")
    )
    assert out.exit_code == 0
    assert out.stderr == ""
    assert out.stdout is not None
    assert json.loads(out.stdout) == {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": "blocked by step4 probe",
        }
    }


def test_the_envelope_is_nested_and_never_flattened() -> None:
    """A top-level `{"permissionDecision": ...}` was never observed being honoured
    by Codex; only the wrapped form was."""
    adapter = _adapter()
    event = adapter.parse_hook_input("pre_tool_use", _PRE_TOOL_USE, profile="probe")
    out = adapter.format_hook_output(event, HookDecision(verdict=Verdict.DENY, reason="r"))
    assert out.stdout is not None
    assert "permissionDecision" not in json.loads(out.stdout)


def test_exit_two_is_never_used_to_refuse() -> None:
    """Claude Code refuses with stderr + exit 2. Codex's exit-2 channel was never
    exercised, so the adapter refuses the way it was observed refusing."""
    adapter = _adapter()
    event = adapter.parse_hook_input("pre_tool_use", _PRE_TOOL_USE, profile="probe")
    out = adapter.format_hook_output(event, HookDecision(verdict=Verdict.DENY, reason="r"))
    assert out.exit_code == 0


def test_abstaining_emits_no_stdout_at_all() -> None:
    adapter = _adapter()
    event = adapter.parse_hook_input("pre_tool_use", _PRE_TOOL_USE, profile="probe")
    out = adapter.format_hook_output(event, HookDecision())
    assert out == type(out)(stdout=None, stderr="", exit_code=0)


def test_additional_context_travels_in_the_same_nested_envelope() -> None:
    adapter = _adapter()
    event = adapter.parse_hook_input("session_start", _SESSION_START, profile="probe")
    out = adapter.format_hook_output(event, HookDecision(additional_context="ctx"))
    assert out.stdout is not None
    assert json.loads(out.stdout) == {
        "hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": "ctx"}
    }


# --- config: hooks.json, not config.toml ---------------------------------


def test_the_only_config_target_is_hooks_json() -> None:
    """Never `config.toml`: Codex writes `[hooks.state]` trust hashes and
    `[projects.*]` into it, so a harness that owns that file can clobber the
    user's trust decisions."""
    assert _adapter().config_targets() == [HOOKS_JSON]


def test_the_adapter_is_a_config_planner() -> None:
    assert isinstance(_adapter(), ConfigPlanner)


def _plan(hooks: dict[str, list[HookEntry]], existing: dict[Path, str] | None = None):
    return _adapter().plan_config(hooks, {}, existing or {}, binary="lh")


def test_plan_writes_the_observed_hooks_json_shape() -> None:
    """Top level accepts only `description` and `hooks`; anything else is a parse
    error that drops every hook in the file with a warning."""
    ops = _plan({"session_start": [HookEntry(command="lh hook context-inject --profile p")]})
    assert len(ops) == 1
    assert ops[0].relative_path == HOOKS_JSON
    assert ops[0].artifact is not None
    document = json.loads(ops[0].artifact.content)
    assert set(document) <= {"description", "hooks"}
    assert document["hooks"] == {
        "SessionStart": [
            {"hooks": [{"type": "command", "command": "lh hook context-inject --profile p"}]}
        ]
    }


def test_a_group_with_no_matcher_omits_the_key_rather_than_emitting_an_empty_one() -> None:
    """`matcher` is honoured: a literal that matches no tool suppresses the hook
    silently. An empty string was never observed, so the key is left out — the
    one form observed firing on every tool call.
    """
    ops = _plan({"session_start": [HookEntry(command="lh hook context-inject")]})
    assert ops[0].artifact is not None
    group = json.loads(ops[0].artifact.content)["hooks"]["SessionStart"][0]
    assert "matcher" not in group


def test_a_declared_matcher_is_emitted_verbatim() -> None:
    """The matcher is part of the hook's **trust identity** — changing it flipped
    the stored `trusted_hash`. Anchored so a redeploy cannot silently re-prompt.
    """
    ops = _plan({"pre_tool_use": [HookEntry(command="lh hook sec", matcher="Bash")]})
    assert ops[0].artifact is not None
    assert json.loads(ops[0].artifact.content)["hooks"]["PreToolUse"] == [
        {"matcher": "Bash", "hooks": [{"type": "command", "command": "lh hook sec"}]}
    ]


def test_each_entry_gets_its_own_matcher_group_in_declaration_order() -> None:
    """The trust key is `<file>:<event>:<group index>:<handler index>`, so the
    group a hook lands in is part of its identity across redeploys."""
    ops = _plan(
        {
            "pre_tool_use": [
                HookEntry(command="lh hook first", matcher="Bash"),
                HookEntry(command="lh hook second"),
            ]
        }
    )
    assert ops[0].artifact is not None
    groups = json.loads(ops[0].artifact.content)["hooks"]["PreToolUse"]
    assert [g["hooks"][0]["command"] for g in groups] == ["lh hook first", "lh hook second"]


def test_an_event_codex_does_not_deliver_is_dropped_from_the_plan() -> None:
    ops = _plan(
        {
            "notification": [HookEntry(command="lh hook notify")],
            "session_start": [HookEntry(command="lh hook ctx")],
        }
    )
    assert ops[0].artifact is not None
    assert list(json.loads(ops[0].artifact.content)["hooks"]) == ["SessionStart"]


def test_every_planned_event_key_is_one_codex_accepts() -> None:
    """The completeness check at the level that actually reaches disk."""
    from lazy_harness.agents.codex import CODEX_EVENT_NAMES

    adapter = _adapter()
    ops = adapter.plan_config(
        {event: [HookEntry(command=f"lh hook {event}")] for event in adapter.supported_hooks()},
        {},
        {},
    )
    assert ops[0].artifact is not None
    assert set(json.loads(ops[0].artifact.content)["hooks"]) <= CODEX_EVENT_NAMES


def test_no_hooks_plans_no_write_at_all() -> None:
    """Not a write of an empty `hooks` block, which would uninstall the user's
    own declarations on a profile that configures none of ours."""
    assert _plan({}) == []


def test_mcp_servers_are_out_of_scope_for_the_throwaway() -> None:
    assert _adapter().mcp_config_file() == ""
    assert _adapter().plan_config({}, {"qmd": {"command": "qmd"}}, {}) == []


def test_the_plan_replaces_an_existing_hooks_json_wholesale() -> None:
    """The harness owns this file entirely, which is precisely why it is not
    `config.toml` — nothing foreign is preserved because nothing foreign belongs."""
    theirs = [{"hooks": [{"type": "command", "command": "theirs"}]}]
    existing = json.dumps({"hooks": {"SessionStart": theirs}})
    ops = _plan({"session_start": [HookEntry(command="ours")]}, {HOOKS_JSON: existing})
    assert ops[0].artifact is not None
    assert "theirs" not in ops[0].artifact.content
    assert ops[0].preserved == []


def test_the_document_is_stable_across_redeploys_of_the_same_input() -> None:
    """A byte that churns per release re-writes the declaring file, and the trust
    key is scoped to that file. Nothing version-dependent goes in."""
    from lazy_harness import __version__

    ops = _plan({"session_start": [HookEntry(command="lh hook ctx")]})
    assert ops[0].artifact is not None
    assert __version__ not in ops[0].artifact.content


# --- registration --------------------------------------------------------


def test_codex_resolves_for_a_profile_that_declares_it() -> None:
    from lazy_harness.agents.registry import agent_for_profile
    from lazy_harness.core.config import (
        AgentConfig,
        Config,
        HarnessConfig,
        ProfileEntry,
        ProfilesConfig,
    )

    cfg = Config(
        harness=HarnessConfig(version="1"),
        agent=AgentConfig(type="claude-code"),
        profiles=ProfilesConfig(
            default="personal",
            items={
                "personal": ProfileEntry(config_dir="~/.claude-personal"),
                "probe": ProfileEntry(config_dir="~/.codex-probe", agent="codex"),
            },
        ),
    )
    assert agent_for_profile(cfg, "probe").name == "codex"
    assert agent_for_profile(cfg, "personal").name == "claude-code"

"""`CodexAdapter` — the full surface, not step 4's throwaway.

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
CONFIG_TOML = Path("config.toml")
DESCRIPTION = "Managed by lazy-harness. Edits are overwritten on the next deploy."


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


def test_config_targets_names_hooks_json_and_config_toml() -> None:
    """Two files, for two reasons that do not generalise to each other.

    Hook *declarations* stay out of `config.toml` — Codex persists
    `[hooks.state]` trust hashes next to `[projects.*]` in it, and the trust key
    is scoped to the declaring file's absolute path, so moving a declaration
    between the two re-prompts for every hook in the file. MCP servers have no
    such home: `[mcp_servers.<id>]` in `config.toml` is the only place Codex
    reads them, so the adapter merges into that file rather than owning it.
    """
    assert _adapter().config_targets() == [HOOKS_JSON, CONFIG_TOML]


def test_no_hook_declaration_ever_reaches_config_toml() -> None:
    """The half of the split that the widening must not erode."""
    ops = _adapter().plan_config(
        {"session_start": [HookEntry(command="lh hook ctx")]},
        {"qmd": {"command": "qmd"}},
        {},
        binary="lh",
    )
    toml_ops = [op for op in ops if op.relative_path == CONFIG_TOML]
    assert toml_ops and toml_ops[0].artifact is not None
    assert "hook" not in toml_ops[0].artifact.content


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


def test_mcp_config_file_stays_empty_because_the_document_is_not_json() -> None:
    """`mcp_config_file()` names a JSON document the engine could read as one.
    Codex's MCP block is a TOML section inside a file it shares with the user, so
    the adapter answers with no such file and plans `config.toml` instead."""
    assert _adapter().mcp_config_file() == ""


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


# --- config.toml: merged, never owned ------------------------------------
#
# `config.toml` is the file decision 4 calls jointly owned. Codex writes into
# it during a session — `[projects."<abs path>"].trust_level` as the user trusts
# a directory, `[hooks.state.<key>].trusted_hash` as they approve a hook — so
# every assertion below is made against `tomllib`, the parser Codex's own
# deserialiser is built on, reading the bytes the adapter produced. Asserting on
# the string the adapter built would be the test checking its own work.

# The shape observed in a real `~/.codex/config.toml`: top-level scalars first,
# then the tables Codex appends as the session goes on.
_LIVE_CONFIG = """\
model = "gpt-6-astra"
model_reasoning_effort = "high"

[projects."/Users/someone/repos/one"]
trust_level = "trusted"

[projects."/Users/someone/repos/two"]
trust_level = "trusted"

[hooks.state."/Users/someone/.codex/hooks.json:session_start:0:0"]
trusted_hash = "sha256:904128e4"

[tui.model_availability_nux]
gpt-6-astra = 4
"""


def _toml_op(ops: list, relative: Path = CONFIG_TOML):
    matched = [op for op in ops if op.relative_path == relative]
    assert matched, f"no op for {relative}"
    return matched[0]


def _parsed(ops: list, relative: Path = CONFIG_TOML) -> dict:
    """The op's bytes, through the parser Codex itself uses."""
    import tomllib

    op = _toml_op(ops, relative)
    assert op.artifact is not None
    return tomllib.loads(op.artifact.content)


def test_detected_servers_land_under_mcp_servers() -> None:
    ops = _adapter().plan_config({}, {"qmd": {"command": "qmd", "args": ["mcp"]}}, {}, binary="lh")
    parsed = _parsed(ops)
    assert parsed["mcp_servers"]["qmd"] == {"command": "qmd", "args": ["mcp"]}


def test_an_env_table_survives_the_toml_round_trip() -> None:
    """A nested dict is the one MCP field TOML could mangle into a sibling table."""
    ops = _adapter().plan_config(
        {},
        {"engram": {"command": "engram", "args": ["mcp"], "env": {"ENGRAM_DB": "/tmp/e.db"}}},
        {},
        binary="lh",
    )
    assert _parsed(ops)["mcp_servers"]["engram"]["env"] == {"ENGRAM_DB": "/tmp/e.db"}


def test_project_trust_survives_a_deploy() -> None:
    ops = _adapter().plan_config(
        {}, {"qmd": {"command": "qmd"}}, {CONFIG_TOML: _LIVE_CONFIG}, binary="lh"
    )
    parsed = _parsed(ops)
    assert parsed["projects"]["/Users/someone/repos/one"]["trust_level"] == "trusted"
    assert parsed["projects"]["/Users/someone/repos/two"]["trust_level"] == "trusted"


def test_project_trust_survives_a_redeploy_of_what_the_first_deploy_wrote() -> None:
    """The round trip, not the write: save, load, save, load.

    A merge can be correct once and lossy the second time — the first pass reads
    a hand-written file and the second reads its own output, which is where a
    reserialisation that quietly restructures `[projects.*]` shows up.
    """
    adapter = _adapter()
    first = _toml_op(
        adapter.plan_config(
            {}, {"qmd": {"command": "qmd"}}, {CONFIG_TOML: _LIVE_CONFIG}, binary="lh"
        )
    )
    assert first.artifact is not None
    second = _parsed(
        adapter.plan_config(
            {},
            {"qmd": {"command": "qmd"}, "engram": {"command": "engram"}},
            {CONFIG_TOML: first.artifact.content},
            binary="lh",
        )
    )
    assert second["projects"]["/Users/someone/repos/one"]["trust_level"] == "trusted"
    assert second["projects"]["/Users/someone/repos/two"]["trust_level"] == "trusted"
    assert set(second["mcp_servers"]) == {"qmd", "engram"}


def test_hook_trust_state_survives_a_deploy() -> None:
    """`[hooks.state]` is how Codex remembers the user approved a hook. A deploy
    that dropped it would silently un-trust every hook it just deployed."""
    ops = _adapter().plan_config(
        {}, {"qmd": {"command": "qmd"}}, {CONFIG_TOML: _LIVE_CONFIG}, binary="lh"
    )
    state = _parsed(ops)["hooks"]["state"]
    key = "/Users/someone/.codex/hooks.json:session_start:0:0"
    assert state[key]["trusted_hash"] == "sha256:904128e4"


def test_unmodelled_sections_and_scalars_survive() -> None:
    """Everything the harness does not model is carried, not just the two
    sections it was taught to name."""
    parsed = _parsed(
        _adapter().plan_config(
            {}, {"qmd": {"command": "qmd"}}, {CONFIG_TOML: _LIVE_CONFIG}, binary="lh"
        )
    )
    assert parsed["model"] == "gpt-6-astra"
    assert parsed["model_reasoning_effort"] == "high"
    assert parsed["tui"]["model_availability_nux"] == {"gpt-6-astra": 4}


def test_a_server_the_user_declared_themselves_is_kept_and_named() -> None:
    existing = '[mcp_servers.mine]\ncommand = "mine"\n'
    ops = _adapter().plan_config(
        {}, {"qmd": {"command": "qmd"}}, {CONFIG_TOML: existing}, binary="lh"
    )
    parsed = _parsed(ops)
    assert parsed["mcp_servers"]["mine"] == {"command": "mine"}
    assert "mcp_servers: mine" in _toml_op(ops).preserved


def test_the_preserved_report_names_each_trusted_project() -> None:
    """The deploy report is where the user sees their decisions came through."""
    ops = _adapter().plan_config(
        {}, {"qmd": {"command": "qmd"}}, {CONFIG_TOML: _LIVE_CONFIG}, binary="lh"
    )
    preserved = _toml_op(ops).preserved
    assert "projects: /Users/someone/repos/one" in preserved
    assert "projects: /Users/someone/repos/two" in preserved


def test_no_servers_plans_no_config_toml_write() -> None:
    """Blanking an input must not reserialise a file the harness does not own.

    `lh deploy-hooks` runs the cycle with `servers` empty; a write here would
    rewrite every trust decision in the file for no reason at all.
    """
    ops = _adapter().plan_config(
        {"session_start": [HookEntry(command="lh hook ctx")]},
        {},
        {CONFIG_TOML: _LIVE_CONFIG},
        binary="lh",
    )
    assert [op.relative_path for op in ops] == [HOOKS_JSON]


def test_a_config_toml_that_does_not_parse_is_refused_rather_than_replaced() -> None:
    """Overwriting an unparseable `config.toml` would destroy trust state the
    user cannot get back. Losing the MCP block is recoverable; that is not."""
    from lazy_harness.agents.codex import CodexConfigUnreadableError

    with pytest.raises(CodexConfigUnreadableError):
        _adapter().plan_config(
            {}, {"qmd": {"command": "qmd"}}, {CONFIG_TOML: "model = \n[broken"}, binary="lh"
        )


# --- retiring hooks.json, in both directions ------------------------------


def test_a_harness_written_hooks_json_is_retired_when_no_hooks_remain() -> None:
    """The delete case. Without it, a profile that stops configuring hooks keeps
    firing the ones the previous release deployed."""
    ours = json.dumps({"description": DESCRIPTION, "hooks": {"SessionStart": []}})
    ops = _adapter().plan_config({}, {}, {HOOKS_JSON: ours}, binary="lh")
    assert [(op.relative_path, op.artifact) for op in ops] == [(HOOKS_JSON, None)]


def test_a_hooks_json_the_user_wrote_is_left_alone() -> None:
    """The other direction, and the reason the delete keys on the description
    rather than on the file existing: `hooks.json` is where a user declares their
    own hooks too, and a harness that deletes it on an empty plan eats them."""
    theirs = json.dumps({"hooks": {"SessionStart": [{"hooks": [{"command": "theirs"}]}]}})
    assert _adapter().plan_config({}, {}, {HOOKS_JSON: theirs}, binary="lh") == []


def test_an_absent_hooks_json_plans_no_delete() -> None:
    """Retiring a file that was never there would make every empty deploy print
    a removal that removed nothing."""
    assert _adapter().plan_config({}, {}, {}, binary="lh") == []


def test_one_plan_retires_hooks_json_while_writing_config_toml() -> None:
    """Both directions in a single plan: the file that must go and the file that
    must be merged, so neither is asserted in isolation from the other."""
    ours = json.dumps({"description": DESCRIPTION, "hooks": {}})
    ops = _adapter().plan_config(
        {},
        {"qmd": {"command": "qmd"}},
        {HOOKS_JSON: ours, CONFIG_TOML: _LIVE_CONFIG},
        binary="lh",
    )
    by_path = {op.relative_path: op for op in ops}
    assert by_path[HOOKS_JSON].artifact is None
    assert by_path[CONFIG_TOML].artifact is not None
    assert _parsed(ops)["projects"]["/Users/someone/repos/one"]["trust_level"] == "trusted"


# --- apply_patch: the native edit path, probe 4c --------------------------
#
# Every blob below is Codex's own, copied from
# `specs/designs/codex-evidence.md` §1 (:335) — a single-file `*** Update
# File:` section under `tool_input.command`, the *same* key `Bash` uses. The
# multi-file, `*** Add File:` and `*** Delete File:` shapes are the format's,
# never observed from the binary (evidence §2, "untested for `apply_patch`"),
# and the tests over them say so where they assert.

_APPLY_PATCH_BLOB = (
    "*** Begin Patch\n"
    "*** Update File: /private/tmp/codex-step4-wd/target.txt\n"
    "@@\n"
    "-untouched\n"
    "+touched\n"
    "*** End Patch"
)

_APPLY_PATCH: dict = {
    "session_id": "01a0a301-0d88-7c91-9483-5276101d5acb",
    "transcript_path": (
        "/private/tmp/codex-step4-probe/sessions/2026/09/14/"
        "rollout-2026-09-14T23-59-10-01a0a301-0d88-7c91-9483-5276101d5acb.jsonl"
    ),
    "cwd": "/private/tmp/codex-step4-wd",
    "hook_event_name": "PreToolUse",
    "tool_name": "apply_patch",
    "tool_input": {"command": _APPLY_PATCH_BLOB},
    "tool_use_id": "call_apply_patch",
}


def _tool_for(blob: object):
    payload = dict(_APPLY_PATCH, tool_input={"command": blob})
    return _adapter().parse_hook_input("pre_tool_use", payload, profile="probe").tool


def test_apply_patch_is_an_edit_rather_than_an_unmapped_tool() -> None:
    """Probe 4c: `PreToolUse` fires with `tool_name: "apply_patch"` literally.

    Before this mapping the native edit path parsed with `operation=None`, which
    reads as "no builtin guards this" rather than "this modifies a file"."""
    tool = _adapter().parse_hook_input("pre_tool_use", _APPLY_PATCH, profile="probe").tool
    assert tool is not None
    assert tool.native_name == "apply_patch"
    assert tool.operation is Operation.MODIFY_FILE


def test_the_patch_blob_becomes_a_file_edit_carrying_the_embedded_path() -> None:
    """The path is inside the blob text, not in a structured field — which is
    why mapping the operation alone revives none of the five builtins."""
    tool = _tool_for(_APPLY_PATCH_BLOB)
    assert tool is not None
    assert [str(e.path) for e in tool.edits] == ["/private/tmp/codex-step4-wd/target.txt"]
    assert tool.edits[0].is_create is False
    assert tool.edits[0].replacements == (("untouched", "touched"),)


def test_apply_patch_leaves_command_unset() -> None:
    """A patch blob is not a shell command, and two builtins read `command` as
    one: `pre_tool_use_security.py:362` and `pre_tool_use_git_scope.py:402` both
    scan it for shell syntax. Feeding them patch text would match on the
    *content* of an edit. The blob stays reachable through `raw_input`."""
    tool = _tool_for(_APPLY_PATCH_BLOB)
    assert tool is not None
    assert tool.command is None
    assert tool.raw_input == {"command": _APPLY_PATCH_BLOB}


def test_bash_still_carries_its_command() -> None:
    """The regression the line above could cause: `command` is keyed on the tool,
    not on the key being absent."""
    tool = _adapter().parse_hook_input("pre_tool_use", _PRE_TOOL_USE, profile="probe").tool
    assert tool is not None
    assert tool.command == "touch /private/tmp/codex-step4-wd/MARKER_ALLOW"


def test_a_two_file_blob_yields_one_edit_per_section() -> None:
    """Plural because the format is plural. Unprobed: no run forced a multi-file
    `apply_patch` (evidence §2), so this asserts the parser is generic over
    sections rather than that Codex emits them."""
    blob = (
        "*** Begin Patch\n"
        "*** Update File: /w/a.txt\n"
        "@@\n"
        "-alpha\n"
        "+ALPHA\n"
        "*** Update File: /w/b.txt\n"
        "@@\n"
        "-beta\n"
        "+BETA\n"
        "*** End Patch"
    )
    tool = _tool_for(blob)
    assert tool is not None
    assert [str(e.path) for e in tool.edits] == ["/w/a.txt", "/w/b.txt"]
    assert tool.edits[1].replacements == (("beta", "BETA"),)


def test_context_and_several_hunks_become_several_replacement_pairs() -> None:
    """`FileEdit.replacements` is what `pre-tool-use-memory-size` replays to
    predict the post-edit size (`pre_tool_use_memory_size.py:148`), so a hunk
    has to round-trip through `str.replace`: context lines belong on both sides
    of the pair or the replacement finds nothing."""
    blob = (
        "*** Begin Patch\n"
        "*** Update File: /w/a.txt\n"
        "@@ def one():\n"
        " keep\n"
        "-old\n"
        "+new\n"
        "@@\n"
        "-second\n"
        "+SECOND\n"
        "*** End Patch"
    )
    tool = _tool_for(blob)
    assert tool is not None
    assert tool.edits[0].replacements == (
        ("keep\nold", "keep\nnew"),
        ("second", "SECOND"),
    )


def test_an_add_file_section_is_a_create_carrying_its_whole_content() -> None:
    """Unprobed shape, derived from the format: every body line of an add is a
    `+` line, so the added lines *are* the file."""
    blob = "*** Begin Patch\n*** Add File: /w/new.txt\n+one\n+two\n*** End Patch"
    tool = _tool_for(blob)
    assert tool is not None
    assert len(tool.edits) == 1
    assert tool.edits[0].is_create is True
    assert tool.edits[0].content == "one\ntwo\n"


def test_a_delete_section_yields_no_edit_because_file_edit_cannot_say_delete() -> None:
    """The deliberate gap, not an oversight. `FileEdit` has `is_create` and no
    counterpart, so a delete emitted as an edit would tell every reader the path
    is still there: `post_tool_use_format.py:37` would format a file that is
    gone. Widening `FileEdit` on a section shape no probe has seen would be the
    guess this adapter exists to refuse — the header names it as a follow-up."""
    blob = "*** Begin Patch\n*** Delete File: /w/gone.txt\n*** End Patch"
    tool = _tool_for(blob)
    assert tool is not None
    assert tool.operation is Operation.MODIFY_FILE
    assert tool.edits == ()


def test_a_blob_with_no_file_section_abstains() -> None:
    """The must-fail half of the parser's contract: no section, no edit, and the
    five builtins gated on `tool.edits` return without acting."""
    tool = _tool_for("*** Begin Patch\n@@\n-a\n+b\n*** End Patch")
    assert tool is not None
    assert tool.edits == ()


@pytest.mark.parametrize("blob", [None, 7, ["*** Begin Patch"], {"a": 1}, ""])
def test_a_command_that_is_not_patch_text_abstains_rather_than_raising(blob: object) -> None:
    """Valid JSON of the wrong type, the payload hazard this repo tests for
    everywhere else. A hook that raises here exits non-zero on a PreToolUse."""
    tool = _tool_for(blob)
    assert tool is not None
    assert tool.native_name == "apply_patch"
    assert tool.edits == ()
    assert tool.command is None


def test_an_absent_tool_input_still_parses_as_an_edit() -> None:
    payload = dict(_APPLY_PATCH)
    del payload["tool_input"]
    tool = _adapter().parse_hook_input("pre_tool_use", payload, profile="probe").tool
    assert tool is not None
    assert tool.operation is Operation.MODIFY_FILE
    assert tool.edits == ()

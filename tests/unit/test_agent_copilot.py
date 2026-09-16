"""`CopilotAdapter` — the `run`/`log`-backed subset, and the refusals around it.

Every assertion here is pinned to something the multi-agent design records as
**observed** against `copilot 1.0.83` — a run of the binary or a line in a
session log — and the citation is in the test's own docstring. Where the
evidence is a string in the vendor artifact or a line of vendor documentation,
the test asserts the adapter **does not** encode it: those rows are probes in
`specs/designs/copilot-evidence.md`, not behaviour, and a test that froze one
as a fact would make the probe unfalsifiable.

That inversion is the point of the file. `CodexAdapter`'s tests could assert
what six probes measured; this adapter ships before its probes, so half of what
is worth testing is what it refuses to claim.
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

HOOKS_FILE = Path("hooks/lazy-harness.json")

# The literal payload a hook registered at `~/.copilot/hooks/` received on
# 1.0.83, from `specs/designs/2026-09-13-multi-agent-harness-design.md:445-449`
# and `:2076-2083`. Not an invented fixture: `toolArgs` being a nested object
# rather than a JSON-encoded string is the one documented detail that run
# contradicted, and a fixture written from the documentation would have
# encoded the wrong one.
OBSERVED_PRE_TOOL_USE = {
    "sessionId": "3ea79314-0000-0000-0000-000000000000",
    "timestamp": 1789405602106,
    "cwd": "/Users/somebody/work",
    "toolName": "bash",
    "toolArgs": {"command": "echo hello", "description": "Print hello"},
}


def _adapter():
    from lazy_harness.agents.copilot import CopilotAdapter

    return CopilotAdapter()


# --- event vocabulary: eleven accepted, five rejected ----------------------


def test_the_eleven_accepted_names_are_the_ones_enumerated_by_rejection() -> None:
    """`:1199`, run, 1.0.83. Sixteen candidates were written into a hook file
    and the binary read back for which it dropped. This is the accepted set,
    and it supersedes the 1.0.40 `strings` list that survived three revisions."""
    from lazy_harness.agents.copilot import COPILOT_EVENT_NAMES

    assert COPILOT_EVENT_NAMES == frozenset(
        {
            "preToolUse",
            "postToolUse",
            "postToolUseFailure",
            "preMcpToolCall",
            "permissionRequest",
            "sessionStart",
            "sessionEnd",
            "preCompact",
            "notification",
            "subagentStart",
            "subagentStop",
        }
    )


def test_every_emitted_native_name_is_one_copilot_accepts() -> None:
    """The load-bearing test, and Copilot's failure mode is Codex's: an
    unrecognised name is dropped at load behind one `Ignoring unknown hook
    event(s) in <file>` line covering all of them, so a single mis-cased name
    disappears into a message that looks like it is about a different one."""
    from lazy_harness.agents.copilot import COPILOT_EVENT_NAMES

    emitted = {support.native_name for support in _adapter().hook_events().values()}
    assert emitted <= COPILOT_EVENT_NAMES, sorted(emitted - COPILOT_EVENT_NAMES)


def test_no_emitted_name_is_one_the_binary_was_seen_to_reject() -> None:
    """Stated as its own assertion rather than inferred from the one above,
    because the five rejects are where the camelCase near-misses live:
    `userPromptSubmit` is one character from nothing at all."""
    from lazy_harness.agents.copilot import (
        COPILOT_EVENT_NAMES,
        COPILOT_REJECTED_EVENT_NAMES,
    )

    assert COPILOT_REJECTED_EVENT_NAMES == frozenset(
        {"userPromptSubmit", "postCompact", "stop", "error", "preResponse"}
    )
    assert not (COPILOT_EVENT_NAMES & COPILOT_REJECTED_EVENT_NAMES)

    emitted = {support.native_name for support in _adapter().hook_events().values()}
    assert not (emitted & COPILOT_REJECTED_EVENT_NAMES)


def test_all_eleven_accepted_names_are_mapped() -> None:
    """An accepted event left unmapped is unreachable: `hook_events()` is the
    only mapping, so a name absent here can never be deployed against."""
    from lazy_harness.agents.copilot import COPILOT_EVENT_NAMES

    emitted = {support.native_name for support in _adapter().hook_events().values()}
    assert emitted == COPILOT_EVENT_NAMES


def test_the_three_events_copilot_rejects_are_absent_keys_not_empty_ones() -> None:
    """An absent key means "not delivered at all" — the contract's own words.
    `session_stop`, `post_compact` and `user_prompt_submit` are canonical events
    this repo's builtins use and Copilot has no name for, which is a stronger
    statement than an event that fires and honours nothing."""
    events = _adapter().hook_events()

    assert "session_stop" not in events
    assert "post_compact" not in events
    assert "user_prompt_submit" not in events


def test_supported_hooks_is_derived_from_the_event_map() -> None:
    """One mapping, not two. A second literal is how the casing desynchronises."""
    adapter = _adapter()
    assert set(adapter.supported_hooks()) == set(adapter.hook_events())


def test_only_pre_tool_use_declares_a_verdict_and_it_is_deny() -> None:
    """`:2135-2146`, run, 1.0.83: four envelopes varied against a control, one
    blocked. `allow` and `ask` appear in the SDK's output union
    (`copilot-sdk/types.d.ts:1052-1058`) and have never been observed being
    honoured — declaring either would let deploy install a guard whose
    approvals nothing checks."""
    events = _adapter().hook_events()

    assert events["pre_tool_use"].verdicts == frozenset({Verdict.DENY})
    assert events["pre_tool_use"].can_block
    for name, support in events.items():
        if name == "pre_tool_use":
            continue
        assert support.verdicts == frozenset(), f"{name} claims {support.verdicts}"
        assert not support.can_block


# --- payload translation ---------------------------------------------------


def test_the_observed_pre_tool_use_payload_parses() -> None:
    """The camelCase set, `:445-449`, run. Codex is Claude-shaped and Copilot
    is not, so nothing here can be reused from `CodexAdapter`."""
    event = _adapter().parse_hook_input("pre_tool_use", OBSERVED_PRE_TOOL_USE, profile="work")

    assert event.event == "pre_tool_use"
    assert event.profile == "work"
    assert event.session_id == "3ea79314-0000-0000-0000-000000000000"
    assert event.cwd == Path("/Users/somebody/work")
    assert event.raw == OBSERVED_PRE_TOOL_USE


def test_the_canonical_event_name_comes_from_the_caller_not_the_payload() -> None:
    """`:450-455`, run: Copilot's payload carries no event-name field at all.
    The adapter is told which event it was invoked for, and a reader looking for
    `hookEventName` would find nothing on every one of the eleven."""
    payload = dict(OBSERVED_PRE_TOOL_USE)
    assert "hookEventName" not in payload
    assert "hook_event_name" not in payload

    event = _adapter().parse_hook_input("post_tool_use", payload, profile="work")
    assert event.event == "post_tool_use"


def test_transcript_path_is_none_because_copilot_sends_none() -> None:
    """`:453-455`, run. This is the asymmetry decision 11 and step 12 lean on:
    Codex hands the path over outright, Copilot delivers no path at all, so a
    Copilot transcript reader needs `locate_sessions` and cannot be driven from
    the hook payload."""
    event = _adapter().parse_hook_input("pre_tool_use", OBSERVED_PRE_TOOL_USE, profile="work")
    assert event.transcript_path is None


def test_a_non_string_session_id_does_not_become_one() -> None:
    """`str()` on a list yields something that looks like a session id and is
    not one — and this field keys the metrics, the memory scope and the
    transcript reads."""
    event = _adapter().parse_hook_input(
        "pre_tool_use", {"sessionId": ["a", "b"], "cwd": 7}, profile="work"
    )
    assert event.session_id == ""
    assert event.cwd == Path()


def test_a_payload_with_no_tool_yields_no_tool_call() -> None:
    event = _adapter().parse_hook_input("session_start", {"sessionId": "s"}, profile="work")
    assert event.tool is None


def test_bash_is_a_run_command_carrying_the_shell_text() -> None:
    """`:2076-2083`, run: `toolArgs` is a nested JSON object, not a
    JSON-encoded string. The whole `pre_tool_use_security` command denylist
    reaches Copilot through this one key."""
    event = _adapter().parse_hook_input("pre_tool_use", OBSERVED_PRE_TOOL_USE, profile="work")

    assert event.tool is not None
    assert event.tool.native_name == "bash"
    assert event.tool.operation is Operation.RUN_COMMAND
    assert event.tool.command == "echo hello"
    assert event.tool.raw_input == OBSERVED_PRE_TOOL_USE["toolArgs"]


def test_tool_args_delivered_as_a_string_is_not_read_as_a_mapping() -> None:
    """The shape the vendor documentation claimed and the binary contradicted.
    If a future build ships it, `command` must come back `None` rather than a
    substring of a JSON document."""
    event = _adapter().parse_hook_input(
        "pre_tool_use",
        {"toolName": "bash", "toolArgs": '{"command": "echo hello"}'},
        profile="work",
    )

    assert event.tool is not None
    assert event.tool.command is None


def test_view_is_a_read_file_with_nothing_in_reads() -> None:
    """`view` is `log, 1.0.83` (27 calls in a real session) but its ARGUMENT
    KEY is unmeasured — no run, no log, no SDK type names it. So the operation
    gate opens and the structure gate does not, which is the F8 gate's own
    finding: a mapping without a structure revives nothing
    (`specs/gates/f8/translation-gate.sh:56-78`). Asserted rather than left
    implicit, because the day the probe lands this test must fail."""
    event = _adapter().parse_hook_input(
        "pre_tool_use",
        {"toolName": "view", "toolArgs": {"path": "/etc/hosts"}},
        profile="work",
    )

    assert event.tool is not None
    assert event.tool.operation is Operation.READ_FILE
    assert event.tool.reads == ()


def test_no_tool_maps_to_modify_file_because_none_has_been_observed() -> None:
    """The largest gap in the adapter, stated as an assertion so it cannot be
    closed by inference. Copilot has never been observed editing a file:
    `apply_patch` and `str_replace_editor` are strings in `runtime.node`, which
    per the design's first gate establishes that the names exist and nothing
    else."""
    from lazy_harness.agents.copilot import _TOOL_OPERATIONS

    assert Operation.MODIFY_FILE not in set(_TOOL_OPERATIONS.values())
    for candidate in ("apply_patch", "str_replace_editor", "edit", "create", "write"):
        assert candidate not in _TOOL_OPERATIONS


def test_every_mapped_tool_name_is_one_a_session_was_seen_to_use() -> None:
    """Copilot does **not** normalise to Claude Code's names (`:1054-1060`,
    run), so `Bash` or `Read` here would install a matcher that never fires."""
    from lazy_harness.agents.copilot import _TOOL_OPERATIONS, COPILOT_TOOL_NAMES

    assert COPILOT_TOOL_NAMES == frozenset(
        {"bash", "view", "rg", "glob", "task", "skill", "web_fetch", "web_search"}
    )
    assert set(_TOOL_OPERATIONS) <= COPILOT_TOOL_NAMES
    assert all(name == name.lower() for name in COPILOT_TOOL_NAMES)


def test_an_unmapped_tool_parses_with_no_operation_rather_than_being_dropped() -> None:
    """`operation=None` is "this ran and no builtin guards it", never "this is
    harmless" — the call still reaches a hook, with its native name intact."""
    event = _adapter().parse_hook_input(
        "pre_tool_use", {"toolName": "web_fetch", "toolArgs": {}}, profile="work"
    )

    assert event.tool is not None
    assert event.tool.native_name == "web_fetch"
    assert event.tool.operation is None


# --- the verdict envelope --------------------------------------------------


def test_deny_is_emitted_top_level_and_unwrapped() -> None:
    """`:2135-2146`, run: this exact shape produced `✗ … Denied by preToolUse
    hook: <reason>` and the command did not run, while the same verdict wrapped
    in `hookSpecificOutput` was read, logged and ignored."""
    adapter = _adapter()
    event = adapter.parse_hook_input("pre_tool_use", OBSERVED_PRE_TOOL_USE, profile="work")

    out = adapter.format_hook_output(event, HookDecision(verdict=Verdict.DENY, reason="nope"))

    assert out.exit_code == 0
    assert out.stderr == ""
    assert out.stdout is not None
    assert json.loads(out.stdout) == {
        "permissionDecision": "deny",
        "permissionDecisionReason": "nope",
    }


def test_the_hook_specific_output_wrapper_is_never_emitted() -> None:
    """The one envelope measured to be ignored. Asserted on the literal, not on
    the parsed shape, so a nested key cannot slip back in under another path."""
    adapter = _adapter()
    event = adapter.parse_hook_input("pre_tool_use", OBSERVED_PRE_TOOL_USE, profile="work")

    out = adapter.format_hook_output(event, HookDecision(verdict=Verdict.DENY, reason="nope"))

    assert out.stdout is not None
    assert "hookSpecificOutput" not in out.stdout
    assert "hookEventName" not in out.stdout


@pytest.mark.parametrize("verdict", [Verdict.ALLOW, Verdict.ASK, Verdict.BLOCK])
def test_an_unhonoured_verdict_raises_rather_than_emitting_nothing(verdict: Verdict) -> None:
    """Emitting nothing on a blocking hook reads as approval. `allow` and `ask`
    are in the SDK's union and have never been seen honoured; `block` has no
    home at all, since `agentStop` — the only event whose SDK output declares
    `decision: "block"` — is not one of the eleven the loader accepts."""
    adapter = _adapter()
    event = adapter.parse_hook_input("pre_tool_use", OBSERVED_PRE_TOOL_USE, profile="work")

    with pytest.raises(ValueError, match="pre_tool_use"):
        adapter.format_hook_output(event, HookDecision(verdict=verdict, reason="x"))


def test_a_verdict_on_an_event_that_honours_none_raises() -> None:
    adapter = _adapter()
    event = adapter.parse_hook_input("post_tool_use", {"sessionId": "s"}, profile="work")

    with pytest.raises(ValueError, match="post_tool_use"):
        adapter.format_hook_output(event, HookDecision(verdict=Verdict.DENY, reason="x"))


def test_a_verdict_on_an_event_copilot_does_not_deliver_raises() -> None:
    """`session_stop` is not in `hook_events()` at all — nothing should ever
    reach here, and if it does the failure must be loud rather than an empty
    stdout that Copilot reads as consent."""
    adapter = _adapter()
    event = adapter.parse_hook_input("session_stop", {"sessionId": "s"}, profile="work")

    with pytest.raises(ValueError, match="session_stop"):
        adapter.format_hook_output(event, HookDecision(verdict=Verdict.BLOCK, reason="x"))


def test_abstaining_writes_nothing_at_all() -> None:
    adapter = _adapter()
    event = adapter.parse_hook_input("pre_tool_use", OBSERVED_PRE_TOOL_USE, profile="work")

    out = adapter.format_hook_output(event, HookDecision())

    assert out.stdout is None
    assert out.stderr == ""
    assert out.exit_code == 0


def test_additional_context_is_dropped_because_no_run_has_shown_it_read() -> None:
    """The row with the widest blast radius, and the reason it is a test.
    `additionalContext` is named in the 1.0.40 bundle and declared on four SDK
    output types — both `src`-level. Emitting it would hand every
    context-injecting builtin a channel nothing has shown Copilot reads, which
    is the failure `CodexAdapter` avoids by not emitting `systemMessage`.
    Probe 2 in `specs/designs/copilot-evidence.md` closes it; until then the
    drop is deliberate and ADR-047's Consequences names what goes quiet."""
    adapter = _adapter()
    event = adapter.parse_hook_input("session_start", {"sessionId": "s"}, profile="work")

    out = adapter.format_hook_output(
        event, HookDecision(additional_context="remember this", system_message="and this")
    )

    assert out.stdout is None


def test_no_unobserved_channel_reaches_stdout_alongside_a_deny() -> None:
    """`continue`/`stopReason` were run and ignored (`:2146`); `systemMessage`
    and `suppressOutput` are `src`-level only."""
    adapter = _adapter()
    event = adapter.parse_hook_input("pre_tool_use", OBSERVED_PRE_TOOL_USE, profile="work")

    out = adapter.format_hook_output(
        event,
        HookDecision(
            verdict=Verdict.DENY,
            reason="nope",
            additional_context="ctx",
            system_message="msg",
            suppress_output=True,
            stop=True,
        ),
    )

    assert out.stdout is not None
    body = json.loads(out.stdout)
    assert set(body) == {"permissionDecision", "permissionDecisionReason"}


# --- config documents ------------------------------------------------------


def test_the_adapter_is_a_config_planner() -> None:
    assert isinstance(_adapter(), ConfigPlanner)


def test_the_single_target_is_a_file_the_harness_owns_outright() -> None:
    """Ownership is the FILENAME, not a stamp. Copilot loads
    `$COPILOT_HOME/hooks/*.json` — a glob — so the harness can take one path in
    it and leave every sibling to the user, which is a cleaner boundary than
    `CodexAdapter`'s `description` stamp and does not depend on the document
    tolerating an unknown top-level key (unmeasured, §4 of the evidence file)."""
    assert _adapter().config_targets() == [HOOKS_FILE]


def test_the_document_carries_the_required_version_literal() -> None:
    """`version: Required` and `version: Invalid literal value, expected 1` are
    both in the declarative hook loader's string region (src, 1.0.83). This is
    the one shape the adapter writes and cannot verify — phase 0 of
    `copilot-probe1.sh` exists to fail it loudly if it is wrong."""
    ops = _adapter().plan_config(
        {"pre_tool_use": [HookEntry(command="lh hook x --profile work")]}, {}, {}
    )

    assert len(ops) == 1
    assert ops[0].artifact is not None
    document = json.loads(ops[0].artifact.content)
    assert document["version"] == 1
    assert set(document) == {"version", "hooks"}


def test_events_map_to_their_camel_case_native_names() -> None:
    ops = _adapter().plan_config(
        {
            "pre_tool_use": [HookEntry(command="lh hook a --profile work")],
            "session_start": [HookEntry(command="lh hook b --profile work")],
        },
        {},
        {},
    )

    document = json.loads(ops[0].artifact.content)
    assert set(document["hooks"]) == {"preToolUse", "sessionStart"}


def test_each_entry_becomes_one_group_in_declaration_order() -> None:
    ops = _adapter().plan_config(
        {
            "pre_tool_use": [
                HookEntry(command="first"),
                HookEntry(command="second"),
            ]
        },
        {},
        {},
    )

    groups = json.loads(ops[0].artifact.content)["hooks"]["preToolUse"]
    assert [group["command"] for group in groups] == ["first", "second"]


def test_a_matcher_is_omitted_rather_than_written_empty() -> None:
    """`matcher cannot be empty` is a load error in the runtime's strings, and
    an empty string is therefore the one value guaranteed to drop the hook."""
    ops = _adapter().plan_config({"pre_tool_use": [HookEntry(command="x")]}, {}, {})

    group = json.loads(ops[0].artifact.content)["hooks"]["preToolUse"][0]
    assert "matcher" not in group


def test_a_declared_matcher_is_passed_through() -> None:
    ops = _adapter().plan_config({"pre_tool_use": [HookEntry(command="x", matcher="bash")]}, {}, {})

    group = json.loads(ops[0].artifact.content)["hooks"]["preToolUse"][0]
    assert group["matcher"] == "bash"


def test_an_event_copilot_does_not_deliver_is_skipped_silently_in_the_document() -> None:
    """Writing `stop` into the file drops **every** hook behind one
    `Ignoring unknown hook event(s)` line, so a single unsupported event
    configured by the user would take the whole profile's hooks down."""
    ops = _adapter().plan_config(
        {
            "session_stop": [HookEntry(command="never")],
            "pre_tool_use": [HookEntry(command="yes")],
        },
        {},
        {},
    )

    document = json.loads(ops[0].artifact.content)
    assert set(document["hooks"]) == {"preToolUse"}
    assert "never" not in ops[0].artifact.content


def test_no_hooks_plans_nothing_when_the_file_does_not_exist() -> None:
    assert _adapter().plan_config({}, {}, {}) == []


def test_no_hooks_retires_a_file_the_harness_previously_wrote() -> None:
    """Keyed on the path, which is the whole reason the harness took a
    dedicated filename under the glob: a user's own `hooks/mine.json` is never
    a candidate for deletion, so no ownership stamp has to be parsed out of a
    document whose schema strictness is unmeasured."""
    ops = _adapter().plan_config({}, {}, {HOOKS_FILE: '{"version": 1, "hooks": {}}'})

    assert len(ops) == 1
    assert ops[0].artifact is None
    assert ops[0].relative_path == HOOKS_FILE


def test_mcp_servers_are_not_placed_and_the_document_stays_hooks_only() -> None:
    """`mcp-config.json` is `present on disk` and the design's own 2026-09-14
    sweep deliberately left it there: *a path that exists is not a path the
    binary was seen to read*. It is also a file Copilot writes itself, next to
    `permissions-config.json`, where a careless rewrite destroys every approval
    the user granted. So `servers` is ignored until probe 7 runs."""
    adapter = _adapter()

    ops = adapter.plan_config(
        {"pre_tool_use": [HookEntry(command="x")]},
        {"qmd": {"command": "qmd", "args": ["mcp"]}},
        {},
    )

    assert [op.relative_path for op in ops] == [HOOKS_FILE]
    assert "qmd" not in ops[0].artifact.content
    assert adapter.mcp_config_file() == ""


def test_servers_alone_plan_no_write_at_all() -> None:
    assert _adapter().plan_config({}, {"qmd": {"command": "qmd"}}, {}) == []


# --- the rest of the adapter surface ---------------------------------------


def test_the_env_var_is_the_one_honoured_end_to_end() -> None:
    """`:1195`, run, 1.0.83."""
    assert _adapter().env_var() == "COPILOT_HOME"


def test_credentials_file_is_none_and_the_reason_is_a_run() -> None:
    """Stronger than `CodexAdapter`'s `None`, which rests on a file nobody
    opened. Here the negative was measured: every deny-matrix run used a
    throwaway `COPILOT_HOME` and auth survived it (`:1195`), so the credential
    is not under the config dir and the harness cannot speak for this login at
    all — which is exactly what ADR-045 reserves `None` to mean."""
    assert _adapter().credentials_file() is None


def test_no_global_symlink_because_the_directory_is_the_vendors() -> None:
    """`deploy/symlinks.py:16-21` renames an existing target to `<name>.bak`
    before linking, and `~/.copilot` holds `permissions-config.json` —
    `locations.<abs path>.tool_approvals[]`, written by the agent as the user
    approves things (`:1277`) — plus `session-store.db` and `settings.json`."""
    assert _adapter().global_config_link() is None


def test_sessions_live_under_session_state() -> None:
    """`:1204`, log, 1.0.83: `session-state/<uuid>/events.jsonl`. `logs` and
    `queue` stay empty — `~/.copilot/logs/` exists on disk, and a directory
    that exists is not a directory the binary was seen to write."""
    assert _adapter().session_dirs() == {"sessions": "session-state", "logs": "", "queue": ""}


def test_system_docs_is_one_destination_and_it_is_not_repo_shaped() -> None:
    """The row step 11 exists for: the first agent whose destination is not a
    repo-shaped filename. `AGENTS.md`, `CLAUDE.md` and `.github/copilot-
    instructions.md` are **repository-discovered** by Copilot, never user-level
    destinations — writing one into the config dir installs nothing (`:96`,
    `:1198`).

    One entry, not two. `instructions/**/*.instructions.md` is a glob rather
    than a path, and `system_docs()` asserts the agent loads **every** entry it
    returns — which nothing has measured. Probe 6 closes it."""
    docs = _adapter().system_docs()

    assert docs == [Path("copilot-instructions.md")]
    for repo_shaped in ("AGENTS.md", "CLAUDE.md", "GEMINI.md"):
        assert Path(repo_shaped) not in docs


def test_the_adapter_names_itself_consistently() -> None:
    adapter = _adapter()
    assert adapter.name == "copilot"
    assert adapter.process_name() == "copilot"


def test_resolve_binary_reports_none_when_copilot_is_absent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("lazy_harness.agents.copilot.shutil.which", lambda _name: None)
    assert _adapter().resolve_binary() is None


def test_resolve_binary_returns_the_path_when_present(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "lazy_harness.agents.copilot.shutil.which",
        lambda name: "/opt/homebrew/bin/copilot" if name == "copilot" else None,
    )
    assert _adapter().resolve_binary() == Path("/opt/homebrew/bin/copilot")


def test_config_dir_expands_the_profile_path() -> None:
    resolved = _adapter().config_dir("~/.copilot-work")
    assert resolved.is_absolute()
    assert resolved.name == ".copilot-work"


def test_no_transcript_reader_is_claimed() -> None:
    """Step 12's, and the design pins the method: Copilot's reader is generated
    from `schemas/session-events.schema.json` shipped beside the binary, not
    reverse-engineered from samples (`:1899-1906`). Declaring the Protocol now
    would route a caller at a parser nobody has fed."""
    from lazy_harness.agents.base import TranscriptReader

    assert not isinstance(_adapter(), TranscriptReader)


def test_no_headless_agent_is_claimed() -> None:
    """`copilot -p` is `run, 1.0.83` — it starts a run. Nothing here has ever
    parsed its output, and `HeadlessAgent` is the declaration that `lh exec`
    may route work at this parser."""
    from lazy_harness.agents.base import HeadlessAgent

    assert not isinstance(_adapter(), HeadlessAgent)


# --- registry and CLI ------------------------------------------------------


def test_copilot_is_registered_and_resolvable() -> None:
    from lazy_harness.agents.registry import get_agent, list_agents

    assert "copilot" in list_agents()
    assert get_agent("copilot").name == "copilot"


def test_the_null_adapter_still_refuses_every_verdict() -> None:
    """Registering a third agent must not disturb the shipped sentinel, which
    is how the Protocol's refusal path is exercised at all."""
    from lazy_harness.agents.base import HookDecision as Decision
    from lazy_harness.agents.registry import get_agent

    null = get_agent("null")
    event = null.parse_hook_input("pre_tool_use", {}, profile="work")

    with pytest.raises(ValueError, match="null honours no verdict"):
        null.format_hook_output(event, Decision(verdict=Verdict.DENY, reason="x"))


def test_doctor_reports_a_copilot_profile_without_crashing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The smoke test through the real CLI. `lh doctor` walks every profile and
    asks its adapter a dozen questions; a `None` where it expects a string takes
    the whole report down, and `credentials_file()` returning `None` is exactly
    such an answer (ADR-045's `n/a` status is what makes it survivable)."""
    from click.testing import CliRunner

    from lazy_harness.cli.doctor_cmd import doctor

    cfg = tmp_path / "config.toml"
    cfg.write_text(
        '[harness]\nversion = "1"\n'
        '[agent]\ntype = "copilot"\n'
        '[profiles]\ndefault = "work"\n\n[profiles.work]\n'
        f'config_dir = "{tmp_path / "copilot-work"}"\nagent = "copilot"\n'
        '[knowledge]\nroot = ""\n'
    )
    monkeypatch.setattr("lazy_harness.cli.doctor_cmd.config_file", lambda: cfg)

    result = CliRunner().invoke(doctor, [])

    # `doctor` exits 1 when any check fails, which a bare temp config always
    # does — so a nonzero exit is not the question. A crash is: anything that
    # is not the `SystemExit` the command raises on purpose means one of the
    # adapter's answers took the whole report down.
    assert result.exception is None or isinstance(result.exception, SystemExit), (
        f"{result.exception!r}\n{result.output}"
    )
    assert result.exit_code in (0, 1), result.output
    assert "Agent: copilot" in result.output

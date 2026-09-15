"""The canonical hook contract — the vocabulary every adapter translates into.

These types are the seam ADR-041 freezes. The tests that matter here are the
ones guarding a *default*: a contract can ship broken while every method works,
because the damage lives in what a caller gets when it says nothing.
"""

from __future__ import annotations

from pathlib import Path

import pytest

# --- Verdict -------------------------------------------------------------


def test_verdict_vocabulary_is_the_four_the_agents_speak() -> None:
    from lazy_harness.agents.base import Verdict

    assert {v.value for v in Verdict} == {"allow", "deny", "ask", "block"}


def test_verdict_is_a_str_enum_so_it_serialises_as_its_wire_value() -> None:
    from lazy_harness.agents.base import Verdict

    assert Verdict.DENY == "deny"


# --- HookDecision --------------------------------------------------------


def test_abstaining_is_not_approving() -> None:
    """The load-bearing default.

    `pre_tool_use_security` exits 0 with no output for every command it merely
    fails to object to. If the default verdict were ALLOW, migrating that branch
    would convert each of those into an explicit, prompt-skipping approval.
    """
    from lazy_harness.agents.base import HookDecision

    assert HookDecision().verdict is None


def test_hook_decision_carries_the_non_verdict_channels() -> None:
    from lazy_harness.agents.base import HookDecision

    decision = HookDecision(
        reason="blocked",
        additional_context="ctx",
        system_message="msg",
        stop=True,
        suppress_output=True,
    )
    assert decision.reason == "blocked"
    assert decision.additional_context == "ctx"
    assert decision.system_message == "msg"
    assert decision.stop is True
    assert decision.suppress_output is True


def test_hook_decision_is_frozen() -> None:
    from lazy_harness.agents.base import HookDecision, Verdict

    decision = HookDecision(verdict=Verdict.DENY)
    with pytest.raises(AttributeError):
        decision.verdict = Verdict.ALLOW  # type: ignore[misc]


# --- HookOutput ----------------------------------------------------------


def test_hook_output_is_three_channels_not_two() -> None:
    """A blocking hook's reason reaches the user via stderr, not stdout.

    Both blocking builtins write the refusal to stderr and exit 2. A pair of
    (document, exit_code) would drop it silently.
    """
    from lazy_harness.agents.base import HookOutput

    out = HookOutput(stdout=None, stderr="refused: rm -rf /", exit_code=2)
    assert out.stdout is None
    assert out.stderr == "refused: rm -rf /"
    assert out.exit_code == 2


def test_stdout_leaves_the_adapter_already_serialised() -> None:
    """The adapter owns the bytes; the runner writes the string it is given and
    never re-encodes. Asserted on what `format_hook_output` actually returns —
    an `isinstance` check on a `str` literal fed to the constructor would hold
    just as well with a `dict` in the annotation, and this repo runs no type
    checker to catch that."""
    import json

    from lazy_harness.agents.base import HookDecision
    from lazy_harness.agents.registry import get_agent

    adapter = get_agent("claude-code")
    event = adapter.parse_hook_input(
        "session_start", {"session_id": "s", "cwd": "/r"}, profile="lazy"
    )
    out = adapter.format_hook_output(event, HookDecision(additional_context="ctx"))
    assert isinstance(out.stdout, str), "the runner must not have to serialise"
    assert json.loads(out.stdout)


# --- HookSupport ---------------------------------------------------------


def test_can_block_is_derived_from_the_honoured_verdicts() -> None:
    from lazy_harness.agents.base import HookSupport, Verdict

    assert HookSupport("PreToolUse", frozenset({Verdict.DENY})).can_block
    assert HookSupport("Stop", frozenset({Verdict.BLOCK})).can_block


def test_an_agent_that_only_warns_cannot_block() -> None:
    """Codex logs `unsupported permissionDecision:ask` and runs the tool anyway."""
    from lazy_harness.agents.base import HookSupport, Verdict

    assert not HookSupport("PreToolUse", frozenset({Verdict.ALLOW, Verdict.ASK})).can_block
    assert not HookSupport("Notification", frozenset()).can_block


# --- Operation / Signal --------------------------------------------------


def test_operation_vocabulary_is_what_the_builtins_reason_about() -> None:
    from lazy_harness.agents.base import Operation

    assert {o.value for o in Operation} == {"run_command", "read_file", "modify_file"}


def test_signal_vocabulary_names_each_transcript_dependency() -> None:
    from lazy_harness.agents.base import Signal

    assert {s.value for s in Signal} == {
        "messages",
        "tool_calls",
        "token_usage",
        "goal_status",
    }


# --- ToolCall / FileEdit -------------------------------------------------


def test_paths_spans_reads_and_edits() -> None:
    from lazy_harness.agents.base import FileEdit, Operation, ToolCall

    call = ToolCall(
        native_name="apply_patch",
        operation=Operation.MODIFY_FILE,
        reads=(Path("a.py"),),
        edits=(FileEdit(path=Path("b.py")), FileEdit(path=Path("c.py"))),
    )
    assert call.paths == (Path("a.py"), Path("b.py"), Path("c.py"))


def test_a_tool_call_no_builtin_reasons_about_has_no_operation() -> None:
    from lazy_harness.agents.base import ToolCall

    assert ToolCall(native_name="WebSearch", operation=None).operation is None


def test_an_unbounded_read_is_none_not_zero() -> None:
    """`pre_tool_use_read_size` tells a bounded read from an unbounded one."""
    from lazy_harness.agents.base import Operation, ToolCall

    call = ToolCall(native_name="Read", operation=Operation.READ_FILE, reads=(Path("x"),))
    assert call.offset is None
    assert call.limit is None


def test_file_edit_defaults_to_a_modification_not_a_create() -> None:
    from lazy_harness.agents.base import FileEdit

    edit = FileEdit(path=Path("x.py"))
    assert edit.is_create is False
    assert edit.content is None
    assert edit.replacements == ()
    assert edit.replace_all is False


# --- HookEvent -----------------------------------------------------------


def test_hook_event_carries_every_field_a_payload_can_name() -> None:
    """A hook reaching into `raw` means the normalisation is a fiction."""
    from lazy_harness.agents.base import HookEvent

    event = HookEvent(
        event="session_start",
        profile="lazy",
        session_id="s1",
        cwd=Path("/tmp"),
        transcript_path=None,
        source="startup",
        trigger="manual",
        stop_hook_active=True,
        tool_use_id="tu1",
        message="hi",
    )
    assert event.source == "startup"
    assert event.trigger == "manual"
    assert event.stop_hook_active is True
    assert event.tool_use_id == "tu1"
    assert event.message == "hi"


def test_hook_event_has_no_native_tool_name_beside_the_canonical_tool() -> None:
    """`ToolCall` is canonical. Two representations of one thing is how the
    builtins keep reading native argument names."""
    from dataclasses import fields

    from lazy_harness.agents.base import HookEvent

    names = {f.name for f in fields(HookEvent)}
    assert "tool_name" not in names
    assert "tool_input" not in names
    assert "tool" in names


def test_tool_response_is_unconstrained() -> None:
    """Copilot delivers `{result_type, text_result_for_llm}`; the Claude SDK
    declares it unconstrained. A `dict` annotation fails at the first `.get()`."""
    from lazy_harness.agents.registry import get_agent

    event = get_agent("claude-code").parse_hook_input(
        "post_tool_use",
        {"session_id": "s", "cwd": "/r", "tool_response": "a bare string"},
        profile="lazy",
    )
    assert event.tool_response == "a bare string", "parsing must not coerce it to a mapping"


# --- ClaudeCodeAdapter: hook_events --------------------------------------


def test_hook_events_is_the_only_place_the_event_mapping_lives() -> None:
    """`supported_hooks()` used to return canonical names while
    `_generate_hook_config` re-mapped them in a second literal."""
    from lazy_harness.agents.registry import get_agent

    adapter = get_agent("claude-code")
    assert set(adapter.hook_events()) == set(adapter.supported_hooks())


def test_hook_events_carries_claude_codes_own_casing() -> None:
    from lazy_harness.agents.registry import get_agent

    events = get_agent("claude-code").hook_events()
    assert events["pre_tool_use"].native_name == "PreToolUse"
    assert events["session_stop"].native_name == "Stop"
    assert events["user_prompt_submit"].native_name == "UserPromptSubmit"


def test_claude_code_honours_deny_where_this_repo_has_seen_it_deny() -> None:
    """`pre_tool_use_security` refuses with stderr + exit 2 at this event."""
    from lazy_harness.agents.base import Verdict
    from lazy_harness.agents.registry import get_agent

    support = get_agent("claude-code").hook_events()["pre_tool_use"]
    assert Verdict.DENY in support.verdicts
    assert support.can_block


def test_claude_code_honours_block_at_stop() -> None:
    """`stop_verify_guard` emits `{"decision": "block"}` at this event."""
    from lazy_harness.agents.base import Verdict
    from lazy_harness.agents.registry import get_agent

    support = get_agent("claude-code").hook_events()["session_stop"]
    assert Verdict.BLOCK in support.verdicts
    assert support.can_block


def test_an_event_with_no_exercised_verdict_does_not_claim_to_block() -> None:
    """Biased toward false negatives: the set grows when a verdict is observed,
    not when a vendor doc names one."""
    from lazy_harness.agents.registry import get_agent

    events = get_agent("claude-code").hook_events()
    assert not events["session_start"].can_block
    assert not events["notification"].can_block


# --- ClaudeCodeAdapter: parse_hook_input ---------------------------------


def test_parse_hook_input_maps_a_pre_tool_use_payload_onto_the_canonical_view() -> None:
    from lazy_harness.agents.base import Operation
    from lazy_harness.agents.registry import get_agent

    event = get_agent("claude-code").parse_hook_input(
        "pre_tool_use",
        {
            "session_id": "s1",
            "transcript_path": "/tmp/t.jsonl",
            "cwd": "/repo",
            "hook_event_name": "PreToolUse",
            "tool_name": "Bash",
            "tool_input": {"command": "rm -rf /"},
        },
        profile="lazy",
    )
    assert event.event == "pre_tool_use"
    assert event.profile == "lazy"
    assert event.session_id == "s1"
    assert event.cwd == Path("/repo")
    assert event.transcript_path == Path("/tmp/t.jsonl")
    assert event.tool is not None
    assert event.tool.native_name == "Bash"
    assert event.tool.operation is Operation.RUN_COMMAND
    assert event.tool.command == "rm -rf /"


def test_a_read_payload_normalises_its_bounds() -> None:
    from lazy_harness.agents.base import Operation
    from lazy_harness.agents.registry import get_agent

    event = get_agent("claude-code").parse_hook_input(
        "pre_tool_use",
        {
            "session_id": "s",
            "cwd": "/repo",
            "tool_name": "Read",
            "tool_input": {"file_path": "/repo/big.log", "offset": 0, "limit": 100},
        },
        profile="lazy",
    )
    assert event.tool is not None
    assert event.tool.operation is Operation.READ_FILE
    assert event.tool.reads == (Path("/repo/big.log"),)
    assert event.tool.offset == 0, "0 is a real offset, not an absent one"
    assert event.tool.limit == 100


def test_an_edit_payload_carries_its_replacement_pair() -> None:
    from lazy_harness.agents.base import Operation
    from lazy_harness.agents.registry import get_agent

    event = get_agent("claude-code").parse_hook_input(
        "pre_tool_use",
        {
            "session_id": "s",
            "cwd": "/repo",
            "tool_name": "Edit",
            "tool_input": {"file_path": "/repo/a.py", "old_string": "x", "new_string": "y"},
        },
        profile="lazy",
    )
    assert event.tool is not None
    assert event.tool.operation is Operation.MODIFY_FILE
    assert event.tool.edits[0].path == Path("/repo/a.py")
    assert event.tool.edits[0].replacements == (("x", "y"),)


def test_a_tool_the_builtins_do_not_reason_about_parses_with_no_operation() -> None:
    from lazy_harness.agents.registry import get_agent

    event = get_agent("claude-code").parse_hook_input(
        "pre_tool_use",
        {"session_id": "s", "cwd": "/repo", "tool_name": "WebSearch", "tool_input": {"query": "x"}},
        profile="lazy",
    )
    assert event.tool is not None
    assert event.tool.operation is None


def test_parse_keeps_the_untranslated_payload_for_adapters() -> None:
    from lazy_harness.agents.registry import get_agent

    payload = {"session_id": "s", "cwd": "/repo", "source": "startup"}
    event = get_agent("claude-code").parse_hook_input("session_start", payload, profile="lazy")
    assert event.raw == payload
    assert event.source == "startup"


def test_a_payload_with_no_tool_has_no_tool_call() -> None:
    from lazy_harness.agents.registry import get_agent

    event = get_agent("claude-code").parse_hook_input(
        "user_prompt_submit",
        {"session_id": "s", "cwd": "/repo", "prompt": "hi"},
        profile="lazy",
    )
    assert event.tool is None
    assert event.prompt == "hi"


def test_a_missing_transcript_path_is_none_not_a_bare_path() -> None:
    from lazy_harness.agents.registry import get_agent

    event = get_agent("claude-code").parse_hook_input(
        "session_start", {"session_id": "s", "cwd": "/repo"}, profile="lazy"
    )
    assert event.transcript_path is None


def test_transcript_path_is_the_only_spelling_the_adapter_reads() -> None:
    """The narrowing away from the builtins' three-spelling tuple is measured.

    `_shared` accepts `transcript_path`, `transcriptPath` and `input`. The two
    extra spellings were defensive from the first line that carried them
    (`b81f0a6`, the original `pre_compact`) and no payload has ever been
    observed sending one: Claude Code 2.1.272 declares the hook payload's base
    fields as `["hook_event_name", "session_id", "transcript_path", "cwd",
    "scratchpad_dir", "prompt_id", "permission_mode", "agent_id", "agent_type",
    "served_call", "caller_session_id", "effort"]`, carried by the one base
    schema that all 33 of its event schemas extend. Every `transcriptPath` in
    that binary is internal resume/summary plumbing, never a hook field.

    Both halves of the rule live on payloads that disagree, because the half
    that a widening breaks is the *absence* one: honouring `transcript_path`
    survives any fallback chain that lists it first, so only a payload that
    omits it can tell a narrow adapter from a wide one.
    """
    from lazy_harness.agents.registry import get_agent

    adapter = get_agent("claude-code")

    both = adapter.parse_hook_input(
        "session_start",
        {
            "session_id": "s",
            "cwd": "/repo",
            "transcript_path": "/snake.jsonl",
            "transcriptPath": "/camel.jsonl",
            "input": "/input.jsonl",
        },
        profile="lazy",
    )
    assert both.transcript_path == Path("/snake.jsonl")

    neither = adapter.parse_hook_input(
        "session_start",
        {
            "session_id": "s",
            "cwd": "/repo",
            "transcriptPath": "/camel.jsonl",
            "input": "/input.jsonl",
        },
        profile="lazy",
    )
    assert neither.transcript_path is None


# --- ClaudeCodeAdapter: format_hook_output -------------------------------


def _event(adapter, name: str = "pre_tool_use"):
    return adapter.parse_hook_input(name, {"session_id": "s", "cwd": "/repo"}, profile="lazy")


def test_abstaining_emits_nothing_at_all() -> None:
    """Exit 0 with no output: the tool call continues through the normal
    permission flow, neither approved nor denied."""
    from lazy_harness.agents.base import HookDecision
    from lazy_harness.agents.registry import get_agent

    adapter = get_agent("claude-code")
    out = adapter.format_hook_output(_event(adapter), HookDecision())
    assert out.stdout is None
    assert out.stderr == ""
    assert out.exit_code == 0


def test_deny_refuses_on_stderr_with_exit_2() -> None:
    """The shape `pre_tool_use_security` ships today."""
    from lazy_harness.agents.base import HookDecision, Verdict
    from lazy_harness.agents.registry import get_agent

    adapter = get_agent("claude-code")
    out = adapter.format_hook_output(
        _event(adapter), HookDecision(verdict=Verdict.DENY, reason="rm -rf refused")
    )
    assert out.exit_code == 2
    assert out.stderr == "rm -rf refused"
    assert out.stdout is None


def test_block_goes_out_on_stdout_and_does_not_exit_2() -> None:
    """The shape `stop_verify_guard` ships today."""
    import json

    from lazy_harness.agents.base import HookDecision, Verdict
    from lazy_harness.agents.registry import get_agent

    adapter = get_agent("claude-code")
    out = adapter.format_hook_output(
        _event(adapter, "session_stop"),
        HookDecision(verdict=Verdict.BLOCK, reason="goal unverified"),
    )
    assert out.exit_code == 0
    assert out.stdout is not None
    assert json.loads(out.stdout) == {"decision": "block", "reason": "goal unverified"}


def test_additional_context_is_nested_under_the_native_event_name() -> None:
    import json

    from lazy_harness.agents.base import HookDecision
    from lazy_harness.agents.registry import get_agent

    adapter = get_agent("claude-code")
    out = adapter.format_hook_output(
        _event(adapter, "session_start"), HookDecision(additional_context="ctx")
    )
    assert out.stdout is not None
    assert json.loads(out.stdout) == {
        "hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": "ctx"}
    }


def test_system_message_stays_at_the_top_level() -> None:
    """Nested, it parses without error and is discarded — the bug four builtins
    shipped, fixed one at a time between v0.58.0 and the systemMessage sweep."""
    import json

    from lazy_harness.agents.base import HookDecision
    from lazy_harness.agents.registry import get_agent

    adapter = get_agent("claude-code")
    out = adapter.format_hook_output(_event(adapter), HookDecision(system_message="warn"))
    assert out.stdout is not None
    assert json.loads(out.stdout) == {"systemMessage": "warn"}


def test_refusing_a_verdict_the_agent_does_not_honour_raises() -> None:
    """Never reached at runtime — deploy refuses the configuration first. But a
    runner that raises here must not be the thing that silently allows."""
    from lazy_harness.agents.base import HookDecision, Verdict
    from lazy_harness.agents.registry import get_agent

    adapter = get_agent("claude-code")
    with pytest.raises(ValueError, match="session_start"):
        adapter.format_hook_output(
            _event(adapter, "session_start"), HookDecision(verdict=Verdict.DENY)
        )


def test_stop_reason_yields_to_a_block_reason() -> None:
    """`decision.reason` already carries the block's reason; repeating it under
    `stopReason` would emit the same text twice under two different keys."""
    import json

    from lazy_harness.agents.base import HookDecision, Verdict
    from lazy_harness.agents.registry import get_agent

    adapter = get_agent("claude-code")
    out = adapter.format_hook_output(
        _event(adapter, "session_stop"),
        HookDecision(verdict=Verdict.BLOCK, reason="goal unverified", stop=True),
    )
    assert out.stdout is not None
    body = json.loads(out.stdout)
    assert body["reason"] == "goal unverified"
    assert body["continue"] is False
    assert "stopReason" not in body


def test_stop_and_suppress_output_travel_beside_no_verdict() -> None:
    import json

    from lazy_harness.agents.base import HookDecision
    from lazy_harness.agents.registry import get_agent

    adapter = get_agent("claude-code")
    out = adapter.format_hook_output(
        _event(adapter), HookDecision(stop=True, suppress_output=True, reason="done")
    )
    assert out.stdout is not None
    body = json.loads(out.stdout)
    assert body["continue"] is False
    assert body["suppressOutput"] is True
    assert body["stopReason"] == "done"


# --- ClaudeCodeAdapter: the PreCompact text channel -----------------------


def _hook_event_names() -> tuple[str, ...]:
    """Canonical event names the Claude Code adapter declares.

    Read from `_HOOK_EVENTS` rather than listed here: a static copy of a table
    is the kind of second answer that drifts from the first one silently.
    """
    from lazy_harness.agents.claude_code import _HOOK_EVENTS

    return tuple(_HOOK_EVENTS)


def test_pre_compact_additional_context_serialises_as_plain_text() -> None:
    """PreCompact has no `hookSpecificOutput` variant; JSON there is discarded.

    Recorded against the 2.1.234 binary in `pre_compact.py` and in ADR-036's
    Context (the union enumeration; D2 is the decision that follows from it):
    a JSON payload fails schema validation, which marks the hook failed and
    drops its output. The executor joins each *successful* hook's raw stdout
    into `newCustomInstructions`, so the summary arrives as the bytes the hook
    wrote or it does not arrive at all.

    Asserted on the bytes rather than on a mapping, because a mapping here
    parses cleanly and displays nothing -- the failure this guards is silent.
    """
    from lazy_harness.agents.base import HookDecision
    from lazy_harness.agents.registry import get_agent

    adapter = get_agent("claude-code")
    out = adapter.format_hook_output(
        _event(adapter, "pre_compact"), HookDecision(additional_context="Preserve X")
    )
    assert out.stdout == "Preserve X\n"
    assert "hookSpecificOutput" not in (out.stdout or "")
    assert out.stderr == ""
    assert out.exit_code == 0


def test_pre_compact_abstention_emits_nothing() -> None:
    """An empty summary is silence, not an empty line.

    `pre_compact.py` only prints when it extracted something; a hook that
    found nothing must not put a bare newline into `newCustomInstructions`.
    """
    from lazy_harness.agents.base import HookDecision
    from lazy_harness.agents.registry import get_agent

    adapter = get_agent("claude-code")
    out = adapter.format_hook_output(_event(adapter, "pre_compact"), HookDecision())
    assert out.stdout is None
    assert out.exit_code == 0


def test_pre_compact_refuses_the_channels_plain_text_cannot_carry() -> None:
    """Naming the narrowing beats dropping it.

    The JSON path carries `system_message`, `stop` and `suppress_output`; raw
    text carries none of them. Returning early while silently discarding all
    three is the same silent-dropout class the migration exists to close, so
    the branch refuses and says which channel it could not express.

    Asserted against `format_hook_output` directly, never through `run_hook`:
    the runner's blanket handler turns any exception from a non-blocking hook
    into exit 0 with the reason on stderr, and Claude Code does not surface a
    successful hook's stderr. At runtime this refusal degrades to a lost
    summary rather than a visible error -- which is why the test has to sit
    here, where the raise is still observable.
    """
    from lazy_harness.agents.base import HookDecision
    from lazy_harness.agents.registry import get_agent

    adapter = get_agent("claude-code")
    for decision, named in (
        (HookDecision(system_message="warn"), "system_message"),
        (HookDecision(stop=True), "stop"),
        (HookDecision(suppress_output=True), "suppress_output"),
    ):
        with pytest.raises(ValueError, match=named):
            adapter.format_hook_output(_event(adapter, "pre_compact"), decision)


def test_pre_compact_names_every_channel_it_cannot_carry_not_just_the_first() -> None:
    """A decision setting three unsupported channels is told about three."""
    from lazy_harness.agents.base import HookDecision
    from lazy_harness.agents.registry import get_agent

    adapter = get_agent("claude-code")
    with pytest.raises(ValueError) as excinfo:
        adapter.format_hook_output(
            _event(adapter, "pre_compact"),
            HookDecision(system_message="warn", stop=True, suppress_output=True),
        )
    message = str(excinfo.value)
    assert "system_message" in message
    assert "stop" in message
    assert "suppress_output" in message


def test_a_verdict_on_pre_compact_is_still_refused() -> None:
    """The text branch sits *below* the verdict check, and that order is load-bearing.

    `_HOOK_EVENTS["pre_compact"]` declares no verdicts, so the check at the top
    of the method refuses every one of them -- which is why the branch does not
    repeat it. Hoisting the branch above that check would return the summary
    with a zero exit and drop the verdict in silence, so the ordering needs a
    test of its own rather than an argument in a commit message.
    """
    from lazy_harness.agents.base import HookDecision, Verdict
    from lazy_harness.agents.registry import get_agent

    adapter = get_agent("claude-code")
    for verdict in Verdict:
        with pytest.raises(ValueError, match="does not honour"):
            adapter.format_hook_output(
                _event(adapter, "pre_compact"),
                HookDecision(verdict=verdict, additional_context="Preserve X"),
            )


def test_pre_compact_emits_no_stderr_even_when_a_reason_is_set() -> None:
    """Raw text has no second channel; `reason` belongs to a verdict it cannot carry."""
    from lazy_harness.agents.base import HookDecision
    from lazy_harness.agents.registry import get_agent

    adapter = get_agent("claude-code")
    out = adapter.format_hook_output(
        _event(adapter, "pre_compact"),
        HookDecision(additional_context="Preserve X", reason="ignored here"),
    )
    assert out.stdout == "Preserve X\n"
    assert out.stderr == ""
    assert out.exit_code == 0


@pytest.mark.parametrize(
    "event_name",
    sorted(name for name in _hook_event_names() if name != "pre_compact"),
)
def test_every_other_event_still_serialises_additional_context_as_json(
    event_name: str,
) -> None:
    """The narrowing is PreCompact's alone, not a change to the channel.

    Parametrised over the adapter's own event table rather than one sample
    event: asserting this against `session_start` alone lets the branch be
    widened to any of the other nine without a test noticing.
    """
    import json

    from lazy_harness.agents.base import HookDecision
    from lazy_harness.agents.registry import get_agent

    adapter = get_agent("claude-code")
    out = adapter.format_hook_output(
        _event(adapter, event_name), HookDecision(additional_context="ctx")
    )
    assert out.stdout is not None
    assert json.loads(out.stdout)["hookSpecificOutput"]["additionalContext"] == "ctx"


# --- corrections found in review -----------------------------------------


def test_an_absent_new_string_is_a_deletion_not_the_text_None() -> None:
    """`pre_tool_use_memory_size` projects the post-edit size by applying the
    replacement. `str(None)` would project the four characters "None" into the
    file and flip the breach verdict."""
    from lazy_harness.agents.registry import get_agent

    event = get_agent("claude-code").parse_hook_input(
        "pre_tool_use",
        {
            "session_id": "s",
            "cwd": "/r",
            "tool_name": "Edit",
            "tool_input": {"file_path": "/r/MEMORY.md", "old_string": "x"},
        },
        profile="lazy",
    )
    assert event.tool is not None
    assert event.tool.edits[0].replacements == (("x", ""),), "missing new_string deletes"


def test_a_write_is_not_claimed_to_be_a_create() -> None:
    """Claude Code's `Write` creates *or* overwrites, and the payload does not
    say which. Claiming `is_create` would make an overwrite of an existing
    MEMORY.md read as a new file to any guard that asks."""
    from lazy_harness.agents.registry import get_agent

    event = get_agent("claude-code").parse_hook_input(
        "pre_tool_use",
        {
            "session_id": "s",
            "cwd": "/r",
            "tool_name": "Write",
            "tool_input": {"file_path": "/r/exists.py", "content": "x"},
        },
        profile="lazy",
    )
    assert event.tool is not None
    assert event.tool.edits[0].is_create is False
    assert event.tool.edits[0].content == "x", "the full replacement text is what is actionable"


def test_a_denial_still_carries_the_channels_beside_it() -> None:
    """Claude Code reads valid JSON on stdout whether or not the hook exits 2.
    Returning early on DENY drops a system message the agent would have shown."""
    import json

    from lazy_harness.agents.base import HookDecision, Verdict
    from lazy_harness.agents.registry import get_agent

    adapter = get_agent("claude-code")
    out = adapter.format_hook_output(
        _event(adapter),
        HookDecision(verdict=Verdict.DENY, reason="refused", system_message="warn"),
    )
    assert out.exit_code == 2
    assert out.stderr == "refused", "the reason the user reads still travels on stderr"
    assert out.stdout is not None
    assert json.loads(out.stdout) == {"systemMessage": "warn"}


def test_a_bare_denial_still_emits_no_stdout() -> None:
    """The shape `pre_tool_use_security` ships today, unchanged."""
    from lazy_harness.agents.base import HookDecision, Verdict
    from lazy_harness.agents.registry import get_agent

    adapter = get_agent("claude-code")
    out = adapter.format_hook_output(
        _event(adapter), HookDecision(verdict=Verdict.DENY, reason="refused")
    )
    assert out.stdout is None

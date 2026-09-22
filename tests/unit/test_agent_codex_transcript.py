"""Codex's `TranscriptReader` — the rollout format, as measured.

Companion to `test_agent_transcript.py`, which pins the *seam*; this file pins
one provider's dialect against it. Every fixture here is synthetic and rebuilt
from the shape recorded in `specs/designs/codex-evidence.md` §5 (`[log]`,
`codex-cli 0.154.0`) — no rollout line from a real session is reproduced, and
none of the assertions depend on one.

The three claims this file exists to hold:

* `signals()` is **narrower than Claude Code's**. Codex 0.154.0 has no explicit
  goal marker anywhere in its rollout, so `GOAL_STATUS` is refused. Decision 11
  of `specs/designs/2026-09-13-multi-agent-harness-design.md` exists to stop the
  opposite — a reader that over-declares re-enables `stop-verify-guard` on an
  agent where it would find nothing and pass.
* A rollout records several things **twice**, at two layers: the model's own
  `response_item` stream and the UI's `event_msg` stream. Only one of the two is
  read per signal, so a consumer counting turns or summing tokens is not
  double-counting (ADR-048).
* The `exec` tool's argument is a program for Codex's cell runtime, not a shell
  command, so it never lands on `ToolCall.command` (ADR-048).
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

_TS = "2026-09-16T12:02:13.926Z"


def _lines(*entries: object) -> str:
    return "".join(json.dumps(e) + "\n" for e in entries)


def _reader():
    from lazy_harness.agents.codex import CodexAdapter

    return CodexAdapter()


def _entry(kind: str, payload: object, *, timestamp: str | None = _TS, ordinal: int = 0) -> dict:
    """The envelope every rollout line carries, with one payload in it."""
    return {"timestamp": timestamp, "type": kind, "payload": payload, "ordinal": ordinal}


def _message(role: str, *texts: str, block: str = "output_text") -> dict:
    return _entry(
        "response_item",
        {
            "type": "message",
            "id": "msg_1",
            "role": role,
            "content": [{"type": block, "text": text} for text in texts],
        },
    )


def _exec_call(program: str, *, call_id: str = "call_1") -> dict:
    return _entry(
        "response_item",
        {
            "type": "custom_tool_call",
            "id": "ctc_1",
            "call_id": call_id,
            "name": "exec",
            "input": program,
            "status": "completed",
        },
    )


def _usage_record(*, response_id: str = "resp_1", **counters: object) -> dict:
    return _entry(
        "token_usage_record",
        {
            "session_id": "sess",
            "turn_id": "turn",
            "response_id": response_id,
            "usage": dict(counters),
            "turn_token_usage": dict(counters),
            "thread_token_usage": dict(counters),
        },
    )


def _turn_context(model: str = "gpt-5-codex") -> dict:
    """The shape evidence §5.3 records, reduced to the keys the reader names."""
    return _entry(
        "turn_context",
        {
            "cwd": "/w",
            "model": model,
            "approval_policy": "on-request",
            "sandbox_policy": {"mode": "workspace-write"},
            "turn_id": "turn",
        },
    )


def _write(tmp_path: Path, *entries: object, name: str = "rollout.jsonl") -> Path:
    path = tmp_path / name
    path.write_text(_lines(*entries))
    return path


def _read(path: Path) -> list:
    return list(_reader().read(path))


def _by_signal(path: Path, signal) -> list:
    return [e for e in _read(path) if e.signal is signal]


# --- the Protocol, and the signal it refuses --------------------------------


def test_codex_satisfies_the_reader_protocol() -> None:
    from lazy_harness.agents.base import TranscriptReader

    assert isinstance(_reader(), TranscriptReader)


def test_codex_declares_three_signals_and_refuses_goal_status() -> None:
    """The refusal is the point: Codex 0.154.0 has no `/goal` and no marker.

    `stop-verify-guard` declares `GOAL_STATUS`; a reader claiming it here would
    have the guard deployed, read a transcript that cannot carry the marker, and
    pass every time — the silent approval decision 11 was written against.
    """
    from lazy_harness.agents.base import Signal

    assert _reader().signals() == {Signal.MESSAGES, Signal.TOOL_CALLS, Signal.TOKEN_USAGE}


def test_no_rollout_kind_yields_a_goal_status_event(tmp_path: Path) -> None:
    from lazy_harness.agents.base import Signal

    path = _write(
        tmp_path,
        _message("user", "start"),
        _exec_call("const x = 1;\nawait x;"),
        _usage_record(input_tokens=1, output_tokens=2),
        _entry("event_msg", {"type": "task_complete", "turn_id": "t"}),
    )

    assert _by_signal(path, Signal.GOAL_STATUS) == []


# --- MESSAGES ---------------------------------------------------------------


def test_a_user_turn_yields_a_message_event_with_role_and_text(tmp_path: Path) -> None:
    from lazy_harness.agents.base import Signal

    path = _write(tmp_path, _message("user", "ship it", block="input_text"))

    (event,) = _by_signal(path, Signal.MESSAGES)
    assert event.role == "user"
    assert event.text == "ship it"


def test_assistant_text_blocks_are_joined_into_one_message_event(tmp_path: Path) -> None:
    from lazy_harness.agents.base import Signal

    path = _write(tmp_path, _message("assistant", "first", "second"))

    (event,) = _by_signal(path, Signal.MESSAGES)
    assert event.text == "first\nsecond"


def test_a_developer_turn_is_not_a_message(tmp_path: Path) -> None:
    """`developer` is Codex's instruction channel, not a turn anyone took.

    It carries the composed `AGENTS.md` / config instructions. `session_export`
    labels anything that is not `user` as the model speaking, so emitting it
    would export the profile's own instruction text as conversation.
    """
    from lazy_harness.agents.base import Signal

    path = _write(tmp_path, _message("developer", "instructions", block="input_text"))

    assert _by_signal(path, Signal.MESSAGES) == []


def test_a_turn_with_no_text_blocks_yields_no_message_event(tmp_path: Path) -> None:
    from lazy_harness.agents.base import Signal

    path = _write(
        tmp_path,
        _entry("response_item", {"type": "message", "role": "assistant", "content": []}),
    )

    assert _by_signal(path, Signal.MESSAGES) == []


def test_a_turn_carries_the_envelope_timestamp(tmp_path: Path) -> None:
    """The time is on the envelope, not in the payload — and it ends in `Z`."""
    from datetime import UTC

    from lazy_harness.agents.base import Signal

    path = _write(tmp_path, _message("user", "x", block="input_text"))

    (event,) = _by_signal(path, Signal.MESSAGES)
    assert event.timestamp is not None
    assert event.timestamp.tzinfo is not None
    assert event.timestamp.astimezone(UTC).hour == 12


def test_an_unparseable_timestamp_arrives_as_none_rather_than_raising(tmp_path: Path) -> None:
    from lazy_harness.agents.base import Signal

    path = _write(
        tmp_path,
        _entry(
            "response_item",
            {"type": "message", "role": "user", "content": [{"type": "input_text", "text": "x"}]},
            timestamp="yesterday",
        ),
    )

    (event,) = _by_signal(path, Signal.MESSAGES)
    assert event.timestamp is None


def test_the_ui_copy_of_a_turn_is_not_a_second_message(tmp_path: Path) -> None:
    """`event_msg/item_completed` repeats the turn the `response_item` stream
    already carried. Reading both would double every count (ADR-048)."""
    from lazy_harness.agents.base import Signal

    path = _write(
        tmp_path,
        _message("assistant", "done"),
        _entry(
            "event_msg",
            {
                "type": "item_completed",
                "turn_id": "t",
                "item": {
                    "type": "AgentMessage",
                    "id": "item_1",
                    "content": [{"type": "output_text", "text": "done"}],
                },
            },
        ),
    )

    assert [e.text for e in _by_signal(path, Signal.MESSAGES)] == ["done"]


# --- TOOL_CALLS -------------------------------------------------------------


def test_a_custom_tool_call_yields_a_normalised_tool_call(tmp_path: Path) -> None:
    from lazy_harness.agents.base import Signal

    path = _write(tmp_path, _exec_call("await run();"))

    (event,) = _by_signal(path, Signal.TOOL_CALLS)
    assert event.tool is not None
    assert event.tool.native_name == "exec"


def test_the_call_id_travels_as_the_tool_use_id(tmp_path: Path) -> None:
    from lazy_harness.agents.base import Signal

    path = _write(tmp_path, _exec_call("await run();", call_id="call_abc"))

    (event,) = _by_signal(path, Signal.TOOL_CALLS)
    assert event.tool_use_id == "call_abc"


def test_the_exec_program_never_lands_on_the_command_field(tmp_path: Path) -> None:
    """`exec`'s argument is a program for Codex's cell runtime, not shell text.

    Two builtins scan `tool.command` for shell syntax. A TypeScript program in
    that field puts the model's source in front of a command denylist — the
    same failure `_parse_tool` already refuses for a patch blob.
    """
    from lazy_harness.agents.base import Signal

    path = _write(tmp_path, _exec_call("const out = await sh('rm -rf /');"))

    (event,) = _by_signal(path, Signal.TOOL_CALLS)
    assert event.tool is not None
    assert event.tool.command is None
    assert event.tool.operation is None


def test_the_exec_program_stays_reachable_as_raw_input(tmp_path: Path) -> None:
    from lazy_harness.agents.base import Signal

    path = _write(tmp_path, _exec_call("await run();"))

    (event,) = _by_signal(path, Signal.TOOL_CALLS)
    assert event.tool is not None
    assert event.tool.raw_input == {"input": "await run();"}


def test_a_function_call_yields_its_parsed_arguments(tmp_path: Path) -> None:
    from lazy_harness.agents.base import Signal

    path = _write(
        tmp_path,
        _entry(
            "response_item",
            {
                "type": "function_call",
                "call_id": "call_2",
                "name": "wait",
                "arguments": json.dumps({"cell_id": "c1", "yield_time_ms": 500}),
            },
        ),
    )

    (event,) = _by_signal(path, Signal.TOOL_CALLS)
    assert event.tool is not None
    assert event.tool.native_name == "wait"
    assert event.tool.raw_input == {"cell_id": "c1", "yield_time_ms": 500}


def test_function_call_arguments_that_are_not_json_degrade_to_empty(tmp_path: Path) -> None:
    from lazy_harness.agents.base import Signal

    path = _write(
        tmp_path,
        _entry(
            "response_item",
            {"type": "function_call", "call_id": "c", "name": "wait", "arguments": "{oops"},
        ),
    )

    (event,) = _by_signal(path, Signal.TOOL_CALLS)
    assert event.tool is not None
    assert event.tool.raw_input == {}


def test_a_tool_call_without_a_name_is_skipped(tmp_path: Path) -> None:
    from lazy_harness.agents.base import Signal

    path = _write(
        tmp_path,
        _entry("response_item", {"type": "custom_tool_call", "call_id": "c", "input": "x"}),
    )

    assert _by_signal(path, Signal.TOOL_CALLS) == []


def test_the_executed_command_record_is_not_a_second_tool_call(tmp_path: Path) -> None:
    """`item_completed/CommandExecution` is the UI's record of what the program
    ran. It has no call id and no tool name; pairing it with the `exec` call it
    came from would count one tool call twice (ADR-048)."""
    from lazy_harness.agents.base import Signal

    path = _write(
        tmp_path,
        _exec_call("await run();"),
        _entry(
            "event_msg",
            {
                "type": "item_completed",
                "item": {
                    "type": "CommandExecution",
                    "id": "item_1",
                    "command": ["/bin/zsh", "-lc", "ls"],
                    "exit_code": 0,
                    "status": "completed",
                    "source": "unified_exec_startup",
                },
            },
        ),
    )

    assert len(_by_signal(path, Signal.TOOL_CALLS)) == 1


# --- TOKEN_USAGE ------------------------------------------------------------


def test_a_usage_record_yields_the_four_counters(tmp_path: Path) -> None:
    """Counters from a record shaped like the ones the provider actually writes.

    The numbers below are a measured record: `total_tokens` is
    `input_tokens + output_tokens`, and `cached_input_tokens` is a subset of
    `input_tokens` rather than a sibling. `cache_write_input_tokens` is the one
    field the corpus never exercised — 0 on all 5893 records — so a non-zero
    value here only pins that the key is read, not a shape it was seen in.
    """
    from lazy_harness.agents.base import Signal

    path = _write(
        tmp_path,
        _usage_record(
            input_tokens=21512,
            output_tokens=433,
            cached_input_tokens=11008,
            cache_write_input_tokens=44,
            reasoning_output_tokens=116,
            total_tokens=21945,
        ),
    )

    (event,) = _by_signal(path, Signal.TOKEN_USAGE)
    assert event.usage is not None
    # ADR-066: the field is the input charged at full rate, so the cached
    # half the provider folded into its own `input_tokens` comes back out.
    assert event.usage.input_tokens == 21512 - 11008
    assert event.usage.output_tokens == 433
    assert event.usage.cache_read_tokens == 11008
    assert event.usage.cache_creation_tokens == 44


def test_a_cached_half_larger_than_the_input_clamps_at_zero(tmp_path: Path) -> None:
    """Never seen in 5893 records; a negative charged input would be worse."""
    from lazy_harness.agents.base import Signal

    path = _write(
        tmp_path,
        _usage_record(input_tokens=10, output_tokens=5, cached_input_tokens=99),
    )

    (event,) = _by_signal(path, Signal.TOKEN_USAGE)
    assert event.usage is not None
    assert event.usage.input_tokens == 0
    assert event.usage.cache_read_tokens == 99


def test_shipped_codex_fixtures_satisfy_the_inclusive_input_invariant() -> None:
    """The premise ADR-066's subtraction rests on, asserted not assumed.

    If a future Codex release reports input exclusive of cache, this fails
    rather than letting the adapter quietly under-count instead of over.
    """
    import json

    paths = sorted(Path("specs/gates/fixtures/codex-pricing").glob("*.jsonl"))
    assert paths, "no codex pricing fixtures to check"
    checked = 0
    for path in paths:
        for line in path.read_text().splitlines():
            usage = (json.loads(line).get("payload") or {}).get("info", {})
            usage = usage.get("last_token_usage") if isinstance(usage, dict) else None
            if not isinstance(usage, dict):
                continue
            checked += 1
            assert usage["cached_input_tokens"] <= usage["input_tokens"]
            assert usage["total_tokens"] == usage["input_tokens"] + usage["output_tokens"]
    assert checked


def test_a_counter_the_record_omitted_is_none_and_not_zero(tmp_path: Path) -> None:
    from lazy_harness.agents.base import Signal

    path = _write(tmp_path, _usage_record(input_tokens=0, output_tokens=7))

    (event,) = _by_signal(path, Signal.TOKEN_USAGE)
    assert event.usage is not None
    assert event.usage.input_tokens == 0
    assert event.usage.cache_read_tokens is None


def test_a_usage_object_of_the_wrong_type_yields_no_token_event(tmp_path: Path) -> None:
    from lazy_harness.agents.base import Signal

    path = _write(tmp_path, _entry("token_usage_record", {"usage": "lots"}))

    assert _by_signal(path, Signal.TOKEN_USAGE) == []


def test_the_ui_token_count_event_is_not_a_second_usage_record(tmp_path: Path) -> None:
    """`event_msg/token_count` restates the same turn's accounting, plus rate
    limits. Reading both would double every sum (ADR-048)."""
    from lazy_harness.agents.base import Signal

    path = _write(
        tmp_path,
        _usage_record(input_tokens=11, output_tokens=22),
        _entry(
            "event_msg",
            {
                "type": "token_count",
                "info": {
                    "last_token_usage": {"input_tokens": 11, "output_tokens": 22},
                    "total_token_usage": {"input_tokens": 11, "output_tokens": 22},
                    "model_context_window": 400000,
                },
            },
        ),
    )

    assert len(_by_signal(path, Signal.TOKEN_USAGE)) == 1


# --- the model, which no usage record carries ------------------------------
#
# `turn_context` is the only kind in the rollout that names the model, and it
# is a different line from the one that reports the tokens. This is the single
# place a Codex event depends on a line the reader has already passed.


def test_the_model_comes_from_the_preceding_turn_context(tmp_path: Path) -> None:
    from lazy_harness.agents.base import Signal

    path = _write(tmp_path, _turn_context("gpt-5-codex"), _usage_record(input_tokens=11))

    (event,) = _by_signal(path, Signal.TOKEN_USAGE)
    assert event.model == "gpt-5-codex"


def test_one_turn_context_names_the_model_for_every_record_after_it(
    tmp_path: Path,
) -> None:
    """Measured: 23 `turn_context` lines to 176 usage records, 1 model per file."""
    from lazy_harness.agents.base import Signal

    path = _write(
        tmp_path,
        _turn_context("gpt-5-codex"),
        _usage_record(response_id="r1", input_tokens=1),
        _usage_record(response_id="r2", input_tokens=2),
        _usage_record(response_id="r3", input_tokens=3),
    )

    assert [e.model for e in _by_signal(path, Signal.TOKEN_USAGE)] == ["gpt-5-codex"] * 3


def test_a_later_turn_context_replaces_the_model_for_what_follows_it(
    tmp_path: Path,
) -> None:
    from lazy_harness.agents.base import Signal

    path = _write(
        tmp_path,
        _turn_context("gpt-5-codex"),
        _usage_record(response_id="r1", input_tokens=1),
        _turn_context("gpt-5-codex-mini"),
        _usage_record(response_id="r2", input_tokens=2),
    )

    assert [e.model for e in _by_signal(path, Signal.TOKEN_USAGE)] == [
        "gpt-5-codex",
        "gpt-5-codex-mini",
    ]


def test_a_usage_record_before_any_turn_context_names_no_model(tmp_path: Path) -> None:
    """`None`, never a placeholder. Measured at 0 occurrences in 15 rollouts, but
    a truncated or rotated file is exactly where it would appear, and metering
    keeps "no model disclosed" apart from a model literally named `unknown`."""
    from lazy_harness.agents.base import Signal

    path = _write(tmp_path, _usage_record(input_tokens=11))

    (event,) = _by_signal(path, Signal.TOKEN_USAGE)
    assert event.model is None


def test_a_turn_context_yields_no_event_of_its_own(tmp_path: Path) -> None:
    """It is read for one field, not delivered: no signal is defined over it."""
    path = _write(tmp_path, _turn_context("gpt-5-codex"))

    assert _read(path) == []


def test_the_carried_model_does_not_leak_from_one_rollout_into_the_next(
    tmp_path: Path,
) -> None:
    """One adapter instance serves every profile — `registry.py` builds a bare
    `cls()` — so carrying the model on `self` would bill one session's tokens
    to the model another session declared. The state belongs to the read."""
    from lazy_harness.agents.base import Signal

    reader = _reader()
    named = _write(
        tmp_path, _turn_context("gpt-5-codex"), _usage_record(input_tokens=1), name="a.jsonl"
    )
    silent = _write(tmp_path, _usage_record(input_tokens=2), name="b.jsonl")

    first = [e for e in reader.read(named) if e.signal is Signal.TOKEN_USAGE]
    second = [e for e in reader.read(silent) if e.signal is Signal.TOKEN_USAGE]

    assert [e.model for e in first] == ["gpt-5-codex"]
    assert [e.model for e in second] == [None]


def test_two_interleaved_reads_do_not_share_a_carried_model(tmp_path: Path) -> None:
    """`read()` is a generator and hooks hold them open; two live at once."""
    from lazy_harness.agents.base import Signal

    reader = _reader()
    named = _write(
        tmp_path, _turn_context("gpt-5-codex"), _usage_record(input_tokens=1), name="a.jsonl"
    )
    silent = _write(tmp_path, _usage_record(input_tokens=2), name="b.jsonl")

    a, b = reader.read(named), reader.read(silent)
    from_a = next(e for e in a if e.signal is Signal.TOKEN_USAGE)
    from_b = next(e for e in b if e.signal is Signal.TOKEN_USAGE)

    assert (from_a.model, from_b.model) == ("gpt-5-codex", None)


def test_messages_and_tool_calls_carry_the_model_too(tmp_path: Path) -> None:
    """The model that produced a turn produced the tool calls in it."""
    from lazy_harness.agents.base import Signal

    path = _write(
        tmp_path,
        _turn_context("gpt-5-codex"),
        _message("assistant", "hi"),
        _exec_call("await run()"),
    )

    events = [e for e in _read(path) if e.signal in (Signal.MESSAGES, Signal.TOOL_CALLS)]
    assert events
    assert all(e.model == "gpt-5-codex" for e in events)


# --- the message id, for dedup ----------------------------------------------


def test_a_usage_record_carries_its_response_id_as_the_message_id(
    tmp_path: Path,
) -> None:
    """Measured: `response_id` is a string on 176/176 records and globally unique
    across all 15 rollouts, which is what a dedup key has to be."""
    from lazy_harness.agents.base import Signal

    path = _write(tmp_path, _turn_context(), _usage_record(response_id="resp_7", input_tokens=1))

    (event,) = _by_signal(path, Signal.TOKEN_USAGE)
    assert event.message_id == "resp_7"


def test_a_usage_record_without_a_response_id_carries_no_message_id(
    tmp_path: Path,
) -> None:
    from lazy_harness.agents.base import Signal

    path = _write(tmp_path, _entry("token_usage_record", {"usage": {"input_tokens": 1}}))

    (event,) = _by_signal(path, Signal.TOKEN_USAGE)
    assert event.message_id is None


def test_the_message_id_is_not_the_turn_id(tmp_path: Path) -> None:
    """Measured: 176 records share 21 `turn_id`s. Deduping on it would drop
    every usage record in a turn but the first."""
    from lazy_harness.agents.base import Signal

    path = _write(
        tmp_path,
        _turn_context(),
        _usage_record(response_id="r1", input_tokens=1),
        _usage_record(response_id="r2", input_tokens=2),
    )

    events = _by_signal(path, Signal.TOKEN_USAGE)
    assert len({e.message_id for e in events}) == 2


# --- malformed input degrades, it never raises ------------------------------


def test_a_corrupt_line_in_the_middle_does_not_lose_the_rest(tmp_path: Path) -> None:
    from lazy_harness.agents.base import Signal

    path = tmp_path / "rollout.jsonl"
    path.write_text(
        _lines(_message("user", "first", block="input_text"))
        + "{not json\n"
        + _lines(_message("user", "second", block="input_text"))
    )

    assert [e.text for e in _by_signal(path, Signal.MESSAGES)] == ["first", "second"]


def test_a_transcript_truncated_mid_line_keeps_every_complete_line(tmp_path: Path) -> None:
    path = tmp_path / "rollout.jsonl"
    path.write_text(_lines(_message("user", "kept", block="input_text")) + '{"type": "respon')

    assert len(_read(path)) == 1


@pytest.mark.parametrize("line", ["[1, 2]", '"a string"', "null", "7"])
def test_a_line_that_is_not_a_json_object_is_skipped(tmp_path: Path, line: str) -> None:
    path = tmp_path / "rollout.jsonl"
    path.write_text(f"{line}\n" + _lines(_message("user", "kept", block="input_text")))

    assert len(_read(path)) == 1


def test_undecodable_bytes_do_not_abort_the_rest_of_the_transcript(tmp_path: Path) -> None:
    path = tmp_path / "rollout.jsonl"
    path.write_bytes(
        b"\xff\xfe not json\n" + _lines(_message("user", "kept", block="input_text")).encode()
    )

    assert len(_read(path)) == 1


def test_an_entry_of_an_unknown_top_level_type_yields_nothing(tmp_path: Path) -> None:
    path = _write(tmp_path, _entry("world_state", {"full": True, "state": {}}))

    assert _read(path) == []


def test_a_response_item_of_an_unknown_kind_yields_nothing(tmp_path: Path) -> None:
    path = _write(tmp_path, _entry("response_item", {"type": "reasoning", "summary": []}))

    assert _read(path) == []


@pytest.mark.parametrize("kind", [[], {}, 7, None])
def test_an_unhashable_or_untyped_entry_is_skipped_and_the_rest_arrives(
    tmp_path: Path, kind: object
) -> None:
    path = tmp_path / "rollout.jsonl"
    path.write_text(
        _lines(_entry(kind, {"type": "message"}))  # type: ignore[arg-type]
        + _lines(_message("user", "kept", block="input_text"))
    )

    assert len(_read(path)) == 1


def test_a_payload_that_is_not_an_object_is_skipped(tmp_path: Path) -> None:
    path = tmp_path / "rollout.jsonl"
    path.write_text(
        _lines(_entry("response_item", "not a payload"))
        + _lines(_message("user", "kept", block="input_text"))
    )

    assert len(_read(path)) == 1


def test_a_missing_transcript_yields_nothing_instead_of_raising(tmp_path: Path) -> None:
    assert _read(tmp_path / "absent.jsonl") == []


def test_a_directory_where_a_transcript_was_expected_yields_nothing(tmp_path: Path) -> None:
    (tmp_path / "rollout.jsonl").mkdir()

    assert _read(tmp_path / "rollout.jsonl") == []


def test_an_empty_transcript_yields_nothing(tmp_path: Path) -> None:
    path = tmp_path / "rollout.jsonl"
    path.write_text("\n\n")

    assert _read(path) == []


def test_the_file_is_opened_at_iteration_and_not_at_the_call(tmp_path: Path) -> None:
    """A hook builds its reader when it starts and judges when it decides."""
    path = tmp_path / "rollout.jsonl"

    stream = _reader().read(path)
    _write(tmp_path, _message("user", "written later", block="input_text"))

    assert len(list(stream)) == 1


# --- the mixed file: one session, every kind, in order ----------------------


def test_a_mixed_rollout_yields_every_signal_in_file_order(tmp_path: Path) -> None:
    from lazy_harness.agents.base import Signal

    path = _write(
        tmp_path,
        _entry("session_meta", {"id": "s", "cli_version": "0.154.0", "source": "cli"}),
        _entry("turn_context", {"cwd": "/w", "model": "m"}),
        _message("developer", "instructions", block="input_text"),
        _message("user", "do the thing", block="input_text"),
        _entry("event_msg", {"type": "task_started", "turn_id": "t"}),
        _entry("response_item", {"type": "reasoning", "summary": []}),
        _exec_call("await run();"),
        _entry(
            "response_item",
            {"type": "custom_tool_call_output", "call_id": "call_1", "output": "ok"},
        ),
        _message("assistant", "done"),
        _usage_record(input_tokens=1, output_tokens=2),
        _entry("event_msg", {"type": "token_count", "info": {}}),
        _entry("event_msg", {"type": "task_complete", "turn_id": "t"}),
        _entry("world_state", {"full": True, "state": {}}),
    )

    assert [e.signal for e in _read(path)] == [
        Signal.MESSAGES,
        Signal.TOOL_CALLS,
        Signal.MESSAGES,
        Signal.TOKEN_USAGE,
    ]


# --- locate_sessions --------------------------------------------------------


def _rollout(config_dir: Path, day: str, stamp: str, *, age_days: float = 0.0) -> Path:
    import time

    path = config_dir / "sessions" / day / f"rollout-{stamp}-01a0aa18-758d-7ef0-a579-fdb.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_lines(_message("user", "x", block="input_text")))
    if age_days:
        when = time.time() - age_days * 86400
        os.utime(path, (when, when))
    return path


def test_locate_sessions_walks_the_day_directories(tmp_path: Path) -> None:
    first = _rollout(tmp_path, "2026/09/15", "2026-09-15T11-05-21")
    second = _rollout(tmp_path, "2026/09/16", "2026-09-16T09-02-04")

    assert sorted(_reader().locate_sessions(tmp_path, None)) == sorted([first, second])


def test_locate_sessions_takes_the_config_dir_as_a_parameter(tmp_path: Path) -> None:
    first = _rollout(tmp_path / "cx", "2026/09/16", "2026-09-16T09-02-04")
    _rollout(tmp_path / "other", "2026/09/16", "2026-09-16T10-31-07")

    assert list(_reader().locate_sessions(tmp_path / "cx", None)) == [first]


def test_locate_sessions_filters_by_modification_time_when_since_is_given(
    tmp_path: Path,
) -> None:
    """Modification time, not the timestamp in the name.

    The name carries the session's *start*, in local wall-clock with no offset
    (ADR-048), so it answers neither question `since` asks.
    """
    from datetime import UTC, datetime, timedelta

    recent = _rollout(tmp_path, "2026/09/16", "2026-09-16T09-02-04")
    _rollout(tmp_path, "2026/09/16", "2026-09-16T10-31-07", age_days=30)

    since = datetime.now(UTC) - timedelta(days=7)
    assert list(_reader().locate_sessions(tmp_path, since)) == [recent]


def test_locate_sessions_ignores_files_that_are_not_rollouts(tmp_path: Path) -> None:
    kept = _rollout(tmp_path, "2026/09/16", "2026-09-16T09-02-04")
    (tmp_path / "sessions" / "2026" / "09" / "16" / "notes.jsonl").write_text("{}\n")

    assert list(_reader().locate_sessions(tmp_path, None)) == [kept]


def test_locate_sessions_on_a_config_dir_with_no_sessions_yields_nothing(
    tmp_path: Path,
) -> None:
    assert list(_reader().locate_sessions(tmp_path, None)) == []


def test_locate_sessions_is_lazy_about_the_directory_walk(tmp_path: Path) -> None:
    _rollout(tmp_path, "2026/09/16", "2026-09-16T09-02-04")

    stream = _reader().locate_sessions(tmp_path, None)

    assert not isinstance(stream, list)
    assert len(list(stream)) == 1


# --- session identity (TranscriptIdentity) ----------------------------------


def _identity_rollout(tmp_path: Path, uuid: str, *entries: object) -> Path:
    d = tmp_path / "sessions" / "2026" / "09" / "16"
    d.mkdir(parents=True, exist_ok=True)
    path = d / f"rollout-2026-09-16T09-02-04-{uuid}.jsonl"
    path.write_text(_lines(*entries))
    return path


def _session_meta(session_id: str, cwd: str) -> dict:
    """Evidence §5.1: `id` equals `session_id`, measured 15/15."""
    return _entry(
        "session_meta",
        {
            "id": session_id,
            "session_id": session_id,
            "cwd": cwd,
            "cli_version": "0.154.0",
            "originator": "codex_cli_rs",
        },
    )


def test_the_session_is_the_uuid_in_the_rollout_name(tmp_path: Path) -> None:
    """Measured: the name's uuid equals `session_meta.id` in 15/15 rollouts."""
    uuid = "01a0aa69-fce1-7930-a795-dc39a8c1ebb4"
    path = _identity_rollout(
        tmp_path, uuid, _session_meta(uuid, "/w/demo"), _usage_record(input_tokens=1)
    )

    assert _reader().session_identity(path).session_id == uuid


def test_the_project_comes_from_the_working_directory_session_meta_records(
    tmp_path: Path,
) -> None:
    """A rollout path encodes a date, never a project — `cwd` is the only source."""
    uuid = "01a0aa69-fce1-7930-a795-dc39a8c1ebb4"
    path = _identity_rollout(
        tmp_path, uuid, _session_meta(uuid, "/w/demo"), _usage_record(input_tokens=1)
    )

    assert _reader().session_identity(path).project == "demo"


def test_a_rollout_without_session_meta_names_no_project(tmp_path: Path) -> None:
    """`None`, not a guess: the session is still identified by its file name."""
    uuid = "01a0aa69-fce1-7930-a795-dc39a8c1ebb4"
    path = _identity_rollout(tmp_path, uuid, _usage_record(input_tokens=1))

    identity = _reader().session_identity(path)
    assert (identity.session_id, identity.project) == (uuid, None)


def test_identifying_a_session_reads_no_further_than_it_must(tmp_path: Path) -> None:
    """`session_meta` is line 1 of a rollout that can run to hundreds of megabytes."""
    uuid = "01a0aa69-fce1-7930-a795-dc39a8c1ebb4"
    path = _identity_rollout(tmp_path, uuid, _session_meta(uuid, "/w/demo"))
    with path.open("a") as fh:
        fh.write("{ not json\n" * 50)

    assert _reader().session_identity(path).project == "demo"


def test_an_unreadable_rollout_still_yields_an_identity(tmp_path: Path) -> None:
    """Never raises: the caller is metering a tree it does not control."""
    uuid = "01a0aa69-fce1-7930-a795-dc39a8c1ebb4"
    path = _identity_rollout(tmp_path, uuid)
    path.unlink()

    identity = _reader().session_identity(path)
    assert (identity.session_id, identity.project) == (uuid, None)

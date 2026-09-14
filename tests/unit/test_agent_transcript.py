"""The transcript seam — `TranscriptReader` and the events it yields.

Modelled on `test_agent_headless.py`: the assertions are about the *normalised*
event, never about Claude Code's own field names except where the fixture
supplies them as input. A second agent's reader has to satisfy these shapes
without any of them naming `attachment`, `usage` or `tool_use`.

The design
(`specs/designs/2026-09-13-multi-agent-harness-design.md`, "`TranscriptReader`
as a separate optional Protocol") makes two claims this file pins:

* the reader is *optional* — an adapter with no readable transcript does not
  implement it, and `isinstance` is what callers ask rather than a boolean; and
* `signals()` exists on the reader so that a hook's declared signals can be
  checked against a reader that is supposed to satisfy them. Decision 11 is
  otherwise a declaration nothing verifies.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest


def _lines(*entries: object) -> str:
    return "".join(json.dumps(e) + "\n" for e in entries)


def _reader():
    from lazy_harness.agents.claude_code import ClaudeCodeAdapter

    return ClaudeCodeAdapter()


def _read(path: Path) -> list:
    return list(_reader().read(path))


def _by_signal(path: Path, signal) -> list:
    return [e for e in _read(path) if e.signal is signal]


# --- the Protocol is optional and checkable --------------------------------


def test_claude_code_satisfies_the_reader_protocol() -> None:
    from lazy_harness.agents.base import TranscriptReader

    assert isinstance(_reader(), TranscriptReader)


def test_an_adapter_without_a_readable_transcript_does_not_satisfy_it() -> None:
    """`NullAdapter` is the stand-in for an agent whose transcript we cannot read.

    The point of a separate Protocol: callers refuse it up front instead of
    calling `read()` and parsing something whose shape they are guessing.
    """
    from lazy_harness.agents.base import TranscriptReader
    from lazy_harness.agents.registry import NullAdapter

    assert not isinstance(NullAdapter(), TranscriptReader)


def test_claude_code_declares_all_four_signals() -> None:
    from lazy_harness.agents.base import Signal

    assert _reader().signals() == {
        Signal.MESSAGES,
        Signal.TOOL_CALLS,
        Signal.TOKEN_USAGE,
        Signal.GOAL_STATUS,
    }


# --- MESSAGES ---------------------------------------------------------------


def test_a_user_turn_yields_a_message_event_with_role_and_text(tmp_path: Path) -> None:
    from lazy_harness.agents.base import Signal

    path = tmp_path / "s.jsonl"
    path.write_text(_lines({"type": "user", "message": {"role": "user", "content": "hola"}}))

    (event,) = _by_signal(path, Signal.MESSAGES)
    assert event.role == "user"
    assert event.text == "hola"


def test_assistant_text_blocks_are_joined_into_one_message_event(tmp_path: Path) -> None:
    """Claude delivers assistant text as a list of blocks; the event is text."""
    from lazy_harness.agents.base import Signal

    path = tmp_path / "s.jsonl"
    path.write_text(
        _lines(
            {
                "type": "assistant",
                "message": {
                    "role": "assistant",
                    "content": [
                        {"type": "text", "text": "first"},
                        {"type": "thinking", "thinking": "ignored"},
                        {"type": "text", "text": "second"},
                    ],
                },
            }
        )
    )

    (event,) = _by_signal(path, Signal.MESSAGES)
    assert event.role == "assistant"
    assert event.text == "first\nsecond"


def test_a_turn_carries_its_timestamp(tmp_path: Path) -> None:
    from lazy_harness.agents.base import Signal

    path = tmp_path / "s.jsonl"
    path.write_text(
        _lines(
            {
                "type": "user",
                "timestamp": "2026-09-14T02:02:40.182Z",
                "message": {"role": "user", "content": "hola"},
            }
        )
    )

    (event,) = _by_signal(path, Signal.MESSAGES)
    assert event.timestamp is not None
    assert event.timestamp.year == 2026
    assert event.timestamp.tzinfo is not None


def test_an_unparseable_timestamp_arrives_as_none_rather_than_raising(tmp_path: Path) -> None:
    from lazy_harness.agents.base import Signal

    path = tmp_path / "s.jsonl"
    path.write_text(
        _lines({"type": "user", "timestamp": "yesterday", "message": {"content": "hola"}})
    )

    (event,) = _by_signal(path, Signal.MESSAGES)
    assert event.timestamp is None


# --- TOOL_CALLS -------------------------------------------------------------


def test_a_tool_use_block_yields_a_normalised_tool_call(tmp_path: Path) -> None:
    """The operation is the normalised one, not Claude Code's tool name."""
    from lazy_harness.agents.base import Operation, Signal

    path = tmp_path / "s.jsonl"
    path.write_text(
        _lines(
            {
                "type": "assistant",
                "message": {
                    "role": "assistant",
                    "content": [
                        {
                            "type": "tool_use",
                            "id": "toolu_1",
                            "name": "Bash",
                            "input": {"command": "ls -la"},
                        }
                    ],
                },
            }
        )
    )

    (event,) = _by_signal(path, Signal.TOOL_CALLS)
    assert event.tool is not None
    assert event.tool.native_name == "Bash"
    assert event.tool.operation is Operation.RUN_COMMAND
    assert event.tool.command == "ls -la"


def test_a_file_tool_lands_its_path_on_the_normalised_call(tmp_path: Path) -> None:
    from lazy_harness.agents.base import Operation, Signal

    path = tmp_path / "s.jsonl"
    path.write_text(
        _lines(
            {
                "type": "assistant",
                "message": {
                    "content": [
                        {
                            "type": "tool_use",
                            "id": "toolu_2",
                            "name": "Read",
                            "input": {"file_path": "/etc/hosts"},
                        }
                    ]
                },
            }
        )
    )

    (event,) = _by_signal(path, Signal.TOOL_CALLS)
    assert event.tool is not None
    assert event.tool.operation is Operation.READ_FILE
    assert event.tool.paths == (Path("/etc/hosts"),)


def test_one_turn_with_two_tool_uses_yields_two_events(tmp_path: Path) -> None:
    from lazy_harness.agents.base import Signal

    path = tmp_path / "s.jsonl"
    path.write_text(
        _lines(
            {
                "type": "assistant",
                "message": {
                    "content": [
                        {"type": "tool_use", "id": "a", "name": "Bash", "input": {"command": "x"}},
                        {"type": "tool_use", "id": "b", "name": "Bash", "input": {"command": "y"}},
                    ]
                },
            }
        )
    )

    events = _by_signal(path, Signal.TOOL_CALLS)
    assert [e.tool.command for e in events] == ["x", "y"]


def test_the_tool_use_id_travels_with_the_call(tmp_path: Path) -> None:
    """Pairing a call with its result needs the id the agent assigned it."""
    from lazy_harness.agents.base import Signal

    path = tmp_path / "s.jsonl"
    path.write_text(
        _lines(
            {
                "type": "assistant",
                "message": {
                    "content": [{"type": "tool_use", "id": "toolu_9", "name": "Bash", "input": {}}]
                },
            }
        )
    )

    (event,) = _by_signal(path, Signal.TOOL_CALLS)
    assert event.tool_use_id == "toolu_9"


# --- TOKEN_USAGE ------------------------------------------------------------


def test_an_assistant_turn_with_usage_yields_the_four_counters(tmp_path: Path) -> None:
    from lazy_harness.agents.base import Signal

    path = tmp_path / "s.jsonl"
    path.write_text(
        _lines(
            {
                "type": "assistant",
                "message": {
                    "content": [],
                    "usage": {
                        "input_tokens": 2,
                        "output_tokens": 161,
                        "cache_read_input_tokens": 34802,
                        "cache_creation_input_tokens": 26241,
                    },
                },
            }
        )
    )

    (event,) = _by_signal(path, Signal.TOKEN_USAGE)
    assert event.usage is not None
    assert event.usage.input_tokens == 2
    assert event.usage.output_tokens == 161
    assert event.usage.cache_read_tokens == 34802
    assert event.usage.cache_creation_tokens == 26241


def test_a_counter_the_provider_omitted_is_none_and_not_zero(tmp_path: Path) -> None:
    """`HeadlessResult`'s rule, applied here: a zero enters a report as a fact.

    "this turn cached nothing" and "this provider reported no cache field" are
    different facts, and a 0 would merge them.
    """
    from lazy_harness.agents.base import Signal

    path = tmp_path / "s.jsonl"
    path.write_text(_lines({"type": "assistant", "message": {"usage": {"input_tokens": 5}}}))

    (event,) = _by_signal(path, Signal.TOKEN_USAGE)
    assert event.usage.input_tokens == 5
    assert event.usage.output_tokens is None
    assert event.usage.cache_read_tokens is None
    assert event.usage.cache_creation_tokens is None


def test_a_turn_with_no_usage_object_yields_no_token_event(tmp_path: Path) -> None:
    from lazy_harness.agents.base import Signal

    path = tmp_path / "s.jsonl"
    path.write_text(_lines({"type": "assistant", "message": {"content": "hi"}}))

    assert _by_signal(path, Signal.TOKEN_USAGE) == []


def test_a_usage_object_of_the_wrong_type_yields_no_token_event(tmp_path: Path) -> None:
    from lazy_harness.agents.base import Signal

    path = tmp_path / "s.jsonl"
    path.write_text(_lines({"type": "assistant", "message": {"usage": "lots"}}))

    assert _by_signal(path, Signal.TOKEN_USAGE) == []


# --- GOAL_STATUS ------------------------------------------------------------


def test_a_goal_status_attachment_yields_its_condition_and_met_flag(tmp_path: Path) -> None:
    from lazy_harness.agents.base import Signal

    path = tmp_path / "s.jsonl"
    path.write_text(
        _lines(
            {
                "type": "attachment",
                "attachment": {
                    "type": "goal_status",
                    "met": False,
                    "sentinel": True,
                    "condition": "tests pass",
                },
            }
        )
    )

    (event,) = _by_signal(path, Signal.GOAL_STATUS)
    assert event.goal is not None
    assert event.goal.condition == "tests pass"
    assert event.goal.met is False


def test_a_goal_status_without_a_condition_still_yields_the_signal(tmp_path: Path) -> None:
    """Presence is the signal `stop_verify_guard` reads; the text is extra."""
    from lazy_harness.agents.base import Signal

    path = tmp_path / "s.jsonl"
    path.write_text(_lines({"type": "attachment", "attachment": {"type": "goal_status"}}))

    (event,) = _by_signal(path, Signal.GOAL_STATUS)
    assert event.goal.condition is None
    assert event.goal.met is None


@pytest.mark.parametrize("attachment", [None, 42, ["a"], "a string"])
def test_an_attachment_of_the_wrong_type_yields_nothing(tmp_path: Path, attachment: object) -> None:
    path = tmp_path / "s.jsonl"
    path.write_text(_lines({"type": "attachment", "attachment": attachment}))

    assert _read(path) == []


def test_an_attachment_of_another_kind_yields_nothing(tmp_path: Path) -> None:
    path = tmp_path / "s.jsonl"
    path.write_text(_lines({"type": "attachment", "attachment": {"type": "total_tokens_reminder"}}))

    assert _read(path) == []


# --- reading is lazy, and degrades rather than raising ----------------------


def test_the_file_is_opened_at_iteration_and_not_at_the_call(tmp_path: Path) -> None:
    """Laziness, asserted through behaviour rather than through `isgenerator`.

    A hook builds its reader when it starts and iterates when it decides. If
    `read()` slurped at call time, a `Stop` hook would be judging the
    transcript as of the moment it was constructed. Rewriting the file between
    the two is how that difference becomes visible.
    """
    from lazy_harness.agents.base import Signal

    path = tmp_path / "s.jsonl"
    path.write_text(_lines({"type": "user", "message": {"content": "before"}}))

    stream = _reader().read(path)
    path.write_text(_lines({"type": "user", "message": {"content": "after"}}))

    assert [e.text for e in stream if e.signal is Signal.MESSAGES] == ["after"]


def test_a_missing_transcript_yields_nothing_instead_of_raising(tmp_path: Path) -> None:
    """A hook that raises takes down the chain, and the file legitimately races.

    `locate_sessions` can name a file the agent rotates away a moment later.
    """
    assert _read(tmp_path / "gone.jsonl") == []


def test_a_directory_where_a_transcript_was_expected_yields_nothing(tmp_path: Path) -> None:
    target = tmp_path / "s.jsonl"
    target.mkdir()

    assert _read(target) == []


def test_a_corrupt_line_in_the_middle_does_not_lose_the_rest(tmp_path: Path) -> None:
    """The case the reader exists to survive: JSONL corrupted halfway through.

    Skipping the bad line and continuing is the only behaviour that keeps a
    long session readable; aborting would throw away everything after the first
    interrupted write.
    """
    from lazy_harness.agents.base import Signal

    path = tmp_path / "s.jsonl"
    path.write_text(
        _lines({"type": "user", "message": {"content": "first"}})
        + "{not json at all\n"
        + '{"type": "user", "message": {"content": "third"\n'
        + _lines({"type": "user", "message": {"content": "fourth"}})
    )

    assert [e.text for e in _read(path) if e.signal is Signal.MESSAGES] == ["first", "fourth"]


def test_a_transcript_truncated_mid_line_keeps_every_complete_line(tmp_path: Path) -> None:
    """A live session's last line is half-written whenever a Stop hook reads it."""
    from lazy_harness.agents.base import Signal

    path = tmp_path / "s.jsonl"
    complete = _lines({"type": "attachment", "attachment": {"type": "goal_status"}})
    path.write_text(complete + '{"type": "user", "message": {"cont')

    assert len(_by_signal(path, Signal.GOAL_STATUS)) == 1


@pytest.mark.parametrize("line", ["", "   ", "42", '"a string"', "null", "[1, 2]"])
def test_a_line_that_is_not_a_json_object_is_skipped(tmp_path: Path, line: str) -> None:
    path = tmp_path / "s.jsonl"
    path.write_text(line + "\n")

    assert _read(path) == []


def test_undecodable_bytes_do_not_abort_the_rest_of_the_transcript(tmp_path: Path) -> None:
    """One bad byte must not cost every line after it.

    Reading strictly would raise `UnicodeDecodeError` mid-iteration, and the
    caller's blanket `except` would turn a single corrupt byte into "this
    session declared no goal".
    """
    from lazy_harness.agents.base import Signal

    path = tmp_path / "s.jsonl"
    path.write_bytes(
        b'{"type": "user", "message": {"content": "\xff\xfe"}}\n'
        + _lines({"type": "attachment", "attachment": {"type": "goal_status"}}).encode()
    )

    assert len(_by_signal(path, Signal.GOAL_STATUS)) == 1


def test_an_entry_of_an_unknown_type_yields_nothing(tmp_path: Path) -> None:
    path = tmp_path / "s.jsonl"
    path.write_text(_lines({"type": "worktree-state", "payload": {"x": 1}}))

    assert _read(path) == []


@pytest.mark.parametrize("kind", [[], {}, [1], {"a": 1}])
def test_an_unhashable_type_is_skipped_and_the_rest_still_arrives(
    tmp_path: Path, kind: object
) -> None:
    """`type` is JSON, so it can be a list or a dict, and both are unhashable.

    `kind not in _TURN_TYPES` hashes its left operand, so such an entry raised
    `TypeError` out of the generator and killed the iteration — costing every
    line after it, which for `stop_verify_guard` reads as "no goal declared".
    """
    from lazy_harness.agents.base import Signal

    path = tmp_path / "s.jsonl"
    path.write_text(
        _lines({"type": kind, "message": {"content": "ignored"}})
        + _lines({"type": "attachment", "attachment": {"type": "goal_status"}})
    )

    assert len(_by_signal(path, Signal.GOAL_STATUS)) == 1


def test_an_empty_transcript_yields_nothing(tmp_path: Path) -> None:
    path = tmp_path / "s.jsonl"
    path.write_text("")

    assert _read(path) == []


# --- locate_sessions --------------------------------------------------------


def _session(config_dir: Path, project: str, name: str, *, age_days: float = 0.0) -> Path:
    import time

    path = config_dir / "projects" / project / f"{name}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_lines({"type": "user", "message": {"content": name}}))
    if age_days:
        when = time.time() - age_days * 86400
        os.utime(path, (when, when))
    return path


def test_locate_sessions_finds_every_transcript_under_the_config_dir(tmp_path: Path) -> None:
    a = _session(tmp_path, "-repo-one", "aaa")
    b = _session(tmp_path, "-repo-two", "bbb")

    assert sorted(_reader().locate_sessions(tmp_path, None)) == sorted([a, b])


def test_locate_sessions_takes_the_config_dir_as_a_parameter(tmp_path: Path) -> None:
    """Adapters are constructed bare, so *whose* sessions is not adapter state.

    Two profiles served by one agent are two config dirs and one instance.
    """
    first = _session(tmp_path / "lazy", "-repo", "aaa")
    _session(tmp_path / "flex", "-repo", "bbb")

    assert list(_reader().locate_sessions(tmp_path / "lazy", None)) == [first]


def test_locate_sessions_filters_by_modification_time_when_since_is_given(
    tmp_path: Path,
) -> None:
    from datetime import UTC, datetime, timedelta

    recent = _session(tmp_path, "-repo", "recent")
    _session(tmp_path, "-repo", "ancient", age_days=30)

    since = datetime.now(UTC) - timedelta(days=7)
    assert list(_reader().locate_sessions(tmp_path, since)) == [recent]


def test_locate_sessions_on_a_config_dir_with_no_sessions_yields_nothing(
    tmp_path: Path,
) -> None:
    assert list(_reader().locate_sessions(tmp_path, None)) == []


def test_locate_sessions_ignores_files_that_are_not_transcripts(tmp_path: Path) -> None:
    kept = _session(tmp_path, "-repo", "aaa")
    (tmp_path / "projects" / "-repo" / "notes.md").write_text("x")

    assert list(_reader().locate_sessions(tmp_path, None)) == [kept]


def test_locate_sessions_is_lazy_about_the_directory_walk(tmp_path: Path) -> None:
    """Returning an iterator matters on a config dir holding thousands of files."""
    _session(tmp_path, "-repo", "aaa")

    stream = _reader().locate_sessions(tmp_path, None)

    assert not isinstance(stream, list)
    assert len(list(stream)) == 1

"""Two paths parse Claude Code's transcript. This asserts exactly how far they agree.

`ClaudeCodeAdapter.read()` serves hooks; `collector.iter_assistant_messages`
serves metering. ADR-051 keeps both, on a measurement over 2,619 real
transcripts and 102,464 usage records: the token buckets are identical and four
dimensions are missing from the reader.

Both halves are asserted here. The equality stops the two parsers drifting into
different numbers; the four inequalities stop the ADR going stale quietly — the
day `TranscriptEvent` gains a model, a test fails and says so, rather than the
decision staying on the page after its reason expired.
"""

from __future__ import annotations

import json
from pathlib import Path

from lazy_harness.agents.base import Signal
from lazy_harness.agents.claude_code import ClaudeCodeAdapter
from lazy_harness.monitoring.collector import iter_assistant_messages

# Synthetic, rebuilt from the shape §5 of the measurement records. Two models,
# a 5m/1h cache split, and a repeated `message.id` across two files — the three
# things the comparison turns on.
_MSG_A = {
    "type": "assistant",
    "message": {
        "id": "msg_a",
        "model": "claude-opus-4-6",
        "usage": {
            "input_tokens": 11,
            "output_tokens": 5,
            "cache_read_input_tokens": 700,
            "cache_creation_input_tokens": 90,
            "cache_creation": {
                "ephemeral_5m_input_tokens": 60,
                "ephemeral_1h_input_tokens": 30,
            },
        },
    },
    "timestamp": "2026-09-16T12:02:13.926Z",
}
_MSG_B = {
    "type": "assistant",
    "message": {
        "id": "msg_b",
        "model": "claude-haiku-4-5-20251001",
        "usage": {
            "input_tokens": 3,
            "output_tokens": 2,
            "cache_read_input_tokens": 0,
            "cache_creation_input_tokens": 0,
        },
    },
    "timestamp": "2026-09-16T12:03:13.926Z",
}


def _transcript(directory: Path, name: str, messages: list[dict]) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    path.write_text("".join(json.dumps(m) + "\n" for m in messages))
    return path


def _hand(path: Path) -> list[dict]:
    return list(iter_assistant_messages(path))


def _reader_usage(path: Path) -> list:
    return [
        e.usage
        for e in ClaudeCodeAdapter().read(path)
        if e.signal is Signal.TOKEN_USAGE and e.usage is not None
    ]


def test_both_paths_find_the_same_number_of_usage_records(tmp_path: Path) -> None:
    path = _transcript(tmp_path, "s.jsonl", [_MSG_A, _MSG_B])
    assert len(_hand(path)) == len(_reader_usage(path)) == 2


def test_both_paths_agree_on_every_token_bucket(tmp_path: Path) -> None:
    """The measured equality: 102,464 records, four buckets, identical."""
    path = _transcript(tmp_path, "s.jsonl", [_MSG_A, _MSG_B])

    hand = _hand(path)
    read = _reader_usage(path)

    assert sum(m["input"] for m in hand) == sum(u.input_tokens or 0 for u in read)
    assert sum(m["output"] for m in hand) == sum(u.output_tokens or 0 for u in read)
    assert sum(m["cache_read"] for m in hand) == sum(u.cache_read_tokens or 0 for u in read)
    # The hand parser splits the write by TTL; the reader carries one total.
    # They agree on the *sum*, which is the only thing both can express.
    assert sum(m["cache_create"] + m["cache_create_1h"] for m in hand) == sum(
        u.cache_creation_tokens or 0 for u in read
    )


# --- the four documented differences (ADR-051) ------------------------------


def test_the_reader_does_not_name_the_model(tmp_path: Path) -> None:
    """`session_stats` is `UNIQUE(session, model)`; the reader has no model.

    Delete this test's reason — add `model` to `TranscriptEvent` — and this
    fails, which is the signal to revisit ADR-051 rather than to widen the
    assertion.
    """
    path = _transcript(tmp_path, "s.jsonl", [_MSG_A, _MSG_B])

    assert {m["model"] for m in _hand(path)} == {
        "claude-opus-4-6",
        "claude-haiku-4-5-20251001",
    }
    events = [e for e in ClaudeCodeAdapter().read(path) if e.signal is Signal.TOKEN_USAGE]
    assert events, "the fixture must produce usage events for the negative to mean anything"
    assert not any(hasattr(e, "model") for e in events)
    assert not any(hasattr(u, "model") for u in _reader_usage(path))


def test_the_reader_does_not_carry_a_message_id(tmp_path: Path) -> None:
    """Cross-file dedup needs one. `tool_use_id` is `None` on a usage event."""
    path = _transcript(tmp_path, "s.jsonl", [_MSG_A, _MSG_B])

    assert [m["msg_id"] for m in _hand(path)] == ["msg_a", "msg_b"]
    events = [e for e in ClaudeCodeAdapter().read(path) if e.signal is Signal.TOKEN_USAGE]
    assert events
    assert not any(hasattr(e, "message_id") for e in events)
    assert all(e.tool_use_id is None for e in events)


def test_the_reader_collapses_the_cache_ttl_split(tmp_path: Path) -> None:
    """5-minute and 1-hour writes are priced differently; `TokenUsage` has one field."""
    path = _transcript(tmp_path, "s.jsonl", [_MSG_A])

    (hand,) = _hand(path)
    assert (hand["cache_create"], hand["cache_create_1h"]) == (60, 30)

    (usage,) = _reader_usage(path)
    assert usage.cache_creation_tokens == 90
    assert not hasattr(usage, "cache_creation_1h_tokens")


def test_locate_sessions_yields_the_memory_logs_ingest_excludes(tmp_path: Path) -> None:
    """17 of them on the measured host. They are this harness's logs, not transcripts."""
    from lazy_harness.monitoring.ingest import _find_session_files

    projects = tmp_path / "projects"
    _transcript(projects / "-repo", "s.jsonl", [_MSG_A])
    _transcript(projects / "-repo" / "memory", "decisions.jsonl", [_MSG_B])

    located = set(ClaudeCodeAdapter().locate_sessions(tmp_path, None))
    walked = {p for _mtime, p, _project, _session in _find_session_files(projects, [])}

    assert located - walked == {projects / "-repo" / "memory" / "decisions.jsonl"}
    assert walked - located == set()


def test_the_cache_breakdown_is_authoritative_when_it_disagrees_with_the_total(
    tmp_path: Path,
) -> None:
    """Measured: 4 messages in 1 file of 102,464 disagree, by +2,640 tokens.

    `split_cache_creation`'s docstring says the two "always agree". They do not,
    and the parser's documented choice — trust the breakdown — is what decides
    the case. Asserted so the choice is a decision and not an accident.
    """
    from lazy_harness.monitoring.collector import split_cache_creation

    disagreeing = {
        "cache_creation_input_tokens": 100,
        "cache_creation": {
            "ephemeral_5m_input_tokens": 60,
            "ephemeral_1h_input_tokens": 80,
        },
    }
    assert split_cache_creation(disagreeing) == (60, 80)

"""Two paths parse Claude Code's transcript. This asserts exactly how far they agree.

`ClaudeCodeAdapter.read()` serves hooks; `collector.iter_assistant_messages`
serves metering. ADR-051 measured both over 2,619 real transcripts and 102,464
usage records: the token buckets are identical and four dimensions were missing
from the reader. ADR-053 closes three of them — model, message id, cache TTL —
and this file is where they are asserted closed: what were inequalities are now
equalities over the same corpus.

The fourth stays open and stays asserted. The `memory/` exclusion is a
statement about what *this harness* writes under an agent's directory, not
about the agent, so the reader yields those files and ingest skips them; both
halves are asserted, because a reader that silently learned to skip them would
be answering a question that is not its own.
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
    # Bucket by bucket now, not just on the sum: both paths split the write by
    # TTL, so agreeing on the total while disagreeing on the halves would be a
    # pricing bug this assertion would have let through.
    assert sum(m["cache_create"] for m in hand) == sum(u.cache_creation_tokens or 0 for u in read)
    assert sum(m["cache_create_1h"] for m in hand) == sum(
        u.cache_creation_1h_tokens or 0 for u in read
    )


# --- the three gaps ADR-053 closed -----------------------------------------
#
# ADR-051 asserted each of these as an inequality, with a `not hasattr(...)`
# tripwire so that widening the Protocol would fail a test naming the ADR
# rather than let the decision go stale quietly. It fired, twice: once when the
# fields landed and once when the reader began filling them. Each is now the
# equality it was always going to become.


def test_both_paths_name_the_same_model_for_the_same_turn(tmp_path: Path) -> None:
    """`session_stats` is `UNIQUE(session, model)` — the dimension must survive the crossing."""
    path = _transcript(tmp_path, "s.jsonl", [_MSG_A, _MSG_B])

    events = [e for e in ClaudeCodeAdapter().read(path) if e.signal is Signal.TOKEN_USAGE]

    assert [m["model"] for m in _hand(path)] == [e.model for e in events]
    assert [e.model for e in events] == ["claude-opus-4-6", "claude-haiku-4-5-20251001"]


def test_both_paths_carry_the_same_message_id_for_the_same_turn(tmp_path: Path) -> None:
    """Cross-file dedup keys on it. `tool_use_id` stays `None`: it is a different id."""
    path = _transcript(tmp_path, "s.jsonl", [_MSG_A, _MSG_B])

    events = [e for e in ClaudeCodeAdapter().read(path) if e.signal is Signal.TOKEN_USAGE]

    assert [m["msg_id"] for m in _hand(path)] == [e.message_id for e in events]
    assert [e.message_id for e in events] == ["msg_a", "msg_b"]
    assert all(e.tool_use_id is None for e in events)


def test_both_paths_split_the_cache_write_by_ttl_the_same_way(tmp_path: Path) -> None:
    """5-minute and 1-hour writes are priced differently; one field cannot say both."""
    path = _transcript(tmp_path, "s.jsonl", [_MSG_A])

    (hand,) = _hand(path)
    (usage,) = _reader_usage(path)

    assert (hand["cache_create"], hand["cache_create_1h"]) == (60, 30)
    assert (usage.cache_creation_tokens, usage.cache_creation_1h_tokens) == (60, 30)


def test_a_transcript_predating_the_breakdown_reports_no_one_hour_write(
    tmp_path: Path,
) -> None:
    """`None`, not `0`: nothing recorded that turn's TTL, and 0 would be a claim.

    The hand parser answers 0 because it sums ints on the way to a price. The
    reader crosses a Protocol whose own docstring refuses that merge, so the
    two agree on the arithmetic (`or 0`) without agreeing on the spelling.
    """
    path = _transcript(tmp_path, "s.jsonl", [_MSG_B])

    (hand,) = _hand(path)
    (usage,) = _reader_usage(path)

    assert (hand["cache_create"], hand["cache_create_1h"]) == (0, 0)
    assert usage.cache_creation_1h_tokens is None


def test_both_paths_trust_the_breakdown_over_the_total_when_they_disagree(
    tmp_path: Path,
) -> None:
    """Measured: 4 messages in 1 file of 102,464 disagree, by +2,640 tokens.

    The hand parser's documented choice is to trust the breakdown. The reader
    has to make the same one or the two paths price the same turn differently
    on exactly the records where it matters — which is the drift this whole
    file exists to prevent.
    """
    disagreeing = {
        "type": "assistant",
        "message": {
            "id": "msg_c",
            "model": "claude-opus-4-6",
            "usage": {
                "input_tokens": 1,
                "output_tokens": 1,
                "cache_read_input_tokens": 0,
                "cache_creation_input_tokens": 100,
                "cache_creation": {
                    "ephemeral_5m_input_tokens": 60,
                    "ephemeral_1h_input_tokens": 80,
                },
            },
        },
        "timestamp": "2026-09-16T12:04:13.926Z",
    }
    path = _transcript(tmp_path, "s.jsonl", [disagreeing])

    (hand,) = _hand(path)
    (usage,) = _reader_usage(path)

    assert (hand["cache_create"], hand["cache_create_1h"]) == (60, 80)
    assert (usage.cache_creation_tokens, usage.cache_creation_1h_tokens) == (60, 80)
    # The total the breakdown contradicts is not what either path bills.
    assert usage.cache_creation_tokens + (usage.cache_creation_1h_tokens or 0) == 140


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

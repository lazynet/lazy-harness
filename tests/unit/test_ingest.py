"""Tests for the metrics ingest pipeline."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest


def _write_session(
    projects_dir: Path,
    project_slug: str,
    session_uuid: str,
    messages: list[dict],
) -> Path:
    d = projects_dir / project_slug
    d.mkdir(parents=True, exist_ok=True)
    f = d / f"{session_uuid}.jsonl"
    with open(f, "w") as fh:
        for m in messages:
            fh.write(json.dumps(m) + "\n")
    return f


def _assistant_msg(
    model: str = "claude-opus-4-6",
    inp: int = 100,
    out: int = 50,
    ts: str = "2026-04-13T10:00:00",
    msg_id: str | None = None,
) -> dict:
    return {
        "type": "assistant",
        "message": {
            "id": msg_id or f"msg_{inp}_{out}_{ts}",
            "model": model,
            "usage": {
                "input_tokens": inp,
                "output_tokens": out,
                "cache_read_input_tokens": 0,
                "cache_creation_input_tokens": 0,
            },
        },
        "timestamp": ts,
    }


def _profile(tmp_path: Path, name: str):
    from lazy_harness.core.profiles import ProfileInfo

    config_dir = tmp_path / name
    (config_dir / "projects").mkdir(parents=True)
    return ProfileInfo(name=name, config_dir=config_dir, roots=[], is_default=True, exists=True)


def test_ingest_profile_upserts_totals(tmp_path: Path) -> None:
    from lazy_harness.monitoring.db import MetricsDB
    from lazy_harness.monitoring.ingest import ingest_profile
    from lazy_harness.monitoring.pricing import load_pricing

    prof = _profile(tmp_path, "lazy")
    _write_session(
        prof.config_dir / "projects",
        "-Users-foo-repos-demo",
        "11111111-1111-1111-1111-111111111111",
        [_assistant_msg(inp=100, out=50)],
    )

    db = MetricsDB(tmp_path / "metrics.db")
    report = ingest_profile(prof, db, load_pricing())
    assert report.sessions_updated == 1
    assert report.sessions_skipped == 0

    rows = db.query_stats(period="all")
    assert len(rows) == 1
    assert rows[0]["input"] == 100
    assert rows[0]["output"] == 50
    assert rows[0]["profile"] == "lazy"
    assert rows[0]["cost"] > 0
    db.close()


def test_ingest_is_idempotent(tmp_path: Path) -> None:
    from lazy_harness.monitoring.db import MetricsDB
    from lazy_harness.monitoring.ingest import ingest_profile
    from lazy_harness.monitoring.pricing import load_pricing

    prof = _profile(tmp_path, "lazy")
    _write_session(
        prof.config_dir / "projects",
        "-Users-foo-repos-demo",
        "22222222-2222-2222-2222-222222222222",
        [_assistant_msg(inp=100, out=50, msg_id="m1")],
    )

    db = MetricsDB(tmp_path / "metrics.db")
    pricing = load_pricing()
    ingest_profile(prof, db, pricing)
    ingest_profile(prof, db, pricing)

    rows = db.query_stats(period="all")
    assert len(rows) == 1
    assert rows[0]["input"] == 100  # not doubled
    assert rows[0]["output"] == 50
    db.close()


def test_ingest_reflects_session_growth(tmp_path: Path) -> None:
    from lazy_harness.monitoring.db import MetricsDB
    from lazy_harness.monitoring.ingest import ingest_profile
    from lazy_harness.monitoring.pricing import load_pricing

    prof = _profile(tmp_path, "lazy")
    session_file = _write_session(
        prof.config_dir / "projects",
        "-Users-foo-repos-demo",
        "33333333-3333-3333-3333-333333333333",
        [_assistant_msg(inp=100, out=50)],
    )

    db = MetricsDB(tmp_path / "metrics.db")
    pricing = load_pricing()
    ingest_profile(prof, db, pricing)

    # Append another assistant turn (simulating session growth)
    with open(session_file, "a") as fh:
        fh.write(json.dumps(_assistant_msg(inp=200, out=80)) + "\n")
    # Bump mtime explicitly to ensure filesystem detects it
    new_mtime = os.stat(session_file).st_mtime + 10
    os.utime(session_file, (new_mtime, new_mtime))

    r2 = ingest_profile(prof, db, pricing)
    assert r2.sessions_updated == 1

    rows = db.query_stats(period="all")
    assert len(rows) == 1
    assert rows[0]["input"] == 300  # new total, not accumulated twice
    assert rows[0]["output"] == 130
    db.close()


def test_ingest_preserves_sessions_after_transcript_pruned(tmp_path: Path) -> None:
    """A session's stats survive once its transcript is pruned by retention.

    Claude Code deletes transcripts older than cleanupPeriodDays. The metrics
    ledger must not drop those sessions on the next ingest, otherwise cost
    history silently shrinks to a rolling retention-window view.
    """
    from lazy_harness.monitoring.db import MetricsDB
    from lazy_harness.monitoring.ingest import ingest_profile
    from lazy_harness.monitoring.pricing import load_pricing

    prof = _profile(tmp_path, "lazy")
    projects = prof.config_dir / "projects"
    old = _write_session(
        projects,
        "-Users-foo-repos-demo",
        "aaaaaaaa-0000-0000-0000-000000000000",
        [_assistant_msg(inp=100, out=50, msg_id="old-1")],
    )

    db = MetricsDB(tmp_path / "metrics.db")
    pricing = load_pricing()
    ingest_profile(prof, db, pricing)

    # Retention prunes the old transcript; a fresh session arrives.
    old.unlink()
    _write_session(
        projects,
        "-Users-foo-repos-demo",
        "bbbbbbbb-0000-0000-0000-000000000000",
        [_assistant_msg(inp=200, out=80, msg_id="new-1")],
    )
    ingest_profile(prof, db, pricing)

    sessions = {r["session"] for r in db.query_stats(period="all")}
    assert "aaaaaaaa-0000-0000-0000-000000000000" in sessions  # pruned but preserved
    assert "bbbbbbbb-0000-0000-0000-000000000000" in sessions
    db.close()


def test_ingest_isolates_profiles(tmp_path: Path) -> None:
    from lazy_harness.monitoring.db import MetricsDB
    from lazy_harness.monitoring.ingest import ingest_profile
    from lazy_harness.monitoring.pricing import load_pricing

    prof_a = _profile(tmp_path, "lazy")
    prof_b = _profile(tmp_path, "flex")
    _write_session(
        prof_a.config_dir / "projects",
        "-Users-foo-repos-a",
        "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        [_assistant_msg(inp=111)],
    )
    _write_session(
        prof_b.config_dir / "projects",
        "-Users-foo-repos-b",
        "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
        [_assistant_msg(inp=222)],
    )

    db = MetricsDB(tmp_path / "metrics.db")
    pricing = load_pricing()
    ingest_profile(prof_a, db, pricing)
    ingest_profile(prof_b, db, pricing)

    rows = db.query_stats(period="all")
    by_profile = {r["profile"]: r["input"] for r in rows}
    assert by_profile == {"lazy": 111, "flex": 222}
    db.close()


def test_ingest_all_walks_every_profile(tmp_path: Path) -> None:
    from lazy_harness.core.config import Config, ProfileEntry, ProfilesConfig
    from lazy_harness.monitoring.db import MetricsDB
    from lazy_harness.monitoring.ingest import ingest_all
    from lazy_harness.monitoring.pricing import load_pricing

    prof_a_dir = tmp_path / "lazy"
    prof_b_dir = tmp_path / "flex"
    (prof_a_dir / "projects").mkdir(parents=True)
    (prof_b_dir / "projects").mkdir(parents=True)
    _write_session(
        prof_a_dir / "projects",
        "-p1",
        "cccccccc-cccc-cccc-cccc-cccccccccccc",
        [_assistant_msg(inp=10)],
    )
    _write_session(
        prof_b_dir / "projects",
        "-p2",
        "dddddddd-dddd-dddd-dddd-dddddddddddd",
        [_assistant_msg(inp=20)],
    )

    cfg = Config()
    cfg.profiles = ProfilesConfig(
        default="lazy",
        items={
            "lazy": ProfileEntry(config_dir=str(prof_a_dir), roots=[]),
            "flex": ProfileEntry(config_dir=str(prof_b_dir), roots=[]),
        },
    )

    db = MetricsDB(tmp_path / "metrics.db")
    report = ingest_all(cfg, db, load_pricing())
    assert report.sessions_updated == 2
    rows = db.query_stats(period="all")
    assert {r["profile"] for r in rows} == {"lazy", "flex"}
    db.close()


def test_ingest_profile_stamps_agent_and_billing_model(tmp_path: Path) -> None:
    from lazy_harness.monitoring.db import MetricsDB
    from lazy_harness.monitoring.ingest import ingest_profile
    from lazy_harness.monitoring.pricing import load_pricing

    prof = _profile(tmp_path, "lazy")
    _write_session(
        prof.config_dir / "projects",
        "-Users-foo-repos-demo",
        "11111111-1111-1111-1111-111111111111",
        [_assistant_msg(inp=100, out=50)],
    )

    db = MetricsDB(tmp_path / "metrics.db")
    ingest_profile(prof, db, load_pricing(), billing_model="flat_rate")
    rows = db.query_stats(period="all")
    assert rows[0]["agent"] == "claude-code"
    assert rows[0]["billing_model"] == "flat_rate"
    assert rows[0]["cost"] == 0.0, "a flat_rate row must never bill per-token"
    db.close()


def test_ingest_profile_defaults_to_claude_code_agent_and_per_token_billing_model(
    tmp_path: Path,
) -> None:
    from lazy_harness.monitoring.db import MetricsDB
    from lazy_harness.monitoring.ingest import ingest_profile
    from lazy_harness.monitoring.pricing import load_pricing

    prof = _profile(tmp_path, "lazy")
    _write_session(
        prof.config_dir / "projects",
        "-Users-foo-repos-demo",
        "22222222-3333-4444-5555-666666666666",
        [_assistant_msg(inp=100, out=50)],
    )

    db = MetricsDB(tmp_path / "metrics.db")
    ingest_profile(prof, db, load_pricing())
    rows = db.query_stats(period="all")
    assert rows[0]["agent"] == "claude-code"
    assert rows[0]["billing_model"] == "per_token"
    db.close()


def test_ingest_profile_flat_rate_does_not_flag_unknown_models(tmp_path: Path) -> None:
    """A flat-rate row's model was never going to be priced, so an unrecognised
    one is not the gap `unknown_models` exists to surface."""
    from lazy_harness.monitoring.db import MetricsDB
    from lazy_harness.monitoring.ingest import ingest_profile

    prof = _profile(tmp_path, "lazy")
    _write_session(
        prof.config_dir / "projects",
        "-Users-foo-repos-demo",
        "33333333-4444-5555-6666-777777777777",
        [_assistant_msg(model="claude-future-model-99", inp=100, out=50)],
    )

    db = MetricsDB(tmp_path / "metrics.db")
    report = ingest_profile(prof, db, {}, billing_model="flat_rate")
    assert report.unknown_models == set()
    db.close()


def test_ingest_dedups_messages_shared_across_resumed_sessions(tmp_path: Path) -> None:
    """Resumed session JSONLs re-include prior messages. Each message.id must count once."""
    from lazy_harness.monitoring.db import MetricsDB
    from lazy_harness.monitoring.ingest import ingest_profile
    from lazy_harness.monitoring.pricing import load_pricing

    prof = _profile(tmp_path, "lazy")

    shared_msg = _assistant_msg(inp=100, out=50, msg_id="msg-shared-1")
    only_in_a = _assistant_msg(inp=200, out=80, msg_id="msg-a-only")
    only_in_b = _assistant_msg(inp=300, out=120, msg_id="msg-b-only")

    _write_session(
        prof.config_dir / "projects",
        "-tmp-proj",
        "aaaaaaaa-1111-1111-1111-111111111111",
        [shared_msg, only_in_a],
    )
    _write_session(
        prof.config_dir / "projects",
        "-tmp-proj",
        "bbbbbbbb-2222-2222-2222-222222222222",
        [shared_msg, only_in_b],  # resume: includes shared_msg again
    )

    db = MetricsDB(tmp_path / "metrics.db")
    ingest_profile(prof, db, load_pricing())

    rows = db.query_stats(period="all")
    total_input = sum(r["input"] for r in rows)
    total_output = sum(r["output"] for r in rows)
    assert total_input == 100 + 200 + 300  # shared counted once
    assert total_output == 50 + 80 + 120
    db.close()


def test_ingest_discovers_subagent_files(tmp_path: Path) -> None:
    """Subagent JSONLs live under <session-uuid>/subagents/ and must be ingested too."""
    from lazy_harness.monitoring.db import MetricsDB
    from lazy_harness.monitoring.ingest import ingest_profile
    from lazy_harness.monitoring.pricing import load_pricing

    prof = _profile(tmp_path, "lazy")
    project_dir = prof.config_dir / "projects" / "-tmp-proj"
    session_uuid = "cccccccc-3333-3333-3333-333333333333"
    project_dir.mkdir(parents=True)

    # Parent session file
    parent_file = project_dir / f"{session_uuid}.jsonl"
    with open(parent_file, "w") as fh:
        fh.write(json.dumps(_assistant_msg(inp=100, out=50, msg_id="parent-msg")) + "\n")

    # Subagent file nested under <session_uuid>/subagents/
    sub_dir = project_dir / session_uuid / "subagents"
    sub_dir.mkdir(parents=True)
    sub_file = sub_dir / "agent-abc123.jsonl"
    with open(sub_file, "w") as fh:
        fh.write(json.dumps(_assistant_msg(inp=40, out=20, msg_id="subagent-msg")) + "\n")

    db = MetricsDB(tmp_path / "metrics.db")
    ingest_profile(prof, db, load_pricing())

    rows = db.query_stats(period="all")
    total_input = sum(r["input"] for r in rows)
    total_output = sum(r["output"] for r in rows)
    assert total_input == 140
    assert total_output == 70
    db.close()


def test_ingest_attributes_subagent_tokens_to_parent_session(tmp_path: Path) -> None:
    """Subagent JSONLs must count toward the parent session, not as new sessions."""
    from lazy_harness.monitoring.db import MetricsDB
    from lazy_harness.monitoring.ingest import ingest_profile
    from lazy_harness.monitoring.pricing import load_pricing

    prof = _profile(tmp_path, "lazy")
    project_dir = prof.config_dir / "projects" / "-tmp-proj"
    session_uuid = "eeeeeeee-5555-5555-5555-555555555555"
    project_dir.mkdir(parents=True)

    parent_file = project_dir / f"{session_uuid}.jsonl"
    with open(parent_file, "w") as fh:
        fh.write(json.dumps(_assistant_msg(inp=100, out=50, msg_id="parent-msg")) + "\n")

    sub_dir = project_dir / session_uuid / "subagents"
    sub_dir.mkdir(parents=True)
    for suffix in ("abc", "def"):
        with open(sub_dir / f"agent-{suffix}.jsonl", "w") as fh:
            fh.write(json.dumps(_assistant_msg(inp=40, out=20, msg_id=f"sub-{suffix}")) + "\n")

    db = MetricsDB(tmp_path / "metrics.db")
    report = ingest_profile(prof, db, load_pricing())

    rows = db.query_stats(period="all")
    # Only one session row — subagents fold into the parent.
    assert {r["session"] for r in rows} == {session_uuid}
    assert report.sessions_updated == 1
    total_input = sum(r["input"] for r in rows)
    total_output = sum(r["output"] for r in rows)
    assert total_input == 100 + 40 + 40
    assert total_output == 50 + 20 + 20
    db.close()


def test_ingest_tracks_unknown_model_in_report(tmp_path: Path) -> None:
    """Sessions using unrecognized models are surfaced in IngestReport.unknown_models."""
    from lazy_harness.monitoring.db import MetricsDB
    from lazy_harness.monitoring.ingest import ingest_profile
    from lazy_harness.monitoring.pricing import load_pricing

    prof = _profile(tmp_path, "lazy")
    _write_session(
        prof.config_dir / "projects",
        "-Users-foo-repos-demo",
        "ffffffff-ffff-ffff-ffff-ffffffffffff",
        [_assistant_msg(model="claude-future-model-99", inp=100, out=50)],
    )

    db = MetricsDB(tmp_path / "metrics.db")
    report = ingest_profile(prof, db, load_pricing())
    assert "claude-future-model-99" in report.unknown_models
    db.close()


def test_ingest_known_models_not_in_unknown_models(tmp_path: Path) -> None:
    """Known models must not appear in IngestReport.unknown_models."""
    from lazy_harness.monitoring.db import MetricsDB
    from lazy_harness.monitoring.ingest import ingest_profile
    from lazy_harness.monitoring.pricing import load_pricing

    prof = _profile(tmp_path, "lazy")
    _write_session(
        prof.config_dir / "projects",
        "-Users-foo-repos-demo",
        "11111111-2222-3333-4444-555555555555",
        [_assistant_msg(model="claude-opus-4-6", inp=100, out=50)],
    )

    db = MetricsDB(tmp_path / "metrics.db")
    report = ingest_profile(prof, db, load_pricing())
    assert not report.unknown_models
    db.close()


def test_ingest_skips_memory_jsonls(tmp_path: Path) -> None:
    """memory/*.jsonl in a project dir are user episodic files, not sessions."""
    from lazy_harness.monitoring.db import MetricsDB
    from lazy_harness.monitoring.ingest import ingest_profile
    from lazy_harness.monitoring.pricing import load_pricing

    prof = _profile(tmp_path, "lazy")
    project_dir = prof.config_dir / "projects" / "-tmp-proj"
    project_dir.mkdir(parents=True)

    # Valid session
    with open(project_dir / "dddddddd-4444-4444-4444-444444444444.jsonl", "w") as fh:
        fh.write(json.dumps(_assistant_msg(inp=100, out=50, msg_id="real")) + "\n")

    # Memory JSONL — must NOT be parsed (may not even have assistant records)
    mem_dir = project_dir / "memory"
    mem_dir.mkdir()
    with open(mem_dir / "decisions.jsonl", "w") as fh:
        fh.write(json.dumps({"type": "decision", "text": "whatever"}) + "\n")
    with open(mem_dir / "failures.jsonl", "w") as fh:
        # Even if it looked like an assistant message, it must be skipped
        fh.write(json.dumps(_assistant_msg(inp=9999, out=9999, msg_id="SHOULD_NOT_COUNT")) + "\n")

    db = MetricsDB(tmp_path / "metrics.db")
    ingest_profile(prof, db, load_pricing())

    rows = db.query_stats(period="all")
    total_input = sum(r["input"] for r in rows)
    assert total_input == 100
    db.close()


def _ingest_sonnet_5_on(tmp_path: Path, session_date: str) -> float:
    """Ingest one 1M-input-token sonnet-5 session dated `session_date`."""
    from lazy_harness.monitoring.db import MetricsDB
    from lazy_harness.monitoring.ingest import ingest_profile
    from lazy_harness.monitoring.pricing import load_pricing

    prof = _profile(tmp_path, "lazy")
    _write_session(
        prof.config_dir / "projects",
        "-Users-foo-repos-demo",
        "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
        [
            _assistant_msg(
                model="claude-sonnet-5",
                inp=1_000_000,
                out=0,
                ts=f"{session_date}T10:00:00",
            )
        ],
    )
    db = MetricsDB(tmp_path / "metrics.db")
    try:
        ingest_profile(prof, db, load_pricing())
        rows = db.query_stats(period="all")
    finally:
        db.close()
    return rows[0]["cost"]


def test_ingest_prices_sonnet_5_at_its_own_rate(tmp_path: Path) -> None:
    """Sonnet 5 bills $2/MTok input, not Sonnet 4.6's $3."""
    assert _ingest_sonnet_5_on(tmp_path, "2026-08-12") == pytest.approx(2.0)


def test_ingest_does_not_apply_the_cancelled_september_increase(tmp_path: Path) -> None:
    """Regression: the 2026-09-01 rise to $3/$15 was cancelled.

    An expiry reverting sonnet-5 to $3/$15 would inflate every reported
    cost by 50% from one day to the next, with no change in usage.
    """
    assert _ingest_sonnet_5_on(tmp_path, "2026-09-15") == pytest.approx(2.0)


def test_ingest_does_not_flag_a_pseudo_model_as_unpriced(tmp_path: Path) -> None:
    """`<synthetic>` costs $0 by nature, not for want of a rate."""
    from lazy_harness.monitoring.db import MetricsDB
    from lazy_harness.monitoring.ingest import ingest_profile
    from lazy_harness.monitoring.pricing import load_pricing

    prof = _profile(tmp_path, "lazy")
    _write_session(
        prof.config_dir / "projects",
        "-Users-foo-repos-demo",
        "cccccccc-cccc-cccc-cccc-cccccccccccc",
        [_assistant_msg(model="<synthetic>", inp=0, out=0)],
    )

    db = MetricsDB(tmp_path / "metrics.db")
    try:
        report = ingest_profile(prof, db, load_pricing())
    finally:
        db.close()
    assert report.unknown_models == set()


def test_ingest_still_flags_a_real_unpriced_model(tmp_path: Path) -> None:
    """The pseudo-model carve-out must not swallow genuine gaps."""
    from lazy_harness.monitoring.db import MetricsDB
    from lazy_harness.monitoring.ingest import ingest_profile
    from lazy_harness.monitoring.pricing import load_pricing

    prof = _profile(tmp_path, "lazy")
    _write_session(
        prof.config_dir / "projects",
        "-Users-foo-repos-demo",
        "dddddddd-dddd-dddd-dddd-dddddddddddd",
        [
            _assistant_msg(model="<synthetic>", inp=0, out=0, msg_id="a"),
            _assistant_msg(model="claude-future-model-99", inp=100, out=50, msg_id="b"),
        ],
    )

    db = MetricsDB(tmp_path / "metrics.db")
    try:
        report = ingest_profile(prof, db, load_pricing())
    finally:
        db.close()
    assert report.unknown_models == {"claude-future-model-99"}


def test_ingest_prices_one_hour_writes_and_stores_the_token_total(tmp_path: Path) -> None:
    """The stored row keeps one token column; the cost knows about both.

    `session_stats.cache_create` stays the total number of cache-write
    tokens — splitting it would mean a schema migration and a wire-format
    bump for no reader that wants the split. The TTL only has to reach
    `calculate_cost`, which happens before the row is written.
    """
    from lazy_harness.monitoring.db import MetricsDB
    from lazy_harness.monitoring.ingest import ingest_profile
    from lazy_harness.monitoring.pricing import load_pricing

    prof = _profile(tmp_path, "lazy")
    _write_session(
        prof.config_dir / "projects",
        "-Users-x-repo",
        "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
        [
            {
                "type": "assistant",
                "message": {
                    "id": "msg_reduce",
                    "model": "claude-opus-5",
                    "usage": {
                        "input_tokens": 10,
                        "output_tokens": 14607,
                        "cache_read_input_tokens": 267362,
                        "cache_creation_input_tokens": 55875,
                        "cache_creation": {
                            "ephemeral_5m_input_tokens": 0,
                            "ephemeral_1h_input_tokens": 55875,
                        },
                    },
                },
                "timestamp": "2026-08-31T10:00:00Z",
            }
        ],
    )

    db = MetricsDB(tmp_path / "metrics.db")
    ingest_profile(prof, db, load_pricing())

    (row,) = db.query_stats(period="all")
    assert row["cache_create"] == 55875
    assert row["cost"] == pytest.approx(1.0577, abs=0.00005)
    db.close()


def test_ingest_bills_a_legacy_transcript_at_the_five_minute_rate(tmp_path: Path) -> None:
    """No breakdown recorded means no evidence of a 1-hour write."""
    from lazy_harness.monitoring.db import MetricsDB
    from lazy_harness.monitoring.ingest import ingest_profile
    from lazy_harness.monitoring.pricing import load_pricing

    prof = _profile(tmp_path, "lazy")
    _write_session(
        prof.config_dir / "projects",
        "-Users-x-repo",
        "11111111-2222-3333-4444-555555555555",
        [
            {
                "type": "assistant",
                "message": {
                    "id": "msg_legacy",
                    "model": "claude-opus-5",
                    "usage": {
                        "input_tokens": 0,
                        "output_tokens": 0,
                        "cache_read_input_tokens": 0,
                        "cache_creation_input_tokens": 1_000_000,
                    },
                },
                "timestamp": "2026-08-31T10:00:00Z",
            }
        ],
    )

    db = MetricsDB(tmp_path / "metrics.db")
    ingest_profile(prof, db, load_pricing())

    (row,) = db.query_stats(period="all")
    assert row["cache_create"] == 1_000_000
    assert row["cost"] == pytest.approx(6.25, abs=0.00005)
    db.close()


# --- the sessions directory comes from the adapter, never from a literal -----


class _FakeAgent:
    """An adapter that only answers the question ingest asks it.

    Deliberately not an `AgentAdapter`: `session_dirs` is duck-typed at this
    call site, and a fake carrying the whole surface would hide the case where
    it is absent.
    """

    def __init__(self, name: str, dirs: dict[str, str] | None = None) -> None:
        self.name = name
        self._dirs = dirs

    def session_dirs(self) -> dict[str, str]:
        assert self._dirs is not None
        return self._dirs


class _AgentWithoutSessionDirs:
    name = "claude-code"


def test_ingest_reads_the_directory_the_adapter_declares(tmp_path: Path) -> None:
    """Not `projects/`: the literal is gone and the adapter is asked."""
    from lazy_harness.core.profiles import ProfileInfo
    from lazy_harness.monitoring.db import MetricsDB
    from lazy_harness.monitoring.ingest import ingest_profile
    from lazy_harness.monitoring.pricing import load_pricing

    config_dir = tmp_path / "declared"
    prof = ProfileInfo(
        name="declared", config_dir=config_dir, roots=[], is_default=True, exists=True
    )
    _write_session(
        config_dir / "transcripts",
        "-Users-foo-repos-demo",
        "33333333-3333-3333-3333-333333333333",
        [_assistant_msg(inp=7, out=3)],
    )

    db = MetricsDB(tmp_path / "m.db")
    report = ingest_profile(
        prof, db, load_pricing(), agent=_FakeAgent("claude-code", {"sessions": "transcripts"})
    )
    assert report.sessions_updated == 1
    assert db.query_stats(period="all")[0]["input"] == 7
    db.close()


def test_ingest_skips_a_profile_whose_agent_declares_no_sessions_directory(
    tmp_path: Path,
) -> None:
    """The `Path(x) / ""` trap, at the site that would walk the whole config dir.

    The transcript sits at the config root, which is exactly where the removed
    fallback would have found it.
    """
    from lazy_harness.core.profiles import ProfileInfo
    from lazy_harness.monitoring.db import MetricsDB
    from lazy_harness.monitoring.ingest import ingest_profile
    from lazy_harness.monitoring.pricing import load_pricing

    config_dir = tmp_path / "nowhere"
    prof = ProfileInfo(
        name="nowhere", config_dir=config_dir, roots=[], is_default=True, exists=True
    )
    _write_session(
        config_dir,
        "-Users-foo-repos-demo",
        "44444444-4444-4444-4444-444444444444",
        [_assistant_msg(inp=100, out=50)],
    )

    db = MetricsDB(tmp_path / "m.db")
    report = ingest_profile(prof, db, load_pricing(), agent=_FakeAgent("opencode", {}))
    assert report.sessions_scanned == 0
    assert report.sessions_updated == 0
    assert db.query_stats(period="all") == []
    db.close()


def test_ingest_skips_an_agent_that_does_not_answer_where_its_sessions_live(
    tmp_path: Path,
) -> None:
    from lazy_harness.monitoring.db import MetricsDB
    from lazy_harness.monitoring.ingest import ingest_profile
    from lazy_harness.monitoring.pricing import load_pricing

    prof = _profile(tmp_path, "mute")
    _write_session(
        prof.config_dir / "projects",
        "-Users-foo-repos-demo",
        "55555555-5555-5555-5555-555555555555",
        [_assistant_msg(inp=100, out=50)],
    )
    db = MetricsDB(tmp_path / "m.db")
    report = ingest_profile(prof, db, load_pricing(), agent=_AgentWithoutSessionDirs())
    assert report.sessions_scanned == 0
    assert db.query_stats(period="all") == []
    db.close()


def test_ingest_refuses_a_transcript_dialect_its_parser_was_not_written_for(
    tmp_path: Path,
) -> None:
    """A Codex rollout is JSONL and is not Claude Code's JSONL.

    Walking it with `iter_assistant_messages` yields nothing, which reads as an
    empty profile. The design's rule is that it be reported unreadable instead,
    so ingest does not scan it at all and `lh doctor` carries the verdict.
    """
    from lazy_harness.core.profiles import ProfileInfo
    from lazy_harness.monitoring.db import MetricsDB
    from lazy_harness.monitoring.ingest import ingest_profile
    from lazy_harness.monitoring.pricing import load_pricing

    config_dir = tmp_path / "cx"
    rollouts = config_dir / "sessions" / "2026" / "09" / "16"
    rollouts.mkdir(parents=True)
    (rollouts / "rollout-2026-09-16T09-02-04-abc.jsonl").write_text(
        json.dumps(
            {
                "timestamp": "2026-09-16T12:02:13.926Z",
                "type": "token_usage_record",
                "payload": {"usage": {"input_tokens": 11, "output_tokens": 5}},
                "ordinal": 1,
            }
        )
        + "\n"
    )
    prof = ProfileInfo(name="cx", config_dir=config_dir, roots=[], is_default=False, exists=True)

    db = MetricsDB(tmp_path / "m.db")
    report = ingest_profile(
        prof, db, load_pricing(), agent=_FakeAgent("codex", {"sessions": "sessions"})
    )
    assert report.sessions_scanned == 0
    assert db.query_stats(period="all") == []
    db.close()


def test_ingest_all_resolves_the_agent_for_each_profile(tmp_path: Path) -> None:
    """Two profiles, two agents, one run.

    The integration half of the unit tests above: `ingest_all` is the only
    caller that knows the config, so it is the only place the per-profile
    adapter can be resolved. A test that passed `agent=` by hand would never
    catch it resolving the global `[agent].type` for every profile.
    """
    from lazy_harness.core.config import Config, ProfileEntry
    from lazy_harness.monitoring.db import MetricsDB
    from lazy_harness.monitoring.ingest import ingest_all
    from lazy_harness.monitoring.pricing import load_pricing

    cfg = Config()
    cfg.agent.type = "claude-code"
    cfg.profiles.default = "lazy"
    cfg.profiles.items = {
        "lazy": ProfileEntry(config_dir=str(tmp_path / "lazy"), agent="claude-code"),
        "cx": ProfileEntry(config_dir=str(tmp_path / "cx"), agent="codex"),
    }

    _write_session(
        tmp_path / "lazy" / "projects",
        "-Users-foo-repos-demo",
        "66666666-6666-6666-6666-666666666666",
        [_assistant_msg(inp=9, out=4)],
    )
    # `projects/`, under the Codex profile, holding Claude-shaped bytes. This
    # is what makes the test discriminating: resolving the global
    # `[agent].type` for every profile — the behaviour being replaced — walks
    # this directory and bills it. Only a per-profile resolution skips it.
    _write_session(
        tmp_path / "cx" / "projects",
        "-Users-foo-repos-demo",
        "77777777-7777-7777-7777-777777777777",
        [_assistant_msg(inp=1000, out=1000)],
    )

    db = MetricsDB(tmp_path / "m.db")
    report = ingest_all(cfg, db, load_pricing())
    rows = db.query_stats(period="all")
    assert report.sessions_updated == 1
    assert [r["profile"] for r in rows] == ["lazy"]
    assert rows[0]["input"] == 9
    db.close()

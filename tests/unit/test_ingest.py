"""Tests for the metrics ingest pipeline."""

from __future__ import annotations

import json
import os
from pathlib import Path


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
    return ProfileInfo(
        name=name, config_dir=config_dir, roots=[], is_default=True, exists=True
    )


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
        fh.write(
            json.dumps(_assistant_msg(inp=100, out=50, msg_id="parent-msg")) + "\n"
        )

    # Subagent file nested under <session_uuid>/subagents/
    sub_dir = project_dir / session_uuid / "subagents"
    sub_dir.mkdir(parents=True)
    sub_file = sub_dir / "agent-abc123.jsonl"
    with open(sub_file, "w") as fh:
        fh.write(
            json.dumps(_assistant_msg(inp=40, out=20, msg_id="subagent-msg")) + "\n"
        )

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
        fh.write(
            json.dumps(_assistant_msg(inp=100, out=50, msg_id="parent-msg")) + "\n"
        )

    sub_dir = project_dir / session_uuid / "subagents"
    sub_dir.mkdir(parents=True)
    for suffix in ("abc", "def"):
        with open(sub_dir / f"agent-{suffix}.jsonl", "w") as fh:
            fh.write(
                json.dumps(
                    _assistant_msg(inp=40, out=20, msg_id=f"sub-{suffix}")
                )
                + "\n"
            )

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
        fh.write(
            json.dumps(_assistant_msg(inp=9999, out=9999, msg_id="SHOULD_NOT_COUNT"))
            + "\n"
        )

    db = MetricsDB(tmp_path / "metrics.db")
    ingest_profile(prof, db, load_pricing())

    rows = db.query_stats(period="all")
    total_input = sum(r["input"] for r in rows)
    assert total_input == 100
    db.close()

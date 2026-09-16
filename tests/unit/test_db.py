"""Tests for SQLite metrics store."""

from __future__ import annotations

from pathlib import Path

import pytest


def test_create_db(tmp_path: Path) -> None:
    from lazy_harness.monitoring.db import MetricsDB

    db = MetricsDB(tmp_path / "metrics.db")
    assert (tmp_path / "metrics.db").is_file()
    db.close()


def test_insert_and_query_sessions(tmp_path: Path) -> None:
    from lazy_harness.monitoring.db import MetricsDB

    db = MetricsDB(tmp_path / "metrics.db")
    db.insert_stats(
        [
            {
                "session": "abc12345",
                "date": "2026-04-12",
                "model": "claude-opus-4-6",
                "profile": "personal",
                "project": "my-project",
                "input": 1000,
                "output": 500,
                "cache_read": 200,
                "cache_create": 10,
                "cost": 0.05,
            }
        ]
    )

    rows = db.query_stats(period="all")
    assert len(rows) == 1
    assert rows[0]["session"] == "abc12345"
    assert rows[0]["cost"] == 0.05
    db.close()


def test_query_by_period(tmp_path: Path) -> None:
    from lazy_harness.monitoring.db import MetricsDB

    db = MetricsDB(tmp_path / "metrics.db")
    db.insert_stats(
        [
            {
                "session": "a",
                "date": "2026-04-10",
                "model": "m",
                "profile": "p",
                "project": "x",
                "input": 100,
                "output": 50,
                "cache_read": 0,
                "cache_create": 0,
                "cost": 0.01,
            },
            {
                "session": "b",
                "date": "2026-04-12",
                "model": "m",
                "profile": "p",
                "project": "x",
                "input": 200,
                "output": 100,
                "cache_read": 0,
                "cache_create": 0,
                "cost": 0.02,
            },
        ]
    )

    rows = db.query_stats(since="2026-04-11")
    assert len(rows) == 1
    assert rows[0]["session"] == "b"
    db.close()


def test_aggregate_costs(tmp_path: Path) -> None:
    from lazy_harness.monitoring.db import MetricsDB

    db = MetricsDB(tmp_path / "metrics.db")
    db.insert_stats(
        [
            {
                "session": "a",
                "date": "2026-04-12",
                "model": "claude-opus-4-6",
                "profile": "personal",
                "project": "x",
                "input": 100,
                "output": 50,
                "cache_read": 0,
                "cache_create": 0,
                "cost": 0.05,
            },
            {
                "session": "b",
                "date": "2026-04-12",
                "model": "claude-opus-4-6",
                "profile": "personal",
                "project": "y",
                "input": 200,
                "output": 100,
                "cache_read": 0,
                "cache_create": 0,
                "cost": 0.10,
            },
        ]
    )

    totals = db.aggregate_costs(period="all")
    assert totals["total_cost"] == 0.15
    assert totals["total_input"] == 300
    db.close()


def test_no_duplicate_insert(tmp_path: Path) -> None:
    from lazy_harness.monitoring.db import MetricsDB

    db = MetricsDB(tmp_path / "metrics.db")
    entry = {
        "session": "abc",
        "date": "2026-04-12",
        "model": "m",
        "profile": "p",
        "project": "x",
        "input": 100,
        "output": 50,
        "cache_read": 0,
        "cache_create": 0,
        "cost": 0.01,
    }
    db.insert_stats([entry])
    db.insert_stats([entry])  # duplicate
    rows = db.query_stats(period="all")
    assert len(rows) == 1
    db.close()


def _entry(
    session: str = "sess-1",
    model: str = "claude-opus-4-6",
    inp: int = 100,
    out: int = 50,
) -> dict:
    return {
        "session": session,
        "date": "2026-04-13",
        "model": model,
        "profile": "lazy",
        "project": "my-project",
        "input": inp,
        "output": out,
        "cache_read": 0,
        "cache_create": 0,
        "cost": 0.01,
    }


def test_upsert_stats_overwrites_existing_totals(tmp_path: Path) -> None:
    from lazy_harness.monitoring.db import MetricsDB

    db = MetricsDB(tmp_path / "metrics.db")
    db.upsert_stats([_entry(inp=100, out=50)])
    db.upsert_stats([_entry(inp=300, out=120)])

    rows = db.query_stats(period="all")
    assert len(rows) == 1
    assert rows[0]["input"] == 300
    assert rows[0]["output"] == 120
    db.close()


def test_upsert_stats_keeps_distinct_models_separate(tmp_path: Path) -> None:
    from lazy_harness.monitoring.db import MetricsDB

    db = MetricsDB(tmp_path / "metrics.db")
    db.upsert_stats(
        [
            _entry(model="claude-opus-4-6", inp=100),
            _entry(model="claude-sonnet-4-6", inp=200),
        ]
    )
    db.upsert_stats(
        [
            _entry(model="claude-opus-4-6", inp=150),
            _entry(model="claude-sonnet-4-6", inp=250),
        ]
    )

    rows = db.query_stats(period="all")
    by_model = {r["model"]: r["input"] for r in rows}
    assert by_model == {"claude-opus-4-6": 150, "claude-sonnet-4-6": 250}
    db.close()


def test_ingest_meta_roundtrip(tmp_path: Path) -> None:
    from lazy_harness.monitoring.db import MetricsDB

    db = MetricsDB(tmp_path / "metrics.db")
    assert db.get_ingest_mtime("sess-1") is None
    db.set_ingest_mtime("sess-1", 1_700_000_000_000_000_000)
    assert db.get_ingest_mtime("sess-1") == 1_700_000_000_000_000_000
    db.set_ingest_mtime("sess-1", 1_800_000_000_000_000_000)
    assert db.get_ingest_mtime("sess-1") == 1_800_000_000_000_000_000
    db.close()


def test_a_new_db_has_the_launches_table(tmp_path: Path) -> None:
    from lazy_harness.monitoring.db import MetricsDB

    db = MetricsDB(tmp_path / "metrics.db")
    try:
        names = {
            r[0] for r in db._conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
    finally:
        db.close()
    assert "launches" in names


def test_a_pre_existing_db_gains_the_launches_table_on_open(tmp_path: Path) -> None:
    """The instrument must appear in the store every machine already has.

    `CREATE TABLE IF NOT EXISTS` runs on every open, so a database written by
    an older `lh` picks the table up the first time a new one touches it —
    the table is not reachable by a migration nobody invokes.
    """
    from lazy_harness.monitoring.db import MetricsDB

    path = tmp_path / "old.db"
    # Exactly the state of every metrics DB on disk before this change: the
    # whole schema minus the one table. Handwriting a narrower `session_stats`
    # would exercise the identity-column migration instead.
    seeded = MetricsDB(path)
    seeded._conn.execute("DROP TABLE launches")
    seeded._conn.commit()
    seeded.close()

    db = MetricsDB(path)
    try:
        names = {
            r[0] for r in db._conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
    finally:
        db.close()
    assert "launches" in names


def test_record_launch_round_trips(tmp_path: Path) -> None:
    from lazy_harness.monitoring.db import MetricsDB

    db = MetricsDB(tmp_path / "metrics.db")
    try:
        db.record_launch(profile="flex", agent="codex", entry="run", host="LazyMBP")
        row = db._conn.execute("SELECT ts, profile, agent, host, entry FROM launches").fetchone()
    finally:
        db.close()
    assert row["profile"] == "flex"
    assert row["agent"] == "codex"
    assert row["host"] == "LazyMBP"
    assert row["entry"] == "run"
    assert isinstance(row["ts"], float)


def test_record_launch_appends_rather_than_replacing(tmp_path: Path) -> None:
    """An event log, not state: the same launch twice is two rows."""
    from lazy_harness.monitoring.db import MetricsDB

    db = MetricsDB(tmp_path / "metrics.db")
    try:
        db.record_launch(profile="lazy", agent="claude-code", entry="run")
        db.record_launch(profile="lazy", agent="claude-code", entry="run")
        total = db._conn.execute("SELECT COUNT(*) AS n FROM launches").fetchone()["n"]
    finally:
        db.close()
    assert total == 2


def test_record_launch_refuses_an_entry_outside_the_vocabulary(tmp_path: Path) -> None:
    from lazy_harness.monitoring.db import MetricsDB

    db = MetricsDB(tmp_path / "metrics.db")
    try:
        with pytest.raises(ValueError, match="entry"):
            db.record_launch(profile="lazy", agent="claude-code", entry="repl")
        total = db._conn.execute("SELECT COUNT(*) AS n FROM launches").fetchone()["n"]
    finally:
        db.close()
    assert total == 0


def test_launch_counts_group_by_profile_agent_and_entry(tmp_path: Path) -> None:
    from lazy_harness.monitoring.db import MetricsDB

    db = MetricsDB(tmp_path / "metrics.db")
    try:
        db.record_launch(profile="lazy", agent="claude-code", entry="run")
        db.record_launch(profile="lazy", agent="claude-code", entry="run")
        db.record_launch(profile="lazy", agent="claude-code", entry="exec")
        db.record_launch(profile="flex", agent="codex", entry="run")
        counts = db.launch_counts()
    finally:
        db.close()
    assert counts == {
        ("lazy", "claude-code", "run"): 2,
        ("lazy", "claude-code", "exec"): 1,
        ("flex", "codex", "run"): 1,
    }


def test_launch_counts_honour_the_window(tmp_path: Path) -> None:
    from lazy_harness.monitoring.db import MetricsDB

    db = MetricsDB(tmp_path / "metrics.db")
    try:
        db._conn.execute(
            "INSERT INTO launches (ts, profile, agent, host, entry) VALUES (?,?,?,?,?)",
            (1000.0, "lazy", "claude-code", "", "run"),
        )
        db._conn.execute(
            "INSERT INTO launches (ts, profile, agent, host, entry) VALUES (?,?,?,?,?)",
            (3000.0, "lazy", "claude-code", "", "run"),
        )
        db._conn.commit()
        counts = db.launch_counts(since_ts=2000.0)
    finally:
        db.close()
    assert counts == {("lazy", "claude-code", "run"): 1}


def _fixed_clock(db: object, monkeypatch: pytest.MonkeyPatch, when: str) -> float:
    """Pin `_now` so both halves of the ratio window are derived from one instant."""
    from datetime import datetime

    ts = datetime.fromisoformat(when).timestamp()
    monkeypatch.setattr(db, "_now", lambda: ts)
    return ts


def _stat(session: str, date: str, profile: str) -> dict[str, object]:
    return {
        "session": session,
        "date": date,
        "model": "claude-opus-4-6",
        "profile": profile,
        "project": "p",
        "input": 1,
        "output": 1,
        "cache_read": 0,
        "cache_create": 0,
        "cost": 0.0,
    }


def test_launch_to_session_ratio_pairs_launches_with_sessions_per_profile(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from lazy_harness.monitoring.db import MetricsDB

    db = MetricsDB(tmp_path / "metrics.db")
    try:
        _fixed_clock(db, monkeypatch, "2026-09-16T12:00:00")
        for _ in range(3):
            db.record_launch(profile="lazy", agent="claude-code", entry="run")
        db.insert_stats([_stat("s1", "2026-09-10", "lazy"), _stat("s2", "2026-09-12", "lazy")])
        ratios = db.launch_to_session_ratio(days=28)
    finally:
        db.close()

    assert ratios["lazy"].launches == 3
    assert ratios["lazy"].sessions == 2
    assert ratios["lazy"].ratio == 1.5


def test_launch_to_session_ratio_reports_no_ratio_without_a_denominator(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A profile with launches and no ingested session cannot be calibrated.

    Reporting 3.0 there would read as three launches per session; the honest
    answer is that the window holds no sessions to divide by.
    """
    from lazy_harness.monitoring.db import MetricsDB

    db = MetricsDB(tmp_path / "metrics.db")
    try:
        _fixed_clock(db, monkeypatch, "2026-09-16T12:00:00")
        db.record_launch(profile="flex", agent="codex", entry="exec")
        ratios = db.launch_to_session_ratio(days=28)
    finally:
        db.close()

    assert ratios["flex"].launches == 1
    assert ratios["flex"].sessions == 0
    assert ratios["flex"].ratio is None


def test_launch_to_session_ratio_cuts_both_halves_at_the_same_instant(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`session_stats` rows outlive the transcripts they describe, so the
    denominator is meaningless without a stated window — and a window that
    bounds only one half is worse than none."""
    from datetime import datetime

    from lazy_harness.monitoring.db import MetricsDB

    db = MetricsDB(tmp_path / "metrics.db")
    try:
        _fixed_clock(db, monkeypatch, "2026-09-16T12:00:00")
        db.record_launch(profile="lazy", agent="claude-code", entry="run")
        db._conn.execute(
            "INSERT INTO launches (ts, profile, agent, host, entry) VALUES (?,?,?,?,?)",
            (
                datetime.fromisoformat("2026-06-01T12:00:00").timestamp(),
                "lazy",
                "claude-code",
                "",
                "run",
            ),
        )
        db._conn.commit()
        db.insert_stats(
            [_stat("recent", "2026-09-10", "lazy"), _stat("ancient", "2026-06-01", "lazy")]
        )
        ratios = db.launch_to_session_ratio(days=28)
    finally:
        db.close()

    assert ratios["lazy"].launches == 1, "the June launch is outside the window"
    assert ratios["lazy"].sessions == 1, "the June session is outside the same window"

"""Tests for SQLite metrics store."""

from __future__ import annotations

from pathlib import Path


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

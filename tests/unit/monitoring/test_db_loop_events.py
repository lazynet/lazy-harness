"""Tests for the loop_events table."""

from __future__ import annotations

import pytest

from lazy_harness.monitoring.db import MetricsDB


@pytest.fixture
def db() -> MetricsDB:
    return MetricsDB(":memory:")


def test_records_and_counts_events_by_kind(db: MetricsDB) -> None:
    db.record_loop_event(session="s1", kind="nontrivial_prompt", project="p")
    db.record_loop_event(session="s1", kind="nontrivial_prompt", project="p")
    db.record_loop_event(session="s2", kind="goal_declared", project="p")

    assert db.loop_event_counts() == {"nontrivial_prompt": 2, "goal_declared": 1}


def test_counts_respect_the_since_cutoff(db: MetricsDB) -> None:
    db.record_loop_event(session="old", kind="nontrivial_prompt")
    cutoff = db._now()  # test seam, see Step 3
    db.record_loop_event(session="new", kind="goal_declared")

    assert db.loop_event_counts(since_ts=cutoff) == {"goal_declared": 1}


def test_detail_round_trips(db: MetricsDB) -> None:
    db.record_loop_event(session="s1", kind="goal_declared", detail="tests pass")

    rows = db._conn.execute("SELECT detail FROM loop_events").fetchall()
    assert rows[0]["detail"] == "tests pass"


def test_empty_table_counts_to_an_empty_mapping(db: MetricsDB) -> None:
    assert db.loop_event_counts() == {}


def test_accepts_string_path_and_creates_parent_dirs(
    tmp_path: pytest.TempPathFactory,
) -> None:
    """MetricsDB should accept a string path, coerce it, and create parent dirs."""
    db_path = tmp_path / "nonexistent" / "parent" / "metrics.db"
    db_str_path = str(db_path)

    db = MetricsDB(db_str_path)
    db.record_loop_event(session="s1", kind="nontrivial_prompt", project="p")

    assert db.loop_event_counts() == {"nontrivial_prompt": 1}
    assert db_path.exists()

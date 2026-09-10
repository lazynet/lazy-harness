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


def test_clear_goal_verdict_removes_a_prior_verdict_for_the_session(db: MetricsDB) -> None:
    db.record_loop_event(session="s1", kind="goal_declared", project="p")

    db.clear_goal_verdict("s1")

    assert db.loop_event_counts() == {}


def test_clear_goal_verdict_leaves_other_kinds_for_the_same_session_alone(
    db: MetricsDB,
) -> None:
    db.record_loop_event(session="s1", kind="goal_declared", project="p")
    db.record_loop_event(session="s1", kind="nontrivial_prompt", project="p")

    db.clear_goal_verdict("s1")

    assert db.loop_event_counts() == {"nontrivial_prompt": 1}


def test_clear_goal_verdict_leaves_other_sessions_alone(db: MetricsDB) -> None:
    db.record_loop_event(session="s1", kind="goal_declared", project="p")
    db.record_loop_event(session="s2", kind="goal_absent", project="p")

    db.clear_goal_verdict("s1")

    assert db.loop_event_counts() == {"goal_absent": 1}


def test_clear_goal_verdict_on_a_session_with_no_verdict_is_a_no_op(db: MetricsDB) -> None:
    db.record_loop_event(session="s1", kind="nontrivial_prompt", project="p")

    db.clear_goal_verdict("s1")

    assert db.loop_event_counts() == {"nontrivial_prompt": 1}


def test_clear_agent_dispatches_removes_prior_dispatched_rows_for_the_session(
    db: MetricsDB,
) -> None:
    db.record_loop_event(session="s1", kind="agent_dispatched", project="p")
    db.record_loop_event(session="s1", kind="agent_dispatched", project="p")

    db.clear_agent_dispatches("s1")

    assert db.loop_event_counts() == {}


def test_clear_agent_dispatches_leaves_other_kinds_for_the_same_session_alone(
    db: MetricsDB,
) -> None:
    db.record_loop_event(session="s1", kind="agent_dispatched", project="p")
    db.record_loop_event(session="s1", kind="nontrivial_prompt", project="p")

    db.clear_agent_dispatches("s1")

    assert db.loop_event_counts() == {"nontrivial_prompt": 1}


def test_clear_agent_dispatches_leaves_other_sessions_alone(db: MetricsDB) -> None:
    db.record_loop_event(session="s1", kind="agent_dispatched", project="p")
    db.record_loop_event(session="s2", kind="agent_dispatched", project="p")

    db.clear_agent_dispatches("s1")

    assert db.loop_event_counts() == {"agent_dispatched": 1}


def test_has_loop_event_is_true_once_the_kind_is_recorded_for_the_session(
    db: MetricsDB,
) -> None:
    db.record_loop_event(session="s1", kind="verify_ran", project="p")

    assert db.has_loop_event("s1", "verify_ran") is True


def test_has_loop_event_is_false_for_an_unrecorded_kind(db: MetricsDB) -> None:
    db.record_loop_event(session="s1", kind="verify_ran", project="p")

    assert db.has_loop_event("s1", "verify_block") is False


def test_has_loop_event_does_not_match_a_different_session(db: MetricsDB) -> None:
    db.record_loop_event(session="s1", kind="verify_ran", project="p")

    assert db.has_loop_event("s2", "verify_ran") is False


def test_has_loop_event_on_an_empty_table_is_false(db: MetricsDB) -> None:
    assert db.has_loop_event("s1", "verify_ran") is False


def test_clear_agent_dispatches_on_a_session_with_no_dispatches_is_a_no_op(
    db: MetricsDB,
) -> None:
    db.record_loop_event(session="s1", kind="nontrivial_prompt", project="p")

    db.clear_agent_dispatches("s1")

    assert db.loop_event_counts() == {"nontrivial_prompt": 1}

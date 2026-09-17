"""Tests for `adoption_check`, the fixed-horizon kill check (blast-radius decision 1).

specs/designs/2026-09-13-multi-agent-blast-radius-design.md:275-373 — baseline,
horizon, adoption check and the calibration rule this function encodes.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from lazy_harness.monitoring.db import MetricsDB
from lazy_harness.monitoring.launches import CODEX_ADAPTER_MERGED, adoption_check


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


def _fixed_clock(db: MetricsDB, monkeypatch: pytest.MonkeyPatch, when: str) -> float:
    """Pin `db._now` so `launch_counts`/`launch_to_session_ratio`'s own window
    lines up with the `now` handed to `adoption_check` — the same instant on
    both ends of the subtraction, not two clocks that happen to agree today."""
    ts = datetime.fromisoformat(when).timestamp()
    monkeypatch.setattr(db, "_now", lambda: ts)
    return ts


def test_below_horizon_returns_none(tmp_path: Path) -> None:
    db = MetricsDB(tmp_path / "m.db")
    try:
        now = datetime(2026, 9, 20, tzinfo=UTC)  # < CODEX_ADAPTER_MERGED + 8 weeks
        verdict = adoption_check(db, now=now)
    finally:
        db.close()
    assert verdict is None


def test_horizon_boundary_is_exactly_eight_weeks_from_the_codex_merge(tmp_path: Path) -> None:
    """One day before the horizon closes: still None. On the day it closes,
    with no calibration data at all, still None for the other reason —
    but the horizon check itself must not open early."""
    db = MetricsDB(tmp_path / "m.db")
    try:
        horizon_end = CODEX_ADAPTER_MERGED + timedelta(weeks=8)
        one_day_early = datetime(
            horizon_end.year, horizon_end.month, horizon_end.day, tzinfo=UTC
        ) - timedelta(days=1)
        assert adoption_check(db, now=one_day_early) is None
    finally:
        db.close()


def test_past_horizon_without_a_measurable_claude_ratio_returns_none(tmp_path: Path) -> None:
    """No `claude-code` row in `launches` at all: calibration is impossible, so
    the threshold is not set and the horizon does not start."""
    db = MetricsDB(tmp_path / "m.db")
    try:
        db.record_launch(profile="flex", agent="codex", entry="exec")
        now = datetime(2026, 12, 1, tzinfo=UTC)
        verdict = adoption_check(db, now=now)
    finally:
        db.close()
    assert verdict is None


def test_past_horizon_calibrated_names_exactly_the_profile_below_threshold(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db = MetricsDB(tmp_path / "m.db")
    try:
        ts = _fixed_clock(db, monkeypatch, "2026-12-01T12:00:00+00:00")
        now = datetime.fromtimestamp(ts, tz=UTC)

        # Claude profile: 10 launches / 5 sessions -> ratio 2.0 -> threshold 10.0
        for _ in range(10):
            db.record_launch(profile="lazy", agent="claude-code", entry="run")
        db.insert_stats([_stat(f"s{i}", "2026-11-20", "lazy") for i in range(5)])

        # Below the threshold (9 < 10)
        for _ in range(9):
            db.record_launch(profile="flex", agent="codex", entry="exec")
        # At/above the threshold (12 >= 10)
        for _ in range(12):
            db.record_launch(profile="urus", agent="codex", entry="exec")

        verdict = adoption_check(db, now=now)
    finally:
        db.close()

    assert verdict is not None
    assert verdict.threshold == 10.0
    assert verdict.ratio_used == 2.0
    assert verdict.below_threshold == ("flex",)
    assert verdict.launches_by_profile == {"flex": 9, "urus": 12}


def test_min_ratio_across_claude_profiles_is_used_not_the_average(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The design's own bias is toward false negatives: an adapter in use must
    not be killed by a threshold inflated by a heavier Claude profile
    elsewhere, so the calibration uses the minimum ratio, not the mean."""
    db = MetricsDB(tmp_path / "m.db")
    try:
        ts = _fixed_clock(db, monkeypatch, "2026-12-01T12:00:00+00:00")
        now = datetime.fromtimestamp(ts, tz=UTC)

        # "lazy": ratio 1.0 (the minimum)
        for _ in range(5):
            db.record_launch(profile="lazy", agent="claude-code", entry="run")
        db.insert_stats([_stat(f"s{i}", "2026-11-20", "lazy") for i in range(5)])

        # "work": ratio 4.0 — would inflate an average-based threshold
        for _ in range(20):
            db.record_launch(profile="work", agent="claude-code", entry="run")
        db.insert_stats([_stat(f"w{i}", "2026-11-20", "work") for i in range(5)])

        db.record_launch(profile="flex", agent="codex", entry="exec")

        verdict = adoption_check(db, now=now)
    finally:
        db.close()

    assert verdict is not None
    assert verdict.ratio_used == 1.0
    assert verdict.threshold == 5.0

"""Unit tests for engram_persist health classifier."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from lazy_harness.monitoring.engram_persist_health import collect_engram_persist_health

NOW = datetime(2026, 5, 4, 12, 0, tzinfo=UTC)


def _run_event(
    *,
    when: datetime,
    saved_ok: int = 1,
    saved_failed: int = 0,
    skipped_malformed: int = 0,
    cursor_lag_bytes: dict[str, int] | None = None,
) -> dict[str, Any]:
    return {
        "ts": when.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "event": "run",
        "duration_ms": 100,
        "subprocess_ms": 80,
        "entries_seen": {"decisions": saved_ok, "failures": 0},
        "saved_ok": saved_ok,
        "saved_failed": saved_failed,
        "skipped_malformed": skipped_malformed,
        "cursor_lag_bytes": cursor_lag_bytes or {"decisions": 0, "failures": 0},
        "project_key": "lazy-harness",
        "engram_version": "1.15.6",
        "hook_version": "0.16.0",
    }


def _write(path: Path, events: list[dict[str, Any]]) -> None:
    path.write_text("\n".join(json.dumps(e) for e in events) + "\n")


def test_missing_metrics_file_returns_missing_state(tmp_path: Path) -> None:
    metrics_path = tmp_path / "engram_persist_metrics.jsonl"

    health = collect_engram_persist_health(metrics_path, now=NOW)

    assert health.state == "missing"
    assert health.last_run_age_seconds is None
    assert health.failure_rate is None
    assert health.cursor_lag_bytes is None
    assert health.runs_considered == 0


def test_only_slow_save_events_treated_as_no_runs(tmp_path: Path) -> None:
    metrics_path = tmp_path / "engram_persist_metrics.jsonl"
    metrics_path.write_text(
        json.dumps({"ts": "2026-05-04T11:00:00Z", "event": "slow_save", "ms": 700}) + "\n"
    )

    health = collect_engram_persist_health(metrics_path, now=NOW)

    assert health.state == "missing"
    assert health.runs_considered == 0


def test_recent_run_no_failures_no_lag_is_ok(tmp_path: Path) -> None:
    metrics_path = tmp_path / "engram_persist_metrics.jsonl"
    _write(metrics_path, [_run_event(when=NOW - timedelta(hours=1))])

    health = collect_engram_persist_health(metrics_path, now=NOW)

    assert health.state == "ok"
    assert health.last_run_age_seconds == 3600
    assert health.failure_rate == 0.0
    assert health.cursor_lag_bytes == 0
    assert health.runs_considered == 1


def test_run_between_24h_and_7d_old_is_warn(tmp_path: Path) -> None:
    metrics_path = tmp_path / "engram_persist_metrics.jsonl"
    _write(metrics_path, [_run_event(when=NOW - timedelta(days=2))])

    health = collect_engram_persist_health(metrics_path, now=NOW)

    assert health.state == "warn"


def test_run_older_than_7d_is_fail(tmp_path: Path) -> None:
    metrics_path = tmp_path / "engram_persist_metrics.jsonl"
    _write(metrics_path, [_run_event(when=NOW - timedelta(days=8))])

    health = collect_engram_persist_health(metrics_path, now=NOW)

    assert health.state == "fail"


def test_failure_rate_above_zero_below_ten_percent_is_warn(tmp_path: Path) -> None:
    metrics_path = tmp_path / "engram_persist_metrics.jsonl"
    events = [
        _run_event(when=NOW - timedelta(minutes=30 + i), saved_ok=19, saved_failed=1)
        for i in range(1)
    ]
    _write(metrics_path, events)

    health = collect_engram_persist_health(metrics_path, now=NOW)

    assert health.failure_rate == 0.05
    assert health.state == "warn"


def test_failure_rate_above_ten_percent_is_fail(tmp_path: Path) -> None:
    metrics_path = tmp_path / "engram_persist_metrics.jsonl"
    _write(
        metrics_path,
        [_run_event(when=NOW - timedelta(minutes=10), saved_ok=4, saved_failed=1)],
    )

    health = collect_engram_persist_health(metrics_path, now=NOW)

    assert health.failure_rate == 0.20
    assert health.state == "fail"


def test_cursor_lag_below_64kb_is_warn(tmp_path: Path) -> None:
    metrics_path = tmp_path / "engram_persist_metrics.jsonl"
    _write(
        metrics_path,
        [
            _run_event(
                when=NOW - timedelta(minutes=10),
                cursor_lag_bytes={"decisions": 1024, "failures": 0},
            )
        ],
    )

    health = collect_engram_persist_health(metrics_path, now=NOW)

    assert health.cursor_lag_bytes == 1024
    assert health.state == "warn"


def test_cursor_lag_at_or_above_64kb_is_fail(tmp_path: Path) -> None:
    metrics_path = tmp_path / "engram_persist_metrics.jsonl"
    _write(
        metrics_path,
        [
            _run_event(
                when=NOW - timedelta(minutes=10),
                cursor_lag_bytes={"decisions": 0, "failures": 64 * 1024},
            )
        ],
    )

    health = collect_engram_persist_health(metrics_path, now=NOW)

    assert health.cursor_lag_bytes == 64 * 1024
    assert health.state == "fail"


def test_failure_rate_aggregates_across_window(tmp_path: Path) -> None:
    metrics_path = tmp_path / "engram_persist_metrics.jsonl"
    events = [
        _run_event(when=NOW - timedelta(minutes=10 + i), saved_ok=10, saved_failed=0)
        for i in range(19)
    ]
    events.append(_run_event(when=NOW - timedelta(minutes=5), saved_ok=0, saved_failed=2))
    _write(metrics_path, events)

    health = collect_engram_persist_health(metrics_path, now=NOW)

    assert health.runs_considered == 20
    assert health.failure_rate == 2 / 192
    assert health.state == "warn"


def test_window_excludes_older_runs(tmp_path: Path) -> None:
    metrics_path = tmp_path / "engram_persist_metrics.jsonl"
    old_failure = _run_event(when=NOW - timedelta(hours=2), saved_ok=0, saved_failed=10)
    fresh_runs = [
        _run_event(when=NOW - timedelta(minutes=20 - i), saved_ok=10, saved_failed=0)
        for i in range(20)
    ]
    _write(metrics_path, [old_failure, *fresh_runs])

    health = collect_engram_persist_health(metrics_path, now=NOW, window=20)

    assert health.runs_considered == 20
    assert health.failure_rate == 0.0
    assert health.state == "ok"


def test_worst_of_three_wins(tmp_path: Path) -> None:
    metrics_path = tmp_path / "engram_persist_metrics.jsonl"
    _write(
        metrics_path,
        [
            _run_event(
                when=NOW - timedelta(hours=1),
                saved_ok=10,
                saved_failed=0,
                cursor_lag_bytes={"decisions": 128 * 1024, "failures": 0},
            )
        ],
    )

    health = collect_engram_persist_health(metrics_path, now=NOW)

    assert health.state == "fail"

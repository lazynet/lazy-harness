"""Unit tests for the sink freshness health classifier.

Mirrors tests/monitoring/test_engram_persist_health.py: the classifier is
pure logic (DB + name + now in, a health verdict out), no rendering.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from lazy_harness.core.config import Config, MetricsConfig, MonitoringConfig, SinkDefinition
from lazy_harness.monitoring.db import MetricsDB
from lazy_harness.monitoring.sink_freshness import (
    collect_sink_freshness,
    collect_sinks_freshness,
)

NOW = datetime(2026, 5, 4, 12, 0, tzinfo=UTC)


def test_missing_when_db_file_does_not_exist(tmp_path: Path) -> None:
    result = collect_sink_freshness(tmp_path / "does-not-exist.db", "http_remote", now=NOW)
    assert result.state == "missing"
    assert result.last_enqueued_age_seconds is None


def test_missing_when_db_exists_but_sink_never_enqueued(tmp_path: Path) -> None:
    db_path = tmp_path / "m.db"
    db = MetricsDB(db_path)
    try:
        db.outbox_enqueue(sink_name="other_sink", event_id="e1", payload_json="{}")
    finally:
        db.close()

    result = collect_sink_freshness(db_path, "http_remote", now=NOW)
    assert result.state == "missing"


def test_ok_for_a_recently_enqueued_sink(tmp_path: Path) -> None:
    db_path = tmp_path / "m.db"
    db = MetricsDB(db_path)
    try:
        db.outbox_enqueue(sink_name="http_remote", event_id="e1", payload_json="{}")
        recent_ts = NOW.timestamp() - 300  # 5 minutes ago
        db._conn.execute(
            "UPDATE sink_outbox SET created_ts = ? WHERE event_id = 'e1'", (recent_ts,)
        )
        db._conn.commit()
    finally:
        db.close()

    result = collect_sink_freshness(db_path, "http_remote", now=NOW)
    assert result.state == "ok"
    assert result.last_enqueued_age_seconds == 300


def test_warn_at_24_hours_stale(tmp_path: Path) -> None:
    db_path = tmp_path / "m.db"
    db = MetricsDB(db_path)
    try:
        db.outbox_enqueue(sink_name="http_remote", event_id="e1", payload_json="{}")
        stale_ts = (NOW - timedelta(hours=25)).timestamp()
        db._conn.execute("UPDATE sink_outbox SET created_ts = ? WHERE event_id = 'e1'", (stale_ts,))
        db._conn.commit()
    finally:
        db.close()

    result = collect_sink_freshness(db_path, "http_remote", now=NOW)
    assert result.state == "warn"


def test_fail_at_7_days_stale(tmp_path: Path) -> None:
    """This is the actual incident: five-plus days of silence must not read as healthy."""
    db_path = tmp_path / "m.db"
    db = MetricsDB(db_path)
    try:
        db.outbox_enqueue(sink_name="http_remote", event_id="e1", payload_json="{}")
        stale_ts = (NOW - timedelta(days=8)).timestamp()
        db._conn.execute("UPDATE sink_outbox SET created_ts = ? WHERE event_id = 'e1'", (stale_ts,))
        db._conn.commit()
    finally:
        db.close()

    result = collect_sink_freshness(db_path, "http_remote", now=NOW)
    assert result.state == "fail"


def test_sink_name_scoping_does_not_leak_freshness_across_sinks(tmp_path: Path) -> None:
    db_path = tmp_path / "m.db"
    db = MetricsDB(db_path)
    try:
        db.outbox_enqueue(sink_name="sqlite_local", event_id="e1", payload_json="{}")
    finally:
        db.close()

    result = collect_sink_freshness(db_path, "http_remote", now=NOW)
    assert result.state == "missing"


# --- collect_sinks_freshness: orchestration over plan_sinks() ---


def test_inactive_sink_is_not_checked_at_all(tmp_path: Path, monkeypatch) -> None:
    """An unset url_env deactivates the sink; that must never read as stale."""
    monkeypatch.delenv("LH_METRICS_URL", raising=False)
    cfg = Config(
        monitoring=MonitoringConfig(enabled=True, db=str(tmp_path / "m.db")),
        metrics=MetricsConfig(
            sinks=["sqlite_local", "http_remote"],
            sink_configs={"http_remote": SinkDefinition(options={"url_env": "LH_METRICS_URL"})},
        ),
    )
    results = collect_sinks_freshness(cfg, now=NOW)
    assert results == []


def test_monitoring_disabled_skips_the_check_entirely(tmp_path: Path) -> None:
    """The whole outbox pipeline is a no-op when monitoring is off (lh metrics
    ingest refuses to run), so flagging staleness here would be a false alarm."""
    cfg = Config(
        monitoring=MonitoringConfig(enabled=False, db=str(tmp_path / "m.db")),
        metrics=MetricsConfig(
            sinks=["sqlite_local", "http_remote"],
            sink_configs={"http_remote": SinkDefinition(options={"url": "https://x.invalid/"})},
        ),
    )
    results = collect_sinks_freshness(cfg, now=NOW)
    assert results == []


def test_sqlite_local_is_never_checked_for_freshness(tmp_path: Path) -> None:
    """sqlite_local is always active by construction; it is the store itself,
    not a delivery pipeline that can silently stop moving."""
    cfg = Config(
        monitoring=MonitoringConfig(enabled=True, db=str(tmp_path / "m.db")),
        metrics=MetricsConfig(sinks=["sqlite_local"]),
    )
    results = collect_sinks_freshness(cfg, now=NOW)
    assert results == []


def test_misconfigured_sink_is_skipped_not_raised(tmp_path: Path) -> None:
    """plan_sinks raises for a sink naming no endpoint; the egress section
    already reports that error, so this check must not also blow up."""
    cfg = Config(
        monitoring=MonitoringConfig(enabled=True, db=str(tmp_path / "m.db")),
        metrics=MetricsConfig(
            sinks=["sqlite_local", "http_remote"],
            sink_configs={"http_remote": SinkDefinition(options={})},
        ),
    )
    results = collect_sinks_freshness(cfg, now=NOW)
    assert results == []


def test_active_sink_is_checked_against_the_configured_db(tmp_path: Path) -> None:
    db_path = tmp_path / "m.db"
    db = MetricsDB(db_path)
    try:
        db.outbox_enqueue(sink_name="http_remote", event_id="e1", payload_json="{}")
        stale_ts = (NOW - timedelta(days=8)).timestamp()
        db._conn.execute("UPDATE sink_outbox SET created_ts = ? WHERE event_id = 'e1'", (stale_ts,))
        db._conn.commit()
    finally:
        db.close()

    cfg = Config(
        monitoring=MonitoringConfig(enabled=True, db=str(db_path)),
        metrics=MetricsConfig(
            sinks=["sqlite_local", "http_remote"],
            sink_configs={"http_remote": SinkDefinition(options={"url": "https://x.invalid/"})},
        ),
    )
    results = collect_sinks_freshness(cfg, now=NOW)
    assert len(results) == 1
    assert results[0].name == "http_remote"
    assert results[0].state == "fail"


def test_default_db_path_resolves_via_data_dir_when_monitoring_db_unset(
    tmp_path: Path, monkeypatch
) -> None:
    """Parameter-less path: no [monitoring].db configured, so this must fall
    back to the same default data dir every other reader/writer uses."""
    monkeypatch.setenv("LH_DATA_DIR", str(tmp_path / "data"))
    cfg = Config(
        monitoring=MonitoringConfig(enabled=True),
        metrics=MetricsConfig(
            sinks=["sqlite_local", "http_remote"],
            sink_configs={"http_remote": SinkDefinition(options={"url": "https://x.invalid/"})},
        ),
    )
    # No db file exists yet anywhere: must resolve to "missing", not crash.
    results = collect_sinks_freshness(cfg, now=NOW)
    assert len(results) == 1
    assert results[0].name == "http_remote"
    assert results[0].state == "missing"
    # And must not have created a db file as a side effect (doctor is read-only).
    assert not (tmp_path / "data" / "metrics.db").exists()


# --- delivery health: is the drain moving what ingest enqueued? ---


def _enqueue(db_path: Path, *, attempts: int, error: str = "HTTP 503") -> None:
    db = MetricsDB(db_path)
    try:
        db.outbox_enqueue(sink_name="http_remote", event_id="e1", payload_json="{}")
        for _ in range(attempts):
            db.outbox_mark_failed("http_remote", "e1", error=error, retry_after_seconds=60)
        db._conn.execute(
            "UPDATE sink_outbox SET created_ts = ? WHERE event_id = 'e1'",
            (NOW.timestamp() - 300,),
        )
        db._conn.commit()
    finally:
        db.close()


def test_a_freshly_enqueued_row_the_drain_has_not_reached_yet_is_not_a_problem(
    tmp_path: Path,
) -> None:
    """Ingest enqueues, then drains, in that order. Between the two there is
    always an untried row; flagging it would fire on every healthy run."""
    db_path = tmp_path / "m.db"
    _enqueue(db_path, attempts=0)

    result = collect_sink_freshness(db_path, "http_remote", now=NOW)
    assert result.delivery_state == "ok"
    assert result.undelivered == 1
    assert result.max_attempts == 0


def test_warn_once_the_drain_has_failed_three_times(tmp_path: Path) -> None:
    """The drain runs on every ingest, so three attempts is roughly 45 minutes
    of a sink that is reachable enough to try and never succeeding."""
    db_path = tmp_path / "m.db"
    _enqueue(db_path, attempts=3)

    result = collect_sink_freshness(db_path, "http_remote", now=NOW)
    assert result.delivery_state == "warn"
    assert result.max_attempts == 3
    assert result.last_error == "HTTP 503"


def test_fail_once_the_drain_has_failed_six_times(tmp_path: Path) -> None:
    db_path = tmp_path / "m.db"
    _enqueue(db_path, attempts=6)

    result = collect_sink_freshness(db_path, "http_remote", now=NOW)
    assert result.delivery_state == "fail"


def test_delivery_failure_is_reported_even_when_the_enqueue_age_is_healthy(
    tmp_path: Path,
) -> None:
    """The whole point of the second signal: a dead endpoint keeps accepting
    enqueues, so enqueue age stays green while nothing is being delivered."""
    db_path = tmp_path / "m.db"
    _enqueue(db_path, attempts=6)

    result = collect_sink_freshness(db_path, "http_remote", now=NOW)
    assert result.state == "ok"
    assert result.delivery_state == "fail"


def test_a_drained_backlog_reports_no_delivery_problem(tmp_path: Path) -> None:
    db_path = tmp_path / "m.db"
    db = MetricsDB(db_path)
    try:
        db.outbox_enqueue(sink_name="http_remote", event_id="e1", payload_json="{}")
        db.outbox_mark_failed("http_remote", "e1", error="HTTP 502", retry_after_seconds=60)
        db.outbox_mark_sent("http_remote", "e1")
    finally:
        db.close()

    result = collect_sink_freshness(db_path, "http_remote", now=NOW)
    assert result.delivery_state == "ok"
    assert result.undelivered == 0


def test_an_idle_machine_reports_no_delivery_problem(tmp_path: Path) -> None:
    """Nothing enqueued means nothing to deliver. This is why attempts beats
    age: a stale sink is ambiguous, a failing attempt is not."""
    db_path = tmp_path / "m.db"
    db = MetricsDB(db_path)
    try:
        db.outbox_enqueue(sink_name="http_remote", event_id="e1", payload_json="{}")
        db.outbox_mark_sent("http_remote", "e1")
        stale_ts = (NOW - timedelta(days=8)).timestamp()
        db._conn.execute("UPDATE sink_outbox SET created_ts = ? WHERE event_id = 'e1'", (stale_ts,))
        db._conn.commit()
    finally:
        db.close()

    result = collect_sink_freshness(db_path, "http_remote", now=NOW)
    assert result.state == "fail"
    assert result.delivery_state == "ok"


def test_missing_sink_carries_no_delivery_verdict(tmp_path: Path) -> None:
    result = collect_sink_freshness(tmp_path / "does-not-exist.db", "http_remote", now=NOW)
    assert result.state == "missing"
    assert result.delivery_state == "ok"
    assert result.undelivered == 0

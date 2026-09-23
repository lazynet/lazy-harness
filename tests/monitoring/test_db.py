import json
import sqlite3
import time
from pathlib import Path

import pytest

from lazy_harness.monitoring.db import MetricsDB
from lazy_harness.plugins.contracts import METRIC_EVENT_SCHEMA_VERSION, MetricEvent


def test_new_db_has_identity_columns(tmp_path: Path) -> None:
    db = MetricsDB(tmp_path / "m.db")
    try:
        cols = {row[1] for row in db._conn.execute("PRAGMA table_info(session_stats)").fetchall()}
    finally:
        db.close()
    assert "user_id" in cols
    assert "tenant_id" in cols
    assert "event_id" in cols


def test_migration_adds_columns_to_old_db(tmp_path: Path) -> None:
    """An existing DB without identity columns is upgraded in place."""
    path = tmp_path / "old.db"
    legacy = sqlite3.connect(str(path))
    legacy.execute(
        """
        CREATE TABLE session_stats (
            session TEXT NOT NULL,
            date TEXT NOT NULL,
            model TEXT NOT NULL,
            profile TEXT NOT NULL DEFAULT '',
            project TEXT NOT NULL DEFAULT '',
            input_tokens INTEGER NOT NULL DEFAULT 0,
            output_tokens INTEGER NOT NULL DEFAULT 0,
            cache_read INTEGER NOT NULL DEFAULT 0,
            cache_create INTEGER NOT NULL DEFAULT 0,
            cost REAL NOT NULL DEFAULT 0.0,
            UNIQUE(session, model)
        )
        """
    )
    legacy.execute(
        "INSERT INTO session_stats (session, date, model) VALUES (?, ?, ?)",
        ("s1", "2026-04-01", "sonnet"),
    )
    legacy.commit()
    legacy.close()

    db = MetricsDB(path)
    try:
        row = db._conn.execute(
            "SELECT session, user_id, tenant_id, event_id FROM session_stats WHERE session = 's1'"
        ).fetchone()
    finally:
        db.close()
    assert row["session"] == "s1"
    assert row["user_id"] == "local"
    assert row["tenant_id"] == "local"
    assert row["event_id"] != ""  # backfilled deterministically


def test_migration_is_idempotent(tmp_path: Path) -> None:
    path = tmp_path / "m.db"
    MetricsDB(path).close()
    # Open a second time — should not raise on duplicate column.
    db = MetricsDB(path)
    db.close()


def test_db_enables_wal_and_busy_timeout(tmp_path: Path) -> None:
    db = MetricsDB(tmp_path / "m.db")
    try:
        journal_mode = db._conn.execute("PRAGMA journal_mode").fetchone()[0]
        busy_timeout = db._conn.execute("PRAGMA busy_timeout").fetchone()[0]
    finally:
        db.close()
    assert journal_mode.lower() == "wal"
    assert busy_timeout == 30000


def test_outbox_claim_acquires_write_lock_before_reading(tmp_path: Path) -> None:
    """The claim must BEGIN IMMEDIATE before SELECTing candidates, so two
    processes cannot both read the same pending rows before either commits."""
    db = MetricsDB(tmp_path / "m.db")
    try:
        db.outbox_enqueue(sink_name="http_remote", event_id="e1", payload_json="{}")
        seen: list[str] = []
        db._conn.set_trace_callback(seen.append)
        db.outbox_claim(sink_name="http_remote", batch_size=10, lease_seconds=60)
    finally:
        db._conn.set_trace_callback(None)
        db.close()

    upper = [s.upper() for s in seen]
    begin_idx = next(i for i, s in enumerate(upper) if "BEGIN IMMEDIATE" in s)
    select_idx = next(i for i, s in enumerate(upper) if "SELECT" in s and "SINK_OUTBOX" in s)
    assert begin_idx < select_idx


def test_outbox_claim_rolls_back_when_the_claim_fails(tmp_path: Path) -> None:
    """A failure inside the claim must not leave the connection in a transaction.

    `BEGIN IMMEDIATE` takes a RESERVED lock; if the claim aborts without a
    rollback, the lock is held until the connection dies — the next claim on
    this connection fails with "cannot start a transaction within a
    transaction" and other processes see "database is locked".
    """
    db = MetricsDB(tmp_path / "m.db")
    try:
        db.outbox_enqueue(sink_name="http_remote", event_id="e1", payload_json="{}")
        # Make the UPDATE half of the claim fail the way a constraint or a disk
        # error would: the statement aborts, the transaction stays open.
        db._conn.execute(
            "CREATE TRIGGER fail_claim BEFORE UPDATE ON sink_outbox "
            "BEGIN SELECT RAISE(ABORT, 'injected claim failure'); END"
        )
        db._conn.commit()

        with pytest.raises(sqlite3.DatabaseError):
            db.outbox_claim(sink_name="http_remote", batch_size=10, lease_seconds=60)

        assert db._conn.in_transaction is False
    finally:
        db.close()


def test_outbox_enqueue_starts_pending(tmp_path: Path) -> None:
    db = MetricsDB(tmp_path / "m.db")
    try:
        db.outbox_enqueue(
            sink_name="http_remote",
            event_id="eid1",
            payload_json='{"event_id":"eid1"}',
        )
        rows = db.outbox_list_pending(sink_name="http_remote")
        assert len(rows) == 1
        assert rows[0].status == "pending"
        assert rows[0].attempts == 0
    finally:
        db.close()


def test_outbox_claim_and_mark_sent(tmp_path: Path) -> None:
    db = MetricsDB(tmp_path / "m.db")
    try:
        db.outbox_enqueue(sink_name="http_remote", event_id="e1", payload_json="{}")
        db.outbox_enqueue(sink_name="http_remote", event_id="e2", payload_json="{}")

        claimed = db.outbox_claim(sink_name="http_remote", batch_size=10, lease_seconds=60)
        assert [r.event_id for r in claimed] == ["e1", "e2"]
        for r in claimed:
            assert r.status == "sending"
            assert r.lease_until is not None

        db.outbox_mark_sent("http_remote", "e1")
        remaining = db.outbox_list_pending(sink_name="http_remote")
        assert [r.event_id for r in remaining] == []
        still_sending = db.outbox_list_sending(sink_name="http_remote")
        assert [r.event_id for r in still_sending] == ["e2"]
    finally:
        db.close()


def test_outbox_expired_lease_is_reclaimable(tmp_path: Path) -> None:
    db = MetricsDB(tmp_path / "m.db")
    try:
        db.outbox_enqueue(sink_name="http_remote", event_id="e1", payload_json="{}")
        db.outbox_claim(sink_name="http_remote", batch_size=10, lease_seconds=0)
        time.sleep(0.01)
        reclaimed = db.outbox_claim(sink_name="http_remote", batch_size=10, lease_seconds=60)
        assert [r.event_id for r in reclaimed] == ["e1"]
    finally:
        db.close()


def test_outbox_mark_failed_increments_attempts_and_sets_next(tmp_path: Path) -> None:
    db = MetricsDB(tmp_path / "m.db")
    try:
        db.outbox_enqueue(sink_name="http_remote", event_id="e1", payload_json="{}")
        db.outbox_claim(sink_name="http_remote", batch_size=1, lease_seconds=60)
        db.outbox_mark_failed("http_remote", "e1", error="timeout", retry_after_seconds=30)

        rows = db.outbox_list_pending(sink_name="http_remote", due_now=False)
        assert len(rows) == 1
        assert rows[0].attempts == 1
        assert rows[0].last_error == "timeout"
        assert rows[0].status == "pending"
        assert rows[0].next_attempt_ts is not None
    finally:
        db.close()


def test_outbox_dedupe_by_event_id_on_enqueue(tmp_path: Path) -> None:
    """Enqueueing the same (sink, event_id) twice updates the row, not duplicates it."""
    db = MetricsDB(tmp_path / "m.db")
    try:
        db.outbox_enqueue(sink_name="http_remote", event_id="e1", payload_json='{"v":1}')
        db.outbox_enqueue(sink_name="http_remote", event_id="e1", payload_json='{"v":2}')
        rows = db.outbox_list_pending(sink_name="http_remote")
        assert len(rows) == 1
        assert json.loads(rows[0].payload_json)["v"] == 2
    finally:
        db.close()


def test_outbox_enqueue_leaves_a_delivered_row_alone_when_the_payload_is_unchanged(
    tmp_path: Path,
) -> None:
    """An unchanged re-enqueue must not undo delivery.

    `ingest` re-emits an event for every (session, model) it can still read on
    every run, so a finished session is re-enqueued with a byte-identical
    payload forever. Flipping those rows back to 'pending' put the outbox on a
    treadmill: `outbox_claim` orders by `created_ts`, so the drain re-sent the
    same oldest batch every run and never reached anything newer.
    """
    db = MetricsDB(tmp_path / "m.db")
    try:
        db.outbox_enqueue(sink_name="http_remote", event_id="e1", payload_json='{"v":1}')
        db.outbox_mark_sent("http_remote", "e1")

        db.outbox_enqueue(sink_name="http_remote", event_id="e1", payload_json='{"v":1}')

        stats = db.outbox_stats("http_remote")
        assert stats["sent"] == 1
        assert stats["pending"] == 0
    finally:
        db.close()


def test_outbox_enqueue_requeues_a_delivered_row_when_the_payload_changed(
    tmp_path: Path,
) -> None:
    """A live session's totals grow, and the newer numbers must still be sent.

    Guards the shape of the unchanged-payload fix above: suppressing every
    conflict (`DO NOTHING`) would also pass that test while permanently
    freezing a session at whatever totals it happened to have when it was
    first delivered.
    """
    db = MetricsDB(tmp_path / "m.db")
    try:
        db.outbox_enqueue(sink_name="http_remote", event_id="e1", payload_json='{"v":1}')
        db.outbox_mark_sent("http_remote", "e1")

        db.outbox_enqueue(sink_name="http_remote", event_id="e1", payload_json='{"v":2}')

        rows = db.outbox_list_pending(sink_name="http_remote")
        assert len(rows) == 1
        assert json.loads(rows[0].payload_json)["v"] == 2
    finally:
        db.close()


def test_outbox_last_enqueued_ts_is_none_for_a_sink_with_no_rows(tmp_path: Path) -> None:
    db = MetricsDB(tmp_path / "m.db")
    try:
        assert db.outbox_last_enqueued_ts("http_remote") is None
    finally:
        db.close()


def test_outbox_last_enqueued_ts_reflects_the_newest_row_regardless_of_status(
    tmp_path: Path,
) -> None:
    """created_ts is when the event was enqueued, not when it was last sent —
    a sink that has drained everything to 'sent' is not thereby "fresh"."""
    db = MetricsDB(tmp_path / "m.db")
    try:
        db.outbox_enqueue(sink_name="http_remote", event_id="e1", payload_json="{}")
        db._conn.execute("UPDATE sink_outbox SET created_ts = ? WHERE event_id = 'e1'", (1000.0,))
        db.outbox_enqueue(sink_name="http_remote", event_id="e2", payload_json="{}")
        db._conn.execute("UPDATE sink_outbox SET created_ts = ? WHERE event_id = 'e2'", (2000.0,))
        db.outbox_mark_sent("http_remote", "e1")
        db.outbox_mark_sent("http_remote", "e2")
        assert db.outbox_last_enqueued_ts("http_remote") == 2000.0
    finally:
        db.close()


def test_outbox_last_enqueued_ts_is_scoped_to_the_named_sink(tmp_path: Path) -> None:
    db = MetricsDB(tmp_path / "m.db")
    try:
        db.outbox_enqueue(sink_name="http_remote", event_id="e1", payload_json="{}")
        assert db.outbox_last_enqueued_ts("other_sink") is None
    finally:
        db.close()


def test_outbox_delivery_health_reports_untried_rows_as_zero_attempts(tmp_path: Path) -> None:
    db = MetricsDB(tmp_path / "m.db")
    db.outbox_enqueue(sink_name="http_remote", event_id="e1", payload_json="{}")

    health = db.outbox_delivery_health("http_remote")

    assert health["undelivered"] == 1
    assert health["max_attempts"] == 0
    assert health["last_error"] == ""


def test_outbox_delivery_health_surfaces_the_worst_attempt_count_and_its_error(
    tmp_path: Path,
) -> None:
    db = MetricsDB(tmp_path / "m.db")
    db.outbox_enqueue(sink_name="http_remote", event_id="e1", payload_json="{}")
    db.outbox_enqueue(sink_name="http_remote", event_id="e2", payload_json="{}")
    db.outbox_mark_failed("http_remote", "e1", error="HTTP 502", retry_after_seconds=60)
    for _ in range(3):
        db.outbox_mark_failed("http_remote", "e2", error="HTTP 503", retry_after_seconds=60)

    health = db.outbox_delivery_health("http_remote")

    assert health["undelivered"] == 2
    assert health["max_attempts"] == 3
    assert health["last_error"] == "HTTP 503"


def test_outbox_delivery_health_reports_the_oldest_undelivered_timestamp(
    tmp_path: Path,
) -> None:
    """Attempts alone cannot see a queue that stalls while every POST succeeds.

    The treadmill delivered a batch, had it resurrected, and re-delivered it —
    `attempts` stayed 0 the whole time, so a health check reading only
    `MAX(attempts)` reported perfect health over a six-day-old backlog. Age of
    the oldest undelivered row is the signal that survives that.
    """
    db = MetricsDB(tmp_path / "m.db")
    try:
        db.outbox_enqueue(sink_name="http_remote", event_id="old", payload_json="{}")
        db._conn.execute("UPDATE sink_outbox SET created_ts = ? WHERE event_id = 'old'", (1000.0,))
        db.outbox_enqueue(sink_name="http_remote", event_id="new", payload_json="{}")
        db._conn.execute("UPDATE sink_outbox SET created_ts = ? WHERE event_id = 'new'", (5000.0,))

        health = db.outbox_delivery_health("http_remote")

        assert health["max_attempts"] == 0
        assert health["oldest_undelivered_ts"] == 1000.0
    finally:
        db.close()


def test_outbox_delivery_health_has_no_oldest_undelivered_when_all_sent(
    tmp_path: Path,
) -> None:
    db = MetricsDB(tmp_path / "m.db")
    try:
        db.outbox_enqueue(sink_name="http_remote", event_id="e1", payload_json="{}")
        db.outbox_mark_sent("http_remote", "e1")

        assert db.outbox_delivery_health("http_remote")["oldest_undelivered_ts"] is None
    finally:
        db.close()


def test_outbox_delivery_health_ignores_rows_already_sent(tmp_path: Path) -> None:
    """A drained backlog is the healthy state, not a silent one."""
    db = MetricsDB(tmp_path / "m.db")
    db.outbox_enqueue(sink_name="http_remote", event_id="e1", payload_json="{}")
    db.outbox_mark_failed("http_remote", "e1", error="HTTP 502", retry_after_seconds=60)
    db.outbox_mark_sent("http_remote", "e1")

    health = db.outbox_delivery_health("http_remote")

    assert health["undelivered"] == 0
    assert health["max_attempts"] == 0
    assert health["last_error"] == ""


def test_outbox_delivery_health_counts_a_row_stuck_in_sending(tmp_path: Path) -> None:
    """A process that died mid-POST leaves 'sending' behind; that is undelivered,
    and outbox_claim only reclaims it once the lease expires."""
    db = MetricsDB(tmp_path / "m.db")
    db.outbox_enqueue(sink_name="http_remote", event_id="e1", payload_json="{}")
    db.outbox_claim(sink_name="http_remote", batch_size=10, lease_seconds=300)

    health = db.outbox_delivery_health("http_remote")

    assert health["undelivered"] == 1


def test_outbox_delivery_health_is_scoped_to_one_sink(tmp_path: Path) -> None:
    db = MetricsDB(tmp_path / "m.db")
    db.outbox_enqueue(sink_name="other_sink", event_id="e1", payload_json="{}")
    db.outbox_mark_failed("other_sink", "e1", error="HTTP 500", retry_after_seconds=60)

    health = db.outbox_delivery_health("http_remote")

    assert health["undelivered"] == 0
    assert health["max_attempts"] == 0


def _event(**over: object) -> MetricEvent:
    base = dict(
        event_id="e1",
        schema_version=METRIC_EVENT_SCHEMA_VERSION,
        user_id="martin",
        tenant_id="local",
        profile="lazy",
        session="s1",
        model="sonnet",
        project="lazy-harness",
        date="2026-08-31",
        input_tokens=10,
        output_tokens=5,
        cache_read=0,
        cache_create=0,
        cost=0.01,
    )
    base.update(over)
    return MetricEvent(**base)  # type: ignore[arg-type]


@pytest.mark.parametrize("writer", ["event", "upsert_stats", "insert_stats"])
@pytest.mark.parametrize("replay", ["event", "upsert_stats"])
@pytest.mark.parametrize("equivalent", [2.5, None])
def test_all_metrics_writers_preserve_v4_costs_against_legacy_replay(
    tmp_path: Path, writer: str, replay: str, equivalent: float | None
) -> None:
    from dataclasses import asdict

    enriched = _event(
        cost=1.25,
        billed_cost=1.25,
        billed_cost_source="pricing",
        billing_model="per_token",
        api_equivalent_cost=equivalent,
        api_equivalent_status="priced" if equivalent is not None else "unknown_tier",
        api_price_basis={"version": "test"},
    )
    db = MetricsDB(tmp_path / "m.db")
    try:
        if writer == "event":
            db.upsert_event(enriched)
        else:
            entry = asdict(enriched)
            entry.pop("schema_version")
            getattr(db, writer)([entry])
        if replay == "event":
            db.upsert_event(_event(schema_version=3, cost=0.1, billing_model="flat_rate"))
        else:
            db.upsert_stats(
                [
                    {
                        "session": enriched.session,
                        "model": enriched.model,
                        "date": enriched.date,
                        "cost": 0.1,
                        "billing_model": "flat_rate",
                    }
                ]
            )

        rows = db.query_stats()
        assert len(rows) == 1
        assert rows[0]["cost"] == 1.25
        assert rows[0]["billed_cost"] == 1.25
        assert rows[0]["billing_model"] == "per_token"
        assert rows[0]["billed_cost_source"] == "pricing"
        assert rows[0]["api_equivalent_cost"] == equivalent
        assert rows[0]["api_equivalent_status"] == enriched.api_equivalent_status
        assert json.loads(rows[0]["api_price_basis"]) == {"version": "test"}
        summary = db.aggregate_costs()
        assert summary["total_cost"] == summary["billed_cost"] == 1.25
    finally:
        db.close()


def test_local_metrics_can_enrich_legacy_rows_and_update_equal_versions(tmp_path: Path) -> None:
    db = MetricsDB(tmp_path / "m.db")
    try:
        db.upsert_event(_event(schema_version=3, cost=0.1))
        for cost in (1.25, 2.5):
            db.upsert_stats(
                [
                    {
                        "session": "s1",
                        "model": "sonnet",
                        "date": "2026-09-19",
                        "cost": cost,
                        "billed_cost": cost,
                        "billed_cost_source": "pricing",
                        "api_equivalent_cost": cost * 2,
                        "api_equivalent_status": "priced",
                    }
                ]
            )
            db.upsert_event(_event(schema_version=3, cost=0.1))
            row = db.query_stats()[0]
            assert row["cost"] == row["billed_cost"] == cost
            assert row["api_equivalent_cost"] == cost * 2
    finally:
        db.close()


def test_new_db_has_host_and_workload_columns(tmp_path: Path) -> None:
    db = MetricsDB(tmp_path / "m.db")
    try:
        cols = {row[1] for row in db._conn.execute("PRAGMA table_info(session_stats)").fetchall()}
    finally:
        db.close()
    assert "host" in cols
    assert "workload" in cols


def test_migration_adds_host_and_workload_to_an_identity_era_db(tmp_path: Path) -> None:
    """A DB created after the identity columns but before ADR-037."""
    path = tmp_path / "mid.db"
    legacy = sqlite3.connect(str(path))
    legacy.execute(
        """
        CREATE TABLE session_stats (
            session TEXT NOT NULL,
            date TEXT NOT NULL,
            model TEXT NOT NULL,
            profile TEXT NOT NULL DEFAULT '',
            project TEXT NOT NULL DEFAULT '',
            input_tokens INTEGER NOT NULL DEFAULT 0,
            output_tokens INTEGER NOT NULL DEFAULT 0,
            cache_read INTEGER NOT NULL DEFAULT 0,
            cache_create INTEGER NOT NULL DEFAULT 0,
            cost REAL NOT NULL DEFAULT 0.0,
            user_id TEXT NOT NULL DEFAULT 'local',
            tenant_id TEXT NOT NULL DEFAULT 'local',
            event_id TEXT NOT NULL DEFAULT '',
            UNIQUE(session, model)
        )
        """
    )
    legacy.execute(
        "INSERT INTO session_stats (session, date, model, cost) VALUES (?, ?, ?, ?)",
        ("old", "2026-04-01", "sonnet", 1.25),
    )
    legacy.commit()
    legacy.close()

    db = MetricsDB(path)
    try:
        row = db._conn.execute(
            "SELECT session, cost, host, workload FROM session_stats WHERE session = 'old'"
        ).fetchone()
    finally:
        db.close()
    assert row["cost"] == 1.25, "a v1 row must survive the migration untouched"
    assert row["host"] == ""
    assert row["workload"] == ""


def test_session_attribution_roundtrips_by_session(tmp_path: Path) -> None:
    db = MetricsDB(tmp_path / "m.db")
    try:
        db.set_attribution(session="sess-a", workload="vault-pass", host="agents")
        assert db.attribution_map() == {"sess-a": "vault-pass"}
    finally:
        db.close()


def test_set_attribution_overwrites_the_same_session(tmp_path: Path) -> None:
    """`lh exec` reconciles the row when the agent reports a different id."""
    db = MetricsDB(tmp_path / "m.db")
    try:
        db.set_attribution(session="sess-a", workload="first", host="agents")
        db.set_attribution(session="sess-a", workload="second", host="agents")
        assert db.attribution_map() == {"sess-a": "second"}
    finally:
        db.close()


def test_attribution_map_is_empty_on_a_fresh_db(tmp_path: Path) -> None:
    db = MetricsDB(tmp_path / "m.db")
    try:
        assert db.attribution_map() == {}
    finally:
        db.close()


def test_upsert_event_stores_host_and_workload(tmp_path: Path) -> None:
    db = MetricsDB(tmp_path / "m.db")
    try:
        db.upsert_event(_event(host="agents", workload="nightly"))
        row = db._conn.execute(
            "SELECT host, workload FROM session_stats WHERE session = 's1'"
        ).fetchone()
    finally:
        db.close()
    assert row["host"] == "agents"
    assert row["workload"] == "nightly"


def test_upsert_event_updates_host_and_workload_on_conflict(tmp_path: Path) -> None:
    db = MetricsDB(tmp_path / "m.db")
    try:
        db.upsert_event(_event(host="mac", workload=""))
        db.upsert_event(_event(host="agents", workload="nightly"))
        rows = db._conn.execute(
            "SELECT host, workload FROM session_stats WHERE session = 's1'"
        ).fetchall()
    finally:
        db.close()
    assert len(rows) == 1
    assert rows[0]["host"] == "agents"
    assert rows[0]["workload"] == "nightly"


def test_query_stats_projects_host_and_workload(tmp_path: Path) -> None:
    """`query_stats` builds a fixed dict, so a new column is invisible until named."""
    db = MetricsDB(tmp_path / "m.db")
    try:
        db.upsert_event(_event(host="agents", workload="nightly"))
        rows = db.query_stats()
    finally:
        db.close()
    assert len(rows) == 1
    assert rows[0]["host"] == "agents"
    assert rows[0]["workload"] == "nightly"


def test_query_stats_reports_empty_strings_for_a_row_written_by_upsert_stats(
    tmp_path: Path,
) -> None:
    """`upsert_stats` never wrote identity columns; that shape must still read."""
    db = MetricsDB(tmp_path / "m.db")
    try:
        db.upsert_stats(
            [
                {
                    "session": "s9",
                    "date": "2026-08-31",
                    "model": "sonnet",
                    "profile": "lazy",
                    "project": "p",
                    "cost": 0.5,
                }
            ]
        )
        rows = db.query_stats()
    finally:
        db.close()
    assert rows[0]["host"] == ""
    assert rows[0]["workload"] == ""
    assert rows[0]["cost"] == 0.5


def test_new_db_has_agent_and_billing_model_columns(tmp_path: Path) -> None:
    db = MetricsDB(tmp_path / "m.db")
    try:
        cols = {row[1] for row in db._conn.execute("PRAGMA table_info(session_stats)").fetchall()}
    finally:
        db.close()
    assert "agent" in cols
    assert "billing_model" in cols


def test_new_db_has_separate_billed_and_api_equivalent_columns(tmp_path: Path) -> None:
    db = MetricsDB(tmp_path / "m.db")
    try:
        cols = {row[1] for row in db._conn.execute("PRAGMA table_info(session_stats)")}
    finally:
        db.close()
    assert {
        "billed_cost",
        "billed_cost_source",
        "api_equivalent_cost",
        "api_equivalent_status",
        "api_price_basis",
    } <= cols


def test_v4_migration_backfills_only_legacy_billed_semantics(tmp_path: Path) -> None:
    path = tmp_path / "v3.db"
    legacy = sqlite3.connect(str(path))
    legacy.execute(
        """
        CREATE TABLE session_stats (
            session TEXT NOT NULL, date TEXT NOT NULL, model TEXT NOT NULL,
            profile TEXT NOT NULL DEFAULT '', project TEXT NOT NULL DEFAULT '',
            input_tokens INTEGER NOT NULL DEFAULT 0,
            output_tokens INTEGER NOT NULL DEFAULT 0,
            cache_read INTEGER NOT NULL DEFAULT 0,
            cache_create INTEGER NOT NULL DEFAULT 0,
            cost REAL NOT NULL DEFAULT 0.0,
            user_id TEXT NOT NULL DEFAULT 'local',
            tenant_id TEXT NOT NULL DEFAULT 'local',
            event_id TEXT NOT NULL DEFAULT '', host TEXT NOT NULL DEFAULT '',
            workload TEXT NOT NULL DEFAULT '', agent TEXT NOT NULL DEFAULT '',
            billing_model TEXT NOT NULL DEFAULT 'per_token',
            UNIQUE(session, model)
        )
        """
    )
    legacy.executemany(
        "INSERT INTO session_stats (session, date, model, cost, billing_model) "
        "VALUES (?, ?, ?, ?, ?)",
        [
            ("metered", "2026-09-19", "known", 1.25, "per_token"),
            ("sub", "2026-09-19", "gpt-5.6-sol", 0.0, "flat_rate"),
        ],
    )
    legacy.commit()
    legacy.close()

    db = MetricsDB(path)
    try:
        rows = {row["session"]: row for row in db.query_stats(period="all")}
    finally:
        db.close()

    assert rows["metered"]["billed_cost"] == 1.25
    assert rows["metered"]["billed_cost_source"] == "unknown"
    assert rows["sub"]["billed_cost"] is None
    assert rows["sub"]["billed_cost_source"] == "subscription"
    assert rows["sub"]["api_equivalent_cost"] is None
    assert rows["sub"]["api_equivalent_status"] is None


def test_same_event_id_replay_enriches_v3_row_without_duplication(tmp_path: Path) -> None:
    db = MetricsDB(tmp_path / "m.db")
    try:
        db.upsert_event(_event(schema_version=3, event_id="stable", cost=1.0))
        db.upsert_event(
            _event(
                schema_version=4,
                event_id="stable",
                cost=1.0,
                billed_cost=1.0,
                billed_cost_source="pricing",
                api_equivalent_cost=2.0,
                api_equivalent_status="priced",
                api_price_basis={"provider": "openai"},
            )
        )
        rows = db.query_stats(period="all")
    finally:
        db.close()
    assert len(rows) == 1
    assert rows[0]["billed_cost"] == 1.0
    assert rows[0]["api_equivalent_cost"] == 2.0
    assert rows[0]["api_equivalent_status"] == "priced"


def test_v3_replay_does_not_degrade_an_enriched_v4_row(tmp_path: Path) -> None:
    db = MetricsDB(tmp_path / "m.db")
    try:
        db.upsert_event(
            _event(
                schema_version=4,
                event_id="stable",
                billed_cost=1.0,
                billed_cost_source="pricing",
                api_equivalent_cost=2.0,
                api_equivalent_status="priced",
                api_price_basis={"provider": "openai"},
            )
        )
        db.upsert_event(_event(schema_version=3, event_id="stable", cost=1.0))
        rows = db.query_stats(period="all")
    finally:
        db.close()

    assert len(rows) == 1
    assert rows[0]["billed_cost"] == 1.0
    assert rows[0]["billed_cost_source"] == "pricing"
    assert rows[0]["api_equivalent_cost"] == 2.0
    assert rows[0]["api_equivalent_status"] == "priced"
    assert json.loads(rows[0]["api_price_basis"]) == {"provider": "openai"}


def test_migration_adds_agent_and_billing_model_to_a_pre_v3_db(tmp_path: Path) -> None:
    """A DB created after host/workload (ADR-037) but before ADR-050."""
    path = tmp_path / "mid.db"
    legacy = sqlite3.connect(str(path))
    legacy.execute(
        """
        CREATE TABLE session_stats (
            session TEXT NOT NULL,
            date TEXT NOT NULL,
            model TEXT NOT NULL,
            profile TEXT NOT NULL DEFAULT '',
            project TEXT NOT NULL DEFAULT '',
            input_tokens INTEGER NOT NULL DEFAULT 0,
            output_tokens INTEGER NOT NULL DEFAULT 0,
            cache_read INTEGER NOT NULL DEFAULT 0,
            cache_create INTEGER NOT NULL DEFAULT 0,
            cost REAL NOT NULL DEFAULT 0.0,
            user_id TEXT NOT NULL DEFAULT 'local',
            tenant_id TEXT NOT NULL DEFAULT 'local',
            event_id TEXT NOT NULL DEFAULT '',
            host TEXT NOT NULL DEFAULT '',
            workload TEXT NOT NULL DEFAULT '',
            UNIQUE(session, model)
        )
        """
    )
    legacy.execute(
        "INSERT INTO session_stats (session, date, model, cost) VALUES (?, ?, ?, ?)",
        ("old", "2026-04-01", "sonnet", 1.25),
    )
    legacy.commit()
    legacy.close()

    db = MetricsDB(path)
    try:
        row = db._conn.execute(
            "SELECT session, cost, agent, billing_model FROM session_stats WHERE session = 'old'"
        ).fetchone()
    finally:
        db.close()
    assert row["cost"] == 1.25, "a pre-v3 row must survive the migration untouched"
    assert row["agent"] == ""
    assert row["billing_model"] == "per_token"


def test_upsert_event_stores_agent_and_billing_model(tmp_path: Path) -> None:
    db = MetricsDB(tmp_path / "m.db")
    try:
        db.upsert_event(_event(agent="claude-code", billing_model="flat_rate"))
        row = db._conn.execute(
            "SELECT agent, billing_model FROM session_stats WHERE session = 's1'"
        ).fetchone()
    finally:
        db.close()
    assert row["agent"] == "claude-code"
    assert row["billing_model"] == "flat_rate"


def test_upsert_event_updates_agent_and_billing_model_on_conflict(tmp_path: Path) -> None:
    db = MetricsDB(tmp_path / "m.db")
    try:
        db.upsert_event(_event(agent="claude-code", billing_model="per_token"))
        db.upsert_event(_event(agent="codex", billing_model="flat_rate"))
        rows = db._conn.execute(
            "SELECT agent, billing_model FROM session_stats WHERE session = 's1'"
        ).fetchall()
    finally:
        db.close()
    assert len(rows) == 1
    assert rows[0]["agent"] == "codex"
    assert rows[0]["billing_model"] == "flat_rate"


def test_query_stats_projects_agent_and_billing_model(tmp_path: Path) -> None:
    db = MetricsDB(tmp_path / "m.db")
    try:
        db.upsert_event(_event(agent="claude-code", billing_model="flat_rate"))
        rows = db.query_stats()
    finally:
        db.close()
    assert len(rows) == 1
    assert rows[0]["agent"] == "claude-code"
    assert rows[0]["billing_model"] == "flat_rate"


def test_upsert_stats_stores_agent_and_billing_model(tmp_path: Path) -> None:
    """`upsert_stats` is ingest's default write path, not just the opt-in
    `sqlite_local` sink's `upsert_event` — the dimension must reach it too."""
    db = MetricsDB(tmp_path / "m.db")
    try:
        db.upsert_stats(
            [
                {
                    "session": "s9",
                    "date": "2026-08-31",
                    "model": "sonnet",
                    "profile": "lazy",
                    "project": "p",
                    "cost": 0.5,
                    "agent": "claude-code",
                    "billing_model": "flat_rate",
                }
            ]
        )
        rows = db.query_stats()
    finally:
        db.close()
    assert rows[0]["agent"] == "claude-code"
    assert rows[0]["billing_model"] == "flat_rate"


def test_upsert_stats_defaults_agent_and_billing_model_when_absent(tmp_path: Path) -> None:
    db = MetricsDB(tmp_path / "m.db")
    try:
        db.upsert_stats([{"session": "s9", "date": "2026-08-31", "model": "sonnet", "cost": 0.5}])
        rows = db.query_stats()
    finally:
        db.close()
    assert rows[0]["agent"] == ""
    assert rows[0]["billing_model"] == "per_token"


def test_delete_attribution_removes_only_the_named_session(tmp_path: Path) -> None:
    """Reconciliation moves a row; it must not leave the stale one behind.

    An adapter that cannot pin a session id would otherwise leave one orphan
    per run — the pinned id never reaches the agent, so every run writes a row
    nothing joins alongside the real one.
    """
    db = MetricsDB(tmp_path / "m.db")
    try:
        db.set_attribution(session="pinned", workload="w")
        db.set_attribution(session="reported", workload="w")
        db.delete_attribution("pinned")
        assert db.attribution_map() == {"reported": "w"}
    finally:
        db.close()


def test_delete_attribution_is_silent_for_an_unknown_session(tmp_path: Path) -> None:
    db = MetricsDB(tmp_path / "m.db")
    try:
        db.delete_attribution("never-existed")
        assert db.attribution_map() == {}
    finally:
        db.close()


# --- host backfill ----------------------------------------------------------


def test_backfill_host_stamps_only_the_rows_that_have_none(tmp_path: Path) -> None:
    """A local metrics DB only ever holds sessions ingested on that machine, so
    stamping the local host on a row that has none is lossless. A row that
    already names a host is an answer someone else wrote and must be left alone."""
    db = MetricsDB(tmp_path / "m.db")
    try:
        db.upsert_event(_event(event_id="e-old", session="s-old", host=""))
        db.upsert_event(_event(event_id="e-new", session="s-new", host="OtherBox"))

        report = db.backfill_host("LazyMBP")

        rows = {r["session"]: r["host"] for r in db.query_stats()}
        assert rows["s-old"] == "LazyMBP"
        assert rows["s-new"] == "OtherBox"
        assert report.rows_stamped == 1
    finally:
        db.close()


def test_backfill_host_is_idempotent(tmp_path: Path) -> None:
    """The second run finds nothing left to stamp. A backfill that keeps
    reporting work is indistinguishable from one that never applied."""
    db = MetricsDB(tmp_path / "m.db")
    try:
        db.upsert_event(_event(event_id="e-old", session="s-old", host=""))
        db.backfill_host("LazyMBP")

        second = db.backfill_host("LazyMBP")

        assert second.rows_stamped == 0
        assert second.events_requeued == 0
    finally:
        db.close()


def test_backfill_host_requeues_an_event_the_remote_already_has(tmp_path: Path) -> None:
    """The remote upserts by event_id and event_id does not include host, so a
    resend corrects the row in place. Without the requeue the local store and
    the dashboard disagree forever, with no error on either side."""
    db = MetricsDB(tmp_path / "m.db")
    try:
        db.upsert_event(_event(event_id="e-old", session="s-old", host=""))
        db.outbox_enqueue(
            sink_name="http_remote",
            event_id="e-old",
            payload_json=json.dumps({"event_id": "e-old", "host": "", "cost": 0.01}),
        )
        db.outbox_mark_sent("http_remote", "e-old")

        report = db.backfill_host("LazyMBP")

        pending = db.outbox_list_pending(sink_name="http_remote")
        assert report.events_requeued == 1
        assert len(pending) == 1
        payload = json.loads(pending[0].payload_json)
        assert payload["host"] == "LazyMBP"
        assert payload["cost"] == 0.01

    finally:
        db.close()


def test_backfill_host_leaves_a_stamped_row_with_no_outbox_entry_alone(tmp_path: Path) -> None:
    """A row the outbox never carried was never sent, so there is nothing to
    correct remotely. Minting an entry would push history the remote never had
    under the guise of a fix."""
    db = MetricsDB(tmp_path / "m.db")
    try:
        db.upsert_event(_event(event_id="e-orphan", session="s-orphan", host=""))

        report = db.backfill_host("LazyMBP")

        assert report.rows_stamped == 1
        assert report.events_requeued == 0
        assert db.outbox_list_pending(sink_name="http_remote") == []
    finally:
        db.close()


# --- rename_profile (Task 5) ------------------------------------------------- #


def test_rename_profile_table_list_is_complete(tmp_path: Path) -> None:
    """A table gaining a `profile` column must be added to `RENAME_PROFILE_TABLES`
    or a rename silently stops covering it."""
    from lazy_harness.monitoring.db import RENAME_PROFILE_TABLES

    db = MetricsDB(tmp_path / "m.db")
    try:
        tables = {
            row["name"]
            for row in db._conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        with_profile = {
            name
            for name in tables
            if any(
                col["name"] == "profile"
                for col in db._conn.execute(f"PRAGMA table_info({name})").fetchall()
            )
        }
        assert with_profile == set(RENAME_PROFILE_TABLES)
    finally:
        db.close()


def test_rename_profile_recomputes_event_id_and_renames_all_three_tables(
    tmp_path: Path,
) -> None:
    from lazy_harness.monitoring.event_id import derive_event_id

    db = MetricsDB(tmp_path / "m.db")
    try:
        db.upsert_event(_event(event_id="e-old", profile="lazy", session="s1", model="sonnet"))
        db.record_loop_event(session="s1", kind="verify_ran", project="p", profile="lazy")
        db._conn.execute(
            "INSERT INTO launches (ts, profile, agent, host, entry) VALUES (?, ?, ?, ?, ?)",
            (time.time(), "lazy", "claude-code", "h", "run"),
        )
        db._conn.commit()

        counts = db.rename_profile("lazy", "claude-lazy")

        assert counts == {"session_stats": 1, "loop_events": 1, "launches": 1}
        row = db._conn.execute(
            "SELECT profile, event_id FROM session_stats WHERE session = 's1'"
        ).fetchone()
        assert row["profile"] == "claude-lazy"
        assert row["event_id"] == derive_event_id(
            profile="claude-lazy", session="s1", model="sonnet"
        )
        assert (
            db._conn.execute("SELECT profile FROM loop_events WHERE session = 's1'").fetchone()[
                "profile"
            ]
            == "claude-lazy"
        )
        assert (
            db._conn.execute("SELECT profile FROM launches").fetchone()["profile"] == "claude-lazy"
        )
    finally:
        db.close()


def test_rename_profile_is_idempotent(tmp_path: Path) -> None:
    db = MetricsDB(tmp_path / "m.db")
    try:
        db.upsert_event(_event(event_id="e-old", profile="lazy", session="s1", model="sonnet"))

        db.rename_profile("lazy", "claude-lazy")
        second = db.rename_profile("lazy", "claude-lazy")

        assert second == {"session_stats": 0, "loop_events": 0, "launches": 0}
    finally:
        db.close()


def test_rename_profile_leaves_preexisting_target_rows_untouched(tmp_path: Path) -> None:
    db = MetricsDB(tmp_path / "m.db")
    try:
        db.upsert_event(
            _event(event_id="e-already-new", profile="claude-lazy", session="s-existing")
        )
        db.upsert_event(_event(event_id="e-old", profile="lazy", session="s1"))

        counts = db.rename_profile("lazy", "claude-lazy")

        assert counts["session_stats"] == 1
        untouched = db._conn.execute(
            "SELECT event_id FROM session_stats WHERE session = 's-existing'"
        ).fetchone()
        assert untouched["event_id"] == "e-already-new"
    finally:
        db.close()


def test_rename_profile_refuses_when_old_equals_new(tmp_path: Path) -> None:
    from lazy_harness.monitoring.db import RenameProfileError

    db = MetricsDB(tmp_path / "m.db")
    try:
        with pytest.raises(RenameProfileError, match="lazy"):
            db.rename_profile("lazy", "lazy")
    finally:
        db.close()


def test_rename_profile_blocks_on_a_pending_outbox_row_and_names_the_count(
    tmp_path: Path,
) -> None:
    db = MetricsDB(tmp_path / "m.db")
    try:
        from lazy_harness.monitoring.db import RenameProfileError

        db.upsert_event(_event(event_id="e-old", profile="lazy", session="s1"))
        db.outbox_enqueue(sink_name="http_remote", event_id="e-old", payload_json="{}")

        with pytest.raises(RenameProfileError, match="1"):
            db.rename_profile("lazy", "claude-lazy")

        # Refused before touching anything.
        row = db._conn.execute(
            "SELECT profile, event_id FROM session_stats WHERE session = 's1'"
        ).fetchone()
        assert row["profile"] == "lazy"
        assert row["event_id"] == "e-old"
    finally:
        db.close()


def test_rename_profile_proceeds_once_the_outbox_row_is_no_longer_pending(
    tmp_path: Path,
) -> None:
    db = MetricsDB(tmp_path / "m.db")
    try:
        db.upsert_event(_event(event_id="e-old", profile="lazy", session="s1"))
        db.outbox_enqueue(sink_name="http_remote", event_id="e-old", payload_json="{}")
        db.outbox_mark_sent("http_remote", "e-old")

        counts = db.rename_profile("lazy", "claude-lazy")

        assert counts["session_stats"] == 1
    finally:
        db.close()


def test_rename_profile_blocks_on_a_pending_row_whose_session_stats_row_was_rekeyed(
    tmp_path: Path,
) -> None:
    """The re-keyed-row sequence from the review report: `upsert_event` moves a
    row's `event_id` in place (`ON CONFLICT(session, model) DO UPDATE`), so a
    pending outbox row enqueued under the old event_id no longer joins to any
    `session_stats` row at all — the JOIN-only guard misses it. The payload
    still carries the old profile, so the guard must check that too."""
    from lazy_harness.monitoring.db import RenameProfileError

    db = MetricsDB(tmp_path / "m.db")
    try:
        db.upsert_event(_event(event_id="e-old", profile="lazy", session="s1", model="sonnet"))
        db.outbox_enqueue(
            sink_name="http_remote",
            event_id="e-old",
            payload_json=json.dumps({"profile": "lazy"}),
        )
        # A later ingest re-keys the same (session, model) row in place —
        # session_stats no longer has an "e-old" row at all.
        db.upsert_event(
            _event(event_id="e-new", profile="claude-lazy", session="s1", model="sonnet")
        )

        with pytest.raises(RenameProfileError, match="1"):
            db.rename_profile("lazy", "claude-lazy")
    finally:
        db.close()


def test_rename_profile_blocks_on_a_pending_row_whose_event_id_no_longer_exists(
    tmp_path: Path,
) -> None:
    """A pending row whose event_id matches no local `session_stats` row at
    all — payload profile unknown or already renamed — is still unsafe to let
    through: the guard cannot prove it does not belong to `old`."""
    from lazy_harness.monitoring.db import RenameProfileError

    db = MetricsDB(tmp_path / "m.db")
    try:
        db.upsert_event(_event(event_id="e-1", profile="lazy", session="s1", model="sonnet"))
        db.outbox_enqueue(sink_name="http_remote", event_id="e-orphan", payload_json="{}")

        with pytest.raises(RenameProfileError, match="1"):
            db.rename_profile("lazy", "claude-lazy")
    finally:
        db.close()


def test_rename_profile_acquires_write_lock_before_the_guard(tmp_path: Path) -> None:
    """The pending-outbox guard SELECT and the rename UPDATEs must run in one
    transaction, or a concurrent ingest can enqueue a pending row for an `old`
    event_id between the guard and the commit."""
    db = MetricsDB(tmp_path / "m.db")
    try:
        db.upsert_event(_event(event_id="e-1", profile="lazy", session="s1", model="sonnet"))
        seen: list[str] = []
        db._conn.set_trace_callback(seen.append)
        db.rename_profile("lazy", "claude-lazy")
    finally:
        db._conn.set_trace_callback(None)
        db.close()

    upper = [s.upper() for s in seen]
    begin_idx = next(i for i, s in enumerate(upper) if "BEGIN IMMEDIATE" in s)
    guard_idx = next(i for i, s in enumerate(upper) if "SELECT" in s and "SINK_OUTBOX" in s)
    assert begin_idx < guard_idx


def test_rename_profile_rolls_back_when_the_rename_fails(tmp_path: Path) -> None:
    """A failure partway through must not leave a half-applied rename
    committed on the connection's next `commit()`, nor a dangling RESERVED
    lock that blocks the next rename attempt."""
    db = MetricsDB(tmp_path / "m.db")
    try:
        db.upsert_event(_event(event_id="e-1", profile="lazy", session="s1", model="sonnet"))
        db._conn.execute(
            "CREATE TRIGGER fail_rename BEFORE UPDATE ON session_stats "
            "BEGIN SELECT RAISE(ABORT, 'injected rename failure'); END"
        )
        db._conn.commit()

        with pytest.raises(sqlite3.DatabaseError):
            db.rename_profile("lazy", "claude-lazy")

        assert db._conn.in_transaction is False
        row = db._conn.execute("SELECT profile FROM session_stats WHERE session = 's1'").fetchone()
        assert row["profile"] == "lazy"
    finally:
        db.close()


def test_a_reingest_after_rename_produces_no_second_row_for_the_session(tmp_path: Path) -> None:
    """The point of recomputing `event_id`: a re-ingest under the new profile
    name must upsert the same row, not mint a duplicate."""
    from lazy_harness.monitoring.event_id import derive_event_id

    db = MetricsDB(tmp_path / "m.db")
    try:
        db.upsert_event(_event(event_id="e-old", profile="lazy", session="s1", model="sonnet"))
        db.rename_profile("lazy", "claude-lazy")

        new_event_id = derive_event_id(profile="claude-lazy", session="s1", model="sonnet")
        db.upsert_event(
            _event(event_id=new_event_id, profile="claude-lazy", session="s1", model="sonnet")
        )

        rows = db._conn.execute("SELECT COUNT(*) AS n FROM session_stats").fetchone()
        assert rows["n"] == 1
    finally:
        db.close()

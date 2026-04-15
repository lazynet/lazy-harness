import json
import sqlite3
import time
from pathlib import Path

from lazy_harness.monitoring.db import MetricsDB


def test_new_db_has_identity_columns(tmp_path: Path) -> None:
    db = MetricsDB(tmp_path / "m.db")
    try:
        cols = {
            row[1]
            for row in db._conn.execute("PRAGMA table_info(session_stats)").fetchall()
        }
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

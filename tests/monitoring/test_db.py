import sqlite3
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

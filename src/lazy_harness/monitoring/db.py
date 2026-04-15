"""SQLite metrics store for session stats."""

from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from lazy_harness.plugins.contracts import MetricEvent


class MetricsDB:
    def __init__(self, path: Path) -> None:
        if str(path) != ":memory:":
            path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(path))
        self._conn.row_factory = sqlite3.Row
        self._create_tables()

    def _create_tables(self) -> None:
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS session_stats (
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
        """)
        self._conn.execute("CREATE INDEX IF NOT EXISTS idx_stats_date ON session_stats(date)")
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS ingest_meta (
                session TEXT PRIMARY KEY,
                mtime_ns INTEGER NOT NULL
            )
        """)
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS sink_outbox (
                sink_name TEXT NOT NULL,
                event_id TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                attempts INTEGER NOT NULL DEFAULT 0,
                last_error TEXT NOT NULL DEFAULT '',
                next_attempt_ts REAL,
                lease_until REAL,
                created_ts REAL NOT NULL,
                PRIMARY KEY (sink_name, event_id)
            )
        """)
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_outbox_pending "
            "ON sink_outbox(sink_name, status, next_attempt_ts)"
        )
        self._migrate_identity_columns()
        self._conn.commit()

    def _migrate_identity_columns(self) -> None:
        """Add user_id/tenant_id/event_id to session_stats if missing.

        Older databases created before the plugin system rename have a
        narrower schema. Use PRAGMA table_info to detect missing columns
        and ALTER TABLE them in. event_id is backfilled deterministically
        from (profile, session, model) for legacy rows so the remote sink
        has a stable idempotency key.
        """
        cols = {row[1] for row in self._conn.execute("PRAGMA table_info(session_stats)")}
        if "user_id" not in cols:
            self._conn.execute(
                "ALTER TABLE session_stats ADD COLUMN user_id TEXT NOT NULL DEFAULT 'local'"
            )
        if "tenant_id" not in cols:
            self._conn.execute(
                "ALTER TABLE session_stats ADD COLUMN tenant_id TEXT NOT NULL DEFAULT 'local'"
            )
        if "event_id" not in cols:
            self._conn.execute(
                "ALTER TABLE session_stats ADD COLUMN event_id TEXT NOT NULL DEFAULT ''"
            )
            from lazy_harness.monitoring.event_id import derive_event_id

            rows = self._conn.execute(
                "SELECT rowid, profile, session, model FROM session_stats WHERE event_id = ''"
            ).fetchall()
            for row in rows:
                eid = derive_event_id(
                    profile=row["profile"], session=row["session"], model=row["model"]
                )
                self._conn.execute(
                    "UPDATE session_stats SET event_id = ? WHERE rowid = ?",
                    (eid, row["rowid"]),
                )

    def replace_profile_stats(
        self, profile: str, entries: list[dict[str, Any]]
    ) -> int:
        """Atomically wipe all rows for a profile and insert a fresh set.

        Used by the ingest pipeline which rebuilds totals from scratch on
        every run (after cross-file message-id dedup). Wrapped in a single
        transaction so partial failures leave the profile's rows unchanged.
        """
        try:
            self._conn.execute("BEGIN")
            self._conn.execute(
                "DELETE FROM session_stats WHERE profile = ?", (profile,)
            )
            for entry in entries:
                self._conn.execute(
                    """INSERT INTO session_stats
                    (session, date, model, profile, project, input_tokens, output_tokens,
                     cache_read, cache_create, cost)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        entry["session"],
                        entry["date"],
                        entry["model"],
                        entry.get("profile", profile),
                        entry.get("project", ""),
                        entry.get("input", 0),
                        entry.get("output", 0),
                        entry.get("cache_read", 0),
                        entry.get("cache_create", 0),
                        entry.get("cost", 0.0),
                    ),
                )
            self._conn.commit()
        except Exception:
            self._conn.rollback()
            raise
        return len(entries)

    def upsert_stats(self, entries: list[dict[str, Any]]) -> int:
        affected = 0
        for entry in entries:
            self._conn.execute(
                """INSERT INTO session_stats
                (session, date, model, profile, project, input_tokens, output_tokens,
                 cache_read, cache_create, cost)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(session, model) DO UPDATE SET
                    date=excluded.date,
                    profile=excluded.profile,
                    project=excluded.project,
                    input_tokens=excluded.input_tokens,
                    output_tokens=excluded.output_tokens,
                    cache_read=excluded.cache_read,
                    cache_create=excluded.cache_create,
                    cost=excluded.cost""",
                (
                    entry["session"],
                    entry["date"],
                    entry["model"],
                    entry.get("profile", ""),
                    entry.get("project", ""),
                    entry.get("input", 0),
                    entry.get("output", 0),
                    entry.get("cache_read", 0),
                    entry.get("cache_create", 0),
                    entry.get("cost", 0.0),
                ),
            )
            affected += 1
        self._conn.commit()
        return affected

    def upsert_event(self, event: MetricEvent) -> None:
        self._conn.execute(
            """
            INSERT INTO session_stats
                (session, date, model, profile, project,
                 input_tokens, output_tokens, cache_read, cache_create, cost,
                 user_id, tenant_id, event_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(session, model) DO UPDATE SET
                date=excluded.date,
                profile=excluded.profile,
                project=excluded.project,
                input_tokens=excluded.input_tokens,
                output_tokens=excluded.output_tokens,
                cache_read=excluded.cache_read,
                cache_create=excluded.cache_create,
                cost=excluded.cost,
                user_id=excluded.user_id,
                tenant_id=excluded.tenant_id,
                event_id=excluded.event_id
            """,
            (
                event.session,
                event.date,
                event.model,
                event.profile,
                event.project,
                event.input_tokens,
                event.output_tokens,
                event.cache_read,
                event.cache_create,
                event.cost,
                event.user_id,
                event.tenant_id,
                event.event_id,
            ),
        )
        self._conn.commit()

    def get_ingest_mtime(self, session: str) -> int | None:
        row = self._conn.execute(
            "SELECT mtime_ns FROM ingest_meta WHERE session = ?", (session,)
        ).fetchone()
        return int(row["mtime_ns"]) if row is not None else None

    def set_ingest_mtime(self, session: str, mtime_ns: int) -> None:
        self._conn.execute(
            """INSERT INTO ingest_meta (session, mtime_ns) VALUES (?, ?)
               ON CONFLICT(session) DO UPDATE SET mtime_ns=excluded.mtime_ns""",
            (session, mtime_ns),
        )
        self._conn.commit()

    def insert_stats(self, entries: list[dict[str, Any]]) -> int:
        inserted = 0
        for entry in entries:
            try:
                self._conn.execute(
                    """INSERT OR IGNORE INTO session_stats
                    (session, date, model, profile, project, input_tokens, output_tokens,
                     cache_read, cache_create, cost)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        entry["session"],
                        entry["date"],
                        entry["model"],
                        entry.get("profile", ""),
                        entry.get("project", ""),
                        entry.get("input", 0),
                        entry.get("output", 0),
                        entry.get("cache_read", 0),
                        entry.get("cache_create", 0),
                        entry.get("cost", 0.0),
                    ),
                )
                inserted += 1
            except sqlite3.IntegrityError:
                pass
        self._conn.commit()
        return inserted

    def query_stats(self, period: str = "all", since: str | None = None) -> list[dict[str, Any]]:
        if since:
            rows = self._conn.execute(
                "SELECT * FROM session_stats WHERE date >= ? ORDER BY date DESC", (since,)
            ).fetchall()
        elif period == "all":
            rows = self._conn.execute("SELECT * FROM session_stats ORDER BY date DESC").fetchall()
        else:
            rows = self._conn.execute(
                "SELECT * FROM session_stats WHERE date LIKE ? ORDER BY date DESC", (f"{period}%",)
            ).fetchall()

        return [
            {
                "session": r["session"],
                "date": r["date"],
                "model": r["model"],
                "profile": r["profile"],
                "project": r["project"],
                "input": r["input_tokens"],
                "output": r["output_tokens"],
                "cache_read": r["cache_read"],
                "cache_create": r["cache_create"],
                "cost": r["cost"],
            }
            for r in rows
        ]

    def aggregate_costs(self, period: str = "all", since: str | None = None) -> dict[str, Any]:
        if since:
            row = self._conn.execute(
                """
                SELECT COALESCE(SUM(cost), 0) as total_cost,
                       COALESCE(SUM(input_tokens), 0) as total_input,
                       COALESCE(SUM(output_tokens), 0) as total_output,
                       COUNT(DISTINCT session) as session_count
                FROM session_stats WHERE date >= ?""",
                (since,),
            ).fetchone()
        elif period == "all":
            row = self._conn.execute("""
                SELECT COALESCE(SUM(cost), 0) as total_cost,
                       COALESCE(SUM(input_tokens), 0) as total_input,
                       COALESCE(SUM(output_tokens), 0) as total_output,
                       COUNT(DISTINCT session) as session_count
                FROM session_stats""").fetchone()
        else:
            row = self._conn.execute(
                """
                SELECT COALESCE(SUM(cost), 0) as total_cost,
                       COALESCE(SUM(input_tokens), 0) as total_input,
                       COALESCE(SUM(output_tokens), 0) as total_output,
                       COUNT(DISTINCT session) as session_count
                FROM session_stats WHERE date LIKE ?""",
                (f"{period}%",),
            ).fetchone()

        return {
            "total_cost": round(row["total_cost"], 2),
            "total_input": row["total_input"],
            "total_output": row["total_output"],
            "session_count": row["session_count"],
        }

    def outbox_enqueue(self, *, sink_name: str, event_id: str, payload_json: str) -> None:
        now = time.time()
        self._conn.execute(
            """
            INSERT INTO sink_outbox (
                sink_name, event_id, payload_json, status, attempts,
                last_error, next_attempt_ts, lease_until, created_ts
            ) VALUES (?, ?, ?, 'pending', 0, '', NULL, NULL, ?)
            ON CONFLICT(sink_name, event_id) DO UPDATE SET
                payload_json = excluded.payload_json,
                status = 'pending',
                next_attempt_ts = NULL,
                lease_until = NULL,
                last_error = ''
            """,
            (sink_name, event_id, payload_json, now),
        )
        self._conn.commit()

    def outbox_claim(
        self, *, sink_name: str, batch_size: int, lease_seconds: int
    ) -> list[OutboxRow]:
        now = time.time()
        lease_until = now + lease_seconds
        candidates = self._conn.execute(
            """
            SELECT sink_name, event_id, payload_json, status, attempts,
                   last_error, next_attempt_ts, lease_until
            FROM sink_outbox
            WHERE sink_name = ?
              AND (
                (status = 'pending' AND (next_attempt_ts IS NULL OR next_attempt_ts <= ?))
                OR (status = 'sending' AND (lease_until IS NULL OR lease_until <= ?))
              )
            ORDER BY created_ts ASC
            LIMIT ?
            """,
            (sink_name, now, now, batch_size),
        ).fetchall()
        claimed: list[OutboxRow] = []
        for row in candidates:
            self._conn.execute(
                """
                UPDATE sink_outbox
                SET status = 'sending', lease_until = ?
                WHERE sink_name = ? AND event_id = ?
                """,
                (lease_until, row["sink_name"], row["event_id"]),
            )
            claimed.append(
                OutboxRow(
                    sink_name=row["sink_name"],
                    event_id=row["event_id"],
                    payload_json=row["payload_json"],
                    status="sending",
                    attempts=row["attempts"],
                    last_error=row["last_error"],
                    next_attempt_ts=row["next_attempt_ts"],
                    lease_until=lease_until,
                )
            )
        self._conn.commit()
        return claimed

    def outbox_mark_sent(self, sink_name: str, event_id: str) -> None:
        self._conn.execute(
            "UPDATE sink_outbox SET status = 'sent', lease_until = NULL "
            "WHERE sink_name = ? AND event_id = ?",
            (sink_name, event_id),
        )
        self._conn.commit()

    def outbox_mark_failed(
        self, sink_name: str, event_id: str, *, error: str, retry_after_seconds: float
    ) -> None:
        next_ts = time.time() + retry_after_seconds
        self._conn.execute(
            """
            UPDATE sink_outbox
            SET status = 'pending',
                attempts = attempts + 1,
                last_error = ?,
                next_attempt_ts = ?,
                lease_until = NULL
            WHERE sink_name = ? AND event_id = ?
            """,
            (error, next_ts, sink_name, event_id),
        )
        self._conn.commit()

    def outbox_list_pending(
        self, *, sink_name: str, due_now: bool = True
    ) -> list[OutboxRow]:
        now = time.time()
        if due_now:
            rows = self._conn.execute(
                """
                SELECT sink_name, event_id, payload_json, status, attempts,
                       last_error, next_attempt_ts, lease_until
                FROM sink_outbox
                WHERE sink_name = ? AND status = 'pending'
                  AND (next_attempt_ts IS NULL OR next_attempt_ts <= ?)
                ORDER BY created_ts ASC
                """,
                (sink_name, now),
            ).fetchall()
        else:
            rows = self._conn.execute(
                """
                SELECT sink_name, event_id, payload_json, status, attempts,
                       last_error, next_attempt_ts, lease_until
                FROM sink_outbox
                WHERE sink_name = ? AND status = 'pending'
                ORDER BY created_ts ASC
                """,
                (sink_name,),
            ).fetchall()
        return [
            OutboxRow(
                sink_name=r["sink_name"],
                event_id=r["event_id"],
                payload_json=r["payload_json"],
                status=r["status"],
                attempts=r["attempts"],
                last_error=r["last_error"],
                next_attempt_ts=r["next_attempt_ts"],
                lease_until=r["lease_until"],
            )
            for r in rows
        ]

    def outbox_list_sending(self, *, sink_name: str) -> list[OutboxRow]:
        rows = self._conn.execute(
            """
            SELECT sink_name, event_id, payload_json, status, attempts,
                   last_error, next_attempt_ts, lease_until
            FROM sink_outbox
            WHERE sink_name = ? AND status = 'sending'
            ORDER BY created_ts ASC
            """,
            (sink_name,),
        ).fetchall()
        return [
            OutboxRow(
                sink_name=r["sink_name"],
                event_id=r["event_id"],
                payload_json=r["payload_json"],
                status=r["status"],
                attempts=r["attempts"],
                last_error=r["last_error"],
                next_attempt_ts=r["next_attempt_ts"],
                lease_until=r["lease_until"],
            )
            for r in rows
        ]

    def outbox_stats(self, sink_name: str) -> dict[str, Any]:
        row = self._conn.execute(
            """
            SELECT
                SUM(CASE WHEN status='pending' THEN 1 ELSE 0 END) AS pending,
                SUM(CASE WHEN status='sending' THEN 1 ELSE 0 END) AS sending,
                SUM(CASE WHEN status='sent' THEN 1 ELSE 0 END) AS sent,
                MIN(CASE WHEN status='pending' THEN created_ts END) AS oldest_pending_ts,
                MAX(next_attempt_ts) AS next_attempt_ts
            FROM sink_outbox
            WHERE sink_name = ?
            """,
            (sink_name,),
        ).fetchone()
        return {
            "pending": int(row["pending"] or 0),
            "sending": int(row["sending"] or 0),
            "sent": int(row["sent"] or 0),
            "oldest_pending_ts": row["oldest_pending_ts"],
            "next_attempt_ts": row["next_attempt_ts"],
        }

    def outbox_reset_backoff(self, sink_name: str) -> None:
        self._conn.execute(
            """
            UPDATE sink_outbox
            SET next_attempt_ts = NULL
            WHERE sink_name = ? AND status = 'pending'
            """,
            (sink_name,),
        )
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()


@dataclass(frozen=True, slots=True)
class OutboxRow:
    sink_name: str
    event_id: str
    payload_json: str
    status: str
    attempts: int
    last_error: str
    next_attempt_ts: float | None
    lease_until: float | None

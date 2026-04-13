"""SQLite metrics store for session stats."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any


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
        self._conn.commit()

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

    def close(self) -> None:
        self._conn.close()

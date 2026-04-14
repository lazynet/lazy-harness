"""Built-in `sqlite_local` sink — the local durable buffer.

This sink is always active (ausencia de config ⇒ solo este). Its write()
upserts into the existing `session_stats` table keyed by (session, model)
with identity columns stamped on every row. It never fails under normal
conditions; the underlying SQLite file is assumed healthy.
"""

from __future__ import annotations

from typing import ClassVar

from lazy_harness.monitoring.db import MetricsDB
from lazy_harness.plugins.contracts import (
    DrainResult,
    MetricEvent,
    SinkHealth,
    SinkWriteResult,
)


class SqliteLocalSink:
    name: ClassVar[str] = "sqlite_local"

    def __init__(self, *, db: MetricsDB) -> None:
        self._db = db

    def write(self, event: MetricEvent) -> SinkWriteResult:
        try:
            self._db.upsert_event(event)
        except Exception as exc:
            return SinkWriteResult.failure(str(exc))
        return SinkWriteResult.ok()

    def drain(self, batch_size: int) -> DrainResult:
        return DrainResult(sent=0, failed=0, remaining=0)

    def health(self) -> SinkHealth:
        return SinkHealth(reachable=True)

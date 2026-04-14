"""Built-in `http_remote` sink — enqueues events on the outbox.

This sink is opt-in. Its write() is non-blocking: it serializes the event
as JSON and upserts it into sink_outbox. The actual HTTP POST happens in
`monitoring.sinks.worker.drain_http_remote` on every `lh` invocation that
goes through the ingest pipeline (or explicit `lh metrics drain`).
"""

from __future__ import annotations

import json
from typing import ClassVar

from lazy_harness.monitoring.db import MetricsDB
from lazy_harness.plugins.contracts import (
    DrainResult,
    MetricEvent,
    SinkHealth,
    SinkWriteResult,
)


class HttpRemoteSink:
    name: ClassVar[str] = "http_remote"

    def __init__(
        self,
        *,
        db: MetricsDB,
        url: str,
        timeout_seconds: float = 5.0,
        batch_size: int = 50,
    ) -> None:
        self._db = db
        self._url = url
        self._timeout = timeout_seconds
        self._batch_size = batch_size

    @property
    def url(self) -> str:
        return self._url

    def write(self, event: MetricEvent) -> SinkWriteResult:
        try:
            payload = json.dumps(event.to_dict(), sort_keys=True)
            self._db.outbox_enqueue(
                sink_name=self.name,
                event_id=event.event_id,
                payload_json=payload,
            )
        except Exception as exc:
            return SinkWriteResult.failure(str(exc))
        return SinkWriteResult.ok()

    def drain(self, batch_size: int) -> DrainResult:
        # Worker module owns the actual network work. The sink delegates so
        # that behavior is testable in isolation and the sink stays small.
        from lazy_harness.monitoring.sinks.worker import drain_http_remote

        return drain_http_remote(
            db=self._db,
            url=self._url,
            timeout_seconds=self._timeout,
            batch_size=batch_size or self._batch_size,
        )

    def health(self) -> SinkHealth:
        stats = self._db.outbox_stats(self.name)
        pending = stats["pending"]
        if pending == 0:
            return SinkHealth(reachable=True, detail="no pending events")
        return SinkHealth(reachable=True, detail=f"{pending} pending")

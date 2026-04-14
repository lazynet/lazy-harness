"""Outbox drainer for remote sinks.

Drain policy (D15, D18 in the spec):
- Opportunistic: called from within `lh` (hooks + CLI) right after ingest,
  or explicitly by `lh metrics drain`.
- Exponential backoff per event: first failure waits 1s, then doubles up
  to a 300s cap.
- Idempotent end-to-end: events carry `event_id`, backend upserts by it.
- Claim-with-lease concurrency: the DB grants a 60s lease when a worker
  picks up a batch so two `lh` processes don't double-send.
"""

from __future__ import annotations

from typing import Final

import httpx

from lazy_harness.monitoring.db import MetricsDB
from lazy_harness.plugins.contracts import DrainResult

_LEASE_SECONDS: Final[int] = 60
_BACKOFF_BASE: Final[float] = 1.0
_BACKOFF_CAP: Final[float] = 300.0


def _backoff_for(attempts: int) -> float:
    delay = _BACKOFF_BASE * (2 ** max(attempts - 1, 0))
    return min(delay, _BACKOFF_CAP)


def drain_http_remote(
    *,
    db: MetricsDB,
    url: str,
    timeout_seconds: float,
    batch_size: int,
) -> DrainResult:
    """Drain one batch from sink_outbox for `http_remote`.

    Never raises to the caller. Network errors and non-2xx responses are
    recorded as failures on the outbox row.
    """
    rows = db.outbox_claim(
        sink_name="http_remote", batch_size=batch_size, lease_seconds=_LEASE_SECONDS
    )
    if not rows:
        return DrainResult(sent=0, failed=0, remaining=0)

    sent = 0
    failed = 0

    with httpx.Client(timeout=timeout_seconds) as client:
        for row in rows:
            try:
                resp = client.post(
                    url,
                    content=row.payload_json,
                    headers={"Content-Type": "application/json"},
                )
            except httpx.HTTPError as exc:
                failed += 1
                db.outbox_mark_failed(
                    row.sink_name,
                    row.event_id,
                    error=f"{type(exc).__name__}: {exc}",
                    retry_after_seconds=_backoff_for(row.attempts + 1),
                )
                continue
            if 200 <= resp.status_code < 300:
                sent += 1
                db.outbox_mark_sent(row.sink_name, row.event_id)
            else:
                failed += 1
                db.outbox_mark_failed(
                    row.sink_name,
                    row.event_id,
                    error=f"HTTP {resp.status_code}",
                    retry_after_seconds=_backoff_for(row.attempts + 1),
                )

    remaining = db.outbox_stats("http_remote")["pending"]
    return DrainResult(sent=sent, failed=failed, remaining=remaining)

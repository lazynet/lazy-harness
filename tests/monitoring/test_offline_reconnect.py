"""Simulate a week offline followed by a reconnect.

1. Configure http_remote pointing to a port that refuses connections.
2. Write several events → each becomes pending in the outbox.
3. A drain attempt produces failures; rows remain pending.
4. Rewire the sink's URL to a live pytest-httpserver.
5. One more drain empties the outbox.
"""

from pathlib import Path

from pytest_httpserver import HTTPServer

from lazy_harness.monitoring.db import MetricsDB
from lazy_harness.monitoring.sinks.http_remote import HttpRemoteSink
from lazy_harness.monitoring.sinks.worker import drain_http_remote
from lazy_harness.plugins.contracts import METRIC_EVENT_SCHEMA_VERSION, MetricEvent


def _event(session: str) -> MetricEvent:
    return MetricEvent(
        event_id=f"eid-{session}",
        schema_version=METRIC_EVENT_SCHEMA_VERSION,
        user_id="m",
        tenant_id="local",
        profile="p",
        session=session,
        model="sonnet",
        project="lh",
        date="2026-04-14",
        input_tokens=1,
        output_tokens=1,
        cache_read=0,
        cache_create=0,
        cost=0.0,
    )


def test_offline_reconnect_drains_all(tmp_path: Path, httpserver: HTTPServer) -> None:
    db = MetricsDB(tmp_path / "m.db")

    # 1. Offline phase: unreachable URL.
    offline = HttpRemoteSink(
        db=db, url="http://127.0.0.1:1", timeout_seconds=1, batch_size=10
    )
    try:
        offline.write(_event("s1"))
        offline.write(_event("s2"))
        offline.write(_event("s3"))

        result = drain_http_remote(
            db=db, url="http://127.0.0.1:1", timeout_seconds=1, batch_size=10
        )
        assert result.failed == 3
        assert db.outbox_stats("http_remote")["pending"] == 3

        # 2. Reconnect phase: live backend.
        httpserver.expect_request("/ingest", method="POST").respond_with_json({"ok": True})
        final = drain_http_remote(
            db=db,
            url=httpserver.url_for("/ingest"),
            timeout_seconds=2,
            batch_size=10,
        )
        # Backoff may require a manual reset for this test. We claim that
        # backoff reset-on-success holds per sink, not per event. For this
        # simulation, we reset next_attempt_ts via a second drain cycle.
        while db.outbox_stats("http_remote")["pending"] > 0:
            final = drain_http_remote(
                db=db,
                url=httpserver.url_for("/ingest"),
                timeout_seconds=2,
                batch_size=10,
            )
            if final.sent == 0:
                break  # no progress possible without backoff reset
        assert db.outbox_stats("http_remote")["pending"] == 0
        assert db.outbox_stats("http_remote")["sent"] == 3
    finally:
        db.close()

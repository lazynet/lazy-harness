import json
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
        user_id="martin",
        tenant_id="local",
        profile="personal",
        session=session,
        model="sonnet",
        project="lazy-harness",
        date="2026-04-14",
        input_tokens=100,
        output_tokens=50,
        cache_read=0,
        cache_create=0,
        cost=0.001,
    )


def test_drain_posts_pending_events_and_marks_sent(
    tmp_path: Path, httpserver: HTTPServer
) -> None:
    httpserver.expect_request("/ingest", method="POST").respond_with_json({"ok": True})
    db = MetricsDB(tmp_path / "m.db")
    sink = HttpRemoteSink(
        db=db, url=httpserver.url_for("/ingest"), timeout_seconds=2, batch_size=10
    )
    try:
        sink.write(_event("s1"))
        sink.write(_event("s2"))
        result = drain_http_remote(
            db=db, url=httpserver.url_for("/ingest"), timeout_seconds=2, batch_size=10
        )
        assert result.sent == 2
        assert result.failed == 0
        assert result.remaining == 0
        assert db.outbox_stats("http_remote")["pending"] == 0
        assert db.outbox_stats("http_remote")["sent"] == 2
    finally:
        db.close()


def test_drain_on_server_error_marks_failed_and_keeps_pending(
    tmp_path: Path, httpserver: HTTPServer
) -> None:
    httpserver.expect_request("/ingest", method="POST").respond_with_data(
        "boom", status=500
    )
    db = MetricsDB(tmp_path / "m.db")
    sink = HttpRemoteSink(
        db=db, url=httpserver.url_for("/ingest"), timeout_seconds=2, batch_size=10
    )
    try:
        sink.write(_event("s1"))
        result = drain_http_remote(
            db=db, url=httpserver.url_for("/ingest"), timeout_seconds=2, batch_size=10
        )
        assert result.sent == 0
        assert result.failed == 1
        stats = db.outbox_stats("http_remote")
        assert stats["pending"] == 1
        assert stats["sent"] == 0
    finally:
        db.close()


def test_drain_when_backend_unreachable_does_not_raise(tmp_path: Path) -> None:
    db = MetricsDB(tmp_path / "m.db")
    sink = HttpRemoteSink(
        db=db, url="http://127.0.0.1:1", timeout_seconds=1, batch_size=10
    )
    try:
        sink.write(_event("s1"))
        result = drain_http_remote(
            db=db, url="http://127.0.0.1:1", timeout_seconds=1, batch_size=10
        )
        assert result.failed == 1
        assert result.sent == 0
    finally:
        db.close()


def test_drain_twice_is_idempotent_against_backend(
    tmp_path: Path, httpserver: HTTPServer
) -> None:
    received: list[dict] = []

    def _handler(req):  # type: ignore[no-untyped-def]
        received.append(json.loads(req.get_data(as_text=True)))
        from werkzeug.wrappers import Response

        return Response('{"ok":true}', 200, content_type="application/json")

    httpserver.expect_request("/ingest", method="POST").respond_with_handler(_handler)

    db = MetricsDB(tmp_path / "m.db")
    sink = HttpRemoteSink(
        db=db, url=httpserver.url_for("/ingest"), timeout_seconds=2, batch_size=10
    )
    try:
        sink.write(_event("s1"))
        drain_http_remote(
            db=db, url=httpserver.url_for("/ingest"), timeout_seconds=2, batch_size=10
        )
        sink.write(_event("s1"))
        drain_http_remote(
            db=db, url=httpserver.url_for("/ingest"), timeout_seconds=2, batch_size=10
        )
    finally:
        db.close()

    assert len(received) == 2
    assert received[0]["event_id"] == received[1]["event_id"]

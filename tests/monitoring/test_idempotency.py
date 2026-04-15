"""Sending the same (profile, session, model) tuple twice produces a single
backend row because event_id is deterministic and the backend upserts."""

from pathlib import Path

from pytest_httpserver import HTTPServer

from lazy_harness.monitoring.db import MetricsDB
from lazy_harness.monitoring.event_id import derive_event_id
from lazy_harness.monitoring.sinks.http_remote import HttpRemoteSink
from lazy_harness.monitoring.sinks.worker import drain_http_remote
from lazy_harness.plugins.contracts import METRIC_EVENT_SCHEMA_VERSION, MetricEvent


def test_same_tuple_yields_one_event_id_regardless_of_count() -> None:
    a = derive_event_id(profile="p", session="s", model="m")
    b = derive_event_id(profile="p", session="s", model="m")
    c = derive_event_id(profile="p", session="s", model="m")
    assert a == b == c


def test_backend_receives_same_event_id_across_rewrites(
    tmp_path: Path, httpserver: HTTPServer
) -> None:
    captured: list[str] = []

    def _handler(req):  # type: ignore[no-untyped-def]
        import json as _json

        captured.append(_json.loads(req.get_data(as_text=True))["event_id"])
        from werkzeug.wrappers import Response

        return Response('{"ok":true}', 200, content_type="application/json")

    httpserver.expect_request("/ingest", method="POST").respond_with_handler(_handler)

    db = MetricsDB(tmp_path / "m.db")
    sink = HttpRemoteSink(
        db=db, url=httpserver.url_for("/ingest"), timeout_seconds=2, batch_size=10
    )
    try:
        eid = derive_event_id(profile="p", session="s", model="m")
        event = MetricEvent(
            event_id=eid,
            schema_version=METRIC_EVENT_SCHEMA_VERSION,
            user_id="u",
            tenant_id="local",
            profile="p",
            session="s",
            model="m",
            project="lh",
            date="2026-04-14",
            input_tokens=1,
            output_tokens=1,
            cache_read=0,
            cache_create=0,
            cost=0.0,
        )
        sink.write(event)
        drain_http_remote(
            db=db, url=httpserver.url_for("/ingest"), timeout_seconds=2, batch_size=10
        )
        sink.write(event)  # rewrite — same tuple
        drain_http_remote(
            db=db, url=httpserver.url_for("/ingest"), timeout_seconds=2, batch_size=10
        )
    finally:
        db.close()

    assert len(captured) == 2
    assert captured[0] == captured[1] == eid

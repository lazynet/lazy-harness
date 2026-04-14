from pathlib import Path

from lazy_harness.monitoring.db import MetricsDB
from lazy_harness.monitoring.sinks.http_remote import HttpRemoteSink
from lazy_harness.plugins.contracts import METRIC_EVENT_SCHEMA_VERSION, MetricEvent


def _mk_event(session: str = "s1") -> MetricEvent:
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


def test_write_enqueues_to_outbox(tmp_path: Path) -> None:
    db = MetricsDB(tmp_path / "m.db")
    try:
        sink = HttpRemoteSink(
            db=db,
            url="https://example.invalid/ingest",
            timeout_seconds=5,
            batch_size=10,
        )
        r = sink.write(_mk_event())
        assert r.success is True
        pending = db.outbox_list_pending(sink_name="http_remote")
        assert len(pending) == 1
        assert pending[0].event_id == "eid-s1"
    finally:
        db.close()


def test_write_same_event_twice_upserts_single_outbox_row(tmp_path: Path) -> None:
    db = MetricsDB(tmp_path / "m.db")
    try:
        sink = HttpRemoteSink(
            db=db, url="https://x.invalid/", timeout_seconds=5, batch_size=10
        )
        sink.write(_mk_event())
        sink.write(_mk_event())
        assert len(db.outbox_list_pending(sink_name="http_remote")) == 1
    finally:
        db.close()


def test_sink_name_is_http_remote() -> None:
    assert HttpRemoteSink.name == "http_remote"

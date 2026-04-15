from pathlib import Path

from lazy_harness.monitoring.db import MetricsDB
from lazy_harness.monitoring.sinks.sqlite_local import SqliteLocalSink
from lazy_harness.plugins.contracts import (
    METRIC_EVENT_SCHEMA_VERSION,
    MetricEvent,
    SinkHealth,
)


def _mk_event(session: str = "s1", model: str = "sonnet") -> MetricEvent:
    return MetricEvent(
        event_id="eid-" + session + "-" + model,
        schema_version=METRIC_EVENT_SCHEMA_VERSION,
        user_id="martin",
        tenant_id="local",
        profile="personal",
        session=session,
        model=model,
        project="lazy-harness",
        date="2026-04-14",
        input_tokens=100,
        output_tokens=50,
        cache_read=0,
        cache_create=0,
        cost=0.001,
    )


def test_write_persists_to_session_stats(tmp_path: Path) -> None:
    db = MetricsDB(tmp_path / "m.db")
    try:
        sink = SqliteLocalSink(db=db)
        result = sink.write(_mk_event())
        assert result.success is True
        rows = db.query_stats()
        assert len(rows) == 1
        assert rows[0]["session"] == "s1"
        assert rows[0]["profile"] == "personal"
    finally:
        db.close()


def test_write_twice_same_event_upserts(tmp_path: Path) -> None:
    db = MetricsDB(tmp_path / "m.db")
    try:
        sink = SqliteLocalSink(db=db)
        sink.write(_mk_event())
        sink.write(_mk_event())
        assert len(db.query_stats()) == 1
    finally:
        db.close()


def test_health_is_always_reachable(tmp_path: Path) -> None:
    db = MetricsDB(tmp_path / "m.db")
    try:
        h = SqliteLocalSink(db=db).health()
        assert isinstance(h, SinkHealth)
        assert h.reachable is True
    finally:
        db.close()


def test_drain_is_noop(tmp_path: Path) -> None:
    db = MetricsDB(tmp_path / "m.db")
    try:
        r = SqliteLocalSink(db=db).drain(batch_size=10)
        assert r.sent == 0 and r.failed == 0 and r.remaining == 0
    finally:
        db.close()


def test_sink_name_is_sqlite_local(tmp_path: Path) -> None:
    assert SqliteLocalSink.name == "sqlite_local"

"""Tests for plugins.contracts."""

from __future__ import annotations

import dataclasses
import json

import pytest

from lazy_harness.plugins.contracts import (
    METRIC_EVENT_SCHEMA_VERSION,
    DrainResult,
    MetricEvent,
    MetricsSink,
    SinkHealth,
    SinkWriteResult,
)


def test_metric_event_is_frozen() -> None:
    event = MetricEvent(
        event_id="01HABCDE",
        schema_version=METRIC_EVENT_SCHEMA_VERSION,
        user_id="martin",
        tenant_id="local",
        profile="personal",
        session="abc123",
        model="claude-sonnet-4-5",
        project="lazy-harness",
        date="2026-04-14",
        input_tokens=100,
        output_tokens=50,
        cache_read=0,
        cache_create=0,
        cost=0.0012,
    )
    with pytest.raises(dataclasses.FrozenInstanceError):
        event.input_tokens = 200  # type: ignore[misc]


def test_metric_event_json_roundtrip() -> None:
    event = MetricEvent(
        event_id="01HABCDE",
        schema_version=METRIC_EVENT_SCHEMA_VERSION,
        user_id="martin",
        tenant_id="local",
        profile="personal",
        session="abc123",
        model="claude-sonnet-4-5",
        project="lazy-harness",
        date="2026-04-14",
        input_tokens=100,
        output_tokens=50,
        cache_read=0,
        cache_create=0,
        cost=0.0012,
    )
    payload = json.dumps(event.to_dict(), sort_keys=True)
    restored = MetricEvent.from_dict(json.loads(payload))
    assert restored == event


def test_schema_version_is_int_two() -> None:
    assert METRIC_EVENT_SCHEMA_VERSION == 2
    assert isinstance(METRIC_EVENT_SCHEMA_VERSION, int)


def test_metric_event_carries_host_and_workload() -> None:
    """ADR-037: both are dimensions of their own, not folded into user_id."""
    event = MetricEvent(
        event_id="01HABCDE",
        schema_version=METRIC_EVENT_SCHEMA_VERSION,
        user_id="martin",
        tenant_id="local",
        profile="personal",
        session="abc123",
        model="claude-sonnet-4-5",
        project="lazy-harness",
        date="2026-04-14",
        input_tokens=100,
        output_tokens=50,
        cache_read=0,
        cache_create=0,
        cost=0.0012,
        host="LazyMBP",
        workload="nightly-pass",
    )
    assert event.host == "LazyMBP"
    assert event.workload == "nightly-pass"
    assert event.user_id == "martin", "host must not be folded into user_id"


def test_host_and_workload_default_to_empty_string() -> None:
    event = MetricEvent(
        event_id="01HABCDE",
        schema_version=METRIC_EVENT_SCHEMA_VERSION,
        user_id="martin",
        tenant_id="local",
        profile="personal",
        session="abc123",
        model="claude-sonnet-4-5",
        project="lazy-harness",
        date="2026-04-14",
        input_tokens=100,
        output_tokens=50,
        cache_read=0,
        cache_create=0,
        cost=0.0012,
    )
    assert event.host == ""
    assert event.workload == ""


def test_from_dict_accepts_a_v1_payload() -> None:
    """A payload stored before the bump has neither key and must still load.

    This is what keeps pending outbox rows drainable across the version
    change: they hold v1 JSON and are posted verbatim.
    """
    v1_payload = {
        "event_id": "01HABCDE",
        "schema_version": 1,
        "user_id": "martin",
        "tenant_id": "local",
        "profile": "personal",
        "session": "abc123",
        "model": "claude-sonnet-4-5",
        "project": "lazy-harness",
        "date": "2026-04-14",
        "input_tokens": 100,
        "output_tokens": 50,
        "cache_read": 0,
        "cache_create": 0,
        "cost": 0.0012,
    }
    restored = MetricEvent.from_dict(v1_payload)
    assert restored.schema_version == 1
    assert restored.host == ""
    assert restored.workload == ""


def test_to_dict_names_match_the_receiver_columns() -> None:
    """The receiver ignores unknown keys silently, so a typo loses the data."""
    event = MetricEvent(
        event_id="01HABCDE",
        schema_version=METRIC_EVENT_SCHEMA_VERSION,
        user_id="martin",
        tenant_id="local",
        profile="personal",
        session="abc123",
        model="claude-sonnet-4-5",
        project="lazy-harness",
        date="2026-04-14",
        input_tokens=1,
        output_tokens=1,
        cache_read=0,
        cache_create=0,
        cost=0.0,
        host="agents",
        workload="vault-pass",
    )
    payload = event.to_dict()
    assert payload["host"] == "agents"
    assert payload["workload"] == "vault-pass"


def test_sink_write_result_ok_and_error() -> None:
    ok = SinkWriteResult.ok()
    assert ok.success is True
    assert ok.error is None

    err = SinkWriteResult.failure("timeout")
    assert err.success is False
    assert err.error == "timeout"


def test_sink_health_defaults_reachable() -> None:
    h = SinkHealth(reachable=True)
    assert h.reachable is True
    assert h.detail == ""


def test_drain_result_counts_sent_and_failed() -> None:
    r = DrainResult(sent=3, failed=1, remaining=5)
    assert r.sent == 3
    assert r.failed == 1
    assert r.remaining == 5


class _FakeSink:
    """Conformance check: duck-typed class must satisfy the Protocol."""

    name = "fake"

    def write(self, event: MetricEvent) -> SinkWriteResult:
        return SinkWriteResult.ok()

    def drain(self, batch_size: int) -> DrainResult:
        return DrainResult(sent=0, failed=0, remaining=0)

    def health(self) -> SinkHealth:
        return SinkHealth(reachable=True)


def test_metrics_sink_is_structural_protocol() -> None:
    sink: MetricsSink = _FakeSink()
    assert sink.name == "fake"
    assert sink.write.__name__ == "write"

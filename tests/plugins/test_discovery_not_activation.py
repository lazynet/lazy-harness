"""A discovered entry point must NOT be instantiated unless the profile
explicitly names it in metrics.sinks."""

from __future__ import annotations

from importlib import metadata as importlib_metadata

import pytest

from lazy_harness.core.config import MetricsConfig
from lazy_harness.monitoring.db import MetricsDB
from lazy_harness.monitoring.sink_setup import build_sinks
from lazy_harness.plugins.contracts import (
    DrainResult,
    MetricEvent,
    MetricsSink,
    SinkHealth,
    SinkWriteResult,
)
from lazy_harness.plugins.registry import PluginRegistry


class _SpyExternalSink:
    name = "spy_sink"
    instantiations = 0

    def __init__(self, **kwargs) -> None:
        type(self).instantiations += 1

    def write(self, event: MetricEvent) -> SinkWriteResult:
        return SinkWriteResult.ok()

    def drain(self, batch_size: int) -> DrainResult:
        return DrainResult(sent=0, failed=0, remaining=0)

    def health(self) -> SinkHealth:
        return SinkHealth(reachable=True)


def test_discovery_does_not_instantiate(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    _SpyExternalSink.instantiations = 0

    class _EP:
        name = "spy_sink"
        value = "x:y"
        dist = type("D", (), {"name": "acme"})

        def load(self):
            return _SpyExternalSink

    class _Eps:
        def select(self, group):
            return [_EP()] if group == "lazy_harness.metrics_sink" else []

    monkeypatch.setattr(importlib_metadata, "entry_points", lambda: _Eps())

    reg = PluginRegistry()
    reg.discover_entry_points(MetricsSink, group="lazy_harness.metrics_sink")
    # Discovery happened but the plugin was not instantiated.
    assert _SpyExternalSink.instantiations == 0

    # And because the default MetricsConfig does not name 'ext:spy_sink',
    # build_sinks will not instantiate it either. (build_sinks currently only
    # handles built-ins; the test documents the invariant for the MVP slice.)
    db = MetricsDB(tmp_path / "m.db")
    try:
        sinks = build_sinks(MetricsConfig(), db=db)
        assert _SpyExternalSink.instantiations == 0
        assert all(type(s).__name__ != "_SpyExternalSink" for s in sinks)
    finally:
        db.close()

"""Tests for plugins.registry."""

from __future__ import annotations

import pytest

from lazy_harness.plugins.contracts import (
    DrainResult,
    MetricEvent,
    MetricsSink,
    SinkHealth,
    SinkWriteResult,
)
from lazy_harness.plugins.errors import PluginConflict, PluginNotFound
from lazy_harness.plugins.registry import PluginRegistry


class _DummySink:
    name = "dummy"

    def write(self, event: MetricEvent) -> SinkWriteResult:
        return SinkWriteResult.ok()

    def drain(self, batch_size: int) -> DrainResult:
        return DrainResult(sent=0, failed=0, remaining=0)

    def health(self) -> SinkHealth:
        return SinkHealth(reachable=True)


def test_register_builtin_and_resolve() -> None:
    reg = PluginRegistry()
    reg.register_builtin(MetricsSink, _DummySink)
    sink_cls = reg.resolve(MetricsSink, "dummy")
    assert sink_cls is _DummySink


def test_resolve_unknown_raises_plugin_not_found() -> None:
    reg = PluginRegistry()
    with pytest.raises(PluginNotFound) as info:
        reg.resolve(MetricsSink, "missing")
    assert info.value.kind == "MetricsSink"
    assert info.value.name == "missing"


def test_builtin_name_collision_raises_plugin_conflict() -> None:
    reg = PluginRegistry()

    class _Other:
        name = "dummy"

        def write(self, event: MetricEvent) -> SinkWriteResult: ...
        def drain(self, batch_size: int) -> DrainResult: ...
        def health(self) -> SinkHealth: ...

    reg.register_builtin(MetricsSink, _DummySink)
    with pytest.raises(PluginConflict):
        reg.register_builtin(MetricsSink, _Other)


def test_list_available_lists_builtins() -> None:
    reg = PluginRegistry()
    reg.register_builtin(MetricsSink, _DummySink)
    listing = reg.list_available(MetricsSink)
    assert ("dummy", "builtin") in [(p.name, p.origin) for p in listing]

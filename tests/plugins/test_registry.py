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


def test_discover_entry_points_adds_prefixed_name(monkeypatch: pytest.MonkeyPatch) -> None:
    from importlib import metadata as importlib_metadata

    class _ExtSink:
        name = "acme_remote"

        def write(self, event: MetricEvent) -> SinkWriteResult: ...
        def drain(self, batch_size: int) -> DrainResult: ...
        def health(self) -> SinkHealth: ...

    class _FakeEntryPoint:
        name = "acme_remote"
        value = "acme_remote_sink:Sink"
        dist = type("D", (), {"name": "acme-remote"})

        def load(self) -> type:
            return _ExtSink

    class _FakeEps:
        def select(self, group: str) -> list[_FakeEntryPoint]:
            return [_FakeEntryPoint()] if group == "lazy_harness.metrics_sink" else []

    monkeypatch.setattr(importlib_metadata, "entry_points", lambda: _FakeEps())

    reg = PluginRegistry()
    reg.discover_entry_points(MetricsSink, group="lazy_harness.metrics_sink")

    resolved = reg.resolve(MetricsSink, "ext:acme_remote")
    assert resolved is _ExtSink

    listing = reg.list_available(MetricsSink)
    origins = {p.origin for p in listing}
    assert "ext:acme-remote" in origins


def test_builtin_wins_over_entry_point_with_same_base_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A plugin registered both as built-in 'http_remote' and as entry point
    'http_remote' must resolve to the built-in. The entry point still gets
    registered under 'ext:http_remote' so the user can reach it explicitly
    if they really want to."""
    from importlib import metadata as importlib_metadata

    class _BuiltinHttp:
        name = "http_remote"

        def write(self, event: MetricEvent) -> SinkWriteResult: ...
        def drain(self, batch_size: int) -> DrainResult: ...
        def health(self) -> SinkHealth: ...

    class _ExtHttp:
        name = "http_remote"

        def write(self, event: MetricEvent) -> SinkWriteResult: ...
        def drain(self, batch_size: int) -> DrainResult: ...
        def health(self) -> SinkHealth: ...

    class _EP:
        name = "http_remote"
        value = "x:y"
        dist = type("D", (), {"name": "acme"})

        def load(self) -> type:
            return _ExtHttp

    class _Eps:
        def select(self, group: str) -> list[_EP]:
            return [_EP()] if group == "lazy_harness.metrics_sink" else []

    monkeypatch.setattr(importlib_metadata, "entry_points", lambda: _Eps())

    reg = PluginRegistry()
    reg.register_builtin(MetricsSink, _BuiltinHttp)
    reg.discover_entry_points(MetricsSink, group="lazy_harness.metrics_sink")

    assert reg.resolve(MetricsSink, "http_remote") is _BuiltinHttp
    assert reg.resolve(MetricsSink, "ext:http_remote") is _ExtHttp

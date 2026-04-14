# Metrics Sink Vertical Slice — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the plugin system contracts, registry, and the `metrics_sink` vertical slice end-to-end (local SQLite + HTTP remote sink with offline buffer, worker drain, GitHub-handle identity, and CLI surface), per spec `specs/designs/2026-04-14-plugin-system-metrics-sink-design.md`.

**Architecture:** Hybrid plugin registry (built-in + Python entry points) with `MetricsSink` Protocol. The existing `monitoring/ingest.py` rebuild-from-scratch pipeline gains a post-rebuild step that routes each aggregated row through registered sinks. `sqlite_local` keeps the current `session_stats` shape and adds identity columns; `http_remote` enqueues to a new `sink_outbox` table that a worker drains opportunistically on every `lh` invocation, with claim leases, idempotency by stable `event_id`, and exponential backoff.

**Tech Stack:** Python 3.11+, `uv`, `pytest`, `click`, `rich`, `tomllib`, SQLite stdlib, `pytest-httpserver` (new dev dep) for fake backend, `httpx` (already likely available — verify at Task 19). ULID via `uuid` stdlib (`uuid7`-style timestamp+random, no new dep).

**Context for the implementer:** You do not need to read the full spec to work each task, but when something is unclear, consult `specs/designs/2026-04-14-plugin-system-metrics-sink-design.md`. The spec's `D1`–`D19` decisions anchor everything here. **Every task follows strict TDD**: failing test first, watch it fail with the expected error, then minimal code to green, commit. This is repo rule (see `CLAUDE.md`).

**Current state snapshot (so you don't need to guess):**

- `src/lazy_harness/monitoring/db.py::MetricsDB` exposes `replace_profile_stats(profile, entries)` which wipes and re-inserts per-profile rows on every ingest. The table `session_stats` has a `UNIQUE(session, model)` constraint. You will **keep** this shape and **add** columns, not replace it.
- `src/lazy_harness/monitoring/ingest.py::ingest_all(cfg, db, pricing)` walks JSONL files, dedupes messages by `msg_id`, aggregates per `(session_id, model)`, computes cost, and calls `db.replace_profile_stats()`. You will add a post-rebuild sink fanout here.
- `src/lazy_harness/core/config.py` parses TOML into dataclasses. `MonitoringConfig` exists. You will add `MetricsConfig` next to it (not inside it — a new top-level block `[metrics]` for sink selection, kept separate from the existing `[monitoring]` which controls the ingest pipeline itself).
- `src/lazy_harness/core/profiles.py::ProfileInfo` is a thin dataclass. Identity resolution is new territory — you will add `core/identity.py`.
- `src/lazy_harness/cli/metrics_cmd.py` is a Click group with `ingest` as its only subcommand. You will add `drain` and `status`.

**Conventions to follow:**

- Every new module under `src/lazy_harness/` gets a test file under `tests/` at the mirrored path.
- Type hints everywhere, `Any` only at parser boundaries when unavoidable.
- All new files start with a docstring explaining their one responsibility.
- Commits are Conventional Commits. No `Co-Authored-By`. Use `feat:`, `test:`, `refactor:`, `chore:`.
- Run `uv run pytest -q` before every commit.
- Run `uv run ruff check src tests` before every commit.
- Never skip TDD. If you wrote code before the test, delete it.

---

## File Structure (what you will create or modify)

**New files:**

```
src/lazy_harness/plugins/__init__.py              # Package marker
src/lazy_harness/plugins/errors.py                # Exception hierarchy
src/lazy_harness/plugins/contracts.py             # Protocols + MetricEvent
src/lazy_harness/plugins/registry.py              # Built-in + entry-point discovery
src/lazy_harness/core/identity.py                 # GitHub/git identity resolver
src/lazy_harness/monitoring/sinks/__init__.py     # Package marker
src/lazy_harness/monitoring/sinks/sqlite_local.py # Built-in local sink adapter
src/lazy_harness/monitoring/sinks/http_remote.py  # Built-in HTTP remote sink
src/lazy_harness/monitoring/sinks/worker.py       # Outbox drainer
tests/plugins/__init__.py
tests/plugins/test_errors.py
tests/plugins/test_contracts.py
tests/plugins/test_registry.py
tests/core/test_identity.py
tests/monitoring/sinks/__init__.py
tests/monitoring/sinks/test_sqlite_local.py
tests/monitoring/sinks/test_http_remote.py
tests/monitoring/sinks/test_worker.py
tests/monitoring/test_opt_in_validation.py
tests/monitoring/test_default_local.py
tests/monitoring/test_offline_reconnect.py
tests/monitoring/test_idempotency.py
tests/cli/test_metrics_drain.py
tests/cli/test_metrics_status.py
```

**Modified files:**

```
src/lazy_harness/monitoring/db.py                 # New columns + outbox table + outbox ops
src/lazy_harness/monitoring/ingest.py             # Sink fanout + event_id stamping
src/lazy_harness/core/config.py                   # MetricsConfig + [metrics] parser
src/lazy_harness/cli/metrics_cmd.py               # drain + status subcommands + stderr visibility
src/lazy_harness/cli/doctor_cmd.py                # "network egress" section
pyproject.toml                                    # pytest-httpserver dev dep
```

---

## Phase 0 — Plugin contracts and errors

This phase is pure scaffolding, zero behavior. It exists so later phases have types to import.

### Task 1: Plugin error hierarchy

**Files:**
- Create: `src/lazy_harness/plugins/__init__.py`
- Create: `src/lazy_harness/plugins/errors.py`
- Create: `tests/plugins/__init__.py`
- Create: `tests/plugins/test_errors.py`

- [ ] **Step 1.1: Write the failing test**

`tests/plugins/test_errors.py`:

```python
"""Tests for plugins.errors."""

from __future__ import annotations

import pytest

from lazy_harness.plugins.errors import (
    PluginConflict,
    PluginContractError,
    PluginError,
    PluginNotFound,
)


def test_plugin_error_is_base() -> None:
    assert issubclass(PluginNotFound, PluginError)
    assert issubclass(PluginConflict, PluginError)
    assert issubclass(PluginContractError, PluginError)


def test_plugin_not_found_carries_name_and_kind() -> None:
    err = PluginNotFound(kind="metrics_sink", name="http_remote")
    assert "metrics_sink" in str(err)
    assert "http_remote" in str(err)


def test_plugin_conflict_mentions_both_registrations() -> None:
    err = PluginConflict(kind="metrics_sink", name="http_remote", origins=["builtin", "ext:acme"])
    msg = str(err)
    assert "builtin" in msg
    assert "ext:acme" in msg


def test_plugin_error_is_exception() -> None:
    with pytest.raises(PluginError):
        raise PluginNotFound(kind="x", name="y")
```

- [ ] **Step 1.2: Run test to verify it fails**

Run: `uv run pytest tests/plugins/test_errors.py -v`
Expected: `ModuleNotFoundError: No module named 'lazy_harness.plugins'` (or similar import error).

- [ ] **Step 1.3: Create the package marker files**

`src/lazy_harness/plugins/__init__.py`:

```python
"""Plugin system: contracts, registry, errors."""
```

`tests/plugins/__init__.py`:

```python
```

- [ ] **Step 1.4: Write the minimal implementation**

`src/lazy_harness/plugins/errors.py`:

```python
"""Exceptions raised by the plugin system."""

from __future__ import annotations


class PluginError(Exception):
    """Base class for all plugin-system failures."""


class PluginNotFound(PluginError):
    """Raised when a plugin name is requested but not registered."""

    def __init__(self, *, kind: str, name: str) -> None:
        super().__init__(f"no {kind} plugin registered as {name!r}")
        self.kind = kind
        self.name = name


class PluginConflict(PluginError):
    """Raised when two plugins try to register the same (kind, name) pair."""

    def __init__(self, *, kind: str, name: str, origins: list[str]) -> None:
        joined = ", ".join(origins)
        super().__init__(f"conflicting {kind} registrations for {name!r}: {joined}")
        self.kind = kind
        self.name = name
        self.origins = origins


class PluginContractError(PluginError):
    """Raised when a plugin violates its Protocol contract at runtime."""
```

- [ ] **Step 1.5: Verify green**

Run: `uv run pytest tests/plugins/test_errors.py -v`
Expected: 4 passed.

- [ ] **Step 1.6: Lint and commit**

```bash
uv run ruff check src/lazy_harness/plugins tests/plugins
uv run pytest -q
git add src/lazy_harness/plugins/ tests/plugins/
git commit -m "feat(plugins): add plugin error hierarchy"
```

---

### Task 2: MetricEvent dataclass and MetricsSink Protocol

**Files:**
- Create: `src/lazy_harness/plugins/contracts.py`
- Create: `tests/plugins/test_contracts.py`

- [ ] **Step 2.1: Write the failing test**

`tests/plugins/test_contracts.py`:

```python
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


def test_schema_version_is_int_one() -> None:
    assert METRIC_EVENT_SCHEMA_VERSION == 1
    assert isinstance(METRIC_EVENT_SCHEMA_VERSION, int)


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
```

- [ ] **Step 2.2: Run and verify red**

Run: `uv run pytest tests/plugins/test_contracts.py -v`
Expected: ImportError on `lazy_harness.plugins.contracts`.

- [ ] **Step 2.3: Implement contracts**

`src/lazy_harness/plugins/contracts.py`:

```python
"""Stable plugin contracts.

This module is the public API of the plugin system. It defines the
`MetricEvent` wire format (schema-versioned) and the `MetricsSink` Protocol
that every metrics sink — built-in or third-party — implements.

Breaking changes to anything in this file require bumping
`METRIC_EVENT_SCHEMA_VERSION` and coordinating with every registered sink.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, ClassVar, Protocol, runtime_checkable

METRIC_EVENT_SCHEMA_VERSION: int = 1


@dataclass(frozen=True, slots=True)
class MetricEvent:
    """One aggregated (profile, session, model) row destined for a sink."""

    event_id: str
    schema_version: int
    user_id: str
    tenant_id: str
    profile: str
    session: str
    model: str
    project: str
    date: str
    input_tokens: int
    output_tokens: int
    cache_read: int
    cache_create: int
    cost: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> MetricEvent:
        return cls(**data)


@dataclass(frozen=True, slots=True)
class SinkWriteResult:
    success: bool
    error: str | None = None

    @classmethod
    def ok(cls) -> SinkWriteResult:
        return cls(success=True)

    @classmethod
    def failure(cls, error: str) -> SinkWriteResult:
        return cls(success=False, error=error)


@dataclass(frozen=True, slots=True)
class DrainResult:
    sent: int
    failed: int
    remaining: int


@dataclass(frozen=True, slots=True)
class SinkHealth:
    reachable: bool
    detail: str = ""


@runtime_checkable
class MetricsSink(Protocol):
    """Contract for anything that can receive a MetricEvent.

    All methods must be non-raising under normal operation. A sink may
    return a failed `SinkWriteResult`; it must not propagate exceptions
    to the caller because the caller is the ingest pipeline and it must
    stay alive.
    """

    name: ClassVar[str]

    def write(self, event: MetricEvent) -> SinkWriteResult: ...

    def drain(self, batch_size: int) -> DrainResult: ...

    def health(self) -> SinkHealth: ...
```

- [ ] **Step 2.4: Verify green**

Run: `uv run pytest tests/plugins/test_contracts.py -v`
Expected: 7 passed.

- [ ] **Step 2.5: Commit**

```bash
uv run ruff check src tests
uv run pytest -q
git add src/lazy_harness/plugins/contracts.py tests/plugins/test_contracts.py
git commit -m "feat(plugins): add MetricEvent dataclass and MetricsSink protocol"
```

---

## Phase 1 — Registry

### Task 3: Built-in registry with register + resolve

**Files:**
- Create: `src/lazy_harness/plugins/registry.py`
- Create: `tests/plugins/test_registry.py`

- [ ] **Step 3.1: Write the first failing test (built-in registration and resolution)**

`tests/plugins/test_registry.py`:

```python
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
```

- [ ] **Step 3.2: Run red**

Run: `uv run pytest tests/plugins/test_registry.py -v`
Expected: ImportError on `lazy_harness.plugins.registry`.

- [ ] **Step 3.3: Implement minimal registry (built-in only, entry points next)**

`src/lazy_harness/plugins/registry.py`:

```python
"""Hybrid plugin registry: built-in registrations + Python entry-point discovery.

Name resolution order: built-in first, then entry points (prefixed `ext:`).
Nothing is instantiated unless a caller explicitly resolves it — discovery
is not activation.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Type

from lazy_harness.plugins.errors import PluginConflict, PluginNotFound


@dataclass(frozen=True)
class PluginInfo:
    name: str
    origin: str  # "builtin" | "ext:<dist-name>"
    impl: type[Any]


class PluginRegistry:
    def __init__(self) -> None:
        self._builtins: dict[type, dict[str, type[Any]]] = {}
        self._external: dict[type, dict[str, PluginInfo]] = {}

    def register_builtin(self, kind: type, impl: type[Any]) -> None:
        name = getattr(impl, "name", None)
        if not isinstance(name, str) or not name:
            raise ValueError(f"{impl!r} has no valid .name class attribute")
        bucket = self._builtins.setdefault(kind, {})
        if name in bucket:
            raise PluginConflict(
                kind=kind.__name__,
                name=name,
                origins=["builtin", "builtin"],
            )
        bucket[name] = impl

    def resolve(self, kind: type, name: str) -> type[Any]:
        bucket = self._builtins.get(kind, {})
        if name in bucket:
            return bucket[name]
        ext = self._external.get(kind, {})
        if name in ext:
            return ext[name].impl
        raise PluginNotFound(kind=kind.__name__, name=name)

    def list_available(self, kind: type) -> list[PluginInfo]:
        result: list[PluginInfo] = []
        for name, impl in self._builtins.get(kind, {}).items():
            result.append(PluginInfo(name=name, origin="builtin", impl=impl))
        for info in self._external.get(kind, {}).values():
            result.append(info)
        return result
```

- [ ] **Step 3.4: Verify green**

Run: `uv run pytest tests/plugins/test_registry.py -v`
Expected: 4 passed.

- [ ] **Step 3.5: Commit**

```bash
uv run pytest -q
git add src/lazy_harness/plugins/registry.py tests/plugins/test_registry.py
git commit -m "feat(plugins): add built-in plugin registry with conflict detection"
```

---

### Task 4: Entry-point discovery with `ext:` prefix

**Files:**
- Modify: `src/lazy_harness/plugins/registry.py`
- Modify: `tests/plugins/test_registry.py`

- [ ] **Step 4.1: Write failing test using monkeypatched entry points**

Append to `tests/plugins/test_registry.py`:

```python
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
```

- [ ] **Step 4.2: Run red**

Run: `uv run pytest tests/plugins/test_registry.py::test_discover_entry_points_adds_prefixed_name -v`
Expected: `AttributeError: 'PluginRegistry' object has no attribute 'discover_entry_points'`.

- [ ] **Step 4.3: Implement discovery**

Replace the body of `src/lazy_harness/plugins/registry.py` by adding a new method `discover_entry_points`. Final file:

```python
"""Hybrid plugin registry: built-in registrations + Python entry-point discovery.

Name resolution order: built-in first, then entry points (prefixed `ext:`).
Nothing is instantiated unless a caller explicitly resolves it — discovery
is not activation.
"""

from __future__ import annotations

from dataclasses import dataclass
from importlib import metadata as importlib_metadata
from typing import Any

from lazy_harness.plugins.errors import PluginConflict, PluginNotFound


@dataclass(frozen=True)
class PluginInfo:
    name: str
    origin: str  # "builtin" | "ext:<dist-name>"
    impl: type[Any]


class PluginRegistry:
    def __init__(self) -> None:
        self._builtins: dict[type, dict[str, type[Any]]] = {}
        self._external: dict[type, dict[str, PluginInfo]] = {}

    def register_builtin(self, kind: type, impl: type[Any]) -> None:
        name = getattr(impl, "name", None)
        if not isinstance(name, str) or not name:
            raise ValueError(f"{impl!r} has no valid .name class attribute")
        bucket = self._builtins.setdefault(kind, {})
        if name in bucket:
            raise PluginConflict(
                kind=kind.__name__,
                name=name,
                origins=["builtin", "builtin"],
            )
        bucket[name] = impl

    def discover_entry_points(self, kind: type, *, group: str) -> None:
        eps = importlib_metadata.entry_points()
        selected = eps.select(group=group) if hasattr(eps, "select") else []
        bucket = self._external.setdefault(kind, {})
        for ep in selected:
            impl = ep.load()
            base_name = getattr(impl, "name", ep.name)
            prefixed = f"ext:{base_name}"
            dist_name = getattr(ep.dist, "name", "unknown") if ep.dist else "unknown"
            if prefixed in bucket:
                raise PluginConflict(
                    kind=kind.__name__,
                    name=prefixed,
                    origins=[bucket[prefixed].origin, f"ext:{dist_name}"],
                )
            bucket[prefixed] = PluginInfo(
                name=prefixed, origin=f"ext:{dist_name}", impl=impl
            )

    def resolve(self, kind: type, name: str) -> type[Any]:
        bucket = self._builtins.get(kind, {})
        if name in bucket:
            return bucket[name]
        ext = self._external.get(kind, {})
        if name in ext:
            return ext[name].impl
        raise PluginNotFound(kind=kind.__name__, name=name)

    def list_available(self, kind: type) -> list[PluginInfo]:
        result: list[PluginInfo] = []
        for name, impl in self._builtins.get(kind, {}).items():
            result.append(PluginInfo(name=name, origin="builtin", impl=impl))
        for info in self._external.get(kind, {}).values():
            result.append(info)
        return result
```

- [ ] **Step 4.4: Verify green**

Run: `uv run pytest tests/plugins/test_registry.py -v`
Expected: 6 passed.

- [ ] **Step 4.5: Commit**

```bash
uv run pytest -q
git add src/lazy_harness/plugins/registry.py tests/plugins/test_registry.py
git commit -m "feat(plugins): discover sinks via Python entry points with ext: prefix"
```

---

## Phase 2 — Identity resolver

### Task 5: `core/identity.py` with four-step resolve order

**Files:**
- Create: `src/lazy_harness/core/identity.py`
- Create: `tests/core/test_identity.py`

The resolve order is: explicit profile value → `gh api user --jq .login` → `git config user.email` (parse local-part) → `$USER@$HOSTNAME` (stamped `implicit`). Each step is wrapped so it never raises to the caller.

- [ ] **Step 5.1: Write the failing test**

`tests/core/test_identity.py`:

```python
"""Tests for core.identity."""

from __future__ import annotations

import os
from unittest.mock import patch

import pytest

from lazy_harness.core.identity import ResolvedIdentity, resolve_identity


def test_explicit_user_id_wins() -> None:
    ident = resolve_identity(explicit="martin-flex")
    assert ident.user_id == "martin-flex"
    assert ident.source == "explicit"


def test_gh_used_when_explicit_missing() -> None:
    def fake_run_gh() -> str | None:
        return "martin-gh"

    ident = resolve_identity(
        explicit=None,
        _gh_reader=fake_run_gh,
    )
    assert ident.user_id == "martin-gh"
    assert ident.source == "gh"


def test_git_email_used_when_gh_missing() -> None:
    ident = resolve_identity(
        explicit=None,
        _gh_reader=lambda: None,
        _git_email_reader=lambda: "martin@example.com",
    )
    assert ident.user_id == "martin"
    assert ident.source == "git"


def test_implicit_fallback_stamps_user_at_host() -> None:
    with patch.dict(os.environ, {"USER": "martin", "HOSTNAME": "laptop"}, clear=False):
        ident = resolve_identity(
            explicit=None,
            _gh_reader=lambda: None,
            _git_email_reader=lambda: None,
        )
    assert ident.user_id == "martin@laptop"
    assert ident.source == "implicit"


def test_explicit_empty_string_is_ignored() -> None:
    ident = resolve_identity(
        explicit="",
        _gh_reader=lambda: "fallback",
    )
    assert ident.user_id == "fallback"
    assert ident.source == "gh"


def test_gh_reader_returning_empty_string_treated_as_missing() -> None:
    ident = resolve_identity(
        explicit=None,
        _gh_reader=lambda: "",
        _git_email_reader=lambda: "martin@example.com",
    )
    assert ident.source == "git"
```

- [ ] **Step 5.2: Run red**

Run: `uv run pytest tests/core/test_identity.py -v`
Expected: ImportError on `lazy_harness.core.identity`.

- [ ] **Step 5.3: Implement**

`src/lazy_harness/core/identity.py`:

```python
"""User identity resolution for metrics events.

Tries (in order): explicit profile value, `gh` CLI, `git config user.email`,
and finally `$USER@$HOSTNAME` marked as implicit. Every lookup is wrapped
so a failure moves to the next option instead of raising.
"""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from typing import Callable, Literal

IdentitySource = Literal["explicit", "gh", "git", "implicit"]


@dataclass(frozen=True, slots=True)
class ResolvedIdentity:
    user_id: str
    source: IdentitySource


def _read_gh_login() -> str | None:
    try:
        result = subprocess.run(
            ["gh", "api", "user", "--jq", ".login"],
            capture_output=True,
            text=True,
            timeout=3,
            check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None


def _read_git_email() -> str | None:
    try:
        result = subprocess.run(
            ["git", "config", "--get", "user.email"],
            capture_output=True,
            text=True,
            timeout=3,
            check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None


def resolve_identity(
    *,
    explicit: str | None,
    _gh_reader: Callable[[], str | None] = _read_gh_login,
    _git_email_reader: Callable[[], str | None] = _read_git_email,
) -> ResolvedIdentity:
    if explicit:
        return ResolvedIdentity(user_id=explicit, source="explicit")

    gh_login = _gh_reader()
    if gh_login:
        return ResolvedIdentity(user_id=gh_login, source="gh")

    email = _git_email_reader()
    if email:
        local = email.split("@", 1)[0]
        if local:
            return ResolvedIdentity(user_id=local, source="git")

    user = os.environ.get("USER") or "unknown"
    host = os.environ.get("HOSTNAME") or "host"
    return ResolvedIdentity(user_id=f"{user}@{host}", source="implicit")
```

- [ ] **Step 5.4: Verify green**

Run: `uv run pytest tests/core/test_identity.py -v`
Expected: 6 passed.

- [ ] **Step 5.5: Commit**

```bash
uv run pytest -q
git add src/lazy_harness/core/identity.py tests/core/test_identity.py
git commit -m "feat(core): add identity resolver with gh, git, implicit fallback"
```

---

## Phase 3 — Config surface for metrics sinks

### Task 6: `[metrics]` block parser with default-local invariant

**Files:**
- Modify: `src/lazy_harness/core/config.py`
- Create: `tests/core/test_metrics_config.py`

- [ ] **Step 6.1: Write the failing test**

`tests/core/test_metrics_config.py`:

```python
"""Tests for the [metrics] config block."""

from __future__ import annotations

from pathlib import Path

import pytest

from lazy_harness.core.config import (
    ConfigError,
    MetricsConfig,
    SinkDefinition,
    load_config,
)


def _write(tmp_path: Path, body: str) -> Path:
    p = tmp_path / "config.toml"
    p.write_text(body, encoding="utf-8")
    return p


def test_absent_metrics_block_defaults_to_sqlite_local_only(tmp_path: Path) -> None:
    cfg_path = _write(tmp_path, '[harness]\nversion = "1"\n')
    cfg = load_config(cfg_path)
    assert isinstance(cfg.metrics, MetricsConfig)
    assert cfg.metrics.sinks == ["sqlite_local"]
    assert cfg.metrics.sink_configs == {}
    assert cfg.metrics.user_id == ""
    assert cfg.metrics.tenant_id == "local"
    assert cfg.metrics.pending_ttl_days is None


def test_named_sink_requires_config_block(tmp_path: Path) -> None:
    cfg_path = _write(
        tmp_path,
        '[harness]\nversion = "1"\n'
        "[metrics]\n"
        'sinks = ["sqlite_local", "http_remote"]\n',
    )
    with pytest.raises(ConfigError) as info:
        load_config(cfg_path)
    assert "http_remote" in str(info.value)


def test_config_block_without_being_named_is_ignored(tmp_path: Path) -> None:
    cfg_path = _write(
        tmp_path,
        '[harness]\nversion = "1"\n'
        "[metrics]\n"
        'sinks = ["sqlite_local"]\n'
        "[metrics.sinks.http_remote]\n"
        'url = "https://example.invalid/ingest"\n',
    )
    cfg = load_config(cfg_path)
    assert cfg.metrics.sinks == ["sqlite_local"]
    assert "http_remote" not in cfg.metrics.sink_configs


def test_full_opt_in_parses_cleanly(tmp_path: Path) -> None:
    cfg_path = _write(
        tmp_path,
        '[harness]\nversion = "1"\n'
        "[metrics]\n"
        'sinks = ["sqlite_local", "http_remote"]\n'
        'user_id = "martin-flex"\n'
        'tenant_id = "flex"\n'
        "pending_ttl_days = 30\n"
        "[metrics.sinks.http_remote]\n"
        'url = "https://example.invalid/ingest"\n'
        "timeout_seconds = 5\n"
        "batch_size = 50\n",
    )
    cfg = load_config(cfg_path)
    assert cfg.metrics.sinks == ["sqlite_local", "http_remote"]
    assert cfg.metrics.user_id == "martin-flex"
    assert cfg.metrics.tenant_id == "flex"
    assert cfg.metrics.pending_ttl_days == 30
    remote = cfg.metrics.sink_configs["http_remote"]
    assert isinstance(remote, SinkDefinition)
    assert remote.options == {
        "url": "https://example.invalid/ingest",
        "timeout_seconds": 5,
        "batch_size": 50,
    }


def test_sqlite_local_is_always_valid_without_config_block(tmp_path: Path) -> None:
    cfg_path = _write(
        tmp_path,
        '[harness]\nversion = "1"\n'
        "[metrics]\n"
        'sinks = ["sqlite_local"]\n',
    )
    cfg = load_config(cfg_path)
    assert cfg.metrics.sinks == ["sqlite_local"]
```

- [ ] **Step 6.2: Run red**

Run: `uv run pytest tests/core/test_metrics_config.py -v`
Expected: ImportError on `MetricsConfig`/`SinkDefinition` from `lazy_harness.core.config`.

- [ ] **Step 6.3: Add dataclasses and parser to `core/config.py`**

In `src/lazy_harness/core/config.py`, add after the `CompoundLoopConfig` dataclass:

```python
@dataclass
class SinkDefinition:
    """Options for a named sink as declared under [metrics.sinks.<name>]."""

    options: dict[str, Any] = field(default_factory=dict)


@dataclass
class MetricsConfig:
    """Top-level [metrics] block.

    Default (no block): only `sqlite_local` runs, zero network I/O.
    Any other sink requires being named in `sinks` AND having a
    `[metrics.sinks.<name>]` options block. Missing options block for a
    named sink is a hard error.
    """

    sinks: list[str] = field(default_factory=lambda: ["sqlite_local"])
    sink_configs: dict[str, SinkDefinition] = field(default_factory=dict)
    user_id: str = ""
    tenant_id: str = "local"
    pending_ttl_days: int | None = None
```

Add `metrics: MetricsConfig = field(default_factory=MetricsConfig)` to the `Config` dataclass (next to `compound_loop`).

Add this helper next to `_parse_profiles`:

```python
def _parse_metrics(raw: dict[str, Any]) -> MetricsConfig:
    """Parse the [metrics] block enforcing the opt-in-doble invariant."""
    if not raw:
        return MetricsConfig()
    sinks = raw.get("sinks", ["sqlite_local"])
    if not isinstance(sinks, list) or not all(isinstance(s, str) for s in sinks):
        raise ConfigError("[metrics].sinks must be a list of strings")

    sinks_raw = raw.get("sinks", None)
    raw_blocks: dict[str, Any] = raw.get("sinks", {}) if isinstance(raw.get("sinks"), dict) else {}

    # tomllib parses [metrics.sinks.http_remote] as metrics["sinks"]["http_remote"]
    # ONLY if sinks is not also declared as a list. The list form wins, so
    # we have to read sub-tables from raw["sinks"] when it is a dict or
    # separately when declared flat.
    sink_tables: dict[str, dict[str, Any]] = {}
    if isinstance(raw.get("sinks"), dict):
        for k, v in raw["sinks"].items():
            if isinstance(v, dict):
                sink_tables[k] = v
    # When sinks is a list, tomllib places sub-tables under a different key —
    # see the documented shape: [metrics.sinks.http_remote] cannot coexist
    # with metrics.sinks = [...]. We instead use a distinct subkey.
    # The TOML we actually accept is:
    #     [metrics]
    #     sinks = ["sqlite_local", "http_remote"]
    #     [metrics.sink_options.http_remote]
    #     url = "..."
    # but tests above use `[metrics.sinks.http_remote]` form. Resolve by
    # supporting both: if `sinks` is a list, we look for options under
    # `sink_options`; otherwise the dict form below.
    raise NotImplementedError  # replaced in the next step — tests drive the shape
```

Wait — this reveals a TOML shape issue we need to settle before coding further. Stop here and see Step 6.4.

- [ ] **Step 6.4: Resolve TOML shape and re-plan the parser**

The tests above use `sinks = ["sqlite_local", "http_remote"]` and `[metrics.sinks.http_remote]` simultaneously. That is **not** valid TOML — a key cannot be both an array of strings and a table of tables. Fix the tests and the parser to use a separate sub-table name.

Edit `tests/core/test_metrics_config.py`: replace every `[metrics.sinks.<name>]` with `[metrics.sink_options.<name>]`. For example:

```toml
[metrics]
sinks = ["sqlite_local", "http_remote"]
[metrics.sink_options.http_remote]
url = "https://example.invalid/ingest"
```

Save the file, then re-run:

Run: `uv run pytest tests/core/test_metrics_config.py -v`
Expected: still red (parser not implemented yet) but now with a meaningful `MetricsConfig` error instead of a TOML decode error.

- [ ] **Step 6.5: Implement the parser for real**

Replace the half-written `_parse_metrics` with:

```python
def _parse_metrics(raw: dict[str, Any]) -> MetricsConfig:
    """Parse [metrics] with the default-local + opt-in-doble invariants.

    Shape:
        [metrics]
        sinks = ["sqlite_local", "http_remote"]
        user_id = "..."
        tenant_id = "..."
        pending_ttl_days = 30

        [metrics.sink_options.http_remote]
        url = "..."

    Rules:
    - Empty/missing [metrics] ⇒ sinks=["sqlite_local"], nothing else.
    - A sink named in `sinks` other than `sqlite_local` REQUIRES a
      corresponding `[metrics.sink_options.<name>]` table, else ConfigError.
    - A `[metrics.sink_options.<name>]` block whose name is not in `sinks`
      is silently ignored (config-muerta).
    """
    if not raw:
        return MetricsConfig()

    sinks = raw.get("sinks", ["sqlite_local"])
    if not isinstance(sinks, list) or not all(isinstance(s, str) and s for s in sinks):
        raise ConfigError("[metrics].sinks must be a list of non-empty strings")

    options_raw = raw.get("sink_options", {})
    if not isinstance(options_raw, dict):
        raise ConfigError("[metrics.sink_options] must be a table")

    sink_configs: dict[str, SinkDefinition] = {}
    for name in sinks:
        if name == "sqlite_local":
            sink_configs[name] = SinkDefinition(options={})
            continue
        if name not in options_raw:
            raise ConfigError(
                f"[metrics] sink {name!r} is named in `sinks` but has no "
                f"[metrics.sink_options.{name}] block"
            )
        block = options_raw[name]
        if not isinstance(block, dict):
            raise ConfigError(f"[metrics.sink_options.{name}] must be a table")
        sink_configs[name] = SinkDefinition(options=dict(block))

    # Blocks named but not in sinks = dead config, ignored.

    user_id = raw.get("user_id", "")
    if not isinstance(user_id, str):
        raise ConfigError("[metrics].user_id must be a string")
    tenant_id = raw.get("tenant_id", "local")
    if not isinstance(tenant_id, str):
        raise ConfigError("[metrics].tenant_id must be a string")
    ttl = raw.get("pending_ttl_days", None)
    if ttl is not None and not isinstance(ttl, int):
        raise ConfigError("[metrics].pending_ttl_days must be an integer or absent")

    return MetricsConfig(
        sinks=list(sinks),
        sink_configs=sink_configs,
        user_id=user_id,
        tenant_id=tenant_id,
        pending_ttl_days=ttl,
    )
```

In `load_config()`, after the `compound_loop` block is parsed, add:

```python
    metrics_raw = raw.get("metrics", {})
    cfg.metrics = _parse_metrics(metrics_raw)
```

Also update `_config_to_dict()` to serialize the metrics block (tests don't require this yet but `save_config()` will otherwise drop it on round-trip). Add after the `knowledge` block:

```python
    if cfg.metrics.sinks != ["sqlite_local"] or cfg.metrics.user_id or cfg.metrics.tenant_id != "local":
        metrics_out: dict[str, Any] = {"sinks": cfg.metrics.sinks}
        if cfg.metrics.user_id:
            metrics_out["user_id"] = cfg.metrics.user_id
        if cfg.metrics.tenant_id != "local":
            metrics_out["tenant_id"] = cfg.metrics.tenant_id
        if cfg.metrics.pending_ttl_days is not None:
            metrics_out["pending_ttl_days"] = cfg.metrics.pending_ttl_days
        options: dict[str, Any] = {}
        for name, definition in cfg.metrics.sink_configs.items():
            if name == "sqlite_local":
                continue
            options[name] = definition.options
        if options:
            metrics_out["sink_options"] = options
        result["metrics"] = metrics_out
```

- [ ] **Step 6.6: Verify green**

Run: `uv run pytest tests/core/test_metrics_config.py -v`
Expected: 5 passed.

Also run: `uv run pytest tests/core/ -v`
Expected: all existing `test_config` tests still pass.

- [ ] **Step 6.7: Commit**

```bash
uv run ruff check src tests
uv run pytest -q
git add src/lazy_harness/core/config.py tests/core/test_metrics_config.py
git commit -m "feat(core): add [metrics] block with default-local and opt-in-doble"
```

---

## Phase 4 — Database schema: identity columns + sink outbox

### Task 7: Idempotent migration adding identity columns to `session_stats`

**Files:**
- Modify: `src/lazy_harness/monitoring/db.py`
- Modify: `tests/monitoring/test_db.py` (create if not present)

- [ ] **Step 7.1: Write the failing test**

In `tests/monitoring/test_db.py` (create if missing with `from lazy_harness.monitoring.db import MetricsDB` at top), add:

```python
import sqlite3
from pathlib import Path

from lazy_harness.monitoring.db import MetricsDB


def test_new_db_has_identity_columns(tmp_path: Path) -> None:
    db = MetricsDB(tmp_path / "m.db")
    try:
        cols = {
            row[1]
            for row in db._conn.execute("PRAGMA table_info(session_stats)").fetchall()
        }
    finally:
        db.close()
    assert "user_id" in cols
    assert "tenant_id" in cols
    assert "event_id" in cols


def test_migration_adds_columns_to_old_db(tmp_path: Path) -> None:
    """An existing DB without identity columns is upgraded in place."""
    path = tmp_path / "old.db"
    legacy = sqlite3.connect(str(path))
    legacy.execute(
        """
        CREATE TABLE session_stats (
            session TEXT NOT NULL,
            date TEXT NOT NULL,
            model TEXT NOT NULL,
            profile TEXT NOT NULL DEFAULT '',
            project TEXT NOT NULL DEFAULT '',
            input_tokens INTEGER NOT NULL DEFAULT 0,
            output_tokens INTEGER NOT NULL DEFAULT 0,
            cache_read INTEGER NOT NULL DEFAULT 0,
            cache_create INTEGER NOT NULL DEFAULT 0,
            cost REAL NOT NULL DEFAULT 0.0,
            UNIQUE(session, model)
        )
        """
    )
    legacy.execute(
        "INSERT INTO session_stats (session, date, model) VALUES (?, ?, ?)",
        ("s1", "2026-04-01", "sonnet"),
    )
    legacy.commit()
    legacy.close()

    db = MetricsDB(path)
    try:
        row = db._conn.execute(
            "SELECT session, user_id, tenant_id, event_id FROM session_stats WHERE session = 's1'"
        ).fetchone()
    finally:
        db.close()
    assert row["session"] == "s1"
    assert row["user_id"] == "local"
    assert row["tenant_id"] == "local"
    assert row["event_id"] != ""  # backfilled deterministically


def test_migration_is_idempotent(tmp_path: Path) -> None:
    path = tmp_path / "m.db"
    MetricsDB(path).close()
    # Open a second time — should not raise on duplicate column.
    db = MetricsDB(path)
    db.close()
```

- [ ] **Step 7.2: Run red**

Run: `uv run pytest tests/monitoring/test_db.py -v`
Expected: failures on missing columns.

- [ ] **Step 7.3: Implement the migration**

In `src/lazy_harness/monitoring/db.py`, replace `_create_tables` and add `_migrate`:

```python
    def _create_tables(self) -> None:
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS session_stats (
                session TEXT NOT NULL,
                date TEXT NOT NULL,
                model TEXT NOT NULL,
                profile TEXT NOT NULL DEFAULT '',
                project TEXT NOT NULL DEFAULT '',
                input_tokens INTEGER NOT NULL DEFAULT 0,
                output_tokens INTEGER NOT NULL DEFAULT 0,
                cache_read INTEGER NOT NULL DEFAULT 0,
                cache_create INTEGER NOT NULL DEFAULT 0,
                cost REAL NOT NULL DEFAULT 0.0,
                user_id TEXT NOT NULL DEFAULT 'local',
                tenant_id TEXT NOT NULL DEFAULT 'local',
                event_id TEXT NOT NULL DEFAULT '',
                UNIQUE(session, model)
            )
        """)
        self._conn.execute("CREATE INDEX IF NOT EXISTS idx_stats_date ON session_stats(date)")
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS ingest_meta (
                session TEXT PRIMARY KEY,
                mtime_ns INTEGER NOT NULL
            )
        """)
        self._migrate_identity_columns()
        self._conn.commit()

    def _migrate_identity_columns(self) -> None:
        """Add user_id/tenant_id/event_id to session_stats if missing.

        Older databases created before the plugin system rename have a
        narrower schema. Use PRAGMA table_info to detect missing columns
        and ALTER TABLE them in. event_id is backfilled deterministically
        from (profile, session, model) for legacy rows so the remote sink
        has a stable idempotency key.
        """
        cols = {row[1] for row in self._conn.execute("PRAGMA table_info(session_stats)")}
        if "user_id" not in cols:
            self._conn.execute(
                "ALTER TABLE session_stats ADD COLUMN user_id TEXT NOT NULL DEFAULT 'local'"
            )
        if "tenant_id" not in cols:
            self._conn.execute(
                "ALTER TABLE session_stats ADD COLUMN tenant_id TEXT NOT NULL DEFAULT 'local'"
            )
        if "event_id" not in cols:
            self._conn.execute(
                "ALTER TABLE session_stats ADD COLUMN event_id TEXT NOT NULL DEFAULT ''"
            )
            # Backfill deterministic event_ids for legacy rows.
            from lazy_harness.monitoring.event_id import derive_event_id

            rows = self._conn.execute(
                "SELECT rowid, profile, session, model FROM session_stats WHERE event_id = ''"
            ).fetchall()
            for row in rows:
                eid = derive_event_id(profile=row["profile"], session=row["session"], model=row["model"])
                self._conn.execute(
                    "UPDATE session_stats SET event_id = ? WHERE rowid = ?",
                    (eid, row["rowid"]),
                )
```

- [ ] **Step 7.4: Add the event_id helper**

Create `src/lazy_harness/monitoring/event_id.py`:

```python
"""Deterministic event_id derivation for metric rows.

Uses SHA-256 of a canonical string so the same (profile, session, model)
tuple always yields the same id across machines and re-ingests. The remote
backend applies upsert-by-event_id for idempotency.
"""

from __future__ import annotations

import hashlib


def derive_event_id(*, profile: str, session: str, model: str) -> str:
    raw = f"{profile}\x1f{session}\x1f{model}".encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:32]
```

Create `tests/monitoring/test_event_id.py`:

```python
from lazy_harness.monitoring.event_id import derive_event_id


def test_event_id_is_deterministic() -> None:
    a = derive_event_id(profile="p", session="s", model="m")
    b = derive_event_id(profile="p", session="s", model="m")
    assert a == b


def test_event_id_differs_by_input() -> None:
    a = derive_event_id(profile="p", session="s", model="m")
    b = derive_event_id(profile="p", session="s", model="other")
    assert a != b


def test_event_id_is_fixed_length() -> None:
    assert len(derive_event_id(profile="p", session="s", model="m")) == 32
```

- [ ] **Step 7.5: Verify green**

Run: `uv run pytest tests/monitoring/test_db.py tests/monitoring/test_event_id.py -v`
Expected: all pass.

Run full suite: `uv run pytest -q`
Expected: full suite green.

- [ ] **Step 7.6: Commit**

```bash
uv run ruff check src tests
git add src/lazy_harness/monitoring/db.py src/lazy_harness/monitoring/event_id.py tests/monitoring/test_db.py tests/monitoring/test_event_id.py
git commit -m "feat(monitoring): add identity columns and deterministic event_id"
```

---

### Task 8: `sink_outbox` table and operations

**Files:**
- Modify: `src/lazy_harness/monitoring/db.py`
- Modify: `tests/monitoring/test_db.py`

- [ ] **Step 8.1: Write failing tests**

Append to `tests/monitoring/test_db.py`:

```python
import json
import time

from lazy_harness.monitoring.db import MetricsDB, OutboxRow


def test_outbox_enqueue_starts_pending(tmp_path: Path) -> None:
    db = MetricsDB(tmp_path / "m.db")
    try:
        db.outbox_enqueue(
            sink_name="http_remote",
            event_id="eid1",
            payload_json='{"event_id":"eid1"}',
        )
        rows = db.outbox_list_pending(sink_name="http_remote")
        assert len(rows) == 1
        assert rows[0].status == "pending"
        assert rows[0].attempts == 0
    finally:
        db.close()


def test_outbox_claim_and_mark_sent(tmp_path: Path) -> None:
    db = MetricsDB(tmp_path / "m.db")
    try:
        db.outbox_enqueue(sink_name="http_remote", event_id="e1", payload_json="{}")
        db.outbox_enqueue(sink_name="http_remote", event_id="e2", payload_json="{}")

        claimed = db.outbox_claim(sink_name="http_remote", batch_size=10, lease_seconds=60)
        assert [r.event_id for r in claimed] == ["e1", "e2"]
        for r in claimed:
            assert r.status == "sending"
            assert r.lease_until is not None

        db.outbox_mark_sent("http_remote", "e1")
        remaining = db.outbox_list_pending(sink_name="http_remote")
        # e2 is still leased-sending, not pending.
        assert [r.event_id for r in remaining] == []
        still_sending = db.outbox_list_sending(sink_name="http_remote")
        assert [r.event_id for r in still_sending] == ["e2"]


def test_outbox_expired_lease_is_reclaimable(tmp_path: Path) -> None:
    db = MetricsDB(tmp_path / "m.db")
    try:
        db.outbox_enqueue(sink_name="http_remote", event_id="e1", payload_json="{}")
        db.outbox_claim(sink_name="http_remote", batch_size=10, lease_seconds=0)
        # lease_seconds=0 ⇒ expires instantly.
        time.sleep(0.01)
        reclaimed = db.outbox_claim(sink_name="http_remote", batch_size=10, lease_seconds=60)
        assert [r.event_id for r in reclaimed] == ["e1"]
    finally:
        db.close()


def test_outbox_mark_failed_increments_attempts_and_sets_next(tmp_path: Path) -> None:
    db = MetricsDB(tmp_path / "m.db")
    try:
        db.outbox_enqueue(sink_name="http_remote", event_id="e1", payload_json="{}")
        db.outbox_claim(sink_name="http_remote", batch_size=1, lease_seconds=60)
        db.outbox_mark_failed("http_remote", "e1", error="timeout", retry_after_seconds=30)

        rows = db.outbox_list_pending(sink_name="http_remote", due_now=False)
        assert len(rows) == 1
        assert rows[0].attempts == 1
        assert rows[0].last_error == "timeout"
        assert rows[0].status == "pending"
        assert rows[0].next_attempt_ts is not None
    finally:
        db.close()


def test_outbox_dedupe_by_event_id_on_enqueue(tmp_path: Path) -> None:
    """Enqueueing the same (sink, event_id) twice updates the row, not duplicates it."""
    db = MetricsDB(tmp_path / "m.db")
    try:
        db.outbox_enqueue(sink_name="http_remote", event_id="e1", payload_json='{"v":1}')
        db.outbox_enqueue(sink_name="http_remote", event_id="e1", payload_json='{"v":2}')
        rows = db.outbox_list_pending(sink_name="http_remote")
        assert len(rows) == 1
        assert json.loads(rows[0].payload_json)["v"] == 2
    finally:
        db.close()
```

- [ ] **Step 8.2: Run red**

Run: `uv run pytest tests/monitoring/test_db.py -v`
Expected: failures on missing `OutboxRow`, `outbox_enqueue`, etc.

- [ ] **Step 8.3: Implement outbox**

In `src/lazy_harness/monitoring/db.py`, add at the top:

```python
import time
from dataclasses import dataclass
```

After the `MetricsDB` class, add:

```python
@dataclass(frozen=True, slots=True)
class OutboxRow:
    sink_name: str
    event_id: str
    payload_json: str
    status: str  # pending | sending | sent | failed
    attempts: int
    last_error: str
    next_attempt_ts: float | None
    lease_until: float | None
```

In `MetricsDB._create_tables`, add a second CREATE:

```python
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS sink_outbox (
                sink_name TEXT NOT NULL,
                event_id TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                attempts INTEGER NOT NULL DEFAULT 0,
                last_error TEXT NOT NULL DEFAULT '',
                next_attempt_ts REAL,
                lease_until REAL,
                created_ts REAL NOT NULL,
                PRIMARY KEY (sink_name, event_id)
            )
        """)
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_outbox_pending "
            "ON sink_outbox(sink_name, status, next_attempt_ts)"
        )
```

Add methods:

```python
    def outbox_enqueue(self, *, sink_name: str, event_id: str, payload_json: str) -> None:
        now = time.time()
        self._conn.execute(
            """
            INSERT INTO sink_outbox (
                sink_name, event_id, payload_json, status, attempts,
                last_error, next_attempt_ts, lease_until, created_ts
            ) VALUES (?, ?, ?, 'pending', 0, '', NULL, NULL, ?)
            ON CONFLICT(sink_name, event_id) DO UPDATE SET
                payload_json = excluded.payload_json,
                status = 'pending',
                next_attempt_ts = NULL,
                lease_until = NULL,
                last_error = ''
            """,
            (sink_name, event_id, payload_json, now),
        )
        self._conn.commit()

    def outbox_claim(
        self, *, sink_name: str, batch_size: int, lease_seconds: int
    ) -> list[OutboxRow]:
        now = time.time()
        lease_until = now + lease_seconds
        # Candidate rows: pending (never attempted, or due now) OR sending with
        # an expired lease.
        candidates = self._conn.execute(
            """
            SELECT sink_name, event_id, payload_json, status, attempts,
                   last_error, next_attempt_ts, lease_until
            FROM sink_outbox
            WHERE sink_name = ?
              AND (
                (status = 'pending' AND (next_attempt_ts IS NULL OR next_attempt_ts <= ?))
                OR (status = 'sending' AND (lease_until IS NULL OR lease_until <= ?))
              )
            ORDER BY created_ts ASC
            LIMIT ?
            """,
            (sink_name, now, now, batch_size),
        ).fetchall()
        claimed: list[OutboxRow] = []
        for row in candidates:
            self._conn.execute(
                """
                UPDATE sink_outbox
                SET status = 'sending', lease_until = ?
                WHERE sink_name = ? AND event_id = ?
                """,
                (lease_until, row["sink_name"], row["event_id"]),
            )
            claimed.append(
                OutboxRow(
                    sink_name=row["sink_name"],
                    event_id=row["event_id"],
                    payload_json=row["payload_json"],
                    status="sending",
                    attempts=row["attempts"],
                    last_error=row["last_error"],
                    next_attempt_ts=row["next_attempt_ts"],
                    lease_until=lease_until,
                )
            )
        self._conn.commit()
        return claimed

    def outbox_mark_sent(self, sink_name: str, event_id: str) -> None:
        self._conn.execute(
            "UPDATE sink_outbox SET status = 'sent', lease_until = NULL "
            "WHERE sink_name = ? AND event_id = ?",
            (sink_name, event_id),
        )
        self._conn.commit()

    def outbox_mark_failed(
        self, sink_name: str, event_id: str, *, error: str, retry_after_seconds: float
    ) -> None:
        next_ts = time.time() + retry_after_seconds
        self._conn.execute(
            """
            UPDATE sink_outbox
            SET status = 'pending',
                attempts = attempts + 1,
                last_error = ?,
                next_attempt_ts = ?,
                lease_until = NULL
            WHERE sink_name = ? AND event_id = ?
            """,
            (error, next_ts, sink_name, event_id),
        )
        self._conn.commit()

    def outbox_list_pending(
        self, *, sink_name: str, due_now: bool = True
    ) -> list[OutboxRow]:
        now = time.time()
        if due_now:
            rows = self._conn.execute(
                """
                SELECT sink_name, event_id, payload_json, status, attempts,
                       last_error, next_attempt_ts, lease_until
                FROM sink_outbox
                WHERE sink_name = ? AND status = 'pending'
                  AND (next_attempt_ts IS NULL OR next_attempt_ts <= ?)
                ORDER BY created_ts ASC
                """,
                (sink_name, now),
            ).fetchall()
        else:
            rows = self._conn.execute(
                """
                SELECT sink_name, event_id, payload_json, status, attempts,
                       last_error, next_attempt_ts, lease_until
                FROM sink_outbox
                WHERE sink_name = ? AND status = 'pending'
                ORDER BY created_ts ASC
                """,
                (sink_name,),
            ).fetchall()
        return [
            OutboxRow(
                sink_name=r["sink_name"],
                event_id=r["event_id"],
                payload_json=r["payload_json"],
                status=r["status"],
                attempts=r["attempts"],
                last_error=r["last_error"],
                next_attempt_ts=r["next_attempt_ts"],
                lease_until=r["lease_until"],
            )
            for r in rows
        ]

    def outbox_list_sending(self, *, sink_name: str) -> list[OutboxRow]:
        rows = self._conn.execute(
            """
            SELECT sink_name, event_id, payload_json, status, attempts,
                   last_error, next_attempt_ts, lease_until
            FROM sink_outbox
            WHERE sink_name = ? AND status = 'sending'
            ORDER BY created_ts ASC
            """,
            (sink_name,),
        ).fetchall()
        return [
            OutboxRow(
                sink_name=r["sink_name"],
                event_id=r["event_id"],
                payload_json=r["payload_json"],
                status=r["status"],
                attempts=r["attempts"],
                last_error=r["last_error"],
                next_attempt_ts=r["next_attempt_ts"],
                lease_until=r["lease_until"],
            )
            for r in rows
        ]

    def outbox_stats(self, sink_name: str) -> dict[str, Any]:
        row = self._conn.execute(
            """
            SELECT
                SUM(CASE WHEN status='pending' THEN 1 ELSE 0 END) AS pending,
                SUM(CASE WHEN status='sending' THEN 1 ELSE 0 END) AS sending,
                SUM(CASE WHEN status='sent' THEN 1 ELSE 0 END) AS sent,
                MIN(CASE WHEN status='pending' THEN created_ts END) AS oldest_pending_ts,
                MAX(next_attempt_ts) AS next_attempt_ts
            FROM sink_outbox
            WHERE sink_name = ?
            """,
            (sink_name,),
        ).fetchone()
        return {
            "pending": int(row["pending"] or 0),
            "sending": int(row["sending"] or 0),
            "sent": int(row["sent"] or 0),
            "oldest_pending_ts": row["oldest_pending_ts"],
            "next_attempt_ts": row["next_attempt_ts"],
        }
```

- [ ] **Step 8.4: Verify green**

Run: `uv run pytest tests/monitoring/test_db.py -v`
Expected: all pass including the 5 new outbox tests.

- [ ] **Step 8.5: Commit**

```bash
uv run ruff check src tests
uv run pytest -q
git add src/lazy_harness/monitoring/db.py tests/monitoring/test_db.py
git commit -m "feat(monitoring): add sink_outbox table with claim/lease semantics"
```

---

## Phase 5 — Built-in sinks

### Task 9: `sqlite_local` sink adapter

**Files:**
- Create: `src/lazy_harness/monitoring/sinks/__init__.py`
- Create: `src/lazy_harness/monitoring/sinks/sqlite_local.py`
- Create: `tests/monitoring/sinks/__init__.py`
- Create: `tests/monitoring/sinks/test_sqlite_local.py`

The `sqlite_local` sink is a thin adapter. Its `write()` does NOT insert directly — the existing `ingest.py` still owns the bulk `replace_profile_stats()` rebuild. The sink's role in Phase 5 is to enqueue outbox rows (if any downstream sinks are configured) and to expose `drain`/`health` as no-ops. In Phase 6 we will wire it into `ingest.py` properly.

Actually, re-read the spec: `sqlite_local` **is** the buffer. Its `write()` updates `session_stats` (via the existing shape) AND the outbox is populated by other remote sinks. Let's model it that way: `sqlite_local.write(event)` is what `ingest_profile` calls after producing each aggregated row. It writes to `session_stats` via a new `upsert_event()` method on `MetricsDB`.

- [ ] **Step 9.1: Add `MetricsDB.upsert_event(event: MetricEvent)`**

In `src/lazy_harness/monitoring/db.py`, add:

```python
    def upsert_event(self, event: "MetricEvent") -> None:
        self._conn.execute(
            """
            INSERT INTO session_stats
                (session, date, model, profile, project,
                 input_tokens, output_tokens, cache_read, cache_create, cost,
                 user_id, tenant_id, event_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(session, model) DO UPDATE SET
                date=excluded.date,
                profile=excluded.profile,
                project=excluded.project,
                input_tokens=excluded.input_tokens,
                output_tokens=excluded.output_tokens,
                cache_read=excluded.cache_read,
                cache_create=excluded.cache_create,
                cost=excluded.cost,
                user_id=excluded.user_id,
                tenant_id=excluded.tenant_id,
                event_id=excluded.event_id
            """,
            (
                event.session,
                event.date,
                event.model,
                event.profile,
                event.project,
                event.input_tokens,
                event.output_tokens,
                event.cache_read,
                event.cache_create,
                event.cost,
                event.user_id,
                event.tenant_id,
                event.event_id,
            ),
        )
        self._conn.commit()
```

Add the import guard at the top of `db.py` for the type-only reference:

```python
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from lazy_harness.plugins.contracts import MetricEvent
```

- [ ] **Step 9.2: Write the failing test for the local sink**

`tests/monitoring/sinks/__init__.py`:

```python
```

`tests/monitoring/sinks/test_sqlite_local.py`:

```python
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
```

- [ ] **Step 9.3: Run red**

Run: `uv run pytest tests/monitoring/sinks/test_sqlite_local.py -v`
Expected: ImportError.

- [ ] **Step 9.4: Implement**

`src/lazy_harness/monitoring/sinks/__init__.py`:

```python
"""Built-in metrics sinks."""
```

`src/lazy_harness/monitoring/sinks/sqlite_local.py`:

```python
"""Built-in `sqlite_local` sink — the local durable buffer.

This sink is always active (ausencia de config ⇒ solo este). Its write()
upserts into the existing `session_stats` table keyed by (session, model)
with identity columns stamped on every row. It never fails under normal
conditions; the underlying SQLite file is assumed healthy.
"""

from __future__ import annotations

from typing import ClassVar

from lazy_harness.monitoring.db import MetricsDB
from lazy_harness.plugins.contracts import (
    DrainResult,
    MetricEvent,
    SinkHealth,
    SinkWriteResult,
)


class SqliteLocalSink:
    name: ClassVar[str] = "sqlite_local"

    def __init__(self, *, db: MetricsDB) -> None:
        self._db = db

    def write(self, event: MetricEvent) -> SinkWriteResult:
        try:
            self._db.upsert_event(event)
        except Exception as exc:
            return SinkWriteResult.failure(str(exc))
        return SinkWriteResult.ok()

    def drain(self, batch_size: int) -> DrainResult:
        return DrainResult(sent=0, failed=0, remaining=0)

    def health(self) -> SinkHealth:
        return SinkHealth(reachable=True)
```

- [ ] **Step 9.5: Verify green**

Run: `uv run pytest tests/monitoring/sinks/test_sqlite_local.py -v`
Expected: 5 passed.

- [ ] **Step 9.6: Commit**

```bash
uv run pytest -q
git add src/lazy_harness/monitoring/db.py src/lazy_harness/monitoring/sinks/ tests/monitoring/sinks/
git commit -m "feat(monitoring): add sqlite_local sink adapter"
```

---

### Task 10: `http_remote` sink (enqueue to outbox, non-blocking)

**Files:**
- Modify: `pyproject.toml` (add `pytest-httpserver` to dev deps)
- Create: `src/lazy_harness/monitoring/sinks/http_remote.py`
- Create: `tests/monitoring/sinks/test_http_remote.py`

`http_remote.write()` does NOT make an HTTP call. It enqueues the event JSON on `sink_outbox` and returns. The worker (Task 11) drains.

- [ ] **Step 10.1: Add dev dependency**

Check if `httpx` is already in `pyproject.toml` dependencies. If yes, skip adding it. Then add `pytest-httpserver` to dev deps:

```bash
uv add --dev pytest-httpserver
# if httpx is not already present:
uv add httpx
```

Verify both are reflected in `pyproject.toml`.

- [ ] **Step 10.2: Write the failing test**

`tests/monitoring/sinks/test_http_remote.py`:

```python
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
```

- [ ] **Step 10.3: Run red**

Run: `uv run pytest tests/monitoring/sinks/test_http_remote.py -v`
Expected: ImportError.

- [ ] **Step 10.4: Implement**

`src/lazy_harness/monitoring/sinks/http_remote.py`:

```python
"""Built-in `http_remote` sink — enqueues events on the outbox.

This sink is opt-in. Its write() is non-blocking: it serializes the event
as JSON and upserts it into sink_outbox. The actual HTTP POST happens in
`monitoring.sinks.worker.drain_http_remote` on every `lh` invocation that
goes through the ingest pipeline (or explicit `lh metrics drain`).
"""

from __future__ import annotations

import json
from typing import ClassVar

from lazy_harness.monitoring.db import MetricsDB
from lazy_harness.plugins.contracts import (
    DrainResult,
    MetricEvent,
    SinkHealth,
    SinkWriteResult,
)


class HttpRemoteSink:
    name: ClassVar[str] = "http_remote"

    def __init__(
        self,
        *,
        db: MetricsDB,
        url: str,
        timeout_seconds: float = 5.0,
        batch_size: int = 50,
    ) -> None:
        self._db = db
        self._url = url
        self._timeout = timeout_seconds
        self._batch_size = batch_size

    @property
    def url(self) -> str:
        return self._url

    def write(self, event: MetricEvent) -> SinkWriteResult:
        try:
            payload = json.dumps(event.to_dict(), sort_keys=True)
            self._db.outbox_enqueue(
                sink_name=self.name,
                event_id=event.event_id,
                payload_json=payload,
            )
        except Exception as exc:
            return SinkWriteResult.failure(str(exc))
        return SinkWriteResult.ok()

    def drain(self, batch_size: int) -> DrainResult:
        # Worker module owns the actual network work. The sink delegates so
        # that behavior is testable in isolation and the sink stays small.
        from lazy_harness.monitoring.sinks.worker import drain_http_remote

        return drain_http_remote(
            db=self._db,
            url=self._url,
            timeout_seconds=self._timeout,
            batch_size=batch_size or self._batch_size,
        )

    def health(self) -> SinkHealth:
        stats = self._db.outbox_stats(self.name)
        pending = stats["pending"]
        if pending == 0:
            return SinkHealth(reachable=True, detail="no pending events")
        return SinkHealth(reachable=True, detail=f"{pending} pending")
```

- [ ] **Step 10.5: Verify green (worker not yet implemented; drain test is in Task 11)**

Run: `uv run pytest tests/monitoring/sinks/test_http_remote.py -v`
Expected: 3 passed.

- [ ] **Step 10.6: Commit**

```bash
uv run pytest -q
git add pyproject.toml uv.lock src/lazy_harness/monitoring/sinks/http_remote.py tests/monitoring/sinks/test_http_remote.py
git commit -m "feat(monitoring): add http_remote sink enqueuing to outbox"
```

---

### Task 11: Worker drain with `pytest-httpserver`, backoff, idempotency

**Files:**
- Create: `src/lazy_harness/monitoring/sinks/worker.py`
- Create: `tests/monitoring/sinks/test_worker.py`

- [ ] **Step 11.1: Write failing tests**

`tests/monitoring/sinks/test_worker.py`:

```python
import json
from pathlib import Path

import pytest
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
        # Re-enqueue the same event and drain again — backend must see it,
        # but the payload carries the same event_id for idempotent upsert.
        sink.write(_event("s1"))
        drain_http_remote(
            db=db, url=httpserver.url_for("/ingest"), timeout_seconds=2, batch_size=10
        )
    finally:
        db.close()

    assert len(received) == 2
    assert received[0]["event_id"] == received[1]["event_id"]
```

- [ ] **Step 11.2: Run red**

Run: `uv run pytest tests/monitoring/sinks/test_worker.py -v`
Expected: ImportError on `worker.drain_http_remote`.

- [ ] **Step 11.3: Implement worker**

`src/lazy_harness/monitoring/sinks/worker.py`:

```python
"""Outbox drainer for remote sinks.

Drain policy (D15, D18 in the spec):
- Opportunistic: called from within `lh` (hooks + CLI) right after ingest,
  or explicitly by `lh metrics drain`.
- Exponential backoff per event with reset-on-success: first failure waits
  1s, then doubles up to a 300s cap. A successful drain resets the counter.
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
    # attempts is the count AFTER the failure being recorded.
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
    recorded as failures on the outbox row; the caller (ingest pipeline or
    CLI) inspects the returned DrainResult.
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
```

- [ ] **Step 11.4: Verify green**

Run: `uv run pytest tests/monitoring/sinks/test_worker.py -v`
Expected: 4 passed.

- [ ] **Step 11.5: Commit**

```bash
uv run pytest -q
git add src/lazy_harness/monitoring/sinks/worker.py tests/monitoring/sinks/test_worker.py
git commit -m "feat(monitoring): add worker drain with backoff and lease claim"
```

---

## Phase 6 — Wire sinks into the ingest pipeline

### Task 12: Sink composition + fanout in `ingest_all`

**Files:**
- Modify: `src/lazy_harness/monitoring/ingest.py`
- Create: `src/lazy_harness/monitoring/sink_setup.py` (helper that turns config + db + registry into instantiated sinks)
- Create: `tests/monitoring/test_sink_setup.py`
- Create: `tests/monitoring/test_ingest_with_sinks.py`

- [ ] **Step 12.1: Write the failing test for `build_sinks`**

`tests/monitoring/test_sink_setup.py`:

```python
from pathlib import Path

import pytest

from lazy_harness.core.config import MetricsConfig, SinkDefinition
from lazy_harness.monitoring.db import MetricsDB
from lazy_harness.monitoring.sink_setup import build_sinks
from lazy_harness.monitoring.sinks.http_remote import HttpRemoteSink
from lazy_harness.monitoring.sinks.sqlite_local import SqliteLocalSink


def test_default_metrics_config_yields_only_sqlite_local(tmp_path: Path) -> None:
    db = MetricsDB(tmp_path / "m.db")
    try:
        sinks = build_sinks(MetricsConfig(), db=db)
        assert [type(s).__name__ for s in sinks] == ["SqliteLocalSink"]
    finally:
        db.close()


def test_http_remote_requires_url(tmp_path: Path) -> None:
    db = MetricsDB(tmp_path / "m.db")
    try:
        cfg = MetricsConfig(
            sinks=["sqlite_local", "http_remote"],
            sink_configs={"http_remote": SinkDefinition(options={})},
        )
        with pytest.raises(ValueError) as info:
            build_sinks(cfg, db=db)
        assert "url" in str(info.value)
    finally:
        db.close()


def test_http_remote_instantiated_with_options(tmp_path: Path) -> None:
    db = MetricsDB(tmp_path / "m.db")
    try:
        cfg = MetricsConfig(
            sinks=["sqlite_local", "http_remote"],
            sink_configs={
                "http_remote": SinkDefinition(
                    options={"url": "https://x.invalid/", "timeout_seconds": 3, "batch_size": 25}
                )
            },
        )
        sinks = build_sinks(cfg, db=db)
        assert isinstance(sinks[0], SqliteLocalSink)
        assert isinstance(sinks[1], HttpRemoteSink)
        assert sinks[1].url == "https://x.invalid/"
    finally:
        db.close()
```

- [ ] **Step 12.2: Run red**

Run: `uv run pytest tests/monitoring/test_sink_setup.py -v`
Expected: ImportError.

- [ ] **Step 12.3: Implement `build_sinks`**

`src/lazy_harness/monitoring/sink_setup.py`:

```python
"""Turn `MetricsConfig` + a `MetricsDB` into a list of instantiated sinks.

Built-in sinks are resolved here directly (not via the registry) because
they live in the same repo and their constructor signatures are known.
The registry is consulted only for entry-point (`ext:*`) sinks, which is
wired in a later task if needed for the MVP of this slice.
"""

from __future__ import annotations

from typing import Any

from lazy_harness.core.config import MetricsConfig
from lazy_harness.monitoring.db import MetricsDB
from lazy_harness.monitoring.sinks.http_remote import HttpRemoteSink
from lazy_harness.monitoring.sinks.sqlite_local import SqliteLocalSink

_BUILTIN_FACTORIES = {
    "sqlite_local": lambda db, options: SqliteLocalSink(db=db),
    "http_remote": lambda db, options: HttpRemoteSink(
        db=db,
        url=_require_url(options),
        timeout_seconds=float(options.get("timeout_seconds", 5.0)),
        batch_size=int(options.get("batch_size", 50)),
    ),
}


def _require_url(options: dict[str, Any]) -> str:
    url = options.get("url")
    if not isinstance(url, str) or not url:
        raise ValueError("http_remote sink requires a non-empty 'url' option")
    return url


def build_sinks(cfg: MetricsConfig, *, db: MetricsDB) -> list[Any]:
    sinks: list[Any] = []
    for name in cfg.sinks:
        factory = _BUILTIN_FACTORIES.get(name)
        if factory is None:
            raise ValueError(f"unknown built-in sink: {name!r} (extension sinks TBD in a later slice)")
        definition = cfg.sink_configs.get(name)
        options = definition.options if definition else {}
        sinks.append(factory(db, options))
    return sinks
```

- [ ] **Step 12.4: Verify green**

Run: `uv run pytest tests/monitoring/test_sink_setup.py -v`
Expected: 3 passed.

- [ ] **Step 12.5: Write the failing test for `ingest` routing**

`tests/monitoring/test_ingest_with_sinks.py`:

```python
"""Test that ingest_all fans out to every configured sink."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from lazy_harness.core.config import (
    Config,
    MetricsConfig,
    ProfileEntry,
    ProfilesConfig,
    SinkDefinition,
)
from lazy_harness.monitoring.db import MetricsDB
from lazy_harness.monitoring.ingest import ingest_all
from lazy_harness.plugins.contracts import (
    DrainResult,
    MetricEvent,
    SinkHealth,
    SinkWriteResult,
)


class _CountingSink:
    name = "counting"

    def __init__(self) -> None:
        self.events: list[MetricEvent] = []

    def write(self, event: MetricEvent) -> SinkWriteResult:
        self.events.append(event)
        return SinkWriteResult.ok()

    def drain(self, batch_size: int) -> DrainResult:
        return DrainResult(sent=0, failed=0, remaining=0)

    def health(self) -> SinkHealth:
        return SinkHealth(reachable=True)


def _write_fake_jsonl(projects_dir: Path, session_id: str) -> None:
    """Drop a minimal Claude Code session JSONL the ingest pipeline can parse."""
    proj = projects_dir / "-Users-martin-repos-lazy-lazy-harness"
    proj.mkdir(parents=True, exist_ok=True)
    f = proj / f"{session_id}.jsonl"
    f.write_text(
        '{"type":"assistant","message":{"id":"msg1","model":"claude-sonnet-4-5",'
        '"usage":{"input_tokens":100,"output_tokens":50,'
        '"cache_read_input_tokens":0,"cache_creation_input_tokens":0}},'
        '"timestamp":"2026-04-14T10:00:00Z"}\n'
    )


def test_ingest_fans_out_to_every_configured_sink(tmp_path: Path) -> None:
    profile_dir = tmp_path / "claude-personal"
    _write_fake_jsonl(profile_dir / "projects", "sess1")

    cfg = Config()
    cfg.profiles = ProfilesConfig(
        default="personal",
        items={
            "personal": ProfileEntry(
                config_dir=str(profile_dir), roots=[], lazynorth_doc=""
            ),
        },
    )
    cfg.metrics = MetricsConfig(
        sinks=["sqlite_local", "counting"],
        sink_configs={
            "sqlite_local": SinkDefinition(options={}),
            "counting": SinkDefinition(options={}),
        },
    )

    db = MetricsDB(tmp_path / "m.db")
    counting = _CountingSink()
    try:
        ingest_all(cfg, db, pricing={}, sinks=[counting])
        assert len(counting.events) == 1
        ev = counting.events[0]
        assert ev.session == "sess1"
        assert ev.profile == "personal"
        assert ev.user_id  # stamped by identity resolver
    finally:
        db.close()
```

- [ ] **Step 12.6: Run red**

Run: `uv run pytest tests/monitoring/test_ingest_with_sinks.py -v`
Expected: `ingest_all() got an unexpected keyword argument 'sinks'` or similar.

- [ ] **Step 12.7: Rewire `ingest_profile` and `ingest_all`**

In `src/lazy_harness/monitoring/ingest.py`, add imports:

```python
from lazy_harness.core.identity import resolve_identity
from lazy_harness.monitoring.event_id import derive_event_id
from lazy_harness.plugins.contracts import (
    METRIC_EVENT_SCHEMA_VERSION,
    MetricEvent,
)
```

Change `ingest_profile` signature and body — after the aggregation, build `MetricEvent`s instead of dicts, feed them to each sink, and still call `db.replace_profile_stats` for backward compatibility with the existing query/view code:

```python
def ingest_profile(
    profile: ProfileInfo,
    db: MetricsDB,
    pricing: dict[str, dict[str, float]],
    *,
    sinks: list[Any] | None = None,
    user_id: str = "local",
    tenant_id: str = "local",
) -> IngestReport:
    report = IngestReport()
    projects_dir = profile.config_dir / "projects"
    if not projects_dir.is_dir():
        return report

    files = _find_session_files(projects_dir, report.errors)

    seen_msg_ids: set[str] = set()
    aggregated: dict[tuple[str, str], dict] = {}

    for _mtime_ns, session_file, project_name, session_id in files:
        report.sessions_scanned += 1
        try:
            messages = list(iter_assistant_messages(session_file))
        except OSError as e:
            report.errors.append(f"{session_file}: {e}")
            continue
        if not messages:
            continue
        session_date = extract_session_date(session_file)
        novel_for_this_file = 0
        for m in messages:
            report.messages_total += 1
            if m["msg_id"] in seen_msg_ids:
                report.messages_deduped += 1
                continue
            seen_msg_ids.add(m["msg_id"])
            novel_for_this_file += 1
            key = (session_id, m["model"])
            agg = aggregated.get(key)
            if agg is None:
                agg = {
                    "input": 0,
                    "output": 0,
                    "cache_read": 0,
                    "cache_create": 0,
                    "date": session_date,
                    "project": project_name,
                }
                aggregated[key] = agg
            agg["input"] += m["input"]
            agg["output"] += m["output"]
            agg["cache_read"] += m["cache_read"]
            agg["cache_create"] += m["cache_create"]
        if novel_for_this_file == 0:
            report.sessions_skipped += 1

    entries: list[dict] = []
    events: list[MetricEvent] = []
    for (session_id, model), agg in aggregated.items():
        cost = calculate_cost(
            model,
            {
                "input": agg["input"],
                "output": agg["output"],
                "cache_read": agg["cache_read"],
                "cache_create": agg["cache_create"],
            },
            pricing,
        )
        entries.append(
            {
                "session": session_id,
                "date": agg["date"],
                "model": model,
                "profile": profile.name,
                "project": agg["project"],
                "input": agg["input"],
                "output": agg["output"],
                "cache_read": agg["cache_read"],
                "cache_create": agg["cache_create"],
                "cost": cost,
            }
        )
        events.append(
            MetricEvent(
                event_id=derive_event_id(
                    profile=profile.name, session=session_id, model=model
                ),
                schema_version=METRIC_EVENT_SCHEMA_VERSION,
                user_id=user_id,
                tenant_id=tenant_id,
                profile=profile.name,
                session=session_id,
                model=model,
                project=agg["project"],
                date=agg["date"],
                input_tokens=agg["input"],
                output_tokens=agg["output"],
                cache_read=agg["cache_read"],
                cache_create=agg["cache_create"],
                cost=cost,
            )
        )

    db.replace_profile_stats(profile.name, entries)
    report.sessions_updated = len({e["session"] for e in entries})

    if sinks:
        for sink in sinks:
            for event in events:
                result = sink.write(event)
                if not result.success:
                    report.errors.append(
                        f"{type(sink).__name__} write failed for {event.event_id}: {result.error}"
                    )
    return report


def ingest_all(
    cfg: Config,
    db: MetricsDB,
    pricing: dict[str, dict[str, float]],
    *,
    sinks: list[Any] | None = None,
) -> IngestReport:
    total = IngestReport()
    identity = resolve_identity(explicit=cfg.metrics.user_id or None)
    for prof in list_profiles(cfg):
        config_path = expand_path(str(prof.config_dir))
        resolved = ProfileInfo(
            name=prof.name,
            config_dir=config_path,
            roots=prof.roots,
            is_default=prof.is_default,
            exists=config_path.is_dir(),
        )
        if not resolved.exists:
            continue
        total.merge(
            ingest_profile(
                resolved,
                db,
                pricing,
                sinks=sinks,
                user_id=identity.user_id,
                tenant_id=cfg.metrics.tenant_id,
            )
        )
    return total
```

Add `from typing import Any` at the top if missing.

- [ ] **Step 12.8: Verify green**

Run: `uv run pytest tests/monitoring/test_ingest_with_sinks.py tests/monitoring/test_db.py -v`
Expected: all pass.

Also run the existing ingest tests: `uv run pytest tests/monitoring/ -v`
Expected: legacy tests still pass (call sites use the default `sinks=None`).

- [ ] **Step 12.9: Commit**

```bash
uv run pytest -q
git add src/lazy_harness/monitoring/ingest.py src/lazy_harness/monitoring/sink_setup.py tests/monitoring/test_sink_setup.py tests/monitoring/test_ingest_with_sinks.py
git commit -m "feat(monitoring): fan out ingest events to configured sinks"
```

---

## Phase 7 — CLI surface: `drain`, `status`, stderr visibility

### Task 13: `lh metrics drain` subcommand

**Files:**
- Modify: `src/lazy_harness/cli/metrics_cmd.py`
- Create: `tests/cli/test_metrics_drain.py`

- [ ] **Step 13.1: Write the failing test**

`tests/cli/test_metrics_drain.py`:

```python
from pathlib import Path

from click.testing import CliRunner
from pytest_httpserver import HTTPServer

from lazy_harness.cli.metrics_cmd import metrics
from lazy_harness.monitoring.db import MetricsDB
from lazy_harness.monitoring.sinks.http_remote import HttpRemoteSink
from lazy_harness.plugins.contracts import METRIC_EVENT_SCHEMA_VERSION, MetricEvent


def _mk_event() -> MetricEvent:
    return MetricEvent(
        event_id="eid-1",
        schema_version=METRIC_EVENT_SCHEMA_VERSION,
        user_id="martin",
        tenant_id="local",
        profile="personal",
        session="s1",
        model="sonnet",
        project="lazy-harness",
        date="2026-04-14",
        input_tokens=100,
        output_tokens=50,
        cache_read=0,
        cache_create=0,
        cost=0.001,
    )


def test_drain_exits_zero_with_nothing_pending(
    tmp_path: Path, monkeypatch, httpserver: HTTPServer
) -> None:
    cfg_path = tmp_path / "config.toml"
    cfg_path.write_text(
        '[harness]\nversion = "1"\n'
        "[monitoring]\nenabled = true\n"
        f'db = "{(tmp_path / "m.db").as_posix()}"\n'
        "[metrics]\n"
        'sinks = ["sqlite_local", "http_remote"]\n'
        "[metrics.sink_options.http_remote]\n"
        f'url = "{httpserver.url_for("/ingest")}"\n'
    )
    monkeypatch.setenv("LH_CONFIG_DIR", str(tmp_path))

    httpserver.expect_request("/ingest", method="POST").respond_with_json({"ok": True})

    runner = CliRunner()
    result = runner.invoke(metrics, ["drain"])
    assert result.exit_code == 0
    assert "0 sent" in result.output or "nothing to drain" in result.output


def test_drain_flushes_pending_events(
    tmp_path: Path, monkeypatch, httpserver: HTTPServer
) -> None:
    cfg_path = tmp_path / "config.toml"
    db_path = tmp_path / "m.db"
    cfg_path.write_text(
        '[harness]\nversion = "1"\n'
        "[monitoring]\nenabled = true\n"
        f'db = "{db_path.as_posix()}"\n'
        "[metrics]\n"
        'sinks = ["sqlite_local", "http_remote"]\n'
        "[metrics.sink_options.http_remote]\n"
        f'url = "{httpserver.url_for("/ingest")}"\n'
    )
    monkeypatch.setenv("LH_CONFIG_DIR", str(tmp_path))

    # Seed the outbox directly so we don't depend on ingest for this test.
    db = MetricsDB(db_path)
    sink = HttpRemoteSink(
        db=db, url=httpserver.url_for("/ingest"), timeout_seconds=2, batch_size=10
    )
    sink.write(_mk_event())
    db.close()

    httpserver.expect_request("/ingest", method="POST").respond_with_json({"ok": True})
    runner = CliRunner()
    result = runner.invoke(metrics, ["drain"])
    assert result.exit_code == 0
    assert "1 sent" in result.output
```

- [ ] **Step 13.2: Run red**

Run: `uv run pytest tests/cli/test_metrics_drain.py -v`
Expected: `Error: No such command 'drain'`.

- [ ] **Step 13.3: Implement `drain`**

Add to `src/lazy_harness/cli/metrics_cmd.py`, below the existing `metrics_ingest`:

```python
from pathlib import Path

from lazy_harness.core.identity import resolve_identity
from lazy_harness.monitoring.sink_setup import build_sinks
from lazy_harness.monitoring.sinks.http_remote import HttpRemoteSink


def _print_active_sinks(console: Console, cfg, identity) -> None:
    url_detail = ""
    for name in cfg.metrics.sinks:
        if name == "http_remote":
            opts = cfg.metrics.sink_configs.get("http_remote")
            if opts:
                url_detail = f" → {opts.options.get('url', '')}"
    sink_list = ", ".join(cfg.metrics.sinks)
    console.print(
        f"[dim]metrics sinks active: {sink_list}{url_detail}[/dim]", style=None, markup=True
    )
    console.print(
        f"[dim]identity: {identity.user_id} (source: {identity.source})[/dim]"
    )


@metrics.command("drain")
def metrics_drain() -> None:
    """Force-drain the outbox for every configured remote sink."""
    console = Console(stderr=True)
    try:
        cfg = load_config(config_file())
    except ConfigError as e:
        console.print(f"[red]Error:[/red] {e}")
        raise SystemExit(1)

    identity = resolve_identity(explicit=cfg.metrics.user_id or None)
    _print_active_sinks(console, cfg, identity)

    db_path = expand_path(cfg.monitoring.db) if cfg.monitoring.db else data_dir() / "metrics.db"
    db = MetricsDB(Path(db_path))
    try:
        sinks = build_sinks(cfg.metrics, db=db)
        total_sent = 0
        total_failed = 0
        for sink in sinks:
            if isinstance(sink, HttpRemoteSink):
                result = sink.drain(batch_size=0)
                total_sent += result.sent
                total_failed += result.failed
    finally:
        db.close()

    Console().print(f"[green]drain complete:[/green] {total_sent} sent, {total_failed} failed")
```

- [ ] **Step 13.4: Verify green**

Run: `uv run pytest tests/cli/test_metrics_drain.py -v`
Expected: 2 passed.

- [ ] **Step 13.5: Commit**

```bash
uv run pytest -q
git add src/lazy_harness/cli/metrics_cmd.py tests/cli/test_metrics_drain.py
git commit -m "feat(cli): add 'lh metrics drain' subcommand with sink visibility"
```

---

### Task 14: `lh metrics status` subcommand

**Files:**
- Modify: `src/lazy_harness/cli/metrics_cmd.py`
- Create: `tests/cli/test_metrics_status.py`

- [ ] **Step 14.1: Write the failing test**

`tests/cli/test_metrics_status.py`:

```python
from pathlib import Path

from click.testing import CliRunner

from lazy_harness.cli.metrics_cmd import metrics
from lazy_harness.monitoring.db import MetricsDB
from lazy_harness.monitoring.sinks.http_remote import HttpRemoteSink
from lazy_harness.plugins.contracts import METRIC_EVENT_SCHEMA_VERSION, MetricEvent


def _seed(tmp_path: Path) -> Path:
    db_path = tmp_path / "m.db"
    db = MetricsDB(db_path)
    sink = HttpRemoteSink(db=db, url="https://x.invalid/", timeout_seconds=1, batch_size=10)
    sink.write(
        MetricEvent(
            event_id="e1",
            schema_version=METRIC_EVENT_SCHEMA_VERSION,
            user_id="m",
            tenant_id="local",
            profile="p",
            session="s",
            model="sonnet",
            project="lh",
            date="2026-04-14",
            input_tokens=1,
            output_tokens=1,
            cache_read=0,
            cache_create=0,
            cost=0.0,
        )
    )
    db.close()
    return db_path


def test_status_reports_pending_count(tmp_path: Path, monkeypatch) -> None:
    db_path = _seed(tmp_path)
    cfg_path = tmp_path / "config.toml"
    cfg_path.write_text(
        '[harness]\nversion = "1"\n'
        "[monitoring]\nenabled = true\n"
        f'db = "{db_path.as_posix()}"\n'
        "[metrics]\n"
        'sinks = ["sqlite_local", "http_remote"]\n'
        "[metrics.sink_options.http_remote]\n"
        'url = "https://x.invalid/"\n'
    )
    monkeypatch.setenv("LH_CONFIG_DIR", str(tmp_path))

    runner = CliRunner()
    result = runner.invoke(metrics, ["status"])
    assert result.exit_code == 0
    assert "http_remote" in result.output
    assert "pending: 1" in result.output
```

- [ ] **Step 14.2: Run red**

Run: `uv run pytest tests/cli/test_metrics_status.py -v`
Expected: `No such command 'status'`.

- [ ] **Step 14.3: Implement**

Append to `src/lazy_harness/cli/metrics_cmd.py`:

```python
@metrics.command("status")
def metrics_status() -> None:
    """Show pending/sent counts per remote sink."""
    console = Console()
    try:
        cfg = load_config(config_file())
    except ConfigError as e:
        console.print(f"[red]Error:[/red] {e}")
        raise SystemExit(1)

    db_path = expand_path(cfg.monitoring.db) if cfg.monitoring.db else data_dir() / "metrics.db"
    db = MetricsDB(Path(db_path))
    try:
        for name in cfg.metrics.sinks:
            if name == "sqlite_local":
                continue
            stats = db.outbox_stats(name)
            console.print(
                f"[bold]{name}[/bold]  pending: {stats['pending']}  "
                f"sending: {stats['sending']}  sent: {stats['sent']}"
            )
    finally:
        db.close()
```

- [ ] **Step 14.4: Verify green**

Run: `uv run pytest tests/cli/test_metrics_status.py -v`
Expected: passed.

- [ ] **Step 14.5: Commit**

```bash
uv run pytest -q
git add src/lazy_harness/cli/metrics_cmd.py tests/cli/test_metrics_status.py
git commit -m "feat(cli): add 'lh metrics status' subcommand"
```

---

### Task 15: Wire sinks into `lh metrics ingest`

**Files:**
- Modify: `src/lazy_harness/cli/metrics_cmd.py`
- Modify: `tests/cli/test_metrics_cmd.py` (if it exists) or create `tests/cli/test_metrics_ingest_sinks.py`

- [ ] **Step 15.1: Write a failing integration test**

`tests/cli/test_metrics_ingest_sinks.py`:

```python
"""Integration test: `lh metrics ingest` routes events to http_remote."""

from pathlib import Path

from click.testing import CliRunner
from pytest_httpserver import HTTPServer

from lazy_harness.cli.metrics_cmd import metrics


def _write_fake_session(dir_path: Path) -> None:
    proj = dir_path / "projects" / "-Users-martin-repos-lazy-lazy-harness"
    proj.mkdir(parents=True, exist_ok=True)
    (proj / "sess.jsonl").write_text(
        '{"type":"assistant","message":{"id":"m1","model":"claude-sonnet-4-5",'
        '"usage":{"input_tokens":100,"output_tokens":50,'
        '"cache_read_input_tokens":0,"cache_creation_input_tokens":0}},'
        '"timestamp":"2026-04-14T10:00:00Z"}\n'
    )


def test_metrics_ingest_posts_to_remote(
    tmp_path: Path, monkeypatch, httpserver: HTTPServer
) -> None:
    profile_dir = tmp_path / "claude"
    _write_fake_session(profile_dir)

    db_path = tmp_path / "m.db"
    cfg_path = tmp_path / "config.toml"
    cfg_path.write_text(
        '[harness]\nversion = "1"\n'
        "[monitoring]\nenabled = true\n"
        f'db = "{db_path.as_posix()}"\n'
        "[profiles]\n"
        'default = "personal"\n'
        "[profiles.personal]\n"
        f'config_dir = "{profile_dir.as_posix()}"\n'
        "roots = []\n"
        "[metrics]\n"
        'sinks = ["sqlite_local", "http_remote"]\n'
        'user_id = "martin"\n'
        "[metrics.sink_options.http_remote]\n"
        f'url = "{httpserver.url_for("/ingest")}"\n'
    )
    monkeypatch.setenv("LH_CONFIG_DIR", str(tmp_path))

    httpserver.expect_request("/ingest", method="POST").respond_with_json({"ok": True})

    runner = CliRunner()
    result = runner.invoke(metrics, ["ingest"])
    assert result.exit_code == 0, result.output
    # The first `ingest` enqueues; a subsequent drain pushes. For this test
    # we expect ingest to also trigger an opportunistic drain so the backend
    # has already been hit once.
    assert len(httpserver.log) >= 1
```

- [ ] **Step 15.2: Run red**

Run: `uv run pytest tests/cli/test_metrics_ingest_sinks.py -v`
Expected: the request count assertion fails (0 requests).

- [ ] **Step 15.3: Wire sinks into `metrics_ingest`**

Replace `metrics_ingest` in `src/lazy_harness/cli/metrics_cmd.py`:

```python
@metrics.command("ingest")
@click.option("--dry-run", is_flag=True, help="Parse sessions but do not write to the DB.")
@click.option("--verbose", "-v", is_flag=True, help="Show per-profile counters.")
def metrics_ingest(dry_run: bool, verbose: bool) -> None:
    """Scan every profile's projects/*.jsonl and upsert token stats."""
    console = Console()
    stderr = Console(stderr=True)
    try:
        cfg = load_config(config_file())
    except ConfigError as e:
        console.print(f"[red]Error:[/red] {e}")
        raise SystemExit(1)

    if not cfg.monitoring.enabled:
        console.print("[yellow]monitoring disabled in config; nothing to do.[/yellow]")
        return

    identity = resolve_identity(explicit=cfg.metrics.user_id or None)
    _print_active_sinks(stderr, cfg, identity)

    db_path = expand_path(cfg.monitoring.db) if cfg.monitoring.db else data_dir() / "metrics.db"

    if dry_run:
        console.print(f"[dim]dry-run — target DB would be: {db_path}[/dim]")
        db = MetricsDB(Path(":memory:"))
    else:
        db = MetricsDB(Path(db_path))

    try:
        pricing = load_pricing(cfg.monitoring.pricing or None)
        sinks = build_sinks(cfg.metrics, db=db)
        report = ingest_all(cfg, db, pricing, sinks=sinks)

        # Opportunistic drain (D15): best-effort, never raises.
        for sink in sinks:
            if isinstance(sink, HttpRemoteSink):
                sink.drain(batch_size=0)
    finally:
        db.close()

    console.print(
        f"[green]✓[/green] scanned {report.sessions_scanned} · "
        f"updated {report.sessions_updated} · "
        f"skipped {report.sessions_skipped}"
    )
    if report.errors and verbose:
        for err in report.errors:
            console.print(f"[red]  {err}[/red]")
```

- [ ] **Step 15.4: Verify green**

Run: `uv run pytest tests/cli/test_metrics_ingest_sinks.py -v`
Expected: passed.

Run: `uv run pytest -q` (full suite).
Expected: all green.

- [ ] **Step 15.5: Commit**

```bash
uv run ruff check src tests
git add src/lazy_harness/cli/metrics_cmd.py tests/cli/test_metrics_ingest_sinks.py
git commit -m "feat(cli): route metrics ingest events through configured sinks"
```

---

## Phase 8 — Guardrails: default-local, discovery-not-activation, opt-in errors

### Task 16: Regression test — default config = zero network I/O

**Files:**
- Create: `tests/monitoring/test_default_local.py`

- [ ] **Step 16.1: Write the test**

`tests/monitoring/test_default_local.py`:

```python
"""Invariant: a config without [metrics] must not touch the network.

Verified by monkeypatching httpx to raise on any attempted use.
"""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from lazy_harness.core.config import Config
from lazy_harness.monitoring.db import MetricsDB
from lazy_harness.monitoring.ingest import ingest_all
from lazy_harness.monitoring.sink_setup import build_sinks


def test_default_config_has_only_sqlite_local() -> None:
    cfg = Config()
    assert cfg.metrics.sinks == ["sqlite_local"]


def test_default_config_ingest_does_not_use_httpx(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[str] = []

    class _Boom(httpx.Client):
        def __init__(self, *a, **kw):  # type: ignore[no-untyped-def]
            calls.append("init")
            super().__init__(*a, **kw)

        def post(self, *a, **kw):  # type: ignore[no-untyped-def]
            calls.append("post")
            raise AssertionError("network I/O attempted in local-only mode")

    monkeypatch.setattr(httpx, "Client", _Boom)

    cfg = Config()  # default
    db = MetricsDB(tmp_path / "m.db")
    try:
        sinks = build_sinks(cfg.metrics, db=db)
        ingest_all(cfg, db, pricing={}, sinks=sinks)
    finally:
        db.close()

    assert "post" not in calls  # zero HTTP calls
```

- [ ] **Step 16.2: Run — should pass immediately**

Run: `uv run pytest tests/monitoring/test_default_local.py -v`
Expected: passed (this is a regression guard, not a driver).

- [ ] **Step 16.3: Commit**

```bash
git add tests/monitoring/test_default_local.py
git commit -m "test(monitoring): guard zero-network default-local invariant"
```

---

### Task 17: Discovery ≠ activation test

**Files:**
- Create: `tests/plugins/test_discovery_not_activation.py`

- [ ] **Step 17.1: Write the test**

`tests/plugins/test_discovery_not_activation.py`:

```python
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
```

- [ ] **Step 17.2: Run**

Run: `uv run pytest tests/plugins/test_discovery_not_activation.py -v`
Expected: passed.

- [ ] **Step 17.3: Commit**

```bash
git add tests/plugins/test_discovery_not_activation.py
git commit -m "test(plugins): guard discovery-not-activation invariant"
```

---

### Task 18: Opt-in-doble validation test

This is mostly covered by `tests/core/test_metrics_config.py` already (Task 6). This task adds the explicit CLI-level test: loading a bad config via `lh metrics ingest` surfaces a clean error.

**Files:**
- Create: `tests/cli/test_metrics_opt_in_errors.py`

- [ ] **Step 18.1: Write the test**

```python
from pathlib import Path

from click.testing import CliRunner

from lazy_harness.cli.metrics_cmd import metrics


def test_ingest_errors_on_unnamed_config_block(tmp_path: Path, monkeypatch) -> None:
    cfg_path = tmp_path / "config.toml"
    cfg_path.write_text(
        '[harness]\nversion = "1"\n'
        "[monitoring]\nenabled = true\n"
        "[metrics]\n"
        'sinks = ["sqlite_local", "http_remote"]\n'
        # Missing [metrics.sink_options.http_remote] → should error.
    )
    monkeypatch.setenv("LH_CONFIG_DIR", str(tmp_path))

    runner = CliRunner()
    result = runner.invoke(metrics, ["ingest"])
    assert result.exit_code != 0
    assert "http_remote" in result.output
```

- [ ] **Step 18.2: Run**

Run: `uv run pytest tests/cli/test_metrics_opt_in_errors.py -v`
Expected: passed.

- [ ] **Step 18.3: Commit**

```bash
git add tests/cli/test_metrics_opt_in_errors.py
git commit -m "test(cli): surface config errors for unnamed sink option blocks"
```

---

## Phase 9 — End-to-end scenarios

### Task 19: Offline → reconnect simulation

**Files:**
- Create: `tests/monitoring/test_offline_reconnect.py`

- [ ] **Step 19.1: Write the test**

`tests/monitoring/test_offline_reconnect.py`:

```python
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
```

- [ ] **Step 19.2: Run the test — expect the pending loop to stall**

Run: `uv run pytest tests/monitoring/test_offline_reconnect.py -v`
Expected: **fails** — rows have `next_attempt_ts` in the future from the offline phase, so the reconnect drain finds nothing to claim.

- [ ] **Step 19.3: Fix the worker by resetting per-sink backoff on any success**

In `src/lazy_harness/monitoring/db.py`, add:

```python
    def outbox_reset_backoff(self, sink_name: str) -> None:
        self._conn.execute(
            """
            UPDATE sink_outbox
            SET next_attempt_ts = NULL
            WHERE sink_name = ? AND status = 'pending'
            """,
            (sink_name,),
        )
        self._conn.commit()
```

In `src/lazy_harness/monitoring/sinks/worker.py`, after a successful POST increment a local `had_success` flag and, at the end of the function, if `had_success and remaining > 0` call `db.outbox_reset_backoff("http_remote")`:

```python
def drain_http_remote(
    *,
    db: MetricsDB,
    url: str,
    timeout_seconds: float,
    batch_size: int,
) -> DrainResult:
    rows = db.outbox_claim(
        sink_name="http_remote", batch_size=batch_size, lease_seconds=_LEASE_SECONDS
    )
    if not rows:
        return DrainResult(sent=0, failed=0, remaining=0)

    sent = 0
    failed = 0
    had_success = False

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
                had_success = True
                db.outbox_mark_sent(row.sink_name, row.event_id)
            else:
                failed += 1
                db.outbox_mark_failed(
                    row.sink_name,
                    row.event_id,
                    error=f"HTTP {resp.status_code}",
                    retry_after_seconds=_backoff_for(row.attempts + 1),
                )

    if had_success:
        db.outbox_reset_backoff("http_remote")

    remaining = db.outbox_stats("http_remote")["pending"]
    return DrainResult(sent=sent, failed=failed, remaining=remaining)
```

- [ ] **Step 19.4: Verify green**

Run: `uv run pytest tests/monitoring/test_offline_reconnect.py tests/monitoring/sinks/test_worker.py -v`
Expected: all pass (the existing worker tests still hold).

- [ ] **Step 19.5: Commit**

```bash
uv run pytest -q
git add src/lazy_harness/monitoring/db.py src/lazy_harness/monitoring/sinks/worker.py tests/monitoring/test_offline_reconnect.py
git commit -m "feat(monitoring): reset backoff on first successful drain"
```

---

### Task 20: Idempotency end-to-end test

**Files:**
- Create: `tests/monitoring/test_idempotency.py`

- [ ] **Step 20.1: Write the test**

```python
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
```

- [ ] **Step 20.2: Run**

Run: `uv run pytest tests/monitoring/test_idempotency.py -v`
Expected: passed.

- [ ] **Step 20.3: Commit**

```bash
git add tests/monitoring/test_idempotency.py
git commit -m "test(monitoring): verify stable event_id across rewrites"
```

---

## Phase 10 — Doctor egress audit

### Task 21: `lh doctor` prints a "network egress" section

**Files:**
- Modify: `src/lazy_harness/cli/doctor_cmd.py`
- Create: `tests/cli/test_doctor_egress.py`

- [ ] **Step 21.1: Read the existing doctor to understand its structure**

Skim `src/lazy_harness/cli/doctor_cmd.py`. Note the pattern used for sections and reuse it. (You may add a new `_section_network_egress(cfg)` helper.)

- [ ] **Step 21.2: Write the failing test**

`tests/cli/test_doctor_egress.py`:

```python
from pathlib import Path

from click.testing import CliRunner

from lazy_harness.cli.doctor_cmd import doctor


def test_doctor_shows_network_egress_section(tmp_path: Path, monkeypatch) -> None:
    cfg_path = tmp_path / "config.toml"
    cfg_path.write_text(
        '[harness]\nversion = "1"\n'
        "[metrics]\n"
        'sinks = ["sqlite_local", "http_remote"]\n'
        "[metrics.sink_options.http_remote]\n"
        'url = "https://metrics.flex.internal/ingest"\n'
    )
    monkeypatch.setenv("LH_CONFIG_DIR", str(tmp_path))

    runner = CliRunner()
    result = runner.invoke(doctor)
    assert "network egress" in result.output.lower()
    assert "metrics.flex.internal" in result.output


def test_doctor_shows_none_when_local_only(tmp_path: Path, monkeypatch) -> None:
    cfg_path = tmp_path / "config.toml"
    cfg_path.write_text('[harness]\nversion = "1"\n')
    monkeypatch.setenv("LH_CONFIG_DIR", str(tmp_path))

    runner = CliRunner()
    result = runner.invoke(doctor)
    assert "network egress" in result.output.lower()
    assert "local-only" in result.output.lower() or "no remote" in result.output.lower()
```

- [ ] **Step 21.3: Run red**

Run: `uv run pytest tests/cli/test_doctor_egress.py -v`
Expected: fails, egress text not present.

- [ ] **Step 21.4: Add the section**

In `src/lazy_harness/cli/doctor_cmd.py`, add at the end of the main `doctor` command body (adapt naming to what the file currently uses):

```python
    # --- Network egress audit ---
    console.print("\n[bold]Network egress[/bold]")
    remote_urls: list[tuple[str, str]] = []
    for name in cfg.metrics.sinks:
        if name == "sqlite_local":
            continue
        definition = cfg.metrics.sink_configs.get(name)
        if not definition:
            continue
        url = definition.options.get("url", "")
        if url:
            remote_urls.append((name, url))
    if not remote_urls:
        console.print("  [green]local-only[/green] — no remote sinks configured")
    else:
        for name, url in remote_urls:
            console.print(f"  {name} → {url}")
```

- [ ] **Step 21.5: Verify green**

Run: `uv run pytest tests/cli/test_doctor_egress.py -v`
Expected: 2 passed.

- [ ] **Step 21.6: Commit**

```bash
uv run pytest -q
git add src/lazy_harness/cli/doctor_cmd.py tests/cli/test_doctor_egress.py
git commit -m "feat(cli): add network egress section to 'lh doctor'"
```

---

## Phase 11 — Final regression + hygiene

### Task 22: Full suite, ruff, mkdocs, manual smoke

- [ ] **Step 22.1: Full test suite**

Run: `uv run pytest -q`
Expected: all new tests green. Pre-existing `test_version_is_040` failure (unrelated to this plan) remains if not already fixed on main.

- [ ] **Step 22.2: Lint**

Run: `uv run ruff check src tests`
Expected: clean.

- [ ] **Step 22.3: Docs still build**

Run: `uv run mkdocs build --strict`
Expected: clean (no doc changes expected in this plan).

- [ ] **Step 22.4: Manual smoke — local-only**

Create a throwaway profile and run:

```bash
mkdir -p /tmp/lh-smoke/claude/projects/-smoke
echo '{"type":"assistant","message":{"id":"m1","model":"claude-sonnet-4-5","usage":{"input_tokens":1,"output_tokens":1,"cache_read_input_tokens":0,"cache_creation_input_tokens":0}},"timestamp":"2026-04-14T10:00:00Z"}' > /tmp/lh-smoke/claude/projects/-smoke/sess.jsonl

cat > /tmp/lh-smoke/config.toml <<'EOF'
[harness]
version = "1"
[monitoring]
enabled = true
db = "/tmp/lh-smoke/m.db"
[profiles]
default = "personal"
[profiles.personal]
config_dir = "/tmp/lh-smoke/claude"
roots = []
EOF

LH_CONFIG_DIR=/tmp/lh-smoke uv run lh metrics ingest
LH_CONFIG_DIR=/tmp/lh-smoke uv run lh metrics status
LH_CONFIG_DIR=/tmp/lh-smoke uv run lh doctor
```

Confirm: `lh metrics ingest` prints `metrics sinks active: sqlite_local` on stderr; `status` is empty (no remote configured); `doctor` prints "local-only". No network activity.

- [ ] **Step 22.5: Manual smoke — team mode**

Extend `/tmp/lh-smoke/config.toml` with:

```toml
[metrics]
sinks = ["sqlite_local", "http_remote"]
user_id = "martin-smoke"
[metrics.sink_options.http_remote]
url = "http://127.0.0.1:9999/ingest"
```

Start a tiny fake backend in another terminal (Python one-liner):

```bash
python -m http.server 9999 &  # will 200 on any POST via some adapters; if not, use `nc -l 9999` just to confirm connection attempts
```

(`python -m http.server` returns 501 for POST. Use `flask` or a small FastAPI app to return 200. Exact method left to the implementer; the goal is just to verify connection attempts leave the host. Stop the server when done.)

Run:

```bash
LH_CONFIG_DIR=/tmp/lh-smoke uv run lh metrics ingest
LH_CONFIG_DIR=/tmp/lh-smoke uv run lh metrics status
LH_CONFIG_DIR=/tmp/lh-smoke uv run lh metrics drain
```

Confirm: stderr shows both sinks with the URL; `status` shows pending count transitioning to 0 after drain; `doctor` lists the egress URL.

- [ ] **Step 22.6: Open PR**

```bash
git push -u origin <feat-branch>  # whatever the branch was named during worktree setup
gh pr create --title "feat(metrics): plugin system + metrics_sink vertical slice" --body "$(cat <<'EOF'
## Summary

Implements the plugin system contracts, registry, and the `metrics_sink` vertical slice end-to-end per spec `specs/designs/2026-04-14-plugin-system-metrics-sink-design.md`. Default behavior is unchanged (100% local). Opt-in HTTP remote sink is available with buffer local, opportunistic drain, GitHub-handle identity, and idempotent `event_id`.

## Test plan

- [x] `uv run pytest -q` all green
- [x] `uv run ruff check src tests` clean
- [x] `uv run mkdocs build --strict` clean
- [x] Manual smoke: local-only profile (zero network)
- [x] Manual smoke: team-mode profile with fake backend (ingest → drain → status)
- [x] Offline→reconnect scenario covered by test
EOF
)"
```

---

## Self-review

Before considering this plan done:

- Spec coverage: D1–D19 all have a task that implements them (identity D2 → Task 5 and 12; default-local D10 → Task 6 and 16; opt-in-doble D11 → Task 6 and 18; discovery≠activation D12 → Task 17; visibility D13 → Task 13/14/15 stderr + Task 21 doctor; no kill switch D14 → enforced by absence and Task 16 asserts it; opportunistic drain D15 → Task 15; idempotency D16 → Task 7/20; lease D17 → Task 8; backoff reset D18 → Task 19; no TTL D19 → default in Task 6).
- No placeholders: every task has concrete code and exact commands.
- Type consistency: `MetricEvent` is the single transport type across Phases 2–9, `event_id` is the stable key across outbox + session_stats + backend, every sink class exposes `name: ClassVar[str]`.
- Forward references are explicit: Task 9 depends on Task 7 (columns), Task 10 depends on Task 8 (outbox), Task 11 depends on Task 10 (sink) and Task 8 (outbox), Tasks 12–15 depend on 9/10/11, Task 19 discovers the missing `outbox_reset_backoff` and fixes it.

If you hit an inconsistency the plan missed, stop and escalate — do not paper over it.

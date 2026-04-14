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

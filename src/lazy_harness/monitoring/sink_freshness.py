"""Health classifier for remote metrics sinks.

Reads two independent signals. `sink_outbox.created_ts` for the most recent
event a sink was handed, regardless of whether it has since been sent, says
whether ingest is still producing. `attempts` on the rows that are not yet
sent says whether the drain is still delivering — the failure this module's
name promises and enqueue age cannot see, because a dead endpoint keeps
accepting enqueues while nothing leaves the machine.
The CLI rendering lives in `lh doctor`; this module is pure logic — mirrors
`engram_persist_health.py`'s split between classifier and renderer.

Only sinks `plan_sinks()` currently says are active are checked. A sink that
was never configured, or whose activation variable is unset, is not a health
problem: flagging it would be a permanent false alarm on every machine that
never turned on a remote sink. This is also why `sqlite_local` is excluded —
it is the store itself, not a delivery pipeline that can silently stall.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Literal

from lazy_harness.core.config import Config
from lazy_harness.core.paths import data_dir, expand_path
from lazy_harness.monitoring.db import MetricsDB
from lazy_harness.monitoring.sink_setup import plan_sinks

HealthState = Literal["ok", "warn", "fail", "missing"]

AGE_WARN = timedelta(hours=24)
AGE_FAIL = timedelta(days=7)

# Deliberately not a duration. `drain_http_remote` runs on every ingest, so
# three failed attempts is a sink that has been tried and refused for roughly
# 45 minutes; an age threshold tight enough to catch that would fire every
# night on a machine nobody used.
ATTEMPTS_WARN = 3
ATTEMPTS_FAIL = 6


@dataclass(frozen=True)
class SinkFreshness:
    name: str
    state: HealthState
    last_enqueued_age_seconds: float | None
    delivery_state: HealthState = "ok"
    undelivered: int = 0
    max_attempts: int = 0
    last_error: str = ""


def _missing(name: str) -> SinkFreshness:
    return SinkFreshness(name=name, state="missing", last_enqueued_age_seconds=None)


def _delivery_state(max_attempts: int) -> HealthState:
    """Never "missing": a sink with nothing undelivered has a verdict, and it
    is "ok". Absence of a backlog is the healthy state, not an unknown one."""
    if max_attempts >= ATTEMPTS_FAIL:
        return "fail"
    if max_attempts >= ATTEMPTS_WARN:
        return "warn"
    return "ok"


def _age_state(age: timedelta) -> HealthState:
    if age >= AGE_FAIL:
        return "fail"
    if age >= AGE_WARN:
        return "warn"
    return "ok"


def collect_sink_freshness(db_path: Path, sink_name: str, *, now: datetime) -> SinkFreshness:
    """Freshness for one sink. Never opens (and so never creates) a DB file
    that does not already exist — `lh doctor` is read-only."""
    if not db_path.is_file():
        return _missing(sink_name)

    db = MetricsDB(db_path)
    try:
        last_ts = db.outbox_last_enqueued_ts(sink_name)
        delivery = db.outbox_delivery_health(sink_name)
    finally:
        db.close()

    if last_ts is None:
        return _missing(sink_name)

    age_seconds = now.timestamp() - last_ts
    return SinkFreshness(
        name=sink_name,
        state=_age_state(timedelta(seconds=age_seconds)),
        last_enqueued_age_seconds=age_seconds,
        delivery_state=_delivery_state(delivery["max_attempts"]),
        undelivered=delivery["undelivered"],
        max_attempts=delivery["max_attempts"],
        last_error=delivery["last_error"],
    )


def collect_sinks_freshness(cfg: Config, *, now: datetime) -> list[SinkFreshness]:
    """Freshness for every remote sink that is active right now.

    Skips entirely (returns `[]`) when monitoring is disabled — `lh metrics
    ingest` itself no-ops in that case, so nothing ever reaches the outbox and
    checking it would only produce a false alarm — and when `plan_sinks`
    cannot resolve a sink's endpoint at all (the egress section already
    reports that misconfiguration).
    """
    if not cfg.monitoring.enabled:
        return []
    try:
        plans = [p for p in plan_sinks(cfg.metrics) if p.name != "sqlite_local" and p.active]
    except ValueError:
        return []
    if not plans:
        return []

    db_path = expand_path(cfg.monitoring.db) if cfg.monitoring.db else data_dir() / "metrics.db"
    return [collect_sink_freshness(db_path, p.name, now=now) for p in plans]

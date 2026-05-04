"""Health classifier for the engram_persist Stop hook.

Reads `engram_persist_metrics.jsonl` (append-only, one JSON object per line)
and reports the latest run's freshness, recent failure rate, and cursor lag.
The CLI rendering lives in `lh doctor`; this module is pure logic.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Literal

HealthState = Literal["ok", "warn", "fail", "missing"]

AGE_WARN = timedelta(hours=24)
AGE_FAIL = timedelta(days=7)
FAILURE_RATE_WARN = 0.0
FAILURE_RATE_FAIL = 0.10
CURSOR_LAG_WARN_BYTES = 0
CURSOR_LAG_FAIL_BYTES = 64 * 1024


@dataclass(frozen=True)
class EngramPersistHealth:
    state: HealthState
    last_run_age_seconds: float | None
    failure_rate: float | None
    cursor_lag_bytes: int | None
    runs_considered: int


def _missing() -> EngramPersistHealth:
    return EngramPersistHealth(
        state="missing",
        last_run_age_seconds=None,
        failure_rate=None,
        cursor_lag_bytes=None,
        runs_considered=0,
    )


def _read_run_events(metrics_path: Path) -> list[dict[str, Any]]:
    runs: list[dict[str, Any]] = []
    with metrics_path.open() as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(obj, dict) and obj.get("event") == "run":
                runs.append(obj)
    return runs


def _parse_ts(ts: str) -> datetime | None:
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt


def _age_state(age: timedelta) -> HealthState:
    if age >= AGE_FAIL:
        return "fail"
    if age >= AGE_WARN:
        return "warn"
    return "ok"


def _failure_rate_state(rate: float) -> HealthState:
    if rate > FAILURE_RATE_FAIL:
        return "fail"
    if rate > FAILURE_RATE_WARN:
        return "warn"
    return "ok"


def _cursor_lag_state(lag: int) -> HealthState:
    if lag >= CURSOR_LAG_FAIL_BYTES:
        return "fail"
    if lag > CURSOR_LAG_WARN_BYTES:
        return "warn"
    return "ok"


def _worst(states: list[HealthState]) -> HealthState:
    order: dict[HealthState, int] = {"ok": 0, "warn": 1, "fail": 2, "missing": 3}
    return max(states, key=lambda s: order[s])


def collect_engram_persist_health(
    metrics_path: Path,
    *,
    now: datetime,
    window: int = 20,
) -> EngramPersistHealth:
    if not metrics_path.is_file():
        return _missing()

    runs = _read_run_events(metrics_path)
    if not runs:
        return _missing()

    last = runs[-1]
    last_ts = _parse_ts(str(last.get("ts", "")))
    if last_ts is None:
        return _missing()
    age = now - last_ts
    age_seconds = age.total_seconds()

    recent = runs[-window:]
    total_attempts = sum(int(r.get("saved_ok", 0)) + int(r.get("saved_failed", 0)) for r in recent)
    total_failed = sum(int(r.get("saved_failed", 0)) for r in recent)
    failure_rate = (total_failed / total_attempts) if total_attempts else 0.0

    lag_map = last.get("cursor_lag_bytes") or {}
    if isinstance(lag_map, dict):
        cursor_lag = max(
            (int(v) for v in lag_map.values() if isinstance(v, (int, float))),
            default=0,
        )
    else:
        cursor_lag = 0

    state = _worst(
        [
            _age_state(age),
            _failure_rate_state(failure_rate),
            _cursor_lag_state(cursor_lag),
        ]
    )

    return EngramPersistHealth(
        state=state,
        last_run_age_seconds=age_seconds,
        failure_rate=failure_rate,
        cursor_lag_bytes=cursor_lag,
        runs_considered=len(recent),
    )

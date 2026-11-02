"""Which `session_stats` rows are sessions (ADR-039 Evolution, 2026-11-01).

`run_inference` records a billed backend call as a `session_stats` row whose
`workload` is `inference:<role>`. That row is spend, not a session: nobody
opened it, and no launch preceded it. Tokens and cost keep summing it; every
count of sessions, and the launch-to-session ratio, must leave it out. This is
the one place that says which rows those are.
"""

from __future__ import annotations

from typing import Any

WORKLOAD_PREFIX = "inference:"

# For `COUNT(DISTINCT <this>)`: NULL for an inference row, so it is not counted.
SESSION_COUNT_EXPR = f"CASE WHEN workload LIKE '{WORKLOAD_PREFIX}%' THEN NULL ELSE session END"


def counts_as_session(row: dict[str, Any]) -> bool:
    """False for a row written by `run_inference`; true for anything else."""
    return not str(row.get("workload") or "").startswith(WORKLOAD_PREFIX)

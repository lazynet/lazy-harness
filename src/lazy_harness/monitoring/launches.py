"""The one write path from a launcher into the `launches` table.

`lh run` and `lh exec` both count a launch, so neither owns the write. The
imports are deferred to the call so that a launcher pays for sqlite only on
the invocation that actually starts an agent.
"""

from __future__ import annotations

import sys


def record_launch(*, profile: str, agent: str, entry: str) -> None:
    """Append one launch event, or say so on stderr and carry on.

    Call after every validation and after the `--dry-run` diversion,
    immediately before the agent starts: the unit is a launch actually
    started, and a counter fed by rehearsals is most of the signal at a
    five-event threshold.

    Fail-soft by construction, which includes the `ValueError` the store
    raises on an unknown `entry`. A launcher that refused to start because
    its own bookkeeping was broken would be a worse failure than an
    undercount, and this counter already undercounts by design — a session
    started by typing `claude` directly never reaches here.
    """
    try:
        from lazy_harness.core.identity import resolve_host
        from lazy_harness.monitoring.db import MetricsDB, resolve_db_path

        db = MetricsDB(resolve_db_path())
        try:
            db.record_launch(profile=profile, agent=agent, entry=entry, host=resolve_host())
        finally:
            db.close()
    except Exception as e:  # noqa: BLE001 - bookkeeping never fails a launch
        print(f"lh: launch not recorded: {e}", file=sys.stderr)

"""The one write path from a launcher into the `launches` table, and the
fixed-horizon kill check that reads it back.

`lh run` and `lh exec` both count a launch, so neither owns the write. The
imports are deferred to the call so that a launcher pays for sqlite only on
the invocation that actually starts an agent.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from lazy_harness.monitoring.db import MetricsDB

# "Claude profile" is a profile whose `agent` column in `launches` is this
# string — read off the table itself, never resolved through config
# (specs/designs/2026-09-13-multi-agent-blast-radius-design.md:275-373).
CLAUDE_AGENT = "claude-code"

# The real CodexAdapter (parent step 9) merged 2026-09-16 (1de385c, #348).
# The horizon is measured from this date, not from the step-4 throwaway.
CODEX_ADAPTER_MERGED = date(2026, 9, 16)


@dataclass(frozen=True, slots=True)
class AdoptionVerdict:
    """One fixed-horizon adoption check, past the horizon and calibrated.

    `launches_by_profile` carries non-Claude profiles only — a Claude
    profile's own launches fed the calibration, not the verdict.
    """

    window_days: int
    threshold: float
    ratio_used: float
    launches_by_profile: dict[str, int]
    below_threshold: tuple[str, ...]


def adoption_check(
    db: MetricsDB,
    *,
    now: datetime,
    horizon_start: date = CODEX_ADAPTER_MERGED,
    horizon_weeks: int = 8,
    window_days: int = 28,
) -> AdoptionVerdict | None:
    """The blast-radius kill criterion's adoption check (decision 1).

    Returns `None` — not a verdict — in either of two cases the design treats
    the same way: the horizon has not elapsed yet, or no Claude profile has a
    measurable launch-to-session ratio in the window, which means calibration
    is impossible and the threshold is not set. Neither case is a kill signal.

    Otherwise `threshold = 5 * min(ratio over Claude profiles)` — the
    minimum, not the mean, because the design's calibration rule is biased
    toward false negatives: an adapter actually in use must not be killed by
    a threshold inflated by a heavier Claude profile elsewhere. A lower
    threshold makes "below threshold" harder to reach, which is the direction
    the bias requires.

    `db` and `now` are both injectable: this function reads no wall clock
    itself, but `MetricsDB.launch_counts`/`launch_to_session_ratio` read
    `db._now()` for their own window arithmetic, so a caller comparing
    against `now` must freeze `db._now` to the same instant — otherwise the
    two halves of the same window disagree with each other's clock.
    """
    horizon_end = horizon_start + timedelta(weeks=horizon_weeks)
    if now.date() < horizon_end:
        return None

    claude_profiles = {
        profile for (profile, agent, _entry) in db.launch_counts() if agent == CLAUDE_AGENT
    }
    ratios = db.launch_to_session_ratio(days=window_days)
    claude_ratios = [
        ratios[profile].ratio
        for profile in claude_profiles
        if profile in ratios and ratios[profile].ratio is not None
    ]
    if not claude_ratios:
        return None

    ratio_used = min(claude_ratios)  # type: ignore[type-var]
    threshold = 5 * ratio_used
    launches_by_profile = {
        profile: r.launches for profile, r in ratios.items() if profile not in claude_profiles
    }
    below_threshold = tuple(
        sorted(profile for profile, n in launches_by_profile.items() if n < threshold)
    )
    return AdoptionVerdict(
        window_days=window_days,
        threshold=threshold,
        ratio_used=ratio_used,
        launches_by_profile=launches_by_profile,
        below_threshold=below_threshold,
    )


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

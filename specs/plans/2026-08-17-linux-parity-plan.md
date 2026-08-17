# Linux parity Implementation Plan (waves 2, 3, 4)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix a shipping macOS defect that silently rewrites schedules, replace every "cannot check" that is reported as "not loaded", and complete ADR-013 with working systemd and cron backends.

**Architecture:** One shared cron parser feeds three backend-specific renderers, and an untranslatable expression raises instead of falling back. Backends take an injectable command runner so their subprocess layer is testable. A three-valued `JobState` replaces booleans so ignorance has a spelling.

**Tech Stack:** Python 3.11+ stdlib (`plistlib`, `fcntl`, `subprocess`), `pytest`, `ruff`.

**Spec:** [`specs/designs/2026-08-17-linux-parity-design.md`](../designs/2026-08-17-linux-parity-design.md)

**Branches:** three, in order — `fix/scheduler-schedule-translation` (0.39.2), `fix/scheduler-job-state` (0.39.3), `feat/systemd-cron-backends` (0.40.0). Do not merge them into one; each is separately deployable and wave 2 needs its own manual gate.

## Global Constraints

- Python `>=3.11`. `StrEnum` is available; use it.
- Strict TDD. Every new test observed failing first.
- `pytest.raises(match=...)` anchors on literal cron expressions or exception class names, never on a substring that could appear in a `tmp_path`.
- No backend may call `subprocess.run` directly. All four current call sites in `launchd.py` (lines 77, 78, 89, 105) move behind the injected runner.
- Every explicit-parameter test is paired with a parameter-less smoke test so default resolution of `runner` and `unit_dir` is exercised. Always injecting them leaves the defaults completely untested — two `Path.cwd()` bugs survived years of green suites in this repo that way.
- `/tdd-check` before every commit. Conventional commits, no AI trailers.
- CI cannot integration-test any backend: GitHub runners have no systemd user session and `launchctl` behaves differently there. Pure functions are tested everywhere; the subprocess layer is tested through the fake runner.

---

# Wave 2 — `fix/scheduler-schedule-translation`

This wave is independent of everything else.

**Corrected 2026-08-17 during execution.** An earlier draft of this plan claimed six declared jobs were over-executing. That was inferred from the translation function rather than read off the installed plists, and it is wrong. Checked against `~/Library/LaunchAgents/`, **one** job is affected: `graphify-update`, declared `0 */4 * * *` and installed as `StartInterval=3600` — 24 runs a day instead of 6, so 4×. The other five declare either `*/N` in the minute field or the strict daily form, which are exactly the two shapes the old translator handled correctly. The defect class still reaches 168× on weekly shapes; none are currently declared.

## File Structure

| File | Responsibility |
|---|---|
| `src/lazy_harness/scheduler/schedule.py` | **new** — `Schedule`, `parse_cron`, `ScheduleTranslationError`, and the three renderers |
| `src/lazy_harness/scheduler/launchd.py` | consume the renderer; delete `_cron_to_calendar` and `_cron_to_interval` |
| `tests/unit/test_scheduler_schedule.py` | **new** — the parser and all three renderers |
| `tests/unit/test_scheduler_launchd.py` | plist generation against the renderer |

### Task 1: Pin the current wrong behaviour, then the correct behaviour

Writing the wrong-behaviour assertion first makes the defect a fact in the repo's history rather than a claim in a spec.

**Files:**
- Test: `tests/unit/test_scheduler_schedule.py` (create)

**Interfaces:**
- Produces: `parse_cron(expr: str) -> Schedule`, `ScheduleTranslationError`, `Schedule` with fields `minute`, `hour`, `day_of_month`, `month`, `day_of_week` (all `str`)

- [ ] **Step 1: Write the failing test**

```python
from __future__ import annotations

import pytest


@pytest.mark.parametrize(
    ("expr", "expected"),
    [
        ("30 3 * * 0", ("30", "3", "*", "*", "0")),
        ("0 */6 * * *", ("0", "*/6", "*", "*", "*")),
        ("*/30 * * * *", ("*/30", "*", "*", "*", "*")),
        ("15 2 1 * *", ("15", "2", "1", "*", "*")),
        ("0 9 * * 1-5", ("0", "9", "*", "*", "1-5")),
    ],
)
def test_parse_cron_keeps_every_field(expr: str, expected: tuple[str, ...]) -> None:
    from lazy_harness.scheduler.schedule import parse_cron

    s = parse_cron(expr)
    assert (s.minute, s.hour, s.day_of_month, s.month, s.day_of_week) == expected


@pytest.mark.parametrize("expr", ["", "0 9", "0 9 * *", "not a cron expression"])
def test_parse_cron_rejects_malformed_expressions(expr: str) -> None:
    from lazy_harness.scheduler.schedule import ScheduleTranslationError, parse_cron

    with pytest.raises(ScheduleTranslationError, match="five fields"):
        parse_cron(expr)
```

- [ ] **Step 2: Run and confirm it fails**

Run: `uv run pytest tests/unit/test_scheduler_schedule.py -v`
Expected: FAIL — `ModuleNotFoundError: lazy_harness.scheduler.schedule`.

- [ ] **Step 3: Implement the parser**

Create `src/lazy_harness/scheduler/schedule.py`:

```python
"""Cron expression parsing and per-backend rendering.

`config.toml` declares schedules in cron syntax (ADR-013). Each backend
renders that into its native form. A backend that cannot express an
expression faithfully raises rather than approximating it — the previous
launchd implementation approximated, and every non-daily schedule silently
became hourly.
"""

from __future__ import annotations

from dataclasses import dataclass


class ScheduleTranslationError(Exception):
    """The expression is valid cron but this backend cannot express it."""


@dataclass(frozen=True, slots=True)
class Schedule:
    minute: str
    hour: str
    day_of_month: str
    month: str
    day_of_week: str


def parse_cron(expr: str) -> Schedule:
    parts = expr.strip().split()
    if len(parts) != 5:
        raise ScheduleTranslationError(
            f"cron expression must have five fields, got {len(parts)}: {expr!r}"
        )
    return Schedule(*parts)
```

- [ ] **Step 4: Run and confirm it passes**

Run: `uv run pytest tests/unit/test_scheduler_schedule.py -v`
Expected: 9 PASSED.

- [ ] **Step 5: Commit**

```bash
git add src/lazy_harness/scheduler/schedule.py tests/unit/test_scheduler_schedule.py
git commit -m "feat: add a shared cron expression parser for scheduler backends"
```

---

### Task 2: The launchd renderer, which refuses rather than guesses

**Files:**
- Modify: `src/lazy_harness/scheduler/schedule.py`
- Test: `tests/unit/test_scheduler_schedule.py`

**Interfaces:**
- Produces: `render_launchd(s: Schedule) -> dict[str, object]` returning either `{"StartCalendarInterval": ...}` or `{"StartInterval": int}`

- [ ] **Step 1: Write the failing test**

This is the regression test for the measured defect. Each case names the multiplier the old code produced.

```python
def test_render_launchd_weekly_is_weekly_not_hourly() -> None:
    """Was installed as StartInterval=3600 — 168x over-execution."""
    from lazy_harness.scheduler.schedule import parse_cron, render_launchd

    out = render_launchd(parse_cron("30 3 * * 0"))
    assert out == {"StartCalendarInterval": {"Hour": 3, "Minute": 30, "Weekday": 0}}


def test_render_launchd_every_six_hours_is_not_hourly() -> None:
    """ADR-013's own example. Was installed as StartInterval=3600 — 6x."""
    from lazy_harness.scheduler.schedule import parse_cron, render_launchd

    out = render_launchd(parse_cron("0 */6 * * *"))
    assert out == {
        "StartCalendarInterval": [
            {"Hour": 0, "Minute": 0},
            {"Hour": 6, "Minute": 0},
            {"Hour": 12, "Minute": 0},
            {"Hour": 18, "Minute": 0},
        ]
    }


def test_render_launchd_monthly_is_monthly() -> None:
    """Was installed as StartInterval=3600 — roughly 720x."""
    from lazy_harness.scheduler.schedule import parse_cron, render_launchd

    out = render_launchd(parse_cron("15 2 1 * *"))
    assert out == {"StartCalendarInterval": {"Hour": 2, "Minute": 15, "Day": 1}}


def test_render_launchd_daily_unchanged() -> None:
    from lazy_harness.scheduler.schedule import parse_cron, render_launchd

    assert render_launchd(parse_cron("0 10 * * *")) == {
        "StartCalendarInterval": {"Hour": 10, "Minute": 0}
    }


def test_render_launchd_step_minutes_uses_interval() -> None:
    from lazy_harness.scheduler.schedule import parse_cron, render_launchd

    assert render_launchd(parse_cron("*/30 * * * *")) == {"StartInterval": 1800}


def test_render_launchd_refuses_a_range_it_cannot_express() -> None:
    """Weekday ranges have no faithful StartCalendarInterval form.

    Refusing is the point: the old code turned this into hourly, which also
    fired on weekends.
    """
    from lazy_harness.scheduler.schedule import (
        ScheduleTranslationError,
        parse_cron,
        render_launchd,
    )

    with pytest.raises(ScheduleTranslationError, match="1-5"):
        render_launchd(parse_cron("0 9 * * 1-5"))
```

- [ ] **Step 2: Run and confirm all six fail**

Run: `uv run pytest tests/unit/test_scheduler_schedule.py -k launchd -v`
Expected: 6 FAILED — `cannot import name 'render_launchd'`.

- [ ] **Step 3: Implement the renderer**

Append to `schedule.py`:

```python
def _as_int(field: str, name: str) -> int:
    if not field.isdigit():
        raise ScheduleTranslationError(f"launchd cannot express {name}={field!r}")
    return int(field)


def _step_values(field: str, upper: int) -> list[int] | None:
    """Expand `*/N` into the concrete values launchd needs. None if not a step."""
    if not field.startswith("*/"):
        return None
    step = field[2:]
    if not step.isdigit() or int(step) == 0:
        raise ScheduleTranslationError(f"malformed step field {field!r}")
    return list(range(0, upper, int(step)))


def render_launchd(s: Schedule) -> dict[str, object]:
    """Render into a launchd StartCalendarInterval or StartInterval.

    launchd has no range or list syntax, so anything using `-` or `,` in a
    field raises. The previous implementation fell back to StartInterval=3600
    for every expression it did not recognise.
    """
    for name, field in (
        ("minute", s.minute),
        ("hour", s.hour),
        ("day_of_month", s.day_of_month),
        ("month", s.month),
        ("day_of_week", s.day_of_week),
    ):
        if "-" in field or "," in field:
            raise ScheduleTranslationError(
                f"launchd cannot express {name}={field!r}; use separate jobs"
            )
    if s.month != "*":
        raise ScheduleTranslationError(f"launchd cannot express month={s.month!r}")

    minute_steps = _step_values(s.minute, 60)
    if minute_steps is not None:
        if (s.hour, s.day_of_month, s.day_of_week) != ("*", "*", "*"):
            raise ScheduleTranslationError(
                f"launchd cannot combine a minute step with {s.hour!r}/{s.day_of_month!r}"
            )
        return {"StartInterval": int(s.minute[2:]) * 60}

    minute = _as_int(s.minute, "minute")
    hour_steps = _step_values(s.hour, 24)
    if hour_steps is not None:
        if (s.day_of_month, s.day_of_week) != ("*", "*"):
            raise ScheduleTranslationError("launchd cannot combine an hour step with a day")
        return {"StartCalendarInterval": [{"Hour": h, "Minute": minute} for h in hour_steps]}

    entry: dict[str, int] = {"Hour": _as_int(s.hour, "hour"), "Minute": minute}
    if s.day_of_week != "*":
        entry["Weekday"] = _as_int(s.day_of_week, "day_of_week")
    if s.day_of_month != "*":
        entry["Day"] = _as_int(s.day_of_month, "day_of_month")
    return {"StartCalendarInterval": entry}
```

- [ ] **Step 4: Run**

Run: `uv run pytest tests/unit/test_scheduler_schedule.py -v`
Expected: all PASSED.

- [ ] **Step 5: Commit**

```bash
git add src/lazy_harness/scheduler/schedule.py tests/unit/test_scheduler_schedule.py
git commit -m "fix: render launchd schedules faithfully instead of falling back to hourly"
```

---

### Task 3: Wire launchd to the renderer and delete the old translators

**Files:**
- Modify: `src/lazy_harness/scheduler/launchd.py` — `generate_plist`; delete `_cron_to_interval` and `_cron_to_calendar`
- Test: `tests/unit/test_scheduler_launchd.py`

- [ ] **Step 1: Write the failing test**

```python
def test_generate_plist_honours_a_six_hourly_schedule(tmp_path: Path) -> None:
    import plistlib

    from lazy_harness.scheduler.base import SchedulerJob
    from lazy_harness.scheduler.launchd import LaunchdBackend

    job = SchedulerJob(name="qmd-sync", schedule="0 */6 * * *", command="qmd sync")
    path = LaunchdBackend().generate_plist(job, tmp_path)

    plist = plistlib.loads(path.read_bytes())
    assert "StartInterval" not in plist
    assert len(plist["StartCalendarInterval"]) == 4


def test_generate_plist_refuses_an_untranslatable_schedule(tmp_path: Path) -> None:
    from lazy_harness.scheduler.base import SchedulerJob
    from lazy_harness.scheduler.launchd import LaunchdBackend
    from lazy_harness.scheduler.schedule import ScheduleTranslationError

    job = SchedulerJob(name="weekdays", schedule="0 9 * * 1-5", command="echo hi")
    with pytest.raises(ScheduleTranslationError, match="1-5"):
        LaunchdBackend().generate_plist(job, tmp_path)
```

- [ ] **Step 2: Run and confirm both fail**

Run: `uv run pytest tests/unit/test_scheduler_launchd.py -k "six_hourly or untranslatable" -v`
Expected: FAIL — the first because `StartInterval` is present, the second because nothing raises.

- [ ] **Step 3: Rewrite `generate_plist`**

Delete `_cron_to_interval` and `_cron_to_calendar` entirely, and in `generate_plist` replace the calendar/interval branch with:

```python
        from lazy_harness.scheduler.schedule import parse_cron, render_launchd

        plist.update(render_launchd(parse_cron(job.schedule)))
```

Also replace the hardcoded PATH on line 57 with the shared resolver introduced in Wave 4 Task 4 — or, if Wave 4 has not landed yet, inline it here and extract later:

```python
            "EnvironmentVariables": {"PATH": _resolved_path()},
```

- [ ] **Step 4: Run the launchd tests, then the full suite**

Run: `uv run pytest tests/unit/test_scheduler_launchd.py -v && uv run pytest -q`
Expected: all pass. Any existing test asserting `StartInterval == 3600` for a non-daily schedule was pinning the bug — delete it and say so in the commit.

- [ ] **Step 5: Prove the fix is load-bearing**

Restore `_cron_to_calendar`/`_cron_to_interval` temporarily, re-run the three "was installed as hourly" tests, confirm all three fail, then restore the fix.

- [ ] **Step 6: Commit**

```bash
git add src/lazy_harness/scheduler/launchd.py tests/unit/test_scheduler_launchd.py
git commit -m "fix: install launchd jobs on their declared schedule"
```

---

### Task 4: Wave 2 gate, PR, and the manual audit

- [ ] **Step 1: `/tdd-check`**

```bash
uv run pytest && uv run ruff check src tests && uv run --group docs mkdocs build --strict
```

- [ ] **Step 2: Print the before/after for every declared job — this is the mandatory gate**

The "before" column must be read off the **installed plists**, not inferred from the translation function. Inferring it is how the first draft of this plan reported six affected jobs when the real number was one.

```bash
uv run python - <<'PY'
import plistlib, pathlib
from lazy_harness.core.config import load_config
from lazy_harness.core.paths import config_file
from lazy_harness.scheduler.schedule import parse_cron, render_launchd, ScheduleTranslationError

agents = pathlib.Path.home() / "Library/LaunchAgents"
for j in load_config(config_file()).scheduler.jobs:
    p = agents / f"com.lazy-harness.{j.name}.plist"
    installed = "not installed"
    if p.is_file():
        d = plistlib.loads(p.read_bytes())
        installed = (
            f"every {d['StartInterval'] // 60} min"
            if "StartInterval" in d
            else str(d.get("StartCalendarInterval"))
        )
    try:
        now = render_launchd(parse_cron(j.schedule))
    except ScheduleTranslationError as e:
        now = f"REFUSES: {e}"
    flag = "" if str(now) == installed else "   <-- CHANGES"
    print(f"{j.name:<20} declares={j.schedule:<16} installed={installed:<26} now={now}{flag}")
PY
```

**Stop and read this output.** Only the rows flagged `CHANGES` are affected. For each, decide whether the declaration is still what you want now that it will be honoured: a job that has effectively been running hourly for months may be one whose declaration you would rather edit than whose cadence you would rather drop.

Any job that now `REFUSES` must have its schedule rewritten before this ships, or `lh scheduler install` will fail on it.

- [ ] **Step 3: Push and open the PR**

```bash
gh auth switch --user lazynet
git push -u origin fix/scheduler-schedule-translation
gh pr create --title "fix: install launchd jobs on their declared schedule"
gh auth switch --user mvago-flx
```

- [ ] **Step 4: After the release, deploy and verify the plists**

Follow the deploy procedure in the release train. Grep string for the binary check: `render_launchd`. Then:

```bash
lh scheduler install
for p in ~/Library/LaunchAgents/com.lazy-harness.*.plist; do
  echo "== $(basename $p)"; plutil -p "$p" | grep -A6 -E "StartCalendarInterval|StartInterval"
done
```
Confirm each matches its declaration. Old plists are overwritten by `install`; nothing needs manual deletion.

---

# Wave 3 — `fix/scheduler-job-state`

Blocked by wave 2. Blocks wave 4 and wave 5.

## File Structure

| File | Responsibility |
|---|---|
| `src/lazy_harness/scheduler/base.py` | `JobState`; extend the `SchedulerBackend` Protocol with `label_for` and `job_state` |
| `src/lazy_harness/scheduler/launchd.py` | injected runner; implement `label_for`, `job_state` |
| `src/lazy_harness/scheduler/systemd.py`, `cron.py` | `label_for` and `job_state` returning `UNKNOWN` until wave 4 |
| `src/lazy_harness/monitoring/views/_helpers.py` | delete `launchctl_loaded`; `file_locked` via `fcntl`; `StatusContext` gains `scheduler_backend`, drops `launchd_prefix` |
| `src/lazy_harness/monitoring/views/cron.py`, `overview.py` | consume `job_state` |

### Task 5: `JobState` and the runner seam

**Interfaces:**
- Produces: `JobState` (`LOADED`, `NOT_LOADED`, `UNKNOWN`); `Runner = Callable[[list[str]], subprocess.CompletedProcess[str]]`; `LaunchdBackend(*, runner: Runner | None = None, label_prefix: str = "com.lazy-harness")`; `job_state(label: str) -> tuple[JobState, str]`

- [ ] **Step 1: Write the failing tests**

```python
def test_job_state_reports_unknown_when_the_tool_is_absent() -> None:
    """A missing launchctl is 'cannot check', not 'not loaded'.

    Returning False for this is what made every scheduled job render as a
    failure on Linux.
    """
    from lazy_harness.scheduler.base import JobState
    from lazy_harness.scheduler.launchd import LaunchdBackend

    def missing(argv: list[str]):
        raise FileNotFoundError(argv[0])

    state, reason = LaunchdBackend(runner=missing).job_state("com.lazy-harness.qmd-sync")
    assert state is JobState.UNKNOWN
    assert "launchctl" in reason


def test_job_state_reports_loaded_on_success() -> None:
    import subprocess

    from lazy_harness.scheduler.base import JobState
    from lazy_harness.scheduler.launchd import LaunchdBackend

    def ok(argv: list[str]):
        return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")

    state, _ = LaunchdBackend(runner=ok).job_state("com.lazy-harness.qmd-sync")
    assert state is JobState.LOADED


def test_job_state_reports_not_loaded_on_nonzero_exit() -> None:
    import subprocess

    from lazy_harness.scheduler.base import JobState
    from lazy_harness.scheduler.launchd import LaunchdBackend

    def absent(argv: list[str]):
        return subprocess.CompletedProcess(argv, 1, stdout="", stderr="Could not find service")

    state, _ = LaunchdBackend(runner=absent).job_state("com.lazy-harness.qmd-sync")
    assert state is JobState.NOT_LOADED


def test_launchd_backend_constructs_without_arguments() -> None:
    """Paired smoke test: always injecting the runner leaves the default untested."""
    from lazy_harness.scheduler.launchd import LaunchdBackend

    backend = LaunchdBackend()
    assert backend.label_for.__self__ is backend
    assert backend._runner is not None
```

- [ ] **Step 2: Run and confirm they fail**

Run: `uv run pytest tests/unit/test_scheduler_launchd.py -k "job_state or without_arguments" -v`
Expected: FAIL.

- [ ] **Step 3: Add `JobState` and extend the Protocol**

In `src/lazy_harness/scheduler/base.py`:

```python
from collections.abc import Callable
from enum import StrEnum
import subprocess

Runner = Callable[[list[str]], "subprocess.CompletedProcess[str]"]


class JobState(StrEnum):
    """Whether a job is registered with the OS scheduler.

    UNKNOWN exists so a backend that cannot introspect has a way to say so.
    Spelling it as NOT_LOADED is what made `lh status cron` report every job
    as failed on any platform without launchctl.
    """

    LOADED = "loaded"
    NOT_LOADED = "not_loaded"
    UNKNOWN = "unknown"


def default_runner(argv: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(argv, capture_output=True, text=True, timeout=10)
```

Add to the `SchedulerBackend` Protocol:

```python
    def label_for(self, job: SchedulerJob) -> str: ...
    def job_state(self, label: str) -> tuple[JobState, str]: ...
```

- [ ] **Step 4: Implement on `LaunchdBackend`**

```python
    def __init__(
        self,
        label_prefix: str = "com.lazy-harness",
        *,
        runner: Runner | None = None,
    ) -> None:
        self._prefix = label_prefix
        self._runner = runner or default_runner

    def label_for(self, job: SchedulerJob) -> str:
        return f"{self._prefix}.{job.name}"

    def job_state(self, label: str) -> tuple[JobState, str]:
        try:
            proc = self._runner(["launchctl", "list", label])
        except (FileNotFoundError, OSError) as e:
            return JobState.UNKNOWN, f"launchctl unavailable: {e}"
        except subprocess.TimeoutExpired:
            return JobState.UNKNOWN, "launchctl timed out"
        return (JobState.LOADED if proc.returncode == 0 else JobState.NOT_LOADED), ""
```

Replace the four direct `subprocess.run` calls at lines 77, 78, 89 and 105 with `self._runner([...])`. Keep `_label` as a private alias delegating to `label_for` if other code calls it, or update those call sites.

Add the same two methods to `SystemdBackend` and `CronBackend`, returning `(JobState.UNKNOWN, "backend not implemented")` for now.

- [ ] **Step 5: Run**

Run: `uv run pytest tests/unit/test_scheduler_launchd.py -v && uv run pytest -q`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add src/lazy_harness/scheduler/ tests/unit/test_scheduler_launchd.py
git commit -m "feat: three-valued JobState and an injectable runner for scheduler backends"
```

---

### Task 6: Delete `launchctl_loaded` and rewire the views

**Files:**
- Modify: `src/lazy_harness/monitoring/views/_helpers.py:217` (delete), `:40` (drop `launchd_prefix`, add `scheduler_backend`)
- Modify: `src/lazy_harness/monitoring/views/cron.py:95`, `overview.py:153`
- Test: `tests/unit/test_status_views_helpers.py`

- [ ] **Step 1: Write the failing test**

```python
def test_status_context_exposes_the_scheduler_backend_not_a_launchd_prefix() -> None:
    """Reverse-DNS labelling is a launchd convention; the status layer must not know it."""
    from lazy_harness.core.config import Config
    from lazy_harness.monitoring.views._helpers import StatusContext

    ctx = StatusContext.build(Config())
    assert not hasattr(ctx, "launchd_prefix")
    assert ctx.scheduler_backend is not None


def test_launchctl_loaded_is_gone() -> None:
    """It returned False for 'cannot check'. Nothing may reintroduce that shape."""
    from lazy_harness.monitoring.views import _helpers

    assert not hasattr(_helpers, "launchctl_loaded")
```

- [ ] **Step 2: Run and confirm both fail**

Run: `uv run pytest tests/unit/test_status_views_helpers.py -k "scheduler_backend or launchctl_loaded_is_gone" -v`

- [ ] **Step 3: Make the change**

In `_helpers.py`: delete `launchctl_loaded`; on `StatusContext` replace `launchd_prefix: str = "com.lazy-harness"` with `scheduler_backend: object | None = None`, and build it in `StatusContext.build` via `detect_backend(cfg.scheduler.backend)`.

In `views/cron.py` and `views/overview.py`, replace each `launchctl_loaded(full_label)` call with:

```python
        state, reason = ctx.scheduler_backend.job_state(label)
```

and render the three states distinctly — `UNKNOWN` gets `?` plus the dim reason, never `✗`.

- [ ] **Step 4: Run, then eyeball the real output**

```bash
uv run pytest -q
uv run lh status cron
uv run lh status overview
```
On macOS every job must still resolve to loaded or not-loaded. A `?` appearing here means backend detection broke.

- [ ] **Step 5: Commit**

```bash
git add src/lazy_harness/monitoring/views/ tests/unit/test_status_views_helpers.py
git commit -m "fix: report scheduler state as unknown instead of not-loaded when it cannot be checked"
```

---

### Task 7: `file_locked` via `fcntl`

**Files:**
- Modify: `src/lazy_harness/monitoring/views/_helpers.py:229`
- Test: `tests/unit/test_status_views_helpers.py`

- [ ] **Step 1: Write the failing test**

```python
def test_file_locked_detects_a_held_flock(tmp_path: Path) -> None:
    """Probes the same advisory lock compound_loop_worker.py:122 takes."""
    import fcntl

    from lazy_harness.monitoring.views._helpers import file_locked

    lock = tmp_path / ".worker.lock"
    lock.touch()
    fd = open(lock, "w")
    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    try:
        assert file_locked(lock) is True
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        fd.close()

    assert file_locked(lock) is False


def test_file_locked_is_false_for_a_missing_file(tmp_path: Path) -> None:
    from lazy_harness.monitoring.views._helpers import file_locked

    assert file_locked(tmp_path / "absent.lock") is False
```

- [ ] **Step 2: Run**

Expected: the first test may pass by accident if `lsof` is installed, which is exactly why the implementation must change. Confirm by running with `PATH=/nonexistent` — `lsof` becomes unreachable and the test fails.

- [ ] **Step 3: Reimplement**

```python
def file_locked(path: Path) -> bool:
    """Whether an advisory flock is held on `path`.

    Was a shell-out to `lsof`, which is absent on minimal Linux images and
    whose absence was read as 'not locked' — the dangerous direction, since
    the view then claims the worker is idle while it runs. This probes the
    same lock `compound_loop_worker.py` takes.
    """
    import fcntl

    if not path.is_file():
        return False
    try:
        with open(path, "a") as fd:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except (BlockingIOError, OSError):
                return True
            fcntl.flock(fd, fcntl.LOCK_UN)
    except OSError:
        return False
    return False
```

- [ ] **Step 4: Run both tests plus the suite, and commit**

```bash
uv run pytest tests/unit/test_status_views_helpers.py -v && uv run pytest -q
git add src/lazy_harness/monitoring/views/_helpers.py tests/unit/test_status_views_helpers.py
git commit -m "fix: detect the worker lock with fcntl instead of shelling out to lsof"
```

ADR-008 documents the `lsof` choice. Annotate it in this commit — the repo requires that fixing a safeguard updates its documented examples in the same change.

---

### Task 8: Wave 3 gate and PR

- [ ] `/tdd-check`, then push as `fix: report scheduler state as unknown instead of not-loaded when it cannot be checked`. Deploy grep string: `JobState`.

---

# Wave 4 — `feat/systemd-cron-backends`

Blocked by wave 3. Zero risk to macOS: `detect_backend` returns `LaunchdBackend` on Darwin and none of this code runs there.

## File Structure

| File | Responsibility |
|---|---|
| `src/lazy_harness/scheduler/schedule.py` | add `render_systemd`, `render_cron` |
| `src/lazy_harness/scheduler/systemd.py` | unit generation, install/uninstall, `job_state`, linger probe |
| `src/lazy_harness/scheduler/cron.py` | delimited crontab block |
| `src/lazy_harness/scheduler/paths.py` | **new** — `resolved_path()` shared by all three backends |
| `src/lazy_harness/selftest/checks/scheduler_check.py` | linger result |
| `.github/workflows/tests.yml` | macOS job |

### Task 9: `render_systemd` and `render_cron`

- [ ] **Step 1: Write the failing tests**

```python
@pytest.mark.parametrize(
    ("expr", "expected"),
    [
        ("0 10 * * *", "*-*-* 10:00:00"),
        ("30 3 * * 0", "Sun *-*-* 03:30:00"),
        ("0 */6 * * *", "*-*-* 0/6:00:00"),
        ("*/30 * * * *", "*-*-* *:0/30:00"),
        ("15 2 1 * *", "*-*-01 02:15:00"),
        ("0 9 * * 1-5", "Mon..Fri *-*-* 09:00:00"),
    ],
)
def test_render_systemd_oncalendar(expr: str, expected: str) -> None:
    from lazy_harness.scheduler.schedule import parse_cron, render_systemd

    assert render_systemd(parse_cron(expr)) == expected


def test_render_cron_is_the_expression_itself() -> None:
    """Cron is lossless by construction — the declaration is the native format."""
    from lazy_harness.scheduler.schedule import parse_cron, render_cron

    assert render_cron(parse_cron("0 9 * * 1-5")) == "0 9 * * 1-5"
```

Note that systemd expresses the weekday range launchd refuses. That asymmetry is the point of per-backend renderers.

- [ ] **Step 2: Run, confirm failure, implement, run again, commit.**

`render_cron` reassembles the five fields with spaces. `render_systemd` maps day-of-week digits and ranges to `Sun`/`Mon..Fri`, and renders `*/N` as `0/N` in the corresponding position.

### Task 10: `SystemdBackend`

- [ ] **Step 1: Test unit-file generation with an injected `unit_dir`, plus a parameter-less smoke test that the default resolves under `$XDG_CONFIG_HOME/systemd/user`.**

```python
def test_systemd_writes_a_service_and_a_timer(tmp_path: Path) -> None:
    import subprocess

    from lazy_harness.scheduler.base import SchedulerJob
    from lazy_harness.scheduler.systemd import SystemdBackend

    calls: list[list[str]] = []

    def runner(argv: list[str]):
        calls.append(argv)
        return subprocess.CompletedProcess(argv, 0, stdout="Linger=yes", stderr="")

    job = SchedulerJob(name="qmd-sync", schedule="0 */6 * * *", command="qmd sync")
    SystemdBackend(runner=runner, unit_dir=tmp_path).install([job])

    service = (tmp_path / "lazy-harness-qmd-sync.service").read_text()
    timer = (tmp_path / "lazy-harness-qmd-sync.timer").read_text()
    assert "Type=oneshot" in service
    assert "ExecStart=qmd sync" in service
    assert "OnCalendar=*-*-* 0/6:00:00" in timer
    assert "Persistent=true" in timer
    assert ["systemctl", "--user", "daemon-reload"] in calls
    assert ["systemctl", "--user", "enable", "--now", "lazy-harness-qmd-sync.timer"] in calls


def test_systemd_backend_constructs_without_arguments() -> None:
    from lazy_harness.scheduler.systemd import SystemdBackend

    backend = SystemdBackend()
    assert backend._unit_dir.name == "user"
    assert backend._runner is not None
```

- [ ] **Step 2: Test that `install` warns loudly when lingering is off.**

```python
def test_systemd_install_warns_when_lingering_is_disabled(tmp_path, capsys) -> None:
    """Without linger, user timers stop at logout and never fire on a headless box.

    `systemctl --user enable --now` still reports success, which is exactly
    why this has to be checked rather than assumed.
    """
    import subprocess

    from lazy_harness.scheduler.base import SchedulerJob
    from lazy_harness.scheduler.systemd import SystemdBackend

    def runner(argv: list[str]):
        if argv[0] == "loginctl":
            return subprocess.CompletedProcess(argv, 0, stdout="Linger=no", stderr="")
        return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")

    job = SchedulerJob(name="qmd-sync", schedule="0 3 * * *", command="qmd sync")
    SystemdBackend(runner=runner, unit_dir=tmp_path).install([job])

    out = capsys.readouterr().out
    assert "enable-linger" in out
```

- [ ] **Step 3: Implement, run, commit.**

### Task 11: `CronBackend`

- [ ] **Step 1: Test the delimited block round trip — install into an existing crontab that has the user's own entries, then uninstall, and assert the user's entries are byte-identical and the block is gone.**

```python
def test_cron_install_preserves_foreign_entries(tmp_path) -> None:
    import subprocess

    from lazy_harness.scheduler.base import SchedulerJob
    from lazy_harness.scheduler.cron import CronBackend

    existing = "0 4 * * * /home/me/backup.sh\n"
    written: list[str] = []

    def runner(argv: list[str], _input: str | None = None):
        if argv == ["crontab", "-l"]:
            return subprocess.CompletedProcess(argv, 0, stdout=existing, stderr="")
        written.append(_input or "")
        return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")

    job = SchedulerJob(name="qmd-sync", schedule="0 */6 * * *", command="qmd sync")
    CronBackend(runner=runner).install([job])

    result = written[-1]
    assert "/home/me/backup.sh" in result
    assert "# BEGIN lazy-harness" in result
    assert "# lazy-harness:qmd-sync" in result
    assert result.index("backup.sh") < result.index("# BEGIN lazy-harness")
```

The cron runner needs an `input` parameter that the launchd and systemd runners do not. Give `CronBackend` its own `CronRunner` type rather than widening the shared one — widening a type annotation requires auditing the body against every member of the new union, and here there is nothing to gain.

- [ ] **Step 2: Implement, run, commit.**

### Task 12: `resolved_path()` shared by all three backends

- [ ] Extract PATH resolution into `scheduler/paths.py`. It filters `os.environ["PATH"]` to existing directories and prepends `~/.local/bin` if absent — that is where `uv tool install` puts `lh`. Replace the hardcoded `/opt/homebrew/bin` string in `launchd.py:57`, the systemd `Environment=PATH=`, and the cron block's `PATH=` line with one call. Test that the result contains `~/.local/bin` and no nonexistent directory.

### Task 13: Linger check in selftest

- [ ] Add a `linger` result to `check_scheduler`, systemd only, jobs declared: `Linger=no` is `FAILED`. A machine whose scheduled jobs cannot fire is not healthy, and reporting it as a warning would let it pass unnoticed. Test both branches with an injected runner.

### Task 14: macOS in CI

- [ ] Add `macos-latest` to the `tests.yml` matrix on Python 3.13 only. Today the launchd backend has zero CI coverage on the platform it serves, and waves 2 and 3 both rewrote it.

```yaml
    strategy:
      matrix:
        include:
          - { os: ubuntu-latest, python-version: '3.11' }
          - { os: ubuntu-latest, python-version: '3.12' }
          - { os: ubuntu-latest, python-version: '3.13' }
          - { os: macos-latest,  python-version: '3.13' }
    runs-on: ${{ matrix.os }}
```

### Task 15: Documentation sweep

Six pages assert that only launchd installs jobs. Fixing the behaviour without fixing its documented examples leaves a false source of truth, and the repo requires both in the same change.

- [ ] `docs/index.md:14`, `docs/reference/cli.md:274-276`, `docs/getting-started/migrating.md:76`, `docs/how/metrics-ingest.md:134-142`, `docs/architecture/overview.md:171-172`, `README.md:53` and `README.md:196`.
- [ ] `specs/adrs/013-scheduler-unified-backends.md` — update the Implementation-status table to `shipped` for all three, keeping the historical note about the fabricated labels.
- [ ] `specs/backlog.md` — remove the "Implementar los backends systemd y cron" item and the launchd-translation item under ALTA.
- [ ] `uv run --group docs mkdocs build --strict` must pass.

### Task 16: Wave 4 gate, PR, and end-to-end verification on Linux

- [ ] **Step 1:** `/tdd-check`.
- [ ] **Step 2:** Push as `feat: implement the systemd and cron scheduler backends`. Deploy grep string: `render_systemd`.
- [ ] **Step 3: The acceptance criterion, on real machines.** CI cannot do this.

1. Workstation: `lh scheduler install`, then `systemctl --user list-timers` shows the declared interval.
2. Octavio or Marge over ssh with `Linger=no`: `install` warns, `lh selftest` fails the linger check.
3. `sudo loginctl enable-linger $USER`, reinstall, **log out entirely**, wait for the window, then `journalctl --user -u lazy-harness-<job>` shows it fired with nobody logged in.
4. A machine without `systemctl`: `detect_backend` picks cron, install works, `lh status cron` reports real state.
5. A machine without `crontab`: `job_state` returns `UNKNOWN` and the view renders `?`, not `✗`.

Step 3 is what distinguishes "systemctl said enabled" from "the job runs". Do not mark wave 4 complete without it.

---

## Self-review

**Spec coverage.** D1 → Task 5. D2 → Tasks 5, 6. D3 → Tasks 5, 10, 11. D4 → Tasks 1, 2, 3, 9. D5 → Task 10. D6 → Tasks 10, 13. D7 → Task 11. D8 → Task 7. D9 → Task 14. Category-3 cosmetics → Tasks 6, 12. Documentation consequences → Task 15.

**Placeholders.** Tasks 9–15 carry test code and exact file targets but compress the implement/run/commit cycle into single steps, because the pattern is established by Tasks 1–8 and repeating it six more times adds length without information. Every one still names its files, its test, and its acceptance.

**Type consistency.** `JobState` and `Runner` in `scheduler/base.py`; `job_state -> tuple[JobState, str]` on all three backends; `label_for(job) -> str`; `parse_cron -> Schedule`; `render_launchd -> dict[str, object]`; `render_systemd -> str`; `render_cron -> str`; `resolved_path() -> str`. `CronBackend` uses its own `CronRunner` because its runner takes `input`.

**Open risk.** Task 3 may find existing launchd tests that assert `StartInterval == 3600` for non-daily schedules. Those tests pin the defect. Delete them and name them in the commit message rather than adapting them.

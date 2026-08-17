# Linux parity: completing the scheduler backends and removing platform lies

**Status:** proposed
**Date:** 2026-08-17
**Relates to:** [ADR-013](../adrs/013-scheduler-unified-backends.md) (unified scheduler backends), [ADR-005](../adrs/005-xdg-first-paths.md) (XDG-first paths), [ADR-017](../adrs/017-selftest-as-health-check.md) (selftest as health check)

## Problem

The framework advertises macOS and Linux support. `README.md:196` and `docs/getting-started/install.md:13-14` both claim it. The test suite backs the claim more than the docs do: all 1338 tests run on `ubuntu-latest` and only on `ubuntu-latest` (`.github/workflows/tests.yml:19`). There is no macOS job at all.

So the framework is not "a macOS tool that needs porting". Path resolution (`core/paths.py`) is XDG-first with a Windows branch. Symlink deployment (`deploy/symlinks.py`) is portable. Advisory locking uses `fcntl.flock` (`knowledge/git_push.py:72`, `knowledge/compound_loop_worker.py:122`), which is POSIX and behaves identically on both platforms. Detached workers use `start_new_session=True`, not a macOS-specific mechanism.

What is actually broken splits into two categories, and the second is worse than the first.

### Category 1 — declared but unimplemented

ADR-013 chose one protocol and three backends. One backend exists.

| Backend | State |
|---|---|
| `LaunchdBackend` | ships — writes `.plist`, loads with `launchctl` |
| `SystemdBackend` | `install()` raises `NotImplementedError` (`scheduler/systemd.py:9`) |
| `CronBackend` | `install()` raises `NotImplementedError` (`scheduler/cron.py:9`) |

This is honest failure. `lh scheduler install` on Linux exits loudly, and ADR-013 already records the gap in its Implementation-status section. It is a hole, not a lie.

### Category 2 — reports success or failure it cannot know

Three defects report a confident answer that is wrong. These are the reason this work is worth doing beyond "fill in two files".

**2a. `launchctl_loaded` returns `False` for "I cannot check".**

`monitoring/views/_helpers.py:217` shells out to `launchctl list <label>` and catches `FileNotFoundError` by returning `False`. On Linux `launchctl` does not exist, so every scheduled job renders as not-loaded. `views/cron.py:95` and `views/overview.py:153` consume this directly and display it as a job state. A user on Octavio reading `lh status cron` sees a column of failures that describe the *checker's* absence, not the jobs'.

This is the failure shape the repo's own verification gates name: a tool's exit code is not proof of its effect, and here a missing tool is being read as a negative result.

**2b. The launchd cron translation silently rewrites schedules.**

`launchd.py:_cron_to_calendar` only recognises the strict daily form `M H * * *`. Everything else returns `None`, and the caller falls through to `_cron_to_interval`, whose default is `3600`. Measured against real expressions:

| `config.toml` schedule | Installed as | Error |
|---|---|---|
| `0 */6 * * *` | every 60 min | **6×** over-execution |
| `30 3 * * 0` (weekly) | every 60 min | **168×** over-execution |
| `0 10 * * 0` (weekly) | every 60 min | **168×** over-execution |
| `15 2 1 * *` (monthly) | every 60 min | **~720×** over-execution |
| `0 9 * * 1-5` (weekdays) | every 60 min | **~34×** over-execution, plus fires on weekends |
| `*/30 * * * *` | every 30 min | correct |
| `M H * * *` | daily at H:M | correct |

`0 */6 * * *` is the example ADR-013 uses in its own Decision section. Only two of the seven forms above translate correctly. Every other declared job runs hourly, and nothing in `lh status`, `lh selftest`, or `lh scheduler status` notices, because all three report on the *label* being loaded, never on the schedule matching what was declared.

This is a shipping defect on the one platform that is supposedly supported, and it is the strongest argument for doing this work now: adding a systemd backend that repeats the pattern would double it.

**2c. `file_locked` depends on `lsof`.**

`_helpers.py:229` determines whether the compound-loop worker lock is held by shelling out to `lsof`, catching `FileNotFoundError` and returning `False`. `lsof` is preinstalled on macOS and is *not* guaranteed on a minimal Linux VM or container. Same shape as 2a: absent tool reads as "not locked", which is the dangerous direction — the status view claims the worker is idle when it may be running.

The choice of `lsof` was deliberate; it replaced an mtime heuristic that was worse, and ADR-008 documents it. The point here is not that the choice was wrong, but that a portable option exists that beats both.

### Category 3 — cosmetic coupling

- `launchd.py:57` hardcodes `/opt/homebrew/bin` into the plist `PATH`. Harmless on Linux (the file is never written there) but it means the one place PATH is handled is macOS-shaped, and PATH is the single most common reason a scheduled job fails on any platform.
- `views/_helpers.py:40` carries `launchd_prefix: str = "com.lazy-harness"` on `StatusContext`. Reverse-DNS labelling is a launchd convention; systemd unit names and crontab tags do not use it. The status layer should not know the naming scheme of any backend.

## Non-goals

- **Windows.** `core/paths.py` branches for it and nothing else does. Out of scope, unchanged.
- **A framework daemon.** ADR-006 and ADR-008 both rejected a long-running process. The scheduler stays a thin wrapper over the OS scheduler.
- **Changing the cron-syntax-in-config decision.** ADR-013 chose cron expressions as the lingua franca. That holds; what changes is that translation failures become loud instead of silent.
- **Container support as a first-class target.** Both named deployment targets (a Linux workstation and the headless homelab servers) run systemd. `CronBackend` is built as the portable floor, not as an optimised container story.

## Design

### D1 — `JobState` as a three-valued answer

The protocol gains a method whose return type can express ignorance.

```python
class JobState(StrEnum):
    LOADED = "loaded"          # registered with the OS scheduler
    NOT_LOADED = "not_loaded"  # checked, and it is absent
    UNKNOWN = "unknown"        # this backend cannot introspect here
```

`UNKNOWN` is the whole point. A backend that cannot answer returns `UNKNOWN` with a reason string, and the views render it distinctly — `?` plus a dim explanation — never as a failure glyph. Category-2a defects become impossible to reintroduce, because there is no longer a way to spell "I could not check" as `False`.

`job_state` answers exactly one question: *is this job registered with the OS scheduler?* It deliberately does not answer "is it healthy" or "did it run recently" — those come from the metrics DB and the logs, and conflating them is how a status view starts lying again.

### D2 — Extended `SchedulerBackend` protocol

```python
@runtime_checkable
class SchedulerBackend(Protocol):
    def label_for(self, job: SchedulerJob) -> str: ...
    def install(self, jobs: list[SchedulerJob]) -> list[str]: ...
    def uninstall(self, jobs: list[SchedulerJob]) -> list[str]: ...
    def status(self) -> list[dict[str, str]]: ...
    def job_state(self, label: str) -> tuple[JobState, str]: ...
```

`label_for` moves label construction behind the seam. `StatusContext.launchd_prefix` is deleted; `StatusContext` gains a lazily-built `scheduler_backend`, and the views call `backend.label_for(job)` and `backend.job_state(label)`.

### D3 — A command-runner seam, because strict TDD requires one

`LaunchdBackend` calls `subprocess.run` at four sites directly (`launchd.py:77,78,89,105`). That makes `install`, `uninstall`, and `status` untestable without executing `launchctl` on the host, which is why they have no tests today.

Every backend takes an injectable runner:

```python
Runner = Callable[[list[str]], subprocess.CompletedProcess[str]]

class SystemdBackend:
    def __init__(self, *, runner: Runner | None = None, unit_dir: Path | None = None) -> None: ...
```

Defaults resolve to the real `subprocess.run` and the real unit directory. Tests inject a fake runner that records the argv it was handed and returns a scripted result. This is what makes the whole design testable under the repo's TDD rule; without it the new backends would ship as untested as the existing one.

The repo's CLI-test gate applies here: **each explicit-parameter test is paired with a parameter-less smoke test**, so the default-resolution path of `runner` and `unit_dir` is exercised too. Always injecting them would leave the defaults completely uncovered.

### D4 — Schedule translation that refuses rather than guesses

A single pure module, `scheduler/schedule.py`, parses a cron expression into a structured intermediate and each backend renders it natively.

```python
@dataclass(frozen=True)
class Schedule:
    minute: str
    hour: str
    day_of_month: str
    month: str
    day_of_week: str

class ScheduleTranslationError(Exception):
    """The expression is valid cron but this backend cannot express it."""

def parse_cron(expr: str) -> Schedule: ...
```

Each backend implements `render(schedule) -> str` (or a dict, for launchd) and raises `ScheduleTranslationError` when the expression has no faithful native form. **`install` propagates the error and installs nothing for that job.** Silently installing a different schedule is not an available outcome.

Coverage per backend:

| Form | systemd `OnCalendar` | launchd | cron |
|---|---|---|---|
| `M H * * *` | `*-*-* H:M:00` | `StartCalendarInterval` | verbatim |
| `*/N * * * *` | `*:0/N` | `StartInterval` | verbatim |
| `M H/N * * *` | `*-*-* H/N:M:00` | `StartCalendarInterval` list | verbatim |
| `M H * * D` (weekly) | `Dow *-*-* H:M:00` | `StartCalendarInterval` + `Weekday` | verbatim |
| `M H D * *` (monthly) | `*-*-D H:M:00` | `StartCalendarInterval` + `Day` | verbatim |
| ranges / lists / steps combined | `OnCalendar` handles most | **raises** | verbatim |

launchd is the weakest target — `StartCalendarInterval` accepts a list of dicts, which covers weekly and monthly, but not arbitrary ranges. Those raise. Cron is lossless by construction: the expression is the native format.

Fixing this is in scope for **this** design even though it is a macOS bug, because the systemd backend must not reproduce it and the shared parser is what prevents that.

### D5 — `SystemdBackend`

Unit files land in `$XDG_CONFIG_HOME/systemd/user/` (default `~/.config/systemd/user/`), named `lazy-harness-<job>.service` and `lazy-harness-<job>.timer`. Flat prefix, not reverse-DNS.

```ini
# lazy-harness-<job>.service
[Unit]
Description=lazy-harness job <job>

[Service]
Type=oneshot
ExecStart=<command>
Environment=PATH=<resolved PATH>
```

```ini
# lazy-harness-<job>.timer
[Unit]
Description=lazy-harness timer for <job>

[Timer]
OnCalendar=<rendered from Schedule>
Persistent=true

[Install]
WantedBy=timers.target
```

`Persistent=true` makes a missed run fire on next boot, which is the closest analogue to launchd's catch-up behaviour and matters on a workstation that sleeps.

- `install` → write units → `systemctl --user daemon-reload` → `systemctl --user enable --now <timer>`
- `uninstall` → `systemctl --user disable --now <timer>` → unlink both files → `daemon-reload`
- `job_state` → `systemctl --user is-active <timer>`; `active` → `LOADED`, `inactive`/`failed` → `NOT_LOADED`; `systemctl` absent, or exit indicating no DBus session → `UNKNOWN` with the reason

**PATH resolution.** The unit inherits nothing from a login shell. `Environment=PATH=` is built at install time by one helper shared with the launchd and cron backends, replacing the hardcoded `/opt/homebrew/bin` string in `launchd.py:57` so no backend guesses on its own.

The helper reads the platform, not the environment: `~/.local/bin` — where `uv tool install` puts `lh` — followed by the standard directories that exist, with `/opt/homebrew/bin` presence-gated so an Intel Mac, an Apple Silicon Mac and a Linux box need no separate code path.

An earlier revision built it from `os.environ["PATH"]` filtered to existing directories. That made a file read for months depend on which terminal generated it: from a developer's interactive shell it produced twenty-five entries with pyenv shims ahead of Homebrew, so a job's `python` resolved to a shim in a context with no shell to initialise it, while the same call over ssh produced five clean entries — which is why it looked correct when verified on Linux. A job needing anything outside the standard set declares the full path in its command, which the live configuration already does.

### D6 — Lingering is a verified precondition, not a footnote

On a headless server, `systemctl --user` units stop when the user's last session ends. Timers do not fire. `systemctl --user enable --now` still reports success. This is precisely the "exit code is not proof of effect" failure the repo has recorded, and on the named targets (ssh-only homelab servers) it is the default state, not an edge case.

Two mechanisms:

1. **`SystemdBackend.install` checks first.** It runs `loginctl show-user <user> --property=Linger`. If `Linger=no` and jobs are being installed, it prints a prominent warning naming the exact fix — `sudo loginctl enable-linger <user>` — and reports the jobs as installed-but-dormant rather than installed. It does not run the command itself: it requires root, and silently escalating privileges is not something an install step should do.
2. **`lh selftest` gains a `linger` check.** In the `scheduler` group, on systemd only, with jobs declared: `Linger=no` is `FAILED`, not a warning. A machine whose scheduled jobs cannot fire is not healthy, and selftest is the surface that is supposed to say so (ADR-017).

### D7 — `CronBackend`

The portable floor. Reads with `crontab -l`, writes with `crontab -`.

```
# BEGIN lazy-harness
PATH=<resolved PATH>
0 */6 * * * qmd update # lazy-harness:qmd_reindex
# END lazy-harness
```

- The block is delimited, so `uninstall` removes exactly what `install` wrote and never touches a user's own entries.
- Each line carries a `# lazy-harness:<name>` tag so a single job can be removed without rewriting the block.
- An explicit `PATH=` line inside the block, because cron's default PATH is `/usr/bin:/bin` and that is the most common reason a cron job fails.
- `crontab -l` exiting non-zero with "no crontab for user" is a normal empty state, not an error.
- `job_state` → the tag is present in the block → `LOADED`; absent → `NOT_LOADED`. Cron has no liveness concept, and that is a complete answer to the question `job_state` asks. If `crontab` itself is missing, `UNKNOWN`.

`uninstall` and `status` on both stub backends currently return empty lists while `install` raises — an asymmetry ADR-013 flagged as deliberate-for-now. Once both are implemented the asymmetry disappears on its own.

### D8 — Portable lock detection

`file_locked` stops shelling out. It opens the path and attempts `fcntl.flock(fd, LOCK_EX | LOCK_NB)`:

- `BlockingIOError` / `OSError` with `EAGAIN` or `EACCES` → the lock is held → `True`
- success → immediately `LOCK_UN` and close → `False`
- the file does not exist → `False`

No external binary, identical semantics on both platforms, and it probes the same advisory lock the worker actually takes (`compound_loop_worker.py:122`) rather than inferring from an open file descriptor. This is strictly better than both the `lsof` approach and the mtime heuristic that preceded it; the note in ADR-008 about `lsof` is superseded by this change and should be annotated when it lands.

### D9 — macOS enters CI

`tests.yml` gains a `macos-latest` job on a single Python version. Today the launchd backend has zero CI coverage, so the refactor described here — which touches it — would land unverified on the platform it serves.

The backends cannot be integration-tested in CI: GitHub runners have no systemd user session, and `launchctl` behaves differently in their environment. The split is:

- **Pure functions** (`parse_cron`, each backend's `render`, unit-file and plist generation, crontab block manipulation) — fully tested on both platforms. This is where the Category-2b defect lives, so this is where the tests matter most.
- **Subprocess layer** (`install` / `uninstall` / `job_state`) — tested with the injected fake runner from D3, asserting the exact argv. Same tests on both platforms.

## Verification

The repo's gate is explicit: assumptions about tool behaviour are verified end-to-end in the target context, and a green test suite is not that verification. Acceptance requires all of the following on a real machine, not in CI:

1. **Workstation (systemd, graphical session).** Declare a job with a non-daily schedule (`0 */6 * * *`). `lh scheduler install`. Confirm `systemctl --user list-timers` shows the *declared* interval, not hourly. Confirm `lh status cron` shows `loaded`.
2. **Headless (Octavio or Marge, ssh only).** With `Linger=no`: confirm `install` warns, and `lh selftest` fails the `linger` check. Enable lingering, reinstall, **log out entirely**, and confirm from `journalctl --user -u lazy-harness-<job>` that the job fired while nobody was logged in. This is the step that distinguishes "systemctl said enabled" from "the job runs".
3. **macOS regression.** Re-install the existing declared jobs and confirm from the generated plists that non-daily schedules now translate correctly — and record which previously-installed jobs were running hourly, since those have been over-executing.
4. **Degradation.** On a machine without `systemctl`, confirm `detect_backend` selects cron, install works, and `lh status cron` reports real state. On a machine without `crontab`, confirm `job_state` reports `UNKNOWN` and the view renders `?`, not `✗`.

## Consequences

- ADR-013's Implementation-status table closes. The ADR is annotated, not superseded — the plugin-over-protocol decision was correct and is being completed, exactly as that ADR anticipated.
- The Category-2b fix changes behaviour for existing macOS users: jobs that were quietly running hourly will start running on their declared schedule. That is the intended correction, but it is a behaviour change on upgrade and belongs in the release notes as such.
- `docs/index.md:14`, `docs/reference/cli.md:274-276`, `docs/getting-started/migrating.md:76`, `docs/how/metrics-ingest.md:134-142`, `docs/architecture/overview.md:171-172` and `README.md:53` all state that only launchd installs jobs. Every one of them is updated in the same change. The repo's gate on this is specific: fixing a safeguard updates its documented examples *and* every diagnostic that reports on it, in the same commit.
- `specs/backlog.md` loses its "Implementar los backends systemd y cron" item under Prioridad MEDIA.
- Adding Windows Task Scheduler later is now a fourth `render` implementation plus a `detect_backend` branch, with the schedule parser already shared.

## Sequencing

This design is independent of the capability-registry and TUI work and can ship first. Internally it is ordered so the riskiest correction is validated before anything is built on it:

1. `scheduler/schedule.py` — parser plus the three renderers, pure, fully tested. Fixes Category 2b.
2. Runner seam retrofitted onto `LaunchdBackend`, existing behaviour pinned by new tests.
3. `JobState` + `job_state` across all three backends; delete `launchctl_loaded`; rewire `views/cron.py` and `views/overview.py`; drop `StatusContext.launchd_prefix`.
4. `SystemdBackend` install/uninstall, plus the linger check and its selftest result.
5. `CronBackend`.
6. `file_locked` via `flock`.
7. macOS CI job; documentation sweep.

"""macOS LaunchAgents scheduler backend."""

from __future__ import annotations

import plistlib
import subprocess
from collections.abc import Callable
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from lazy_harness.scheduler.base import DriftState, JobDrift, JobRecord, JobState, SchedulerJob
from lazy_harness.scheduler.paths import resolved_path
from lazy_harness.scheduler.schedule import (
    ScheduleTranslationError,
    parse_cron,
    render_launchd,
)


def _default_runner(argv: list[str]) -> subprocess.CompletedProcess[bytes]:
    """Run `argv` and return the result.

    Returning matters: `job_state` reads the exit status, so a runner that
    returns None makes every job report UNKNOWN — the same non-answer the
    three-valued state exists to avoid, just from the other direction.
    """
    return subprocess.run(argv, capture_output=True, timeout=10)


_WEEKDAYS = ("Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat")


def _clock(entry: dict) -> str:
    return f"{entry.get('Hour', 0):02d}:{entry.get('Minute', 0):02d}"


def _describe_entry(entry: dict) -> str:
    """Name a StartCalendarInterval entry by the keys it actually carries.

    An absent key means "every", so Weekday and Day are what make an entry
    weekly or monthly. Reading only Hour and Minute reported every shape as
    `daily`, including the weekly and monthly ones.
    """
    if "Weekday" in entry:
        day = _WEEKDAYS[entry["Weekday"] % 7]
        return f"weekly {day} {_clock(entry)}"
    if "Day" in entry:
        return f"monthly day {entry['Day']} {_clock(entry)}"
    if "Hour" not in entry:
        return f"hourly :{entry.get('Minute', 0):02d}"
    return f"daily {_clock(entry)}"


def format_schedule(plist_file: Path) -> str:
    """Render a launchd plist's schedule as a short human string.

    Lives here rather than in the status view: parsing a plist is launchd's
    business, and a view that does it cannot report on any other backend."""
    if not plist_file.is_file():
        return "—"
    try:
        with open(plist_file, "rb") as f:
            data = plistlib.load(f)
    except (OSError, plistlib.InvalidFileException):
        return "—"
    interval = data.get("StartInterval")
    if isinstance(interval, int):
        if interval < 3600:
            return f"every {interval // 60}m"
        if interval < 86400:
            return f"every {interval // 3600}h"
        return f"every {interval // 86400}d"
    cal = data.get("StartCalendarInterval")
    if isinstance(cal, dict):
        return _describe_entry(cal)
    if isinstance(cal, list):
        first = cal[0] if cal else {}
        n = len(cal)
        # Which key varies across the entries is what the list means. Reading
        # the length alone reported an hour list as a weekday count.
        if n > 1 and "Hour" in first and len({e.get("Hour") for e in cal}) == n:
            return f"{n}x/day {_clock(first)}"
        if n > 1 and len({e.get("Minute") for e in cal}) == n and "Hour" not in first:
            return f"{n}x/hour :{first.get('Minute', 0):02d}"
        if n > 1 and len({e.get("Weekday") for e in cal}) == n:
            return f"{n}x/week {_clock(first)}"
        return _describe_entry(first)
    return "—"


class LaunchdBackend:
    def __init__(
        self,
        label_prefix: str = "com.lazy-harness",
        *,
        agents_dir: Path | None = None,
        runner: Callable[[list[str]], object] | None = None,
        timezone: str | None = None,
    ) -> None:
        self._prefix = label_prefix
        self._agents_dir = agents_dir or Path.home() / "Library" / "LaunchAgents"
        self._runner = runner or _default_runner
        self._timezone = timezone

    @staticmethod
    def _local_utcoffset() -> timedelta:
        """This machine's current offset from UTC."""
        return datetime.now().astimezone().utcoffset() or timedelta(0)

    def _check_timezone(self) -> None:
        """Refuse a declared zone this machine does not currently observe.

        launchd reads `StartCalendarInterval` in local time and has no key to
        override it, so a zone it does not share cannot be expressed — only
        approximated, which is what `schedule.py` exists to refuse.

        Offsets are compared, not names: the config names an IANA zone and the
        OS reports an abbreviation. Comparing at install time means a zone that
        agrees today and diverges under DST passes here; the shared config this
        guard was written for names a zone without DST, and a false accept in
        that direction is still louder than the silent one it replaces.
        """
        if not self._timezone:
            return
        try:
            declared = datetime.now(ZoneInfo(self._timezone)).utcoffset() or timedelta(0)
        except (ZoneInfoNotFoundError, ValueError) as e:
            raise ScheduleTranslationError(
                f"[scheduler] timezone={self._timezone!r} is not a known zone"
            ) from e
        if declared != self._local_utcoffset():
            raise ScheduleTranslationError(
                f"[scheduler] timezone={self._timezone!r} is not this machine's zone, "
                "and launchd reads its schedules in local time with no way to override it. "
                "Declare the jobs under a backend that can express the zone, or drop the key."
            )

    def label_for(self, job: SchedulerJob) -> str:
        return f"{self._prefix}.{job.name}"

    def generate_plist(self, job: SchedulerJob, output_dir: Path) -> Path:
        label = self.label_for(job)
        cmd_parts = job.command.split()
        log_dir = Path.home() / ".local" / "share" / "lazy-harness" / "logs"
        plist: dict = {
            "Label": label,
            "ProgramArguments": cmd_parts,
            "RunAtLoad": True,
            "StandardOutPath": str(log_dir / f"{job.name}-stdout.log"),
            "StandardErrorPath": str(log_dir / f"{job.name}-stderr.log"),
            "EnvironmentVariables": {"PATH": resolved_path()},
        }
        # Raises rather than approximating: installing a schedule other than
        # the one declared is what made every non-daily job run hourly.
        plist.update(render_launchd(parse_cron(job.schedule)))
        plist_path = output_dir / f"{label}.plist"
        with open(plist_path, "wb") as f:
            plistlib.dump(plist, f)
        return plist_path

    def install(self, jobs: list[SchedulerJob]) -> list[str]:
        """Install every job, or none of them.

        Translation is validated for the whole set before anything is written.
        Writing as it went left a half-installed set behind whenever one job
        could not be translated — the earlier jobs loaded, the later ones
        untouched, and nothing reported which.
        """
        self._check_timezone()
        for job in jobs:
            try:
                render_launchd(parse_cron(job.schedule))
            except ScheduleTranslationError as e:
                raise ScheduleTranslationError(f"job {job.name!r}: {e}") from e

        self._agents_dir.mkdir(parents=True, exist_ok=True)
        installed: list[str] = []
        for job in jobs:
            plist_path = self.generate_plist(job, self._agents_dir)
            label = self.label_for(job)
            self._runner(["launchctl", "unload", str(plist_path)])
            self._runner(["launchctl", "load", str(plist_path)])
            installed.append(label)
        return installed

    def uninstall(self, jobs: list[SchedulerJob]) -> list[str]:
        agents_dir = self._agents_dir
        removed: list[str] = []
        for job in jobs:
            label = self.label_for(job)
            plist_path = agents_dir / f"{label}.plist"
            if plist_path.is_file():
                self._runner(["launchctl", "unload", str(plist_path)])
                plist_path.unlink()
                removed.append(label)
        return removed

    def drift(self, jobs: list[SchedulerJob]) -> list[JobDrift]:
        """Compare each installed plist against what this version would write.

        Generated into a temporary directory and compared as parsed plists
        rather than as bytes: `plistlib` is free to order keys or format the
        XML differently between releases, and a diagnostic that reports every
        job stale on a formatting change is worse than none.
        """
        import tempfile

        out: list[JobDrift] = []
        for job in jobs:
            installed = self._agents_dir / f"{self.label_for(job)}.plist"
            if not installed.is_file():
                out.append(JobDrift(job.name, DriftState.ABSENT))
                continue
            try:
                with tempfile.TemporaryDirectory() as tmp:
                    expected = plistlib.loads(self.generate_plist(job, Path(tmp)).read_bytes())
                actual = plistlib.loads(installed.read_bytes())
            except Exception as e:  # noqa: BLE001 — cannot render or cannot read
                out.append(JobDrift(job.name, DriftState.UNKNOWN, f"{type(e).__name__}: {e}"))
                continue
            differing = sorted(
                k for k in set(expected) | set(actual) if expected.get(k) != actual.get(k)
            )
            out.append(
                JobDrift(job.name, DriftState.STALE, ", ".join(differing))
                if differing
                else JobDrift(job.name, DriftState.CURRENT)
            )
        return out

    def list_jobs(self, search_dir: Path | None = None) -> list[str]:
        agents_dir = search_dir or self._agents_dir
        if not agents_dir.is_dir():
            return []
        return [f.stem for f in agents_dir.glob(f"{self._prefix}.*.plist")]

    def job_state(self, label: str) -> tuple[JobState, str]:
        """Whether launchd has this label loaded, or UNKNOWN with the reason."""
        try:
            proc = self._runner(["launchctl", "list", label])
        except OSError as e:
            # FileNotFoundError is an OSError, so one clause covers both the
            # missing binary and every other exec failure.
            return JobState.UNKNOWN, f"launchctl unavailable: {e}"
        except subprocess.TimeoutExpired:
            return JobState.UNKNOWN, "launchctl timed out"
        except Exception as e:  # noqa: BLE001
            # The runner is an injection point. Anything it raises degrades to
            # UNKNOWN rather than crashing `lh status cron`, which is a
            # read-only view and has no business propagating a failure.
            return JobState.UNKNOWN, f"launchctl probe failed: {type(e).__name__}: {e}"
        code = getattr(proc, "returncode", None)
        if code is None:
            return JobState.UNKNOWN, "launchctl produced no exit status"
        return (JobState.LOADED if code == 0 else JobState.NOT_LOADED), ""

    def discover(self) -> list[JobRecord]:
        """Every job this backend manages on this machine."""
        if not self._agents_dir.is_dir():
            return []
        records: list[JobRecord] = []
        for plist_file in sorted(self._agents_dir.glob(f"{self._prefix}.*.plist")):
            label = plist_file.stem
            state, detail = self.job_state(label)
            records.append(
                JobRecord(
                    name=label[len(self._prefix) + 1 :],
                    label=label,
                    schedule=format_schedule(plist_file),
                    state=state,
                    detail=detail,
                )
            )
        return records

    def status(self) -> list[dict[str, str]]:
        jobs = self.list_jobs()
        result: list[dict[str, str]] = []
        for label in jobs:
            try:
                proc = subprocess.run(["launchctl", "list", label], capture_output=True, text=True)
                st = "loaded" if proc.returncode == 0 else "not loaded"
            except (FileNotFoundError, OSError):
                st = "unknown"
            result.append({"label": label, "status": st})
        return result

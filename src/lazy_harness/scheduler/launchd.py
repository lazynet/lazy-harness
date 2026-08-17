"""macOS LaunchAgents scheduler backend."""

from __future__ import annotations

import plistlib
import subprocess
from collections.abc import Callable
from pathlib import Path

from lazy_harness.scheduler.base import SchedulerJob
from lazy_harness.scheduler.schedule import (
    ScheduleTranslationError,
    parse_cron,
    render_launchd,
)


def _default_runner(argv: list[str]) -> None:
    subprocess.run(argv, capture_output=True)


class LaunchdBackend:
    def __init__(
        self,
        label_prefix: str = "com.lazy-harness",
        *,
        agents_dir: Path | None = None,
        runner: Callable[[list[str]], object] | None = None,
    ) -> None:
        self._prefix = label_prefix
        self._agents_dir = agents_dir or Path.home() / "Library" / "LaunchAgents"
        self._runner = runner or _default_runner

    def _label(self, job: SchedulerJob) -> str:
        return f"{self._prefix}.{job.name}"

    def generate_plist(self, job: SchedulerJob, output_dir: Path) -> Path:
        label = self._label(job)
        cmd_parts = job.command.split()
        log_dir = Path.home() / ".local" / "share" / "lazy-harness" / "logs"
        plist: dict = {
            "Label": label,
            "ProgramArguments": cmd_parts,
            "RunAtLoad": True,
            "StandardOutPath": str(log_dir / f"{job.name}-stdout.log"),
            "StandardErrorPath": str(log_dir / f"{job.name}-stderr.log"),
            "EnvironmentVariables": {
                "PATH": f"{Path.home()}/.local/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"
            },
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
        for job in jobs:
            try:
                render_launchd(parse_cron(job.schedule))
            except ScheduleTranslationError as e:
                raise ScheduleTranslationError(f"job {job.name!r}: {e}") from e

        self._agents_dir.mkdir(parents=True, exist_ok=True)
        installed: list[str] = []
        for job in jobs:
            plist_path = self.generate_plist(job, self._agents_dir)
            label = self._label(job)
            self._runner(["launchctl", "unload", str(plist_path)])
            self._runner(["launchctl", "load", str(plist_path)])
            installed.append(label)
        return installed

    def uninstall(self, jobs: list[SchedulerJob]) -> list[str]:
        agents_dir = self._agents_dir
        removed: list[str] = []
        for job in jobs:
            label = self._label(job)
            plist_path = agents_dir / f"{label}.plist"
            if plist_path.is_file():
                self._runner(["launchctl", "unload", str(plist_path)])
                plist_path.unlink()
                removed.append(label)
        return removed

    def list_jobs(self, search_dir: Path | None = None) -> list[str]:
        agents_dir = search_dir or self._agents_dir
        if not agents_dir.is_dir():
            return []
        return [f.stem for f in agents_dir.glob(f"{self._prefix}.*.plist")]

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

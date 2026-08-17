"""macOS LaunchAgents scheduler backend."""

from __future__ import annotations

import plistlib
import subprocess
from pathlib import Path

from lazy_harness.scheduler.base import SchedulerJob
from lazy_harness.scheduler.schedule import parse_cron, render_launchd


class LaunchdBackend:
    def __init__(self, label_prefix: str = "com.lazy-harness") -> None:
        self._prefix = label_prefix

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
        agents_dir = Path.home() / "Library" / "LaunchAgents"
        agents_dir.mkdir(parents=True, exist_ok=True)
        installed: list[str] = []
        for job in jobs:
            plist_path = self.generate_plist(job, agents_dir)
            label = self._label(job)
            subprocess.run(["launchctl", "unload", str(plist_path)], capture_output=True)
            subprocess.run(["launchctl", "load", str(plist_path)], capture_output=True)
            installed.append(label)
        return installed

    def uninstall(self, jobs: list[SchedulerJob]) -> list[str]:
        agents_dir = Path.home() / "Library" / "LaunchAgents"
        removed: list[str] = []
        for job in jobs:
            label = self._label(job)
            plist_path = agents_dir / f"{label}.plist"
            if plist_path.is_file():
                subprocess.run(["launchctl", "unload", str(plist_path)], capture_output=True)
                plist_path.unlink()
                removed.append(label)
        return removed

    def list_jobs(self, search_dir: Path | None = None) -> list[str]:
        agents_dir = search_dir or Path.home() / "Library" / "LaunchAgents"
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

"""macOS LaunchAgents scheduler backend."""

from __future__ import annotations

import plistlib
import re
import subprocess
from pathlib import Path

from lazy_harness.scheduler.base import SchedulerJob


def _cron_to_interval(cron_expr: str) -> int:
    parts = cron_expr.strip().split()
    if len(parts) < 5:
        return 3600
    minute_part = parts[0]
    match = re.match(r"\*/(\d+)", minute_part)
    if match:
        return int(match.group(1)) * 60
    if minute_part == "0" and parts[1] == "*":
        return 3600
    return 3600


def _cron_to_calendar(cron_expr: str) -> dict[str, int] | None:
    """Convert `M H * * *` → StartCalendarInterval dict. Returns None if not daily."""
    parts = cron_expr.strip().split()
    if len(parts) < 5:
        return None
    minute, hour, dom, mon, dow = parts[:5]
    if not minute.isdigit() or not hour.isdigit():
        return None
    if dom != "*" or mon != "*" or dow != "*":
        return None
    return {"Hour": int(hour), "Minute": int(minute)}


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
        calendar = _cron_to_calendar(job.schedule)
        if calendar is not None:
            plist["StartCalendarInterval"] = calendar
        else:
            plist["StartInterval"] = _cron_to_interval(job.schedule)
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

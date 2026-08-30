"""Scheduler manager — auto-detect backend + parse jobs from config."""

from __future__ import annotations

import platform
import shutil

from lazy_harness.core.config import Config
from lazy_harness.scheduler.base import SchedulerJob
from lazy_harness.scheduler.cron import CronBackend
from lazy_harness.scheduler.launchd import LaunchdBackend
from lazy_harness.scheduler.systemd import SystemdBackend


def detect_backend(
    override: str | None = None, timezone: str | None = None
) -> LaunchdBackend | SystemdBackend | CronBackend:
    """The backend for this machine, carrying the zone its units are read in.

    `timezone` reaches systemd only. launchd and cron read their schedules in
    the machine's local zone with no way to say otherwise, so passing it to
    them would be an approximation — the class of defect `schedule.py` exists
    to refuse. `LaunchdBackend` rejects a mismatching zone at install instead.

    Every call site resolves it from `cfg.scheduler.timezone`, because a
    backend built without it renders a bare `OnCalendar=` and reports the unit
    it just wrote as drifted.
    """
    if override and override != "auto":
        if override == "systemd":
            return SystemdBackend(timezone=timezone)
        if override == "launchd":
            return LaunchdBackend(timezone=timezone)
        if override == "cron":
            return CronBackend()
    system = platform.system()
    if system == "Darwin":
        return LaunchdBackend(timezone=timezone)
    if system == "Linux":
        if shutil.which("systemctl"):
            return SystemdBackend(timezone=timezone)
        return CronBackend()
    return CronBackend()


def parse_jobs_from_config(cfg: Config) -> list[SchedulerJob]:
    return [
        SchedulerJob(name=j.name, schedule=j.schedule, command=j.command)
        for j in cfg.scheduler.jobs
    ]

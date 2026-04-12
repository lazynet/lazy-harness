"""Scheduler manager — auto-detect backend + parse jobs from config."""

from __future__ import annotations

import platform
import shutil

from lazy_harness.core.config import Config
from lazy_harness.scheduler.base import SchedulerJob
from lazy_harness.scheduler.cron import CronBackend
from lazy_harness.scheduler.launchd import LaunchdBackend
from lazy_harness.scheduler.systemd import SystemdBackend


def detect_backend(override: str | None = None) -> LaunchdBackend | SystemdBackend | CronBackend:
    if override and override != "auto":
        backends: dict[str, type[LaunchdBackend | SystemdBackend | CronBackend]] = {
            "launchd": LaunchdBackend,
            "systemd": SystemdBackend,
            "cron": CronBackend,
        }
        cls = backends.get(override)
        if cls:
            return cls()
    system = platform.system()
    if system == "Darwin":
        return LaunchdBackend()
    if system == "Linux":
        if shutil.which("systemctl"):
            return SystemdBackend()
        return CronBackend()
    return CronBackend()


def parse_jobs_from_config(cfg: Config) -> list[SchedulerJob]:
    return []

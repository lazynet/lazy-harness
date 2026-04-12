"""Cron scheduler backend (fallback stub for v1)."""

from __future__ import annotations

from lazy_harness.scheduler.base import SchedulerJob


class CronBackend:
    def install(self, jobs: list[SchedulerJob]) -> list[str]:
        return [f"cron-{j.name}" for j in jobs]

    def uninstall(self, jobs: list[SchedulerJob]) -> list[str]:
        return []

    def status(self) -> list[dict[str, str]]:
        return []

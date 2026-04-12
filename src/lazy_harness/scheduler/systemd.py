"""Linux systemd timers scheduler backend (stub for v1)."""

from __future__ import annotations

from lazy_harness.scheduler.base import SchedulerJob


class SystemdBackend:
    def install(self, jobs: list[SchedulerJob]) -> list[str]:
        return [f"lazy-harness-{j.name}" for j in jobs]

    def uninstall(self, jobs: list[SchedulerJob]) -> list[str]:
        return []

    def status(self) -> list[dict[str, str]]:
        return []

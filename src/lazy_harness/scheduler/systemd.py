"""Linux systemd timers scheduler backend (stub for v1)."""

from __future__ import annotations

from lazy_harness.scheduler.base import SchedulerJob


class SystemdBackend:
    def install(self, jobs: list[SchedulerJob]) -> list[str]:
        raise NotImplementedError(
            "systemd scheduler backend is not implemented yet; only the launchd "
            "(macOS) backend installs jobs. Install jobs manually until systemd support lands."
        )

    def uninstall(self, jobs: list[SchedulerJob]) -> list[str]:
        return []

    def status(self) -> list[dict[str, str]]:
        return []

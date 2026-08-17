"""Cron scheduler backend (fallback stub for v1)."""

from __future__ import annotations

from lazy_harness.scheduler.base import JobRecord, JobState, SchedulerJob


class CronBackend:
    def install(self, jobs: list[SchedulerJob]) -> list[str]:
        raise NotImplementedError(
            "cron scheduler backend is not implemented yet; only the launchd "
            "(macOS) backend installs jobs. Install jobs manually until cron support lands."
        )

    def uninstall(self, jobs: list[SchedulerJob]) -> list[str]:
        return []

    def status(self) -> list[dict[str, str]]:
        return []

    def label_for(self, job: SchedulerJob) -> str:
        return f'lazy-harness-{job.name}'

    def job_state(self, label: str) -> tuple[JobState, str]:
        return JobState.UNKNOWN, 'backend not implemented'

    def discover(self) -> list[JobRecord]:
        return []

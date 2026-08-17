"""Crontab scheduler backend — the portable floor.

Entries live inside a delimited block so `uninstall` removes exactly what
`install` wrote and never touches the user's own lines. Cron is lossless by
construction: the expression declared in `config.toml` is already the native
format, so nothing is translated.
"""

from __future__ import annotations

import subprocess
from collections.abc import Callable

from lazy_harness.scheduler.base import JobRecord, JobState, SchedulerJob
from lazy_harness.scheduler.paths import resolved_path
from lazy_harness.scheduler.schedule import parse_cron, render_cron

# The runner takes `input` because writing a crontab means piping to
# `crontab -`. Widening the other backends' Runner to match would advertise a
# parameter they neither accept nor need.
CronRunner = Callable[..., "subprocess.CompletedProcess[str]"]

BEGIN = "# BEGIN lazy-harness"
END = "# END lazy-harness"
TAG = "# lazy-harness:"


def _default_runner(argv: list[str], *, input: str | None = None):  # noqa: A002
    return subprocess.run(argv, capture_output=True, text=True, timeout=10, input=input)


class CronBackend:
    def __init__(self, *, runner: CronRunner | None = None) -> None:
        self._runner = runner or _default_runner

    def label_for(self, job: SchedulerJob) -> str:
        return f"lazy-harness-{job.name}"

    def _read(self) -> str | None:
        """The current crontab, or None if crontab itself is unreachable.

        `crontab -l` exits non-zero with "no crontab for user" when the user
        has none. That is an empty crontab, not a failure.
        """
        try:
            proc = self._runner(["crontab", "-l"])
        except (OSError, subprocess.TimeoutExpired):
            # An absent or hung `crontab` is a state, not a crash. Narrow on
            # purpose: a blanket `except Exception` here also swallowed the
            # test-suite guard that catches a test reaching the real crontab,
            # turning a precise assertion into a generic RuntimeError.
            return None
        return getattr(proc, "stdout", "") or ""

    def _write(self, content: str) -> None:
        self._runner(["crontab", "-"], input=content)

    @staticmethod
    def _strip_block(content: str) -> str:
        lines = content.splitlines()
        out: list[str] = []
        inside = False
        for line in lines:
            if line.strip() == BEGIN:
                inside = True
                continue
            if line.strip() == END:
                inside = False
                continue
            if not inside:
                out.append(line)
        return "\n".join(out).rstrip("\n")

    def install(self, jobs: list[SchedulerJob]) -> list[str]:
        existing = self._read()
        if existing is None:
            raise RuntimeError("crontab is not available on this machine")

        block = [BEGIN, f"PATH={resolved_path()}"]
        installed: list[str] = []
        for job in jobs:
            schedule = render_cron(parse_cron(job.schedule))
            block.append(f"{schedule} {job.command} {TAG}{job.name}")
            installed.append(self.label_for(job))
        block.append(END)

        preserved = self._strip_block(existing)
        parts = [p for p in (preserved, "\n".join(block)) if p]
        self._write("\n".join(parts) + "\n")
        return installed

    def uninstall(self, jobs: list[SchedulerJob]) -> list[str]:
        existing = self._read()
        if existing is None:
            return []
        wanted = {job.name for job in jobs}
        present = {name for name, _, _ in self._entries(existing)}
        removed = [self.label_for(job) for job in jobs if job.name in present]
        if not removed:
            return []

        kept = [
            f"{schedule} {command} {TAG}{name}"
            for name, schedule, command in self._entries(existing)
            if name not in wanted
        ]
        preserved = self._strip_block(existing)
        if kept:
            block = "\n".join([BEGIN, f"PATH={resolved_path()}", *kept, END])
            parts = [p for p in (preserved, block) if p]
        else:
            parts = [p for p in (preserved,) if p]
        self._write(("\n".join(parts) + "\n") if parts else "")
        return removed

    @staticmethod
    def _entries(content: str) -> list[tuple[str, str, str]]:
        """Every managed entry as (name, schedule, command)."""
        found: list[tuple[str, str, str]] = []
        inside = False
        for line in content.splitlines():
            stripped = line.strip()
            if stripped == BEGIN:
                inside = True
                continue
            if stripped == END:
                inside = False
                continue
            if not inside or TAG not in stripped:
                continue
            body, _, name = stripped.partition(TAG)
            fields = body.split()
            if len(fields) < 6:
                continue
            found.append((name.strip(), " ".join(fields[:5]), " ".join(fields[5:])))
        return found

    def job_state(self, label: str) -> tuple[JobState, str]:
        """Whether the entry is registered.

        Cron has no liveness concept, so presence in the crontab is a complete
        answer to the question `job_state` asks — not a proxy for one.
        """
        content = self._read()
        if content is None:
            return JobState.UNKNOWN, "crontab unavailable on this machine"
        name = label[len("lazy-harness-") :] if label.startswith("lazy-harness-") else label
        present = any(entry_name == name for entry_name, _, _ in self._entries(content))
        return (JobState.LOADED if present else JobState.NOT_LOADED), ""

    def discover(self) -> list[JobRecord]:
        content = self._read()
        if content is None:
            return []
        return [
            JobRecord(
                name=name,
                label=f"lazy-harness-{name}",
                schedule=schedule,
                state=JobState.LOADED,
            )
            for name, schedule, _command in self._entries(content)
        ]

    def status(self) -> list[dict[str, str]]:
        return [{"label": r.label, "status": r.state.value} for r in self.discover()]

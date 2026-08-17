"""Crontab scheduler backend — the portable floor.

Entries live inside a delimited block so `uninstall` removes exactly what
`install` wrote and never touches the user's own lines. Cron is lossless by
construction: the expression declared in `config.toml` is already the native
format, so nothing is translated.
"""

from __future__ import annotations

import subprocess
from collections.abc import Callable

from lazy_harness.scheduler.base import (
    DriftState,
    JobDrift,
    JobRecord,
    JobState,
    SchedulerJob,
)
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
        """Write the crontab and raise on rejection.

        Discarding the exit code let `install` return every label while the
        crontab was refused — a green tick per job with nothing installed.
        """
        proc = self._runner(["crontab", "-"], input=content)
        code = getattr(proc, "returncode", 0)
        if code:
            err = (getattr(proc, "stderr", "") or "").strip() or f"exit {code}"
            raise RuntimeError(f"crontab write failed: {err}")

    @staticmethod
    def _existing_path_line(content: str) -> str | None:
        """The PATH line the previous `install` wrote, if the block has one."""
        inside = False
        for line in content.splitlines():
            stripped = line.strip()
            if stripped == BEGIN:
                inside = True
                continue
            if stripped == END:
                break
            if inside and stripped.startswith("PATH="):
                return stripped
        return None

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
            # Reuse the PATH `install` computed rather than re-deriving it.
            # Removing one job is not an occasion to rewrite the others: the
            # block may have been written by an older version of this tool, or
            # on a machine whose standard directories differ, and either way
            # the surviving entries keep the PATH they were installed with.
            path_line = self._existing_path_line(existing) or f"PATH={resolved_path()}"
            block = "\n".join([BEGIN, path_line, *kept, END])
            parts = [p for p in (preserved, block) if p]
        else:
            parts = [p for p in (preserved,) if p]
        self._write(("\n".join(parts) + "\n") if parts else "")
        return removed

    @staticmethod
    def _managed_lines(content: str) -> dict[str, str]:
        """Every managed entry as name -> the exact line in the crontab.

        Kept verbatim because `drift` compares against the line `install`
        wrote. Splitting and re-joining on single spaces — which is what
        `_entries` does, correctly, for its own callers — turns a command
        holding a tab or a doubled space into a different string, so a job
        nobody touched compares unequal to itself.
        """
        found: dict[str, str] = {}
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
            _, _, name = stripped.partition(TAG)
            found[name.strip()] = stripped
        return found

    @classmethod
    def _entries(cls, content: str) -> list[tuple[str, str, str]]:
        """Every managed entry as (name, schedule, command)."""
        found: list[tuple[str, str, str]] = []
        for name, line in cls._managed_lines(content).items():
            body, _, _ = line.partition(TAG)
            fields = body.split()
            if len(fields) < 6:
                continue
            found.append((name, " ".join(fields[:5]), " ".join(fields[5:])))
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

    def drift(self, jobs: list[SchedulerJob]) -> list[JobDrift]:
        """Compare each managed entry, and the block's PATH, against this version.

        PATH is written once for the whole block, so a job whose own line is
        untouched still runs with an environment the current generator would
        not produce. That counts as stale for every job in the block.
        """
        content = self._read()
        if content is None:
            return [
                JobDrift(job.name, DriftState.UNKNOWN, "crontab unavailable on this machine")
                for job in jobs
            ]

        lines = self._managed_lines(content)
        # An absent PATH line is the strongest evidence of an old install, not
        # a reason to skip the comparison: this backend always emits one, so
        # `is not None` here reported CURRENT for exactly the blocks written
        # before it started doing so.
        path_differs = self._existing_path_line(content) != f"PATH={resolved_path()}"

        out: list[JobDrift] = []
        for job in jobs:
            if job.name not in lines:
                out.append(JobDrift(job.name, DriftState.ABSENT))
                continue
            try:
                expected_schedule = render_cron(parse_cron(job.schedule))
            except Exception as e:  # noqa: BLE001 — an untranslatable schedule
                out.append(JobDrift(job.name, DriftState.UNKNOWN, f"{type(e).__name__}: {e}"))
                continue
            reasons = []
            if lines[job.name] != f"{expected_schedule} {job.command} {TAG}{job.name}":
                reasons.append("entry")
            if path_differs:
                reasons.append("PATH")
            out.append(
                JobDrift(job.name, DriftState.STALE, ", ".join(reasons))
                if reasons
                else JobDrift(job.name, DriftState.CURRENT)
            )
        return out

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

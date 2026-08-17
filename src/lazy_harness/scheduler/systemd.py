"""Linux systemd user-timer scheduler backend.

Units live under `$XDG_CONFIG_HOME/systemd/user/` with a flat
`lazy-harness-<job>` prefix — reverse-DNS labelling is a launchd convention
and has no meaning here.
"""

from __future__ import annotations

import os
import re
import subprocess
from collections.abc import Callable
from pathlib import Path

from lazy_harness.scheduler.base import JobRecord, JobState, SchedulerJob
from lazy_harness.scheduler.paths import resolved_path
from lazy_harness.scheduler.schedule import (
    ScheduleTranslationError,
    parse_cron,
    render_systemd,
)

Runner = Callable[[list[str]], "subprocess.CompletedProcess[str]"]

_ONCALENDAR = re.compile(r"^OnCalendar=(.*)$", re.MULTILINE)


def _default_runner(argv: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(argv, capture_output=True, text=True, timeout=10)


def _default_unit_dir() -> Path:
    xdg = os.environ.get("XDG_CONFIG_HOME")
    base = Path(xdg) if xdg else Path.home() / ".config"
    return base / "systemd" / "user"


class SystemdBackend:
    def __init__(
        self,
        *,
        unit_dir: Path | None = None,
        runner: Runner | None = None,
    ) -> None:
        self._unit_dir = unit_dir or _default_unit_dir()
        self._runner = runner or _default_runner

    def label_for(self, job: SchedulerJob) -> str:
        return f"lazy-harness-{job.name}"

    def _service_text(self, job: SchedulerJob) -> str:
        return (
            "[Unit]\n"
            f"Description=lazy-harness job {job.name}\n"
            "\n"
            "[Service]\n"
            "Type=oneshot\n"
            f"ExecStart={job.command}\n"
            f"Environment=PATH={resolved_path()}\n"
        )

    def _timer_text(self, job: SchedulerJob) -> str:
        return (
            "[Unit]\n"
            f"Description=lazy-harness timer for {job.name}\n"
            "\n"
            "[Timer]\n"
            f"OnCalendar={render_systemd(parse_cron(job.schedule))}\n"
            # A missed run fires on next boot — the closest analogue to
            # launchd's catch-up, and it matters on a machine that sleeps.
            "Persistent=true\n"
            "\n"
            "[Install]\n"
            "WantedBy=timers.target\n"
        )

    def _warn_if_not_lingering(self) -> None:
        """Lingering is a precondition, not a footnote.

        `systemctl --user` units stop when the user's last session ends, so on
        an ssh-only machine the timers never fire — and `enable --now` reports
        success anyway. Enabling it needs root, so this reports rather than
        escalating on its own.
        """
        user = os.environ.get("USER") or os.environ.get("LOGNAME") or ""
        try:
            proc = self._runner(["loginctl", "show-user", user, "--property=Linger"])
        except Exception:  # noqa: BLE001 — an absent loginctl is not fatal here
            return
        if "Linger=no" in (getattr(proc, "stdout", "") or ""):
            print(
                f"  !  Lingering is disabled for {user!r}. User timers stop when your "
                "last session ends, so these jobs will not fire on a headless machine.\n"
                f"     Fix with: sudo loginctl enable-linger {user}"
            )

    def install(self, jobs: list[SchedulerJob]) -> list[str]:
        """Install every job, or none of them."""
        for job in jobs:
            try:
                render_systemd(parse_cron(job.schedule))
            except ScheduleTranslationError as e:
                raise ScheduleTranslationError(f"job {job.name!r}: {e}") from e

        self._unit_dir.mkdir(parents=True, exist_ok=True)
        installed: list[str] = []
        for job in jobs:
            label = self.label_for(job)
            (self._unit_dir / f"{label}.service").write_text(self._service_text(job))
            (self._unit_dir / f"{label}.timer").write_text(self._timer_text(job))
            installed.append(label)

        self._runner(["systemctl", "--user", "daemon-reload"])
        for label in installed:
            self._runner(["systemctl", "--user", "enable", "--now", f"{label}.timer"])
        self._warn_if_not_lingering()
        return installed

    def uninstall(self, jobs: list[SchedulerJob]) -> list[str]:
        removed: list[str] = []
        for job in jobs:
            label = self.label_for(job)
            timer = self._unit_dir / f"{label}.timer"
            service = self._unit_dir / f"{label}.service"
            if not timer.is_file() and not service.is_file():
                continue
            self._runner(["systemctl", "--user", "disable", "--now", f"{label}.timer"])
            timer.unlink(missing_ok=True)
            service.unlink(missing_ok=True)
            removed.append(label)
        if removed:
            self._runner(["systemctl", "--user", "daemon-reload"])
        return removed

    def job_state(self, label: str) -> tuple[JobState, str]:
        try:
            proc = self._runner(["systemctl", "--user", "is-active", f"{label}.timer"])
        except OSError as e:
            return JobState.UNKNOWN, f"systemctl unavailable: {e}"
        except subprocess.TimeoutExpired:
            return JobState.UNKNOWN, "systemctl timed out"
        except Exception as e:  # noqa: BLE001 — the runner is an injection point
            return JobState.UNKNOWN, f"systemctl probe failed: {type(e).__name__}: {e}"
        out = (getattr(proc, "stdout", "") or "").strip()
        if out == "active":
            return JobState.LOADED, ""
        if out in ("inactive", "failed", "unknown"):
            return JobState.NOT_LOADED, ""
        return JobState.UNKNOWN, f"systemctl reported {out!r}"

    def discover(self) -> list[JobRecord]:
        if not self._unit_dir.is_dir():
            return []
        records: list[JobRecord] = []
        for timer in sorted(self._unit_dir.glob("lazy-harness-*.timer")):
            label = timer.stem
            match = _ONCALENDAR.search(timer.read_text())
            state, detail = self.job_state(label)
            records.append(
                JobRecord(
                    name=label[len("lazy-harness-") :],
                    label=label,
                    schedule=match.group(1).strip() if match else "—",
                    state=state,
                    detail=detail,
                )
            )
        return records

    def status(self) -> list[dict[str, str]]:
        return [{"label": r.label, "status": r.state.value} for r in self.discover()]

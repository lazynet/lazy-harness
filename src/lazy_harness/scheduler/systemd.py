"""Linux systemd user-timer scheduler backend.

Units live under `$XDG_CONFIG_HOME/systemd/user/` with a flat
`lazy-harness-<job>` prefix — reverse-DNS labelling is a launchd convention
and has no meaning here.
"""

from __future__ import annotations

import os
import re
import shutil
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


def _current_user() -> str:
    """The user whose systemd session owns the timers.

    `getpass.getuser` reads the password database when the environment does
    not carry USER — which is the case under systemd and cron, the very
    contexts this check reasons about.
    """
    import getpass

    try:
        return getpass.getuser()
    except (KeyError, OSError):
        return os.environ.get("USER") or os.environ.get("LOGNAME") or ""


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

    @staticmethod
    def _which(name: str) -> str | None:
        """Resolve `name` against the PATH the unit will run with.

        `shutil.which` defaults to the invoking process's PATH, which is not
        the one written into the unit: `resolved_path` is deliberately built
        from the platform rather than the environment, so a generated unit
        outlives the shell that generated it. Resolving here against the
        environment instead put the worktree's `.venv/bin` into `ExecStart` as
        an absolute path — where nothing can correct it, because an absolute
        ExecStart never consults PATH at all.
        """
        return shutil.which(name, path=resolved_path())

    def _exec_start(self, job: SchedulerJob) -> str:
        """Resolve the command into an absolute ExecStart line.

        systemd does not consult `Environment=PATH` when resolving the
        executable — it uses a compiled-in list of standard directories — so a
        bare name like `lh` fails with 203/EXEC every window while the PATH
        line right below it makes the unit look correct.

        It also does not run through a shell, so an operator in the command is
        a literal argument rather than a pipeline. Both cases refuse rather
        than writing a unit that never works.
        """
        for token in ("|", "&&", "||", ";", ">", "<", "$(", "`"):
            if token in job.command:
                raise ValueError(
                    f"job {job.name!r}: systemd does not run ExecStart through a shell, so "
                    f"{token!r} in {job.command!r} would be passed as a literal argument. "
                    "Wrap it in a script and point the command at that."
                )
        parts = job.command.split()
        if not parts:
            raise ValueError(f"job {job.name!r} has an empty command")
        binary = parts[0]
        if not binary.startswith("/"):
            resolved = self._which(binary)
            if resolved is None:
                raise ValueError(
                    f"job {job.name!r}: {binary!r} is not on PATH, and systemd needs an "
                    "absolute ExecStart. Install it or declare the full path."
                )
            binary = resolved
        return " ".join([binary, *parts[1:]])

    def _service_text(self, job: SchedulerJob) -> str:
        return (
            "[Unit]\n"
            f"Description=lazy-harness job {job.name}\n"
            "\n"
            "[Service]\n"
            "Type=oneshot\n"
            f"ExecStart={self._exec_start(job)}\n"
            # Quoted: systemd splits `Environment=` on whitespace into separate
            # assignments, so an unquoted PATH containing a space sets PATH to
            # its first fragment and drops the rest.
            f'Environment="PATH={resolved_path()}"\n'
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
        user = _current_user()
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
        # Everything that can be rejected is rejected before anything is
        # written, so a bad job leaves the existing set untouched.
        for job in jobs:
            try:
                render_systemd(parse_cron(job.schedule))
            except ScheduleTranslationError as e:
                raise ScheduleTranslationError(f"job {job.name!r}: {e}") from e
            self._exec_start(job)

        self._unit_dir.mkdir(parents=True, exist_ok=True)
        installed: list[str] = []
        for job in jobs:
            label = self.label_for(job)
            (self._unit_dir / f"{label}.service").write_text(self._service_text(job))
            (self._unit_dir / f"{label}.timer").write_text(self._timer_text(job))
            installed.append(label)

        self._check(["systemctl", "--user", "daemon-reload"])
        for label in installed:
            self._check(["systemctl", "--user", "enable", "--now", f"{label}.timer"])
        self._warn_if_not_lingering()
        return installed

    def _check(self, argv: list[str]) -> None:
        """Run and raise on a non-zero exit.

        Discarding the return code let `install` print a green tick per job
        while systemd had rejected the unit — the exact "reports success while
        installing nothing" failure ADR-013 records as fixed in 0.25.0.
        """
        proc = self._runner(argv)
        code = getattr(proc, "returncode", 0)
        if code:
            err = (getattr(proc, "stderr", "") or "").strip() or f"exit {code}"
            raise RuntimeError(f"{' '.join(argv)} failed: {err}")

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

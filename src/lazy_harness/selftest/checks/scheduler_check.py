from __future__ import annotations

import os
from pathlib import Path

from lazy_harness.core.config import ConfigError, load_config
from lazy_harness.scheduler.manager import detect_backend, parse_jobs_from_config
from lazy_harness.selftest.result import CheckResult, CheckStatus


def check_scheduler(*, config_path: Path) -> list[CheckResult]:
    """Verify scheduler backend is detected and declared jobs match installed jobs."""
    results: list[CheckResult] = []
    group = "scheduler"
    try:
        cfg = load_config(config_path)
    except (ConfigError, FileNotFoundError) as e:
        return [CheckResult(group=group, name="load", status=CheckStatus.FAILED, message=str(e))]

    try:
        backend = detect_backend(cfg.scheduler.backend)
        backend_name = type(backend).__name__
        results.append(
            CheckResult(
                group=group,
                name="backend",
                status=CheckStatus.PASSED,
                message=f"detected {backend_name}",
            )
        )
    except Exception as e:
        results.append(
            CheckResult(
                group=group,
                name="backend",
                status=CheckStatus.FAILED,
                message=f"backend detection failed: {e}",
            )
        )
        return results

    declared = parse_jobs_from_config(cfg)
    declared_count = len(declared)
    results.append(
        CheckResult(
            group=group,
            name="declared-jobs",
            status=CheckStatus.PASSED,
            message=f"{declared_count} jobs declared",
        )
    )

    if declared_count > 0:
        try:
            installed = backend.status()
            installed_count = len(installed)
            if installed_count != declared_count:
                results.append(
                    CheckResult(
                        group=group,
                        name="jobs-drift",
                        status=CheckStatus.WARNING,
                        message=f"drift: {declared_count} declared, {installed_count} installed",
                    )
                )
            else:
                results.append(
                    CheckResult(group=group, name="jobs-drift", status=CheckStatus.PASSED)
                )
        except Exception as e:
            results.append(
                CheckResult(
                    group=group,
                    name="jobs-drift",
                    status=CheckStatus.WARNING,
                    message=f"could not query installed jobs: {e}",
                )
            )

    return results


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


def check_linger(*, config_path: Path, runner: object | None = None) -> list[CheckResult]:
    """Verify that systemd user timers can actually fire.

    `systemctl --user` units stop when the user's last session ends, so on an
    ssh-only machine a job that installed cleanly never runs — and
    `enable --now` reports success either way. This is a FAILED rather than a
    warning: a machine whose scheduled jobs cannot fire is not healthy, and a
    warning would let it pass unnoticed.

    Silent on any other backend; lingering is a systemd concept.
    """
    import subprocess

    group = "scheduler"
    try:
        cfg = load_config(config_path)
    except (ConfigError, FileNotFoundError):
        return []

    backend = detect_backend(cfg.scheduler.backend)
    if type(backend).__name__ != "SystemdBackend":
        return []
    if not parse_jobs_from_config(cfg):
        return []

    def _run(argv: list[str]) -> subprocess.CompletedProcess[str]:
        return subprocess.run(argv, capture_output=True, text=True, timeout=10)

    call = runner if callable(runner) else _run
    user = _current_user()
    try:
        proc = call(["loginctl", "show-user", user, "--property=Linger"])
    except Exception as e:  # noqa: BLE001
        return [
            CheckResult(
                group=group,
                name="linger",
                status=CheckStatus.WARNING,
                message=f"could not determine lingering state: {e}",
            )
        ]

    out = (getattr(proc, "stdout", "") or "").strip()
    if "Linger=yes" in out:
        return [
            CheckResult(
                group=group,
                name="linger",
                status=CheckStatus.PASSED,
                message="user timers survive logout",
            )
        ]
    if "Linger=no" in out:
        return [
            CheckResult(
                group=group,
                name="linger",
                status=CheckStatus.FAILED,
                message=(
                    f"lingering is disabled for {user!r}, so declared jobs will not fire "
                    f"when no session is open. Fix with: sudo loginctl enable-linger {user}"
                ),
            )
        ]
    return [
        CheckResult(
            group=group,
            name="linger",
            status=CheckStatus.WARNING,
            message=f"loginctl reported {out!r}",
        )
    ]

from __future__ import annotations

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

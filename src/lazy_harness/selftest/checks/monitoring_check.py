from __future__ import annotations

import errno
import sqlite3
from pathlib import Path

from lazy_harness.core.config import ConfigError, load_config
from lazy_harness.monitoring.pricing import load_pricing
from lazy_harness.selftest.result import CheckResult, CheckStatus


def _db_path_result(group: str, error: Exception, *, permission_denied: bool) -> CheckResult:
    """One `db-path` result, classified: `permission_denied` is a WARNING
    (unverifiable in this environment, not a genuine failure) so it never
    turns a real corruption or config finding green, and never masks it as
    a false PASSED either."""
    if permission_denied:
        return CheckResult(
            group=group,
            name="db-path",
            status=CheckStatus.WARNING,
            message=f"cannot verify write access (permission denied): {error}",
        )
    return CheckResult(
        group=group,
        name="db-path",
        status=CheckStatus.FAILED,
        message=f"cannot open DB: {error}",
    )


def check_monitoring(*, config_path: Path) -> list[CheckResult]:
    """Verify monitoring DB path is usable and pricing config loads."""
    results: list[CheckResult] = []
    group = "monitoring"
    try:
        cfg = load_config(config_path)
    except (ConfigError, FileNotFoundError) as e:
        return [CheckResult(group=group, name="load", status=CheckStatus.FAILED, message=str(e))]

    if not cfg.monitoring.enabled:
        return [
            CheckResult(
                group=group,
                name="disabled",
                status=CheckStatus.PASSED,
                message="monitoring disabled",
            )
        ]

    db_path_str = cfg.monitoring.db
    if not db_path_str:
        results.append(
            CheckResult(
                group=group,
                name="db-path",
                status=CheckStatus.FAILED,
                message="monitoring.db not configured",
            )
        )
    else:
        db_path = Path(db_path_str).expanduser()
        try:
            from lazy_harness.monitoring.db import MetricsDB

            db = MetricsDB(db_path)
            db.close()
            results.append(CheckResult(group=group, name="db-path", status=CheckStatus.PASSED))
        except OSError as e:
            # A bare OSError (`Path.mkdir`, the underlying file open) never
            # reaches sqlite3's own wrapping. EACCES/EPERM are the only
            # errnos that mean "this environment couldn't prove anything";
            # anything else (ENOSPC, …) is a genuine finding.
            permission_denied = e.errno in (errno.EACCES, errno.EPERM)
            results.append(_db_path_result(group, e, permission_denied=permission_denied))
        except sqlite3.OperationalError as e:
            from lazy_harness.monitoring.db import looks_like_permission_denied

            results.append(
                _db_path_result(group, e, permission_denied=looks_like_permission_denied(str(e)))
            )
        except Exception as e:
            results.append(_db_path_result(group, e, permission_denied=False))

    try:
        pricing = load_pricing(cfg.monitoring.pricing or None)
        if pricing:
            results.append(CheckResult(group=group, name="pricing", status=CheckStatus.PASSED))
        else:
            results.append(
                CheckResult(
                    group=group,
                    name="pricing",
                    status=CheckStatus.WARNING,
                    message="pricing table is empty",
                )
            )
    except Exception as e:
        results.append(
            CheckResult(
                group=group,
                name="pricing",
                status=CheckStatus.FAILED,
                message=f"pricing load error: {e}",
            )
        )

    return results

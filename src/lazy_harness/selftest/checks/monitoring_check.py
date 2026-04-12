from __future__ import annotations

from pathlib import Path

from lazy_harness.core.config import ConfigError, load_config
from lazy_harness.monitoring.pricing import load_pricing
from lazy_harness.selftest.result import CheckResult, CheckStatus


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
        except Exception as e:
            results.append(
                CheckResult(
                    group=group,
                    name="db-path",
                    status=CheckStatus.FAILED,
                    message=f"cannot open DB: {e}",
                )
            )

    try:
        pricing = load_pricing(cfg.monitoring.pricing or None)
        if pricing:
            results.append(
                CheckResult(group=group, name="pricing", status=CheckStatus.PASSED)
            )
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

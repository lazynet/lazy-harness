from __future__ import annotations

from pathlib import Path

from lazy_harness.core.config import ConfigError, load_config
from lazy_harness.selftest.result import CheckResult, CheckStatus

SUPPORTED_AGENTS = {"claude-code"}


def check_config(*, config_path: Path) -> list[CheckResult]:
    """Validate that config.toml exists, parses, and has required fields."""
    results: list[CheckResult] = []
    group = "config"

    if not config_path.is_file():
        results.append(
            CheckResult(
                group=group,
                name="exists",
                status=CheckStatus.FAILED,
                message=f"{config_path} not found",
            )
        )
        return results
    results.append(CheckResult(group=group, name="exists", status=CheckStatus.PASSED))

    try:
        cfg = load_config(config_path)
    except ConfigError as e:
        results.append(
            CheckResult(
                group=group,
                name="parses",
                status=CheckStatus.FAILED,
                message=str(e),
            )
        )
        return results
    results.append(CheckResult(group=group, name="parses", status=CheckStatus.PASSED))

    if not cfg.profiles.items:
        results.append(
            CheckResult(
                group=group,
                name="has-profiles",
                status=CheckStatus.FAILED,
                message="no profiles defined",
            )
        )
    else:
        results.append(
            CheckResult(group=group, name="has-profiles", status=CheckStatus.PASSED)
        )

    if cfg.agent.type not in SUPPORTED_AGENTS:
        results.append(
            CheckResult(
                group=group,
                name="agent-valid",
                status=CheckStatus.FAILED,
                message=f"unknown agent type: {cfg.agent.type}",
            )
        )
    else:
        results.append(
            CheckResult(group=group, name="agent-valid", status=CheckStatus.PASSED)
        )

    return results

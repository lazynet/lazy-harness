from __future__ import annotations

import json
from pathlib import Path

from lazy_harness.core.config import ConfigError, load_config
from lazy_harness.selftest.result import CheckResult, CheckStatus


def check_profiles(*, config_path: Path) -> list[CheckResult]:
    """Verify each declared profile dir exists, has CLAUDE.md, and valid settings.json."""
    results: list[CheckResult] = []
    group = "profiles"
    try:
        cfg = load_config(config_path)
    except (ConfigError, FileNotFoundError) as e:
        return [CheckResult(group=group, name="load", status=CheckStatus.FAILED, message=str(e))]

    if not cfg.profiles.items:
        return [
            CheckResult(
                group=group,
                name="no-profiles",
                status=CheckStatus.WARNING,
                message="no profiles defined",
            )
        ]

    for name, profile in cfg.profiles.items.items():
        expanded = Path(profile.config_dir).expanduser()
        if not expanded.is_dir():
            results.append(
                CheckResult(
                    group=group,
                    name=f"{name}:exists",
                    status=CheckStatus.FAILED,
                    message=f"{expanded} does not exist",
                )
            )
            continue
        results.append(CheckResult(group=group, name=f"{name}:exists", status=CheckStatus.PASSED))

        if not (expanded / "CLAUDE.md").is_file():
            results.append(
                CheckResult(
                    group=group,
                    name=f"{name}:claude-md",
                    status=CheckStatus.WARNING,
                    message="CLAUDE.md missing",
                )
            )
        else:
            results.append(
                CheckResult(group=group, name=f"{name}:claude-md", status=CheckStatus.PASSED)
            )

        settings = expanded / "settings.json"
        if settings.is_file():
            try:
                json.loads(settings.read_text())
                results.append(
                    CheckResult(
                        group=group,
                        name=f"{name}:settings-json",
                        status=CheckStatus.PASSED,
                    )
                )
            except json.JSONDecodeError as e:
                results.append(
                    CheckResult(
                        group=group,
                        name=f"{name}:settings-json",
                        status=CheckStatus.FAILED,
                        message=f"invalid JSON: {e}",
                    )
                )
        else:
            results.append(
                CheckResult(
                    group=group,
                    name=f"{name}:settings-json",
                    status=CheckStatus.WARNING,
                    message="settings.json missing",
                )
            )

    return results

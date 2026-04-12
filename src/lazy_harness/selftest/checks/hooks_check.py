from __future__ import annotations

from pathlib import Path

from lazy_harness.core.config import ConfigError, load_config
from lazy_harness.hooks.loader import resolve_hooks_for_event
from lazy_harness.selftest.result import CheckResult, CheckStatus


def check_hooks(*, config_path: Path) -> list[CheckResult]:
    """Verify declared hooks resolve to executable files (without running them)."""
    results: list[CheckResult] = []
    group = "hooks"
    try:
        cfg = load_config(config_path)
    except (ConfigError, FileNotFoundError) as e:
        return [CheckResult(group=group, name="load", status=CheckStatus.FAILED, message=str(e))]

    if not cfg.hooks:
        return [
            CheckResult(
                group=group,
                name="no-hooks",
                status=CheckStatus.PASSED,
                message="no user hooks declared",
            )
        ]

    for event, event_cfg in cfg.hooks.items():
        for script_name in event_cfg.scripts:
            resolved = resolve_hooks_for_event(cfg, event)
            matched = next((h for h in resolved if h.name == script_name), None)
            if matched is None:
                results.append(
                    CheckResult(
                        group=group,
                        name=f"{event}:{script_name}",
                        status=CheckStatus.WARNING,
                        message=f"hook '{script_name}' not found (built-in or user hooks dir)",
                    )
                )
            elif not matched.path.is_file():
                results.append(
                    CheckResult(
                        group=group,
                        name=f"{event}:{script_name}",
                        status=CheckStatus.FAILED,
                        message=f"resolved to {matched.path} but file missing",
                    )
                )
            else:
                results.append(
                    CheckResult(
                        group=group,
                        name=f"{event}:{script_name}",
                        status=CheckStatus.PASSED,
                    )
                )

    return results

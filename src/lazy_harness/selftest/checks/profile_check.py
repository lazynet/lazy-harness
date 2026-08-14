from __future__ import annotations

import json
from pathlib import Path

from lazy_harness.core.config import ConfigError, load_config
from lazy_harness.selftest.result import CheckResult, CheckStatus


def _hook_schema_violations(settings: object) -> list[str]:
    """Report hook entries Claude Code's settings schema rejects.

    Parsing as JSON is not enough: the agent validates `matcher` as a string and
    skips the entire file when one entry fails, so a single bad field silently
    disables every hook in the profile. This cannot be detected from a hook —
    the failure is exactly what stops hooks from running — so it lives here.
    """
    if not isinstance(settings, dict):
        return []
    hooks = settings.get("hooks")
    if not isinstance(hooks, dict):
        return []
    violations: list[str] = []
    for event, entries in hooks.items():
        if not isinstance(entries, list):
            violations.append(f"{event}: expected a list of hook entries")
            continue
        for index, entry in enumerate(entries):
            if not isinstance(entry, dict):
                violations.append(f"{event}[{index}]: expected a table")
                continue
            matcher = entry.get("matcher")
            if matcher is not None and not isinstance(matcher, str):
                violations.append(
                    f"{event}[{index}].matcher: expected a string, got {type(matcher).__name__}"
                )
            elif matcher is None and "matcher" in entry:
                violations.append(f"{event}[{index}].matcher: expected a string, got null")
    return violations


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
                parsed = json.loads(settings.read_text())
                results.append(
                    CheckResult(
                        group=group,
                        name=f"{name}:settings-json",
                        status=CheckStatus.PASSED,
                    )
                )
                violations = _hook_schema_violations(parsed)
                results.append(
                    CheckResult(
                        group=group,
                        name=f"{name}:settings-schema",
                        status=CheckStatus.FAILED if violations else CheckStatus.PASSED,
                        message="; ".join(violations),
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

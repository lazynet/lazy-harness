from __future__ import annotations

from pathlib import Path

from lazy_harness.core.config import ConfigError, load_config, save_config
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
        results.append(CheckResult(group=group, name="has-profiles", status=CheckStatus.PASSED))

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
        results.append(CheckResult(group=group, name="agent-valid", status=CheckStatus.PASSED))

    return results


def _flat_keys(data: dict, prefix: str = "") -> set[str]:
    """Every dotted key path in a parsed TOML document, tables included."""
    out: set[str] = set()
    for key, value in data.items():
        path = f"{prefix}{key}"
        out.add(path)
        if isinstance(value, dict):
            out |= _flat_keys(value, path + ".")
    return out


def check_config_round_trip(*, config_path: Path) -> list[CheckResult]:
    """Verify that writing the config back preserves every key it started with.

    A writer that silently drops a section is invisible until the day a
    command rewrites the file. `save_config` emitted 10 of the 14 sections
    `load_config` reads and destroyed 51 keys per write; this is the net for
    the next time that happens.
    """
    import shutil
    import tempfile
    import tomllib

    group = "config"
    if not config_path.is_file():
        # CheckStatus has exactly three members — PASSED, FAILED, WARNING.
        # A missing config is `check_config`'s failure to report, not this one's.
        return [
            CheckResult(
                group=group,
                name="round-trip",
                status=CheckStatus.WARNING,
                message=f"no config at {config_path}",
            )
        ]

    try:
        before = _flat_keys(tomllib.loads(config_path.read_text(encoding="utf-8")))
        # The probe runs against a copy: a health check that mutates what it
        # checks is not a health check.
        with tempfile.TemporaryDirectory() as td:
            probe = Path(td) / "config.toml"
            shutil.copyfile(config_path, probe)
            save_config(load_config(probe), probe)
            after = _flat_keys(tomllib.loads(probe.read_text(encoding="utf-8")))
    except (ConfigError, OSError, tomllib.TOMLDecodeError) as e:
        return [
            CheckResult(
                group=group,
                name="round-trip",
                status=CheckStatus.FAILED,
                message=f"round-trip probe failed: {e}",
            )
        ]

    lost = sorted(before - after)
    if lost:
        shown = ", ".join(lost[:8]) + (f" (+{len(lost) - 8} more)" if len(lost) > 8 else "")
        return [
            CheckResult(
                group=group,
                name="round-trip",
                status=CheckStatus.FAILED,
                message=f"save_config would drop {len(lost)} keys: {shown}",
            )
        ]
    return [
        CheckResult(
            group=group,
            name="round-trip",
            status=CheckStatus.PASSED,
            message=f"{len(before)} keys survive a write",
        )
    ]


def check_capability_paths(
    *, config_path: Path, registry: object | None = None
) -> list[CheckResult]:
    """Verify every registered capability's config path resolves.

    A capability declaring a key that is not in `Config` is a broken contract
    that nothing else notices: `lh doctor` would render it, the TUI would offer
    a toggle for it, and both would be pointing at nothing. Paired with
    `check_config_round_trip`, this is what makes the registry's paths a
    checkable claim rather than a comment.
    """
    from lazy_harness.plugins.builtins import builtin_registry
    from lazy_harness.plugins.capabilities import _resolve

    group = "config"
    name = "capability-paths"
    if not config_path.is_file():
        return [
            CheckResult(
                group=group,
                name=name,
                status=CheckStatus.WARNING,
                message=f"no config at {config_path}",
            )
        ]

    try:
        cfg = load_config(config_path)
    except (ConfigError, FileNotFoundError) as e:
        return [CheckResult(group=group, name=name, status=CheckStatus.FAILED, message=str(e))]

    reg = registry if registry is not None else builtin_registry()
    caps = reg.capabilities()  # type: ignore[attr-defined]

    broken: list[str] = []
    for cap in caps:
        if not cap.config_path:
            # Presence-only capabilities declare no path on purpose.
            continue
        try:
            _resolve(cfg, cap.config_path, owner=cap.name)
        except AttributeError as e:
            broken.append(str(e))

    if broken:
        return [
            CheckResult(
                group=group,
                name=name,
                status=CheckStatus.FAILED,
                message="; ".join(broken),
            )
        ]
    return [
        CheckResult(
            group=group,
            name=name,
            status=CheckStatus.PASSED,
            message=f"{len(caps)} capabilities, every declared path resolves",
        )
    ]

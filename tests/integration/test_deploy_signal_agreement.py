"""`lh doctor` and `lh deploy` answer the signal question the same way.

Both commands are invoked for real and their outputs compared, because the
agreement is the point: doctor *reports* a hook as unfeedable and deploy *acts*
on it, so a hook doctor names must be absent from the artifact deploy writes,
and a hook doctor stays quiet about must be present. Reading the shared helper
instead would prove only that one function returns what it returns.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from click.testing import CliRunner

from lazy_harness.core.config import (
    Config,
    HarnessConfig,
    HookEventConfig,
    ProfileEntry,
    ProfilesConfig,
    save_config,
)
from lazy_harness.core.paths import config_dir


def _write_config(home_dir: Path) -> Path:
    """One Codex profile, wired to a signal-declaring hook and a signal-free one."""
    codex_home = home_dir / ".codex-p1"
    cfg = Config(
        harness=HarnessConfig(version="1"),
        profiles=ProfilesConfig(
            default="p1",
            items={"p1": ProfileEntry(config_dir=str(codex_home), agent="codex")},
        ),
    )
    cfg.agent.type = "codex"
    cfg.hooks = {
        "session_stop": HookEventConfig(scripts=["stop-verify-guard"]),
        "pre_tool_use": HookEventConfig(scripts=["pre-tool-use-security"]),
    }
    save_config(cfg, config_dir() / "config.toml")
    return codex_home


def _doctor_hook_signal_names(output: str) -> set[str]:
    """Builtin names `lh doctor` lists under its Hook signals heading.

    Cut at the next section's blank-line separator, not just the string's end:
    step 10 added `Hook operations` and `Hook events` right after this section,
    and both can legitimately name `pre-tool-use-security` for a reason that
    has nothing to do with a signal gap — reading to end-of-output would
    misattribute their names to this one.

    Rich wraps at the terminal width, so the section is flattened before it is
    searched — a wrapped line would otherwise hide a name the comparison needs.
    """
    section = output.partition("Hook signals")[2].split("\n\n", 1)[0]
    flat = re.sub(r"\s+", " ", section)
    from lazy_harness.hooks.loader import list_builtin_hooks

    return {name for name in list_builtin_hooks() if name in flat}


def test_no_hook_doctor_names_survives_into_the_deployed_artifact(home_dir: Path) -> None:
    from lazy_harness.cli.main import cli

    codex_home = _write_config(home_dir)
    runner = CliRunner()

    doctor = runner.invoke(cli, ["doctor"])
    deploy = runner.invoke(cli, ["deploy", "--profile", "p1"])
    assert deploy.exit_code == 0, deploy.output

    named = _doctor_hook_signal_names(doctor.output)
    assert named, f"fixture must give doctor something to name:\n{doctor.output}"

    written = json.dumps(json.loads((codex_home / "hooks.json").read_text()))
    for name in named:
        assert name not in written, f"{name} is named by doctor and still deployed"


def test_a_hook_doctor_stays_quiet_about_is_deployed(home_dir: Path) -> None:
    """The inverse. Without it the filter could pass by deploying nothing."""
    from lazy_harness.cli.main import cli

    codex_home = _write_config(home_dir)
    runner = CliRunner()

    doctor = runner.invoke(cli, ["doctor"])
    deploy = runner.invoke(cli, ["deploy", "--profile", "p1"])
    assert deploy.exit_code == 0, deploy.output

    written = json.dumps(json.loads((codex_home / "hooks.json").read_text()))

    assert "pre-tool-use-security" not in _doctor_hook_signal_names(doctor.output)
    assert "pre-tool-use-security" in written


def test_the_deploy_names_the_hook_it_omitted(home_dir: Path) -> None:
    from lazy_harness.cli.main import cli

    _write_config(home_dir)
    result = CliRunner().invoke(cli, ["deploy", "--profile", "p1"])

    assert result.exit_code == 0, result.output
    assert (
        "stop-verify-guard omitted in 'p1': agent 'codex' does not deliver goal_status"
        in result.output
    )

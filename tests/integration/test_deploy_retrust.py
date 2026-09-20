"""`lh deploy` prints the re-trust instruction when a Codex hook declaration
changes (lane B3, deploy-retrust; specs/backlog.md, "`lh deploy` no imprime la
instrucción de re-trust").

Every default builtin hook is suppressed so the fixture controls one external
declaration at a time. Changing that declaration ensures a second group rather
than replacing the first: omission or change does not transfer lifecycle
ownership to the harness.
"""

from __future__ import annotations

from pathlib import Path

from click.testing import CliRunner

from lazy_harness.core.config import (
    Config,
    ExternalHookConfig,
    HarnessConfig,
    HookEventConfig,
    ProfileEntry,
    ProfilesConfig,
    save_config,
)
from lazy_harness.core.paths import config_dir
from lazy_harness.deploy.defaults import DEFAULT_HOOKS


def _write_codex_config(home_dir: Path, *, matcher: str = "Bash") -> None:
    src = config_dir() / "profiles" / "cx"
    src.mkdir(parents=True, exist_ok=True)
    (src / "AGENTS.md").write_text("# cx\n")

    no_defaults = {event: HookEventConfig(scripts=[]) for event in DEFAULT_HOOKS}
    no_defaults["pre_tool_use"] = HookEventConfig(
        scripts=[], external=[ExternalHookConfig(command="probe", matcher=matcher)]
    )
    cfg = Config(
        harness=HarnessConfig(version="1"),
        profiles=ProfilesConfig(
            default="cx",
            items={"cx": ProfileEntry(config_dir=str(home_dir / ".codex"), agent="codex")},
        ),
        hooks=no_defaults,
    )
    save_config(cfg, config_dir() / "config.toml")


def _write_claude_config(home_dir: Path) -> None:
    src = config_dir() / "profiles" / "lazy"
    src.mkdir(parents=True, exist_ok=True)
    (src / "CLAUDE.md").write_text("# lazy\n")
    cfg = Config(
        harness=HarnessConfig(version="1"),
        profiles=ProfilesConfig(
            default="lazy",
            items={"lazy": ProfileEntry(config_dir=str(home_dir / ".claude-lazy"))},
        ),
    )
    save_config(cfg, config_dir() / "config.toml")


def test_first_deploy_of_a_codex_profile_prints_the_retrust_instruction(home_dir: Path) -> None:
    from lazy_harness.cli.main import cli

    _write_codex_config(home_dir)
    result = CliRunner().invoke(cli, ["deploy", "--profile", "cx"])

    assert result.exit_code == 0, result.output
    assert "cx/hooks.json" in result.output
    assert "pre_tool_use[0]" in result.output
    assert "Approve them in Codex's own review screen" in result.output
    assert "trust stale" in result.output


def test_redeploy_of_the_same_declaration_is_silent(home_dir: Path) -> None:
    from lazy_harness.cli.main import cli

    _write_codex_config(home_dir)
    runner = CliRunner()
    runner.invoke(cli, ["deploy", "--profile", "cx"])

    result = runner.invoke(cli, ["deploy", "--profile", "cx"])

    assert result.exit_code == 0, result.output
    assert "re-trust" not in result.output
    assert "trust stale" not in result.output


def test_changing_an_external_matcher_preserves_the_old_group_and_names_the_new_one(
    home_dir: Path,
) -> None:
    from lazy_harness.cli.main import cli

    _write_codex_config(home_dir, matcher="Bash")
    runner = CliRunner()
    runner.invoke(cli, ["deploy", "--profile", "cx"])

    _write_codex_config(home_dir, matcher="Edit")
    result = runner.invoke(cli, ["deploy", "--profile", "cx"])

    assert result.exit_code == 0, result.output
    assert "pre_tool_use[1]" in result.output
    assert "re-trust" in result.output

    hooks = (home_dir / ".codex" / "hooks.json").read_text()
    assert hooks.count('"command": "probe"') == 2


def test_an_external_change_does_not_call_the_preserved_group_stale(home_dir: Path) -> None:
    """The old external group keeps index 0; only the new index is untrusted."""
    from lazy_harness.cli.main import cli

    _write_codex_config(home_dir, matcher="Bash")
    runner = CliRunner()
    runner.invoke(cli, ["deploy", "--profile", "cx"])

    # The user approved the pre_tool_use[0] hook in Codex's own TUI, between
    # the two deploys — the key is positional, so it survives the redeploy.
    hooks_file = home_dir / ".codex" / "hooks.json"
    key = f"{hooks_file.resolve()}:pre_tool_use:0:0"
    (home_dir / ".codex" / "config.toml").write_text(
        f'[hooks.state."{key}"]\ntrusted_hash = "sha256:deadbeef"\n'
    )

    _write_codex_config(home_dir, matcher="Edit")
    deploy_result = runner.invoke(cli, ["deploy", "--profile", "cx"])
    assert deploy_result.exit_code == 0, deploy_result.output

    doctor_result = runner.invoke(cli, ["doctor"])

    assert doctor_result.exception is None, doctor_result.output
    assert "pre_tool_use[1]" in doctor_result.output
    assert "trust stale" not in doctor_result.output


def test_a_claude_profile_stays_silent(home_dir: Path) -> None:
    from lazy_harness.cli.main import cli

    _write_claude_config(home_dir)
    result = CliRunner().invoke(cli, ["deploy"])

    assert result.exit_code == 0, result.output
    assert "re-trust" not in result.output
    assert "trust stale" not in result.output

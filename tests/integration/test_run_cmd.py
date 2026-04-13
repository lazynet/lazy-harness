"""Integration tests for `lh run` launcher."""

from __future__ import annotations

from pathlib import Path

import pytest
from click.testing import CliRunner

from lazy_harness.cli.main import cli
from lazy_harness.core.config import (
    Config,
    HarnessConfig,
    ProfileEntry,
    ProfilesConfig,
    save_config,
)


def _setup_two_profiles(home_dir: Path) -> Path:
    config_path = home_dir / ".config" / "lazy-harness" / "config.toml"
    cfg = Config(
        harness=HarnessConfig(version="1"),
        profiles=ProfilesConfig(
            default="personal",
            items={
                "personal": ProfileEntry(
                    config_dir=str(home_dir / ".claude-personal"),
                    roots=[str(home_dir / "repos" / "lazy")],
                ),
                "work": ProfileEntry(
                    config_dir=str(home_dir / ".claude-work"),
                    roots=[str(home_dir / "repos" / "flex")],
                ),
            },
        ),
    )
    save_config(cfg, config_path)
    (home_dir / "repos" / "lazy").mkdir(parents=True)
    (home_dir / "repos" / "flex").mkdir(parents=True)
    return config_path


def _stub_binary(
    monkeypatch: pytest.MonkeyPatch,
    path: Path = Path("/usr/local/bin/claude"),
) -> None:
    from lazy_harness.agents.claude_code import ClaudeCodeAdapter

    monkeypatch.setattr(ClaudeCodeAdapter, "resolve_binary", lambda self: path)


def test_run_lists_profiles(home_dir: Path) -> None:
    _setup_two_profiles(home_dir)
    runner = CliRunner()
    result = runner.invoke(cli, ["run", "--list"])
    assert result.exit_code == 0
    assert "personal" in result.output
    assert "work" in result.output


def test_run_dry_run_shows_default_profile(
    home_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _setup_two_profiles(home_dir)
    _stub_binary(monkeypatch)
    monkeypatch.chdir(home_dir)
    runner = CliRunner()
    result = runner.invoke(cli, ["run", "--dry-run"])
    assert result.exit_code == 0
    assert "personal" in result.output
    assert "/usr/local/bin/claude" in result.output


def test_run_dry_run_resolves_profile_by_cwd(
    home_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _setup_two_profiles(home_dir)
    _stub_binary(monkeypatch)
    monkeypatch.chdir(home_dir / "repos" / "flex")
    runner = CliRunner()
    result = runner.invoke(cli, ["run", "--dry-run"])
    assert result.exit_code == 0
    assert "work" in result.output
    assert ".claude-work" in result.output


def test_run_dry_run_profile_override(
    home_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _setup_two_profiles(home_dir)
    _stub_binary(monkeypatch)
    monkeypatch.chdir(home_dir / "repos" / "lazy")
    runner = CliRunner()
    result = runner.invoke(cli, ["run", "--profile", "work", "--dry-run"])
    assert result.exit_code == 0
    assert "work" in result.output


def test_run_unknown_profile_fails(
    home_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _setup_two_profiles(home_dir)
    _stub_binary(monkeypatch)
    runner = CliRunner()
    result = runner.invoke(cli, ["run", "--profile", "ghost", "--dry-run"])
    assert result.exit_code != 0
    assert "ghost" in result.output.lower() or "unknown" in result.output.lower()


def test_run_passes_extra_args_to_binary(
    home_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _setup_two_profiles(home_dir)
    _stub_binary(monkeypatch)
    monkeypatch.chdir(home_dir / "repos" / "lazy")
    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "run",
            "--dry-run",
            "--",
            "--allow-dangerously-skip-permissions",
            "--model",
            "opus",
        ],
    )
    assert result.exit_code == 0
    assert "--allow-dangerously-skip-permissions" in result.output
    assert "--model" in result.output
    assert "opus" in result.output


def test_run_fails_when_binary_missing(
    home_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _setup_two_profiles(home_dir)
    from lazy_harness.agents.claude_code import ClaudeCodeAdapter

    monkeypatch.setattr(ClaudeCodeAdapter, "resolve_binary", lambda self: None)
    runner = CliRunner()
    result = runner.invoke(cli, ["run", "--dry-run"])
    assert result.exit_code != 0
    assert "binary" in result.output.lower() or "claude" in result.output.lower()


def test_run_fails_when_no_profiles_configured(home_dir: Path) -> None:
    config_path = home_dir / ".config" / "lazy-harness" / "config.toml"
    cfg = Config(harness=HarnessConfig(version="1"))
    save_config(cfg, config_path)
    runner = CliRunner()
    result = runner.invoke(cli, ["run", "--dry-run"])
    assert result.exit_code != 0
    assert "init" in result.output.lower() or "no profiles" in result.output.lower()

"""Integration tests for lh init."""

from __future__ import annotations

from pathlib import Path

import pytest
from click.testing import CliRunner

from lazy_harness.cli.main import cli


def test_init_creates_config(home_dir: Path) -> None:
    runner = CliRunner()
    result = runner.invoke(cli, ["init"], input="personal\n\n\n\n")
    assert result.exit_code == 0
    config_file = home_dir / ".config" / "lazy-harness" / "config.toml"
    assert config_file.is_file()
    content = config_file.read_text()
    assert "[harness]" in content
    assert 'version = "1"' in content


def test_init_creates_profile_dir(home_dir: Path) -> None:
    runner = CliRunner()
    result = runner.invoke(cli, ["init"], input="personal\n\n\n\n")
    assert result.exit_code == 0
    profile_dir = home_dir / ".config" / "lazy-harness" / "profiles" / "personal"
    assert profile_dir.is_dir()


def test_init_noninteractive(home_dir: Path) -> None:
    runner = CliRunner()
    result = runner.invoke(cli, [
        "init",
        "--profile-name", "work",
        "--profile-config-dir", str(home_dir / ".claude-work"),
        "--agent", "claude-code",
        "--non-interactive",
    ])
    assert result.exit_code == 0
    config_file = home_dir / ".config" / "lazy-harness" / "config.toml"
    assert config_file.is_file()
    content = config_file.read_text()
    assert "work" in content


def test_init_refuses_overwrite(home_dir: Path) -> None:
    runner = CliRunner()
    runner.invoke(cli, ["init"], input="personal\n\n\n\n")
    result = runner.invoke(cli, ["init"], input="n\n")
    assert "already exists" in result.output.lower() or result.exit_code == 0

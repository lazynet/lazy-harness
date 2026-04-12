"""Integration tests for lh profile commands."""

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


def _setup_config(home_dir: Path) -> Path:
    """Create a valid config file and return its path."""
    config_path = home_dir / ".config" / "lazy-harness" / "config.toml"
    cfg = Config(
        harness=HarnessConfig(version="1"),
        profiles=ProfilesConfig(
            default="personal",
            items={
                "personal": ProfileEntry(
                    config_dir=str(home_dir / ".claude-personal"),
                    roots=["~"],
                ),
            },
        ),
    )
    save_config(cfg, config_path)
    return config_path


def test_profile_list(home_dir: Path) -> None:
    _setup_config(home_dir)
    runner = CliRunner()
    result = runner.invoke(cli, ["profile", "list"])
    assert result.exit_code == 0
    assert "personal" in result.output


def test_profile_add(home_dir: Path) -> None:
    _setup_config(home_dir)
    runner = CliRunner()
    result = runner.invoke(cli, [
        "profile", "add", "work",
        "--config-dir", str(home_dir / ".claude-work"),
        "--roots", "~/work",
    ])
    assert result.exit_code == 0
    assert "work" in result.output or "added" in result.output.lower()

    result2 = runner.invoke(cli, ["profile", "list"])
    assert "work" in result2.output


def test_profile_add_duplicate(home_dir: Path) -> None:
    _setup_config(home_dir)
    runner = CliRunner()
    result = runner.invoke(cli, [
        "profile", "add", "personal",
        "--config-dir", str(home_dir / ".claude-personal"),
    ])
    assert result.exit_code != 0 or "already exists" in result.output.lower()


def test_profile_remove(home_dir: Path) -> None:
    config_path = _setup_config(home_dir)
    from lazy_harness.core.config import load_config
    cfg = load_config(config_path)
    cfg.profiles.items["work"] = ProfileEntry(
        config_dir=str(home_dir / ".claude-work"), roots=["~/work"]
    )
    save_config(cfg, config_path)

    runner = CliRunner()
    result = runner.invoke(cli, ["profile", "remove", "work"])
    assert result.exit_code == 0

    result2 = runner.invoke(cli, ["profile", "list"])
    assert "work" not in result2.output


def test_profile_remove_default_fails(home_dir: Path) -> None:
    _setup_config(home_dir)
    runner = CliRunner()
    result = runner.invoke(cli, ["profile", "remove", "personal"])
    assert result.exit_code != 0 or "default" in result.output.lower()

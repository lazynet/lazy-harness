"""Integration tests for lh hooks commands."""

from __future__ import annotations

from pathlib import Path

from click.testing import CliRunner

from lazy_harness.cli.main import cli
from lazy_harness.core.config import (
    Config,
    HarnessConfig,
    HookEventConfig,
    save_config,
)


def _setup_config(home_dir: Path) -> Path:
    config_path = home_dir / ".config" / "lazy-harness" / "config.toml"
    cfg = Config(
        harness=HarnessConfig(version="1"),
        hooks={
            "session_start": HookEventConfig(scripts=["context-inject"]),
            "pre_compact": HookEventConfig(scripts=["pre-compact"]),
        },
    )
    save_config(cfg, config_path)
    return config_path


def test_hooks_list(home_dir: Path) -> None:
    _setup_config(home_dir)
    runner = CliRunner()
    result = runner.invoke(cli, ["hooks", "list"])
    assert result.exit_code == 0
    assert "context-inject" in result.output


def test_hooks_list_no_config(home_dir: Path) -> None:
    runner = CliRunner()
    result = runner.invoke(cli, ["hooks", "list"])
    assert "context-inject" in result.output or result.exit_code != 0

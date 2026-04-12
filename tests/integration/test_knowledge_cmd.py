"""Integration tests for lh knowledge commands."""

from __future__ import annotations

from pathlib import Path

from click.testing import CliRunner

from lazy_harness.cli.main import cli
from lazy_harness.core.config import Config, HarnessConfig, KnowledgeConfig, save_config


def _setup_config(home_dir: Path) -> Path:
    config_path = home_dir / ".config" / "lazy-harness" / "config.toml"
    knowledge_dir = home_dir / "knowledge"
    knowledge_dir.mkdir()
    cfg = Config(
        harness=HarnessConfig(version="1"), knowledge=KnowledgeConfig(path=str(knowledge_dir))
    )
    save_config(cfg, config_path)
    return config_path


def test_knowledge_status(home_dir: Path) -> None:
    _setup_config(home_dir)
    runner = CliRunner()
    result = runner.invoke(cli, ["knowledge", "status"])
    assert result.exit_code == 0
    assert "knowledge" in result.output.lower()


def test_knowledge_no_path(home_dir: Path) -> None:
    config_path = home_dir / ".config" / "lazy-harness" / "config.toml"
    cfg = Config(harness=HarnessConfig(version="1"))
    save_config(cfg, config_path)
    runner = CliRunner()
    result = runner.invoke(cli, ["knowledge", "status"])
    assert "not configured" in result.output.lower() or result.exit_code != 0

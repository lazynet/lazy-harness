"""Tests for the lh config CLI command group."""

from __future__ import annotations

from pathlib import Path

import pytest
from click.testing import CliRunner


def test_config_memory_init_invokes_wizard(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from lazy_harness.cli import config_cmd

    cfg_path = tmp_path / "config.toml"
    monkeypatch.setattr(config_cmd, "config_file", lambda: cfg_path)

    called: dict[str, Path] = {}

    def fake_wizard(path, **kwargs):
        called["path"] = path
        return True

    monkeypatch.setattr(config_cmd, "wizard_memory", fake_wizard)

    runner = CliRunner()
    result = runner.invoke(config_cmd.config, ["memory", "--init"])

    assert result.exit_code == 0
    assert called["path"] == cfg_path


def test_config_knowledge_init_invokes_wizard(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from lazy_harness.cli import config_cmd

    cfg_path = tmp_path / "config.toml"
    monkeypatch.setattr(config_cmd, "config_file", lambda: cfg_path)

    called: dict[str, Path] = {}

    def fake_wizard(path, **kwargs):
        called["path"] = path
        return True

    monkeypatch.setattr(config_cmd, "wizard_knowledge", fake_wizard)

    runner = CliRunner()
    result = runner.invoke(config_cmd.config, ["knowledge", "--init"])

    assert result.exit_code == 0
    assert called["path"] == cfg_path


def test_config_memory_without_init_prints_usage(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from lazy_harness.cli import config_cmd

    monkeypatch.setattr(config_cmd, "config_file", lambda: tmp_path / "config.toml")

    runner = CliRunner()
    result = runner.invoke(config_cmd.config, ["memory"])

    assert result.exit_code == 0
    assert "--init" in result.output

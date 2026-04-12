"""Integration tests for lh init wizard (C3)."""

from __future__ import annotations

from pathlib import Path

from click.testing import CliRunner

from lazy_harness.cli.main import cli


def test_init_on_empty_home(home_dir: Path) -> None:
    runner = CliRunner()
    result = runner.invoke(cli, ["init"], input="\n\n\n\n")
    assert result.exit_code == 0, result.output
    assert (home_dir / ".config" / "lazy-harness" / "config.toml").is_file()


def test_init_blocks_on_existing_lazy_claudecode(home_dir: Path) -> None:
    lazy = home_dir / ".claude-lazy"
    lazy.mkdir()
    (lazy / "settings.json").write_text("{}")

    runner = CliRunner()
    result = runner.invoke(cli, ["init"])
    assert result.exit_code != 0
    assert "migrate" in result.output.lower()


def test_init_blocks_on_vanilla_claude(home_dir: Path) -> None:
    claude = home_dir / ".claude"
    claude.mkdir()
    (claude / "settings.json").write_text("{}")

    runner = CliRunner()
    result = runner.invoke(cli, ["init"])
    assert result.exit_code != 0
    assert "migrate" in result.output.lower()

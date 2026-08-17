"""Integration tests for lh doctor."""

from __future__ import annotations

from pathlib import Path

from click.testing import CliRunner

from lazy_harness.cli.main import cli
from lazy_harness.core.config import (
    Config,
    HarnessConfig,
    ProfileEntry,
    ProfilesConfig,
    save_config,
)


def _setup_config(home_dir: Path, create_profile_dirs: bool = True) -> Path:
    config_path = home_dir / ".config" / "lazy-harness" / "config.toml"
    profile_dir = home_dir / ".claude-personal"
    cfg = Config(
        harness=HarnessConfig(version="1"),
        profiles=ProfilesConfig(
            default="personal",
            items={
                "personal": ProfileEntry(
                    config_dir=str(profile_dir),
                    roots=["~"],
                ),
            },
        ),
    )
    save_config(cfg, config_path)
    if create_profile_dirs:
        profile_dir.mkdir(parents=True, exist_ok=True)
    return config_path


def test_doctor_healthy(home_dir: Path) -> None:
    _setup_config(home_dir, create_profile_dirs=True)
    runner = CliRunner()
    result = runner.invoke(cli, ["doctor"])
    assert result.exit_code == 0
    assert "config" in result.output.lower()


def test_doctor_missing_config(home_dir: Path) -> None:
    runner = CliRunner()
    result = runner.invoke(cli, ["doctor"])
    out = result.output.lower()
    assert result.exit_code != 0 or "not found" in out or "missing" in out


def test_doctor_missing_profile_dir(home_dir: Path) -> None:
    _setup_config(home_dir, create_profile_dirs=False)
    runner = CliRunner()
    result = runner.invoke(cli, ["doctor"])
    assert "missing" in result.output.lower()


def test_feature_hint_keeps_the_config_section_it_names(home_dir: Path, monkeypatch) -> None:
    """`console.print(f"[grey50]{hint}[/grey50]")` hands the hint to rich as
    markup, so the `[memory.engram]` inside it is parsed as a tag and removed.

    The hint exists to tell the user which key to set. It reached the terminal
    as `Set .enabled = true to activate.` — the one word it was written for.
    """
    _setup_config(home_dir, create_profile_dirs=True)
    # Dormant: the binary is present, the capability is not enabled.
    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/engram")

    result = CliRunner().invoke(cli, ["doctor"])

    assert "[memory.engram]" in result.output, result.output

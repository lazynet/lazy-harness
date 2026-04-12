"""Tests for TOML config loading and validation."""

from __future__ import annotations

from pathlib import Path

import pytest


def test_load_config_from_file(config_dir: Path) -> None:
    config_file = config_dir / "config.toml"
    config_file.write_text("""
[harness]
version = "1"

[agent]
type = "claude-code"

[profiles]
default = "personal"

[profiles.personal]
config_dir = "~/.claude-personal"
roots = ["~"]
""")
    from lazy_harness.core.config import load_config

    cfg = load_config(config_file)
    assert cfg.harness.version == "1"
    assert cfg.agent.type == "claude-code"
    assert cfg.profiles.default == "personal"
    assert "personal" in cfg.profiles.items
    assert cfg.profiles.items["personal"].config_dir == "~/.claude-personal"


def test_load_config_missing_file(tmp_path: Path) -> None:
    from lazy_harness.core.config import ConfigError, load_config

    with pytest.raises(ConfigError, match="not found"):
        load_config(tmp_path / "nonexistent.toml")


def test_load_config_invalid_toml(config_dir: Path) -> None:
    config_file = config_dir / "config.toml"
    config_file.write_text("this is not [valid toml")
    from lazy_harness.core.config import ConfigError, load_config

    with pytest.raises(ConfigError, match="parse"):
        load_config(config_file)


def test_load_config_missing_version(config_dir: Path) -> None:
    config_file = config_dir / "config.toml"
    config_file.write_text("""
[agent]
type = "claude-code"
""")
    from lazy_harness.core.config import ConfigError, load_config

    with pytest.raises(ConfigError, match="version"):
        load_config(config_file)


def test_load_config_defaults(config_dir: Path) -> None:
    config_file = config_dir / "config.toml"
    config_file.write_text("""
[harness]
version = "1"
""")
    from lazy_harness.core.config import load_config

    cfg = load_config(config_file)
    assert cfg.agent.type == "claude-code"
    assert cfg.monitoring.enabled is False
    assert cfg.scheduler.backend == "auto"


def test_config_get_profile(config_dir: Path) -> None:
    config_file = config_dir / "config.toml"
    config_file.write_text("""
[harness]
version = "1"

[profiles]
default = "work"

[profiles.work]
config_dir = "~/.claude-work"
roots = ["~/work"]

[profiles.personal]
config_dir = "~/.claude-personal"
roots = ["~"]
""")
    from lazy_harness.core.config import load_config

    cfg = load_config(config_file)
    assert cfg.profiles.default == "work"
    assert len(cfg.profiles.items) == 2
    assert cfg.profiles.items["work"].roots == ["~/work"]


def test_save_config(config_dir: Path) -> None:
    config_file = config_dir / "config.toml"
    config_file.write_text("""
[harness]
version = "1"
""")
    from lazy_harness.core.config import load_config, save_config

    cfg = load_config(config_file)
    cfg.agent.type = "ollama"
    save_config(cfg, config_file)

    cfg2 = load_config(config_file)
    assert cfg2.agent.type == "ollama"

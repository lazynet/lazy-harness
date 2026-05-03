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


def test_load_config_with_hooks(config_dir: Path) -> None:
    config_file = config_dir / "config.toml"
    config_file.write_text("""
[harness]
version = "1"

[hooks.session_start]
scripts = ["context-inject", "git-status"]

[hooks.session_stop]
scripts = ["session-export"]
""")
    from lazy_harness.core.config import load_config

    cfg = load_config(config_file)
    assert "session_start" in cfg.hooks
    assert cfg.hooks["session_start"].scripts == ["context-inject", "git-status"]
    assert cfg.hooks["session_stop"].scripts == ["session-export"]


def test_load_config_scheduler_jobs(config_dir: Path) -> None:
    config_file = config_dir / "config.toml"
    config_file.write_text("""
[harness]
version = "1"

[scheduler]
backend = "launchd"

[scheduler.jobs.qmd-sync]
schedule = "*/30 * * * *"
command = "/usr/local/bin/lh knowledge sync"

[scheduler.jobs.qmd-embed]
schedule = "0 6 * * *"
command = "/usr/local/bin/lh knowledge embed"
""")
    from lazy_harness.core.config import load_config

    cfg = load_config(config_file)
    assert cfg.scheduler.backend == "launchd"
    assert len(cfg.scheduler.jobs) == 2
    names = {j.name for j in cfg.scheduler.jobs}
    assert names == {"qmd-sync", "qmd-embed"}
    sync_job = next(j for j in cfg.scheduler.jobs if j.name == "qmd-sync")
    assert sync_job.schedule == "*/30 * * * *"
    assert sync_job.command.endswith("lh knowledge sync")


def test_load_config_scheduler_jobs_missing_schedule_raises(config_dir: Path) -> None:
    config_file = config_dir / "config.toml"
    config_file.write_text("""
[harness]
version = "1"

[scheduler.jobs.broken]
command = "/bin/true"
""")
    from lazy_harness.core.config import ConfigError, load_config

    with pytest.raises(ConfigError, match="broken"):
        load_config(config_file)


def test_load_config_scheduler_no_jobs_section(config_dir: Path) -> None:
    config_file = config_dir / "config.toml"
    config_file.write_text("""
[harness]
version = "1"

[scheduler]
backend = "auto"
""")
    from lazy_harness.core.config import load_config

    cfg = load_config(config_file)
    assert cfg.scheduler.jobs == []


def test_load_config_no_hooks_defaults_empty(config_dir: Path) -> None:
    config_file = config_dir / "config.toml"
    config_file.write_text("""
[harness]
version = "1"
""")
    from lazy_harness.core.config import load_config

    cfg = load_config(config_file)
    assert cfg.hooks == {}


def test_config_memory_engram_defaults_when_missing() -> None:
    from lazy_harness.core.config import Config

    cfg = Config()
    assert cfg.memory.engram.enabled is False
    assert cfg.memory.engram.git_sync is True
    assert cfg.memory.engram.cloud is False
    assert cfg.memory.engram.version == "1.15.4"


def test_config_memory_engram_parses_from_toml(config_dir: Path) -> None:
    config_file = config_dir / "config.toml"
    config_file.write_text("""
[harness]
version = "1"

[memory.engram]
enabled = true
cloud = true
version = "1.15.4"
""")
    from lazy_harness.core.config import load_config

    cfg = load_config(config_file)
    assert cfg.memory.engram.enabled is True
    assert cfg.memory.engram.cloud is True
    assert cfg.memory.engram.git_sync is True
    assert cfg.memory.engram.version == "1.15.4"

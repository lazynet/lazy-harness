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


def test_config_memory_engram_binary_defaults_to_empty() -> None:
    from lazy_harness.core.config import Config

    assert Config().memory.engram.binary == ""


def test_config_memory_engram_parses_explicit_binary(config_dir: Path) -> None:
    """PATH is unreliable for hook subprocesses; an explicit path must win."""
    config_file = config_dir / "config.toml"
    config_file.write_text("""
[harness]
version = "1"

[memory.engram]
enabled = true
binary = "/opt/homebrew/bin/engram"
""")
    from lazy_harness.core.config import load_config

    cfg = load_config(config_file)
    assert cfg.memory.engram.binary == "/opt/homebrew/bin/engram"


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


def test_config_knowledge_structure_defaults_when_missing() -> None:
    from lazy_harness.core.config import Config

    cfg = Config()
    assert cfg.knowledge.structure.engine == "graphify"
    assert cfg.knowledge.structure.enabled is False
    assert cfg.knowledge.structure.version == "0.9.38"


def test_config_knowledge_structure_parses_from_toml(config_dir: Path) -> None:
    config_file = config_dir / "config.toml"
    config_file.write_text("""
[harness]
version = "1"

[knowledge.structure]
enabled = true
version = "0.9.38"
""")
    from lazy_harness.core.config import load_config

    cfg = load_config(config_file)
    assert cfg.knowledge.structure.enabled is True
    assert cfg.knowledge.structure.engine == "graphify"
    assert cfg.knowledge.structure.version == "0.9.38"


def test_compound_loop_backend_defaults_when_missing() -> None:
    from lazy_harness.core.config import CompoundLoopConfig, Config

    assert CompoundLoopConfig().backend == "claude"
    assert CompoundLoopConfig().backend_options == {}
    cfg = Config()
    assert cfg.compound_loop.backend == "claude"
    assert cfg.compound_loop.backend_options == {}


def test_compound_loop_backend_parses_from_toml(config_dir: Path) -> None:
    config_file = config_dir / "config.toml"
    config_file.write_text("""
[harness]
version = "1"

[compound_loop]
enabled = true
backend = "openai-compatible"
model = "mistral-nemo"

[compound_loop.backend_options]
base_url = "http://my-gpu-box:11434"
api_key = "sk-test"
""")
    from lazy_harness.core.config import load_config

    cfg = load_config(config_file)
    assert cfg.compound_loop.backend == "openai-compatible"
    assert cfg.compound_loop.backend_options == {
        "base_url": "http://my-gpu-box:11434",
        "api_key": "sk-test",
    }
    assert cfg.compound_loop.model == "mistral-nemo"


def test_compound_loop_backend_defaults_to_claude_when_section_present(
    config_dir: Path,
) -> None:
    config_file = config_dir / "config.toml"
    config_file.write_text("""
[harness]
version = "1"

[compound_loop]
enabled = true
""")
    from lazy_harness.core.config import load_config

    cfg = load_config(config_file)
    assert cfg.compound_loop.backend == "claude"
    assert cfg.compound_loop.backend_options == {}


def test_compound_loop_slim_handoff_parses_from_toml(config_dir: Path) -> None:
    config_file = config_dir / "config.toml"
    config_file.write_text("""
[harness]
version = "1"

[compound_loop]
enabled = true
slim_handoff_enabled = false
""")
    from lazy_harness.core.config import load_config

    cfg = load_config(config_file)
    assert cfg.compound_loop.slim_handoff_enabled is False


def test_context_inject_proposals_summary_defaults_when_missing() -> None:
    from lazy_harness.core.config import Config, ContextInjectConfig

    assert ContextInjectConfig().proposals_summary is True
    cfg = Config()
    assert cfg.context_inject.proposals_summary is True


def test_context_inject_proposals_summary_parses_from_toml(config_dir: Path) -> None:
    config_file = config_dir / "config.toml"
    config_file.write_text("""
[harness]
version = "1"

[context_inject]
max_body_chars = 1500
proposals_summary = false
""")
    from lazy_harness.core.config import load_config

    cfg = load_config(config_file)
    assert cfg.context_inject.max_body_chars == 1500
    assert cfg.context_inject.proposals_summary is False


def test_config_ignores_retired_auto_rebuild_key(config_dir: Path) -> None:
    """Configs written by older wizards must keep loading after the key is retired."""
    config_file = config_dir / "config.toml"
    config_file.write_text("""
[harness]
version = "1"

[knowledge.structure]
engine = "graphify"
enabled = true
auto_rebuild_on_commit = true
version = "0.9.38"
""")
    from lazy_harness.core.config import load_config

    cfg = load_config(config_file)
    assert cfg.knowledge.structure.enabled is True
    assert cfg.knowledge.structure.version == "0.9.38"


def test_knowledge_root_replaces_path(tmp_path: Path) -> None:
    from lazy_harness.core.config import load_config

    cfg_file = tmp_path / "config.toml"
    cfg_file.write_text(
        '[harness]\nversion = "1"\n\n[knowledge]\nroot = "~/repos/lazy/lazy-knowledge"\n',
        encoding="utf-8",
    )
    cfg = load_config(cfg_file)
    assert cfg.knowledge.root == "~/repos/lazy/lazy-knowledge"


def test_legacy_knowledge_path_raises_naming_new_key(tmp_path: Path) -> None:
    from lazy_harness.core.config import ConfigError, load_config

    cfg_file = tmp_path / "config.toml"
    cfg_file.write_text(
        '[harness]\nversion = "1"\n\n[knowledge]\npath = "~/vault/Meta"\n', encoding="utf-8"
    )
    with pytest.raises(ConfigError, match=r"\[knowledge\]\.root"):
        load_config(cfg_file)


def test_legacy_knowledge_subdir_raises(tmp_path: Path) -> None:
    from lazy_harness.core.config import ConfigError, load_config

    cfg_file = tmp_path / "config.toml"
    cfg_file.write_text(
        '[harness]\nversion = "1"\n\n[knowledge]\nroot = "~/k"\n\n'
        '[knowledge.learnings]\nsubdir = "Learnings"\n',
        encoding="utf-8",
    )
    with pytest.raises(ConfigError, match=r"\[knowledge\.learnings\]\.subdir"):
        load_config(cfg_file)


def test_legacy_learnings_subdir_raises(tmp_path: Path) -> None:
    from lazy_harness.core.config import ConfigError, load_config

    cfg_file = tmp_path / "config.toml"
    cfg_file.write_text(
        '[harness]\nversion = "1"\n\n[knowledge]\nroot = "~/k"\n\n'
        '[compound_loop]\nlearnings_subdir = "Learnings"\n',
        encoding="utf-8",
    )
    with pytest.raises(ConfigError, match=r"\[compound_loop\]\.learnings_subdir"):
        load_config(cfg_file)


def test_compound_loop_lazymind_dir_survives(tmp_path: Path) -> None:
    from lazy_harness.core.config import load_config

    cfg_file = tmp_path / "config.toml"
    cfg_file.write_text(
        '[harness]\nversion = "1"\n\n[knowledge]\nroot = "~/k"\n\n'
        '[compound_loop]\nlazymind_dir = "~/vault"\n',
        encoding="utf-8",
    )
    cfg = load_config(cfg_file)
    assert cfg.compound_loop.lazymind_dir == "~/vault"


def test_structure_config_parses_the_repo_list(tmp_path) -> None:
    """Graph rebuilds need to know which repos to walk."""
    from lazy_harness.core.config import load_config

    cfg_path = tmp_path / "config.toml"
    cfg_path.write_text(
        '[harness]\nversion = "1"\n'
        "[knowledge.structure]\n"
        "enabled = true\n"
        'repos = ["~/repos/lazy/lazy-harness", "~/repos/flex/ydi-data-layer"]\n'
    )

    cfg = load_config(cfg_path)

    assert cfg.knowledge.structure.repos == [
        "~/repos/lazy/lazy-harness",
        "~/repos/flex/ydi-data-layer",
    ]


def test_structure_config_repo_list_defaults_to_empty(tmp_path) -> None:
    from lazy_harness.core.config import load_config

    cfg_path = tmp_path / "config.toml"
    cfg_path.write_text('[harness]\nversion = "1"\n[knowledge.structure]\nenabled = true\n')

    assert load_config(cfg_path).knowledge.structure.repos == []


def test_hook_event_external_command_string_parses(tmp_path) -> None:
    """A bare string under `external` is a command using the event's default matcher."""
    from lazy_harness.core.config import load_config

    cfg_path = tmp_path / "config.toml"
    cfg_path.write_text(
        '[harness]\nversion = "1"\n'
        "[hooks.session_start]\n"
        'scripts = ["context-inject"]\n'
        'external = ["/opt/homebrew/bin/moshi claude-hook"]\n'
    )

    event = load_config(cfg_path).hooks["session_start"]

    assert event.scripts == ["context-inject"]
    assert len(event.external) == 1
    assert event.external[0].command == "/opt/homebrew/bin/moshi claude-hook"
    assert event.external[0].matcher is None


def test_hook_event_external_table_carries_matcher(tmp_path) -> None:
    """An external entry may pin its own matcher instead of the event default."""
    from lazy_harness.core.config import load_config

    cfg_path = tmp_path / "config.toml"
    cfg_path.write_text(
        '[harness]\nversion = "1"\n'
        "[[hooks.pre_tool_use.external]]\n"
        'command = "/opt/homebrew/bin/moshi claude-hook"\n'
        'matcher = "AskUserQuestion"\n'
    )

    external = load_config(cfg_path).hooks["pre_tool_use"].external

    assert [(e.command, e.matcher) for e in external] == [
        ("/opt/homebrew/bin/moshi claude-hook", "AskUserQuestion")
    ]


def test_external_hooks_survive_a_full_save_load_cycle(tmp_path) -> None:
    """Round-trip, not just write: a field save_config drops is a silent data loss."""
    from lazy_harness.core.config import load_config, save_config

    cfg_path = tmp_path / "config.toml"
    cfg_path.write_text(
        '[harness]\nversion = "1"\n'
        "[[hooks.post_tool_use.external]]\n"
        'command = "/opt/homebrew/bin/moshi claude-hook"\n'
        'matcher = "ExitPlanMode"\n'
    )

    save_config(load_config(cfg_path), cfg_path)
    external = load_config(cfg_path).hooks["post_tool_use"].external

    assert [(e.command, e.matcher) for e in external] == [
        ("/opt/homebrew/bin/moshi claude-hook", "ExitPlanMode")
    ]

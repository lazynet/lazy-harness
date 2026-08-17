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


def test_context_inject_repo_map_scope_defaults_to_disabled() -> None:
    """Opt-in: no scope means the section never renders."""
    from lazy_harness.core.config import Config, ContextInjectConfig

    assert ContextInjectConfig().repo_map_scope == ""
    assert Config().context_inject.repo_map_scope == ""


def test_context_inject_repo_map_parses_from_toml(config_dir: Path) -> None:
    config_file = config_dir / "config.toml"
    config_file.write_text("""
[harness]
version = "1"

[context_inject]
repo_map_scope = "~/repos/lazy"
repo_map_doc = "docs/otro.md"
repo_map_max_chars = 2400
""")
    from lazy_harness.core.config import load_config

    cfg = load_config(config_file)
    assert cfg.context_inject.repo_map_scope == "~/repos/lazy"
    assert cfg.context_inject.repo_map_doc == "docs/otro.md"
    assert cfg.context_inject.repo_map_max_chars == 2400


def test_context_inject_repo_map_survives_round_trip(config_dir: Path) -> None:
    """save → load → save → load must not drop the scope on the second rewrite."""
    from lazy_harness.core.config import Config, load_config, save_config

    config_file = config_dir / "config.toml"
    cfg = Config()
    cfg.context_inject.repo_map_scope = "~/repos/lazy"
    cfg.context_inject.repo_map_max_chars = 2400
    save_config(cfg, config_file)

    reloaded = load_config(config_file)
    assert reloaded.context_inject.repo_map_scope == "~/repos/lazy"

    save_config(reloaded, config_file)
    again = load_config(config_file)
    assert again.context_inject.repo_map_scope == "~/repos/lazy"
    assert again.context_inject.repo_map_doc == "docs/repos.md"
    assert again.context_inject.repo_map_max_chars == 2400


_FULL_CONFIG = """\
[harness]
version = "1"

[agent]
type = "claude-code"

[profiles]
default = "lazy"

[profiles.lazy]
config_dir = "~/.claude-lazy"
roots = ["~/repos/lazy"]
lazynorth_doc = "LazyNorth.md"

[profiles.flex]
config_dir = "~/.claude-flex"
roots = ["~/repos/flex"]
lazynorth_doc = "FlexNorth.md"

[knowledge]
root = "~/repos/lazy/lazy-knowledge"

[knowledge.sessions]
enabled = true

[knowledge.learnings]
enabled = true

[knowledge.search]
engine = "qmd"

[knowledge.structure]
engine = "graphify"
enabled = true
version = "0.9.38"
repos = ["~/repos/lazy/lazy-harness"]

[memory.engram]
enabled = true
git_sync = true
cloud = false
version = "1.15.4"
binary = "/usr/local/bin/engram"

[monitoring]
enabled = true
db = "~/.local/share/lazy-harness/metrics.db"

[scheduler]
backend = "auto"

[scheduler.jobs.qmd-sync]
schedule = "0 */6 * * *"
command = "qmd sync"

[scheduler.jobs.metrics-ingest]
schedule = "*/30 * * * *"
command = "lh metrics ingest"

[hooks.session_start]
scripts = ["context-inject"]

[hooks.pre_tool_use]
scripts = ["pre-tool-use-security"]
allow_patterns = ["rm -rf ./build"]

[compound_loop]
enabled = true
model = "claude-haiku-4-5-20251001"
min_messages = 4
slim_handoff_enabled = true

[lazynorth]
enabled = true
path = "~/LazyMind/LazyNorth.md"
universal_doc = "LazyNorth.md"

[context_inject]
enabled = true
max_body_chars = 12000
qmd_suggest_enabled = false
qmd_suggest_top_k = 7
graphify_surface_enabled = false

[loops]
inject_goal_prompt = true
"""


def _flat_keys(data: dict, prefix: str = "") -> set[str]:
    """Every dotted key path in a parsed TOML document, tables included."""
    out: set[str] = set()
    for key, value in data.items():
        path = f"{prefix}{key}"
        out.add(path)
        if isinstance(value, dict):
            out |= _flat_keys(value, path + ".")
    return out


def test_save_config_preserves_every_key_it_did_not_change(tmp_path: Path) -> None:
    """save_config must not drop sections the serializer does not model.

    Measured against the live config before this fix: 51 keys were lost per
    write, including all six declared scheduler jobs.
    """
    import tomllib

    from lazy_harness.core.config import load_config, save_config

    cfg_path = tmp_path / "config.toml"
    cfg_path.write_text(_FULL_CONFIG)
    before = _flat_keys(tomllib.loads(cfg_path.read_text()))

    save_config(load_config(cfg_path), cfg_path)

    after = _flat_keys(tomllib.loads(cfg_path.read_text()))
    lost = sorted(before - after)
    assert not lost, f"save_config dropped {len(lost)} keys: {lost}"


def test_save_config_preserves_comments(tmp_path: Path) -> None:
    """Config is hand-edited and version-controlled; comments carry rationale.

    The live config has seven comment lines explaining why the engram MCP is
    off and why the graphify sweep exists. `cli/knowledge_cmd.py:_write_repo_list`
    hand-edits a single line specifically to avoid losing them.
    """
    from lazy_harness.core.config import load_config, save_config

    cfg_path = tmp_path / "config.toml"
    cfg_path.write_text(
        "# top-of-file rationale\n"
        + _FULL_CONFIG
        + "\n# why this sweep exists\n[scheduler.jobs.graphify-update]\n"
        + 'schedule = "0 3 * * *"\ncommand = "lh knowledge graph update"\n'
    )

    save_config(load_config(cfg_path), cfg_path)

    text = cfg_path.read_text()
    assert "# top-of-file rationale" in text
    assert "# why this sweep exists" in text


def test_save_load_save_load_is_stable(tmp_path: Path) -> None:
    """save -> load -> save -> load must reach the same document as one cycle.

    A field the loader defaults and the writer omits survives the first
    rewrite and vanishes on the second, so one round trip cannot see it.
    """
    import tomllib

    from lazy_harness.core.config import load_config, save_config

    cfg_path = tmp_path / "config.toml"
    cfg_path.write_text(_FULL_CONFIG)

    save_config(load_config(cfg_path), cfg_path)
    once = tomllib.loads(cfg_path.read_text())

    save_config(load_config(cfg_path), cfg_path)
    twice = tomllib.loads(cfg_path.read_text())

    assert once == twice


def test_context_inject_qmd_and_graphify_switches_are_read(tmp_path: Path) -> None:
    """These three are consumed by context_inject.py:779,787,790 and were never parsed.

    Declared on the dataclass, read by a live hook, and pinned to their
    defaults because the loader skipped them.
    """
    from lazy_harness.core.config import load_config

    cfg_path = tmp_path / "config.toml"
    cfg_path.write_text(
        '[harness]\nversion = "1"\n\n'
        "[context_inject]\n"
        "qmd_suggest_enabled = false\n"
        "qmd_suggest_top_k = 7\n"
        "graphify_surface_enabled = false\n"
    )

    ci = load_config(cfg_path).context_inject
    assert ci.qmd_suggest_enabled is False
    assert ci.qmd_suggest_top_k == 7
    assert ci.graphify_surface_enabled is False


def test_removing_a_profile_survives_a_save(tmp_path: Path) -> None:
    """`lh profile remove` expresses deletion by absence; the overlay must honour it.

    Applying an overlay can only add or overwrite, so without an explicit
    prune the removed profile comes back on the next write.
    """
    import tomllib

    from lazy_harness.core.config import load_config, save_config

    cfg_path = tmp_path / "config.toml"
    cfg_path.write_text(_FULL_CONFIG)

    cfg = load_config(cfg_path)
    del cfg.profiles.items["flex"]
    save_config(cfg, cfg_path)

    raw = tomllib.loads(cfg_path.read_text())
    assert "flex" not in raw["profiles"]
    assert "lazy" in raw["profiles"]
    assert raw["profiles"]["lazy"]["lazynorth_doc"] == "LazyNorth.md"


def test_save_config_does_not_materialise_defaults_the_user_never_set(tmp_path: Path) -> None:
    """Writing today's defaults into the file freezes them.

    ADR-018's invariant is that an upgrade changes no behaviour. If
    `save_config` bakes in every default, a later release that changes one
    never reaches a user whose file now pins the old value.
    """
    import tomllib

    from lazy_harness.core.config import load_config, save_config

    cfg_path = tmp_path / "config.toml"
    cfg_path.write_text('[harness]\nversion = "1"\n\n[monitoring]\nenabled = true\n')

    save_config(load_config(cfg_path), cfg_path)

    raw = tomllib.loads(cfg_path.read_text())
    assert "classify_rules" not in raw.get("knowledge", {})
    assert "search" not in raw.get("knowledge", {})
    assert "loops" not in raw
    assert "backend_options" not in raw.get("compound_loop", {})
    assert raw["monitoring"]["enabled"] is True


def test_save_config_leaves_unchanged_values_byte_identical(tmp_path: Path) -> None:
    """A value the Config did not change must not be reformatted.

    tomlkit re-serialises whatever it is assigned, so assigning an unchanged
    value rewrites multi-line arrays as inline ones and churns the diff.
    """
    from lazy_harness.core.config import load_config, save_config

    original = (
        '[harness]\nversion = "1"\n\n'
        "[profiles]\n"
        'default = "lazy"\n\n'
        "[profiles.lazy]\n"
        'config_dir = "~/.claude-lazy"\n'
        "roots = [\n"
        '    "~/repos/lazy",\n'
        '    "~/repos/other",\n'
        "]\n"
    )
    cfg_path = tmp_path / "config.toml"
    cfg_path.write_text(original)

    save_config(load_config(cfg_path), cfg_path)

    text = cfg_path.read_text()
    assert "roots = [\n" in text
    assert '    "~/repos/lazy",\n' in text


def test_a_config_written_from_scratch_loads_back(tmp_path: Path) -> None:
    """Writing to a path that does not exist must produce a loadable file.

    `[harness].version` equals its default, so a rule that skips defaults
    omits it and `load_config` then rejects the result. Verified through a
    full load cycle, not just a successful write.
    """
    from lazy_harness.core.config import Config, load_config, save_config

    cfg_path = tmp_path / "fresh" / "config.toml"
    save_config(Config(), cfg_path)

    assert cfg_path.is_file()
    reloaded = load_config(cfg_path)
    assert reloaded.harness.version == "1"


def test_shorthand_external_hooks_round_trip_without_reformatting(tmp_path: Path) -> None:
    """`external = ["cmd"]` must come back as `external = ["cmd"]`.

    The parser accepts a bare string (matcher inherited) or a table (matcher
    pinned). The writer emitted the table form for both, so every save
    rewrote the shorthand into an array of tables — semantically identical,
    but it churns a version-controlled file on every write.
    """
    from lazy_harness.core.config import load_config, save_config

    original = (
        '[harness]\nversion = "1"\n\n'
        "[hooks.session_start]\n"
        'scripts = ["context-inject"]\n'
        'external = ["/opt/homebrew/bin/moshi claude-hook"]\n'
    )
    cfg_path = tmp_path / "config.toml"
    cfg_path.write_text(original)

    save_config(load_config(cfg_path), cfg_path)

    text = cfg_path.read_text()
    assert 'external = ["/opt/homebrew/bin/moshi claude-hook"]' in text
    assert "[[hooks.session_start.external]]" not in text


def test_external_hook_with_a_matcher_still_uses_the_table_form(tmp_path: Path) -> None:
    """A pinned matcher has no shorthand, so it must stay a table."""
    import tomllib

    from lazy_harness.core.config import load_config, save_config

    cfg_path = tmp_path / "config.toml"
    cfg_path.write_text(
        '[harness]\nversion = "1"\n\n'
        "[hooks.pre_tool_use]\n"
        'scripts = ["pre-tool-use-security"]\n'
        'external = [{ command = "moshi claude-hook", matcher = "ExitPlanMode" }]\n'
    )

    save_config(load_config(cfg_path), cfg_path)

    entry = tomllib.loads(cfg_path.read_text())["hooks"]["pre_tool_use"]["external"][0]
    assert entry == {"command": "moshi claude-hook", "matcher": "ExitPlanMode"}


def test_an_event_with_no_scripts_key_does_not_gain_an_empty_one(tmp_path: Path) -> None:
    """An event declaring only `external` must not sprout `scripts = []`."""
    import tomllib

    from lazy_harness.core.config import load_config, save_config

    cfg_path = tmp_path / "config.toml"
    cfg_path.write_text(
        '[harness]\nversion = "1"\n\n'
        "[hooks.permission_request]\n"
        'external = ["moshi claude-hook"]\n'
    )

    save_config(load_config(cfg_path), cfg_path)

    event = tomllib.loads(cfg_path.read_text())["hooks"]["permission_request"]
    assert "scripts" not in event

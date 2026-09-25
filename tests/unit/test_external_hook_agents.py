"""`[hooks.<event>].external` entries can be scoped to named agents.

The graph-assist design (`specs/designs/2026-09-24-graph-assist-design.md`
§3.3) keeps graphify's upstream search guard on Codex only, as the control
group, while Claude Code gets the harness builtin instead. `config.toml` is
shared across profiles, so the scoping has to live on the entry itself and be
enforced by deploy against the profile's *resolved* agent.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from lazy_harness.core.config import (
    Config,
    ConfigError,
    ExternalHookConfig,
    HookEventConfig,
    ProfileEntry,
    load_config,
    save_config,
)

_HEADER = '[harness]\nversion = "1"\n'


def _write(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "config.toml"
    path.write_text(_HEADER + body)
    return path


def test_external_table_carries_agents(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        "[[hooks.pre_tool_use.external]]\n"
        'command = "graphify hook-guard search"\n'
        'matcher = "Bash|Grep"\n'
        'agents = ["codex"]\n',
    )

    [entry] = load_config(path).hooks["pre_tool_use"].external

    assert entry.agents == ["codex"]


def test_external_without_agents_means_every_agent(tmp_path: Path) -> None:
    path = _write(tmp_path, '[hooks.pre_tool_use]\nexternal = ["graphify hook-guard read"]\n')

    [entry] = load_config(path).hooks["pre_tool_use"].external

    assert entry.agents == []


def test_misspelled_agent_names_the_value_and_the_known_names(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        "[[hooks.pre_tool_use.external]]\n"
        'command = "graphify hook-guard search"\n'
        'agents = ["codx"]\n',
    )

    with pytest.raises(ConfigError, match=r"'codx'.*claude-code.*codex"):
        load_config(path)


@pytest.mark.parametrize("raw", ['"codex"', "[1]", "true"])
def test_agents_of_the_wrong_type_is_refused(tmp_path: Path, raw: str) -> None:
    path = _write(
        tmp_path,
        f'[[hooks.pre_tool_use.external]]\ncommand = "x"\nagents = {raw}\n',
    )

    with pytest.raises(ConfigError, match=r"'agents' must be a list of agent names"):
        load_config(path)


def _cycle(path: Path) -> list[ExternalHookConfig]:
    for _ in range(2):
        save_config(load_config(path), path)
    return load_config(path).hooks["pre_tool_use"].external


def test_agents_survive_two_save_load_cycles_on_an_existing_file(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        "# kept comment\n"
        "[hooks.pre_tool_use]\n"
        "external = [\n"
        '  { command = "graphify hook-guard search", matcher = "Bash|Grep", agents = ["codex"] },\n'
        '  "graphify hook-guard read",\n'
        "]\n",
    )

    external = _cycle(path)

    assert [(e.command, e.matcher, e.agents) for e in external] == [
        ("graphify hook-guard search", "Bash|Grep", ["codex"]),
        ("graphify hook-guard read", None, []),
    ]
    text = path.read_text()
    assert "# kept comment" in text
    # The matcher-less, agent-less entry keeps its shorthand.
    assert '"graphify hook-guard read"' in text


def test_agents_survive_two_save_load_cycles_on_a_new_file(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    cfg = Config()
    cfg.hooks = {
        "pre_tool_use": HookEventConfig(
            external=[ExternalHookConfig(command="g search", agents=["codex"])]
        )
    }
    save_config(cfg, path)

    external = _cycle(path)

    assert [(e.command, e.matcher, e.agents) for e in external] == [("g search", None, ["codex"])]


def _two_agent_cfg() -> Config:
    cfg = Config()
    cfg.profiles.default = "cl"
    cfg.profiles.items = {
        "cl": ProfileEntry(config_dir="~/.claude-cl", agent="claude-code"),
        "cx": ProfileEntry(config_dir="~/.codex-cx", agent="codex"),
    }
    cfg.hooks = {
        "pre_tool_use": HookEventConfig(
            scripts=[],
            external=[
                ExternalHookConfig(command="graphify hook-guard search", agents=["codex"]),
                ExternalHookConfig(command="graphify hook-guard read"),
            ],
        )
    }
    return cfg


def _commands(entries: dict) -> list[str]:
    return [e.command for e in entries.get("pre_tool_use", [])]


def test_deploy_emits_a_scoped_external_only_to_its_agents(
    capsys: pytest.CaptureFixture[str],
) -> None:
    from lazy_harness.deploy.engine import _hook_entries_for

    cfg = _two_agent_cfg()

    claude = _commands(_hook_entries_for(cfg, "cl", "lh"))
    codex = _commands(_hook_entries_for(cfg, "cx", "lh"))

    assert "graphify hook-guard search" not in claude
    assert "graphify hook-guard read" in claude
    assert "graphify hook-guard search" in codex
    assert "graphify hook-guard read" in codex
    assert (
        "· graphify hook-guard search omitted in 'cl': declared for agents codex"
        in capsys.readouterr().out
    )

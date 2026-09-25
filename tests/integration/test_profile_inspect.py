"""Effective profile inspection agrees with temporary native deployments."""

from __future__ import annotations

import json
import tomllib
from pathlib import Path

import pytest
from click.testing import CliRunner

from lazy_harness.cli.main import cli
from lazy_harness.core.config import (
    Config,
    ExternalHookConfig,
    HarnessConfig,
    HookEventConfig,
    ProfileEntry,
    ProfilesConfig,
    load_config,
    save_config,
)
from lazy_harness.core.paths import config_dir


def _configure(home_dir: Path, agent: str) -> tuple[str, Path]:
    name = f"{'claude' if agent == 'claude-code' else agent}-personal"
    runtime = home_dir / f".{name}"
    source = config_dir() / "profiles" / "personal"
    (source / "shared").mkdir(parents=True)
    (source / "shared" / "skills" / "example").mkdir(parents=True)
    (source / "shared" / "skills" / "example" / "SKILL.md").write_text("# Example\n")
    cfg = Config(
        harness=HarnessConfig(version="1"),
        profiles=ProfilesConfig(
            default=name,
            items={name: ProfileEntry(config_dir=str(runtime), agent=agent, identity="personal")},
        ),
    )
    cfg.hooks = {
        "pre_tool_use": HookEventConfig(
            scripts=[],
            external=[ExternalHookConfig(command="echo {profile}")],
        ),
        "session_stop": HookEventConfig(scripts=["stop-verify-guard"]),
    }
    save_config(cfg, config_dir() / "config.toml")
    return name, runtime


@pytest.mark.parametrize("agent", ["claude-code", "codex"])
@pytest.mark.parametrize("detected_servers", [False, True])
def test_inspect_agrees_with_native_temporary_deploy(
    home_dir: Path, monkeypatch: pytest.MonkeyPatch, agent: str, detected_servers: bool
) -> None:
    from lazy_harness.deploy import engine

    servers = {"example": {"command": "example-mcp"}} if detected_servers else {}
    monkeypatch.setattr(engine, "_collect_mcp_servers", lambda cfg: servers)
    name, runtime = _configure(home_dir, agent)
    runner = CliRunner()
    inspected = runner.invoke(cli, ["profile", "inspect", name, "--json"])
    assert inspected.exit_code == 0, inspected.output
    info = json.loads(inspected.output)
    assert info["profile"] == name
    assert info["agent"] == agent
    assert info["identity"] == "personal"
    assert info["source_dir"] == str(config_dir() / "profiles" / "personal")
    assert info["runtime_dir"] == str(runtime)
    assert info["observed"] == "unknown"
    assert info["deployed"] == "unknown"
    assert info["suppressed_defaults"]["pre_tool_use"]
    assert [h["command"] for h in info["hooks"]["pre_tool_use"]] == ["echo " + name]
    assert info["system_docs"]["available"] is False
    assert info["skills"]["available"] is True
    if agent == "codex":
        assert any(gap["hook"] == "stop-verify-guard" for gap in info["omissions"]["signal"])
        assert "session_stop" not in info["hooks"]

    deployed = runner.invoke(cli, ["deploy", "--profile", name])
    assert deployed.exit_code == 0, deployed.output
    if agent == "claude-code":
        from lazy_harness.agents.claude_code import _as_document

        native = json.loads((runtime / "settings.json").read_text())
        assert _as_document((runtime / "settings.json").read_text()) == native
        commands = [
            hook["command"]
            for groups in native["hooks"].values()
            for group in groups
            for hook in group["hooks"]
        ]
    else:
        from lazy_harness.agents.codex import _parse_hooks_document

        native = json.loads((runtime / "hooks.json").read_text())
        assert _parse_hooks_document((runtime / "hooks.json").read_text()) == native
        config_path = runtime / "config.toml"
        assert config_path.exists() is detected_servers
        if detected_servers:
            assert tomllib.loads(config_path.read_text())["mcp_servers"] == servers
        commands = [
            hook["command"]
            for groups in native["hooks"].values()
            for group in groups
            for hook in group["hooks"]
        ]
    expected = [hook["command"] for entries in info["hooks"].values() for hook in entries]
    assert sorted(commands) == sorted(expected)

    after = runner.invoke(cli, ["profile", "inspect", name, "--json"])
    assert after.exit_code == 0, after.output
    wired = json.loads(after.output)
    assert all(
        hook["deployed"] == "deployed" for entries in wired["hooks"].values() for hook in entries
    )

    path = runtime / ("settings.json" if agent == "claude-code" else "hooks.json")
    document = json.loads(path.read_text())
    native_event = next(iter(document["hooks"]))
    document["hooks"][native_event][0]["matcher"] = "ImpossibleMatcher"
    path.write_text(json.dumps(document))
    stale = runner.invoke(cli, ["profile", "inspect", name, "--json"])
    assert stale.exit_code == 0, stale.output
    drifted = json.loads(stale.output)
    assert any(
        hook["deployed"] == "drift" for entries in drifted["hooks"].values() for hook in entries
    )

    document["hooks"][native_event][0]["hooks"][0]["command"] = "echo stale"
    path.write_text(json.dumps(document))
    missing = runner.invoke(cli, ["profile", "inspect", name, "--json"])
    assert missing.exit_code == 0, missing.output
    stale_command = json.loads(missing.output)
    assert any(
        hook["deployed"] == "missing"
        for entries in stale_command["hooks"].values()
        for hook in entries
    )
    assert any(hook["command"] == "echo stale" for hook in stale_command["runtime_only_hooks"])

    path.write_text(json.dumps({}))
    empty = runner.invoke(cli, ["profile", "inspect", name, "--json"])
    assert empty.exit_code == 0, empty.output
    empty_runtime = json.loads(empty.output)
    assert empty_runtime["deployed"] == "drift"
    assert all(
        hook["deployed"] == "missing"
        for entries in empty_runtime["hooks"].values()
        for hook in entries
    )

    path.write_text("{invalid")
    unreadable = runner.invoke(cli, ["profile", "inspect", name, "--json"])
    assert unreadable.exit_code == 0, unreadable.output
    broken = json.loads(unreadable.output)
    assert broken["deployed"] == "unreadable"


def test_inspect_default_and_readable_output(home_dir: Path) -> None:
    name, _ = _configure(home_dir, "claude-code")
    result = CliRunner().invoke(cli, ["profile", "inspect"])
    assert result.exit_code == 0, result.output
    assert name in result.output
    assert "Suppressed defaults" in result.output
    assert "unknown" in result.output


def test_inspect_unknown_profile_is_diagnostic(home_dir: Path) -> None:
    name, _ = _configure(home_dir, "codex")
    result = CliRunner().invoke(cli, ["profile", "inspect", "typo", "--json"])
    assert result.exit_code != 0
    assert "typo" in result.output
    assert name in result.output


def test_inspect_names_agent_scoped_omissions(home_dir: Path) -> None:
    name, _ = _configure(home_dir, "codex")
    path = config_dir() / "config.toml"
    cfg = load_config(path)
    cfg.hooks["pre_tool_use"].scripts = ["pre-tool-use-graph-assist"]
    cfg.hooks["pre_tool_use"].external.append(
        ExternalHookConfig(command="echo claude-only", agents=["claude-code"])
    )
    save_config(cfg, path)

    result = CliRunner().invoke(cli, ["profile", "inspect", name, "--json"])
    assert result.exit_code == 0, result.output
    info = json.loads(result.output)
    assert {row["hook"] for row in info["omissions"]["agent"]} == {"pre-tool-use-graph-assist"}
    assert {row["command"] for row in info["omissions"]["external_agent"]} == {"echo claude-only"}
    assert [row["command"] for row in info["hooks"]["pre_tool_use"]] == ["echo " + name]


def test_inspect_uses_native_matcher_resolution(
    home_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from lazy_harness.agents.claude_code import ClaudeCodeAdapter

    name, _ = _configure(home_dir, "claude-code")
    original = ClaudeCodeAdapter._generate_hook_config

    def changed(self: ClaudeCodeAdapter, hooks: dict) -> dict:
        native = original(self, hooks)
        native["PreToolUse"][0]["matcher"] = "DifferentMatcher"
        return native

    monkeypatch.setattr(ClaudeCodeAdapter, "_generate_hook_config", changed)
    result = CliRunner().invoke(cli, ["profile", "inspect", name, "--json"])
    assert result.exit_code == 0, result.output
    info = json.loads(result.output)
    assert info["hooks"]["pre_tool_use"][0]["matcher"] == "DifferentMatcher"


@pytest.mark.parametrize("agent", ["claude-code", "codex"])
def test_empty_override_reports_stale_managed_runtime_hooks(home_dir: Path, agent: str) -> None:
    name, runtime = _configure(home_dir, agent)
    path = config_dir() / "config.toml"
    cfg = load_config(path)
    del cfg.hooks["pre_tool_use"]
    save_config(cfg, path)
    deployed = CliRunner().invoke(cli, ["deploy", "--profile", name])
    assert deployed.exit_code == 0, deployed.output

    cfg = load_config(path)
    cfg.hooks["pre_tool_use"] = HookEventConfig(scripts=[])
    save_config(cfg, path)
    result = CliRunner().invoke(cli, ["profile", "inspect", name, "--json"])
    assert result.exit_code == 0, result.output
    info = json.loads(result.output)
    assert info["hooks"].get("pre_tool_use", []) == []
    assert info["deployed"] == "drift"
    assert any(row["ownership"] == "managed" for row in info["runtime_only_hooks"])
    assert (runtime / ("settings.json" if agent == "claude-code" else "hooks.json")).exists()


def test_claude_prompt_and_agent_hooks_are_valid_runtime_only(home_dir: Path) -> None:
    name, runtime = _configure(home_dir, "claude-code")
    deployed = CliRunner().invoke(cli, ["deploy", "--profile", name])
    assert deployed.exit_code == 0, deployed.output
    path = runtime / "settings.json"
    native = json.loads(path.read_text())
    native["hooks"].setdefault("PreToolUse", []).extend(
        [
            {"matcher": "Bash", "hooks": [{"type": "prompt", "prompt": "Review this call"}]},
            {"matcher": "Bash", "hooks": [{"type": "agent", "prompt": "Review this call"}]},
        ]
    )
    path.write_text(json.dumps(native))
    result = CliRunner().invoke(cli, ["profile", "inspect", name, "--json"])
    assert result.exit_code == 0, result.output
    info = json.loads(result.output)
    assert info["deployed"] == "deployed"
    assert {row["type"] for row in info["runtime_only_hooks"]} == {"prompt", "agent"}
    assert all(row["ownership"] == "unknown" for row in info["runtime_only_hooks"])
    redeployed = CliRunner().invoke(cli, ["deploy", "--profile", name])
    assert redeployed.exit_code == 0, redeployed.output
    native_after = json.loads(path.read_text())
    assert {
        hook["type"]
        for group in native_after["hooks"]["PreToolUse"]
        for hook in group["hooks"]
        if hook["type"] in {"prompt", "agent"}
    } == {"prompt", "agent"}


def test_composed_system_doc_sources_are_available_before_deploy(home_dir: Path) -> None:
    name, runtime = _configure(home_dir, "codex")
    source = config_dir() / "profiles" / "personal"
    (source / "head.md").write_text("# Head\n")
    (source / "tail.md").write_text("# Tail\n")
    common = config_dir() / "profiles" / "_common"
    common.mkdir()
    (common / "common.md").write_text("# Common\n")

    before = CliRunner().invoke(cli, ["profile", "inspect", name, "--json"])
    assert before.exit_code == 0, before.output
    info = json.loads(before.output)
    assert info["system_docs"]["available"] is True
    assert info["system_docs"]["sources"] == [
        str(source / "head.md"),
        str(common / "common.md"),
        str(source / "tail.md"),
    ]
    deployed = CliRunner().invoke(cli, ["deploy", "--profile", name])
    assert deployed.exit_code == 0, deployed.output
    assert (runtime / "AGENTS.md").is_file()


def test_unreadable_runtime_is_not_unknown(home_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    name, runtime = _configure(home_dir, "codex")
    path = runtime / "hooks.json"
    original_exists = Path.exists
    original_read_text = Path.read_text

    def denied_exists(self: Path) -> bool:
        if self == path:
            raise AssertionError("native path must be read directly")
        return original_exists(self)

    def denied_read(self: Path, *args: object, **kwargs: object) -> str:
        if self == path:
            raise PermissionError(path)
        return original_read_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "exists", denied_exists)
    monkeypatch.setattr(Path, "read_text", denied_read)
    result = CliRunner().invoke(cli, ["profile", "inspect", name, "--json"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["deployed"] == "unreadable"


@pytest.mark.parametrize("agent", ["claude-code", "codex"])
def test_foreign_group_before_managed_hooks_preserves_deployment_match(
    home_dir: Path, agent: str
) -> None:
    name, runtime = _configure(home_dir, agent)
    path = runtime / ("settings.json" if agent == "claude-code" else "hooks.json")
    native_event = "PreToolUse"
    foreign = {"matcher": "Bash", "hooks": [{"type": "command", "command": "echo foreign"}]}
    deployed = CliRunner().invoke(cli, ["deploy", "--profile", name])
    assert deployed.exit_code == 0, deployed.output
    native = json.loads(path.read_text())
    native["hooks"][native_event].insert(0, foreign)
    path.write_text(json.dumps(native))

    inspected = CliRunner().invoke(cli, ["profile", "inspect", name, "--json"])
    assert inspected.exit_code == 0, inspected.output
    info = json.loads(inspected.output)
    assert all(row["deployed"] == "deployed" for rows in info["hooks"].values() for row in rows)
    assert info["deployed"] == "deployed"
    assert any(row["command"] == "echo foreign" for row in info["runtime_only_hooks"])
    redeployed = CliRunner().invoke(cli, ["deploy", "--profile", name])
    assert redeployed.exit_code == 0, redeployed.output
    native_after = json.loads(path.read_text())
    assert any(
        hook["command"] == "echo foreign"
        for group in native_after["hooks"][native_event]
        for hook in group["hooks"]
    )


def test_invalid_ownership_ledger_is_unknown_not_crash(home_dir: Path) -> None:
    name, runtime = _configure(home_dir, "claude-code")
    deployed = CliRunner().invoke(cli, ["deploy", "--profile", name])
    assert deployed.exit_code == 0, deployed.output
    (runtime / "lh-hook-ownership.json").write_bytes(b"\xff")

    result = CliRunner().invoke(cli, ["profile", "inspect", name, "--json"])
    assert result.exit_code == 0, result.output
    info = json.loads(result.output)
    assert info["deployed"] == "deployed"
    assert info["observed"] == "unknown"

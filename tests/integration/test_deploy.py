"""Integration tests for lh deploy."""

from __future__ import annotations

from pathlib import Path

from click.testing import CliRunner

from lazy_harness.cli.main import cli
from lazy_harness.core.config import (
    Config,
    HarnessConfig,
    HookEventConfig,
    ProfileEntry,
    ProfilesConfig,
    save_config,
)


def _setup_with_profile_content(home_dir: Path) -> Path:
    """Create config + profile content to deploy."""
    config_path = home_dir / ".config" / "lazy-harness" / "config.toml"
    profile_content_dir = home_dir / ".config" / "lazy-harness" / "profiles" / "personal"
    profile_content_dir.mkdir(parents=True)
    (profile_content_dir / "CLAUDE.md").write_text("# My profile\n")
    (profile_content_dir / "settings.json").write_text("{}\n")

    target_dir = home_dir / ".claude-personal"

    cfg = Config(
        harness=HarnessConfig(version="1"),
        profiles=ProfilesConfig(
            default="personal",
            items={
                "personal": ProfileEntry(
                    config_dir=str(target_dir),
                    roots=["~"],
                ),
            },
        ),
    )
    save_config(cfg, config_path)
    return config_path


def test_deploy_creates_profile_symlinks(home_dir: Path) -> None:
    _setup_with_profile_content(home_dir)
    runner = CliRunner()
    result = runner.invoke(cli, ["deploy"])
    assert result.exit_code == 0

    target = home_dir / ".claude-personal"
    assert target.is_dir()
    claude_md = target / "CLAUDE.md"
    assert claude_md.exists()
    assert claude_md.is_symlink()


def test_deploy_idempotent(home_dir: Path) -> None:
    _setup_with_profile_content(home_dir)
    runner = CliRunner()
    runner.invoke(cli, ["deploy"])
    result = runner.invoke(cli, ["deploy"])
    assert result.exit_code == 0


def test_deploy_generates_hooks_in_settings(home_dir: Path) -> None:
    import json

    config_path = home_dir / ".config" / "lazy-harness" / "config.toml"
    profile_content_dir = home_dir / ".config" / "lazy-harness" / "profiles" / "personal"
    profile_content_dir.mkdir(parents=True)
    (profile_content_dir / "CLAUDE.md").write_text("# Profile\n")

    target_dir = home_dir / ".claude-personal"

    from lazy_harness.core.config import (
        Config,
        HarnessConfig,
        HookEventConfig,
        ProfileEntry,
        ProfilesConfig,
        save_config,
    )

    cfg = Config(
        harness=HarnessConfig(version="1"),
        profiles=ProfilesConfig(
            default="personal",
            items={"personal": ProfileEntry(config_dir=str(target_dir), roots=["~"])},
        ),
        hooks={"session_start": HookEventConfig(scripts=["context-inject"])},
    )
    save_config(cfg, config_path)

    runner = CliRunner()
    result = runner.invoke(cli, ["deploy"])
    assert result.exit_code == 0

    settings_file = target_dir / "settings.json"
    assert settings_file.is_file()
    settings = json.loads(settings_file.read_text())
    assert "hooks" in settings
    assert "SessionStart" in settings["hooks"]


def test_deploy_writes_per_script_matcher_in_settings(home_dir: Path, monkeypatch) -> None:
    """Plumbs HookInfo.matcher → HookEntry.matcher → settings.json matcher."""
    import json

    from lazy_harness.hooks import loader
    from lazy_harness.hooks.loader import BuiltinHookSpec

    monkeypatch.setitem(
        loader._BUILTIN_HOOKS,
        "test-pre-tool-use-with-matcher",
        BuiltinHookSpec(
            module="lazy_harness.hooks.builtins.pre_tool_use_security",
            matcher="Edit|Write",
        ),
    )

    config_path = home_dir / ".config" / "lazy-harness" / "config.toml"
    target_dir = home_dir / ".claude-personal"

    cfg = Config(
        harness=HarnessConfig(version="1"),
        profiles=ProfilesConfig(
            default="personal",
            items={"personal": ProfileEntry(config_dir=str(target_dir), roots=["~"])},
        ),
        hooks={
            "pre_tool_use": HookEventConfig(
                scripts=["test-pre-tool-use-with-matcher", "pre-tool-use-security"]
            )
        },
    )
    save_config(cfg, config_path)

    runner = CliRunner()
    result = runner.invoke(cli, ["deploy"])
    assert result.exit_code == 0

    settings = json.loads((target_dir / "settings.json").read_text())
    pre_tool = settings["hooks"]["PreToolUse"]
    matchers = [entry["matcher"] for entry in pre_tool]
    assert "Edit|Write" in matchers
    assert "Bash" in matchers


def test_deploy_creates_claude_symlink(home_dir: Path) -> None:
    _setup_with_profile_content(home_dir)
    runner = CliRunner()
    result = runner.invoke(cli, ["deploy"])
    assert result.exit_code == 0

    claude_link = home_dir / ".claude"
    assert claude_link.is_symlink()
    assert str(home_dir / ".claude-personal") in str(claude_link.resolve())

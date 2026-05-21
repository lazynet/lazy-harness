"""Tests for deploy_hooks — engine-level integration with merge_with_defaults."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from lazy_harness.core.config import (
    Config,
    HarnessConfig,
    HookEventConfig,
    ProfileEntry,
    ProfilesConfig,
)
from lazy_harness.deploy.engine import deploy_hooks


def _cfg_with_profile(profile_dir: Path, hooks: dict[str, HookEventConfig] | None = None) -> Config:
    """Build a minimal Config pointing one profile at `profile_dir`."""
    return Config(
        harness=HarnessConfig(version="1"),
        profiles=ProfilesConfig(
            default="personal",
            items={"personal": ProfileEntry(config_dir=str(profile_dir), roots=["~"])},
        ),
        hooks=hooks or {},
    )


def test_deploy_hooks_fresh_profile_writes_all_defaults(tmp_path: Path) -> None:
    profile_dir = tmp_path / "profile"
    cfg = _cfg_with_profile(profile_dir, hooks={})

    deploy_hooks(cfg)

    settings = json.loads((profile_dir / "settings.json").read_text())
    cc_hooks = settings["hooks"]
    for cc_event in (
        "SessionStart",
        "Stop",
        "SessionEnd",
        "PreCompact",
        "PostCompact",
        "PreToolUse",
        "PostToolUse",
    ):
        assert cc_event in cc_hooks, f"missing {cc_event} in deployed hooks"


def test_deploy_hooks_idempotent_on_clean_managed_state(tmp_path: Path) -> None:
    profile_dir = tmp_path / "profile"
    cfg = _cfg_with_profile(profile_dir, hooks={})

    deploy_hooks(cfg)
    first = (profile_dir / "settings.json").read_text()

    deploy_hooks(cfg)
    second = (profile_dir / "settings.json").read_text()

    assert first == second
    assert not (profile_dir / "settings.json.bak").exists()


def test_deploy_hooks_backs_up_and_removes_unknown_entries(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    profile_dir = tmp_path / "profile"
    profile_dir.mkdir(parents=True)
    pre = {
        "hooks": {
            "Stop": [
                {
                    "matcher": "",
                    "hooks": [{"type": "command", "command": "/usr/local/bin/my-manual-hook"}],
                }
            ]
        }
    }
    (profile_dir / "settings.json").write_text(json.dumps(pre, indent=2) + "\n")
    cfg = _cfg_with_profile(profile_dir, hooks={})

    deploy_hooks(cfg)

    backup = profile_dir / "settings.json.bak"
    assert backup.is_file(), "expected backup of pre-existing settings.json"
    assert "my-manual-hook" in backup.read_text()

    new = json.loads((profile_dir / "settings.json").read_text())
    serialized = json.dumps(new["hooks"])
    assert "my-manual-hook" not in serialized

    out = capsys.readouterr().out
    assert "unknown" in out.lower()
    assert "my-manual-hook" in out


def test_deploy_hooks_empty_existing_hooks_block(tmp_path: Path) -> None:
    profile_dir = tmp_path / "profile"
    profile_dir.mkdir(parents=True)
    (profile_dir / "settings.json").write_text(json.dumps({"hooks": {}}, indent=2) + "\n")
    cfg = _cfg_with_profile(profile_dir, hooks={})

    deploy_hooks(cfg)

    settings = json.loads((profile_dir / "settings.json").read_text())
    assert "SessionStart" in settings["hooks"]
    assert not (profile_dir / "settings.json.bak").exists()


def test_deploy_hooks_honors_per_event_opt_out(tmp_path: Path) -> None:
    profile_dir = tmp_path / "profile"
    cfg = _cfg_with_profile(profile_dir, hooks={"pre_compact": HookEventConfig(scripts=[])})

    deploy_hooks(cfg)

    settings = json.loads((profile_dir / "settings.json").read_text())
    assert "PreCompact" not in settings["hooks"]
    assert "SessionStart" in settings["hooks"]
    assert "Stop" in settings["hooks"]


def test_deploy_hooks_regression_2026_04_17(tmp_path: Path) -> None:
    """Partial user config (only pre_tool_use + post_tool_use declared) must
    not strip the SessionStart / Stop / SessionEnd / PreCompact / PostCompact
    defaults. Captures the real incident from 2026-04-17."""
    profile_dir = tmp_path / "profile"
    cfg = _cfg_with_profile(
        profile_dir,
        hooks={
            "pre_tool_use": HookEventConfig(scripts=["pre-tool-use-security"]),
            "post_tool_use": HookEventConfig(scripts=["post-tool-use-format"]),
        },
    )

    deploy_hooks(cfg)

    cc_hooks = json.loads((profile_dir / "settings.json").read_text())["hooks"]
    assert "SessionStart" in cc_hooks
    assert "Stop" in cc_hooks
    assert "SessionEnd" in cc_hooks
    assert "PreCompact" in cc_hooks
    assert "PostCompact" in cc_hooks
    pre_tool_serialized = json.dumps(cc_hooks["PreToolUse"])
    assert "pre_tool_use_security.py" in pre_tool_serialized
    assert "pre_tool_use_memory_size.py" not in pre_tool_serialized

"""Tests for the profile narrowing `lh deploy --profile <name>` applies.

`selected_profiles` is the one importable place that decides which profiles a
deploy touches. The engine loops and `snapshot_targets` both read it, because a
snapshot narrowed differently from the deploy is a rollback that misses an
artifact it was asked to protect.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from lazy_harness.core.config import Config, ProfileEntry


def _two_profiles(home: Path) -> Config:
    cfg = Config()
    cfg.profiles.default = "lazy"
    cfg.profiles.items = {
        "lazy": ProfileEntry(config_dir=str(home / ".claude-lazy")),
        "flex": ProfileEntry(config_dir=str(home / ".claude-flex")),
    }
    return cfg


def test_selected_profiles_without_a_name_returns_every_profile(tmp_path: Path) -> None:
    from lazy_harness.deploy.engine import selected_profiles

    cfg = _two_profiles(tmp_path)

    assert list(selected_profiles(cfg, None)) == ["lazy", "flex"]


def test_selected_profiles_narrows_to_the_named_profile(tmp_path: Path) -> None:
    from lazy_harness.deploy.engine import selected_profiles

    cfg = _two_profiles(tmp_path)
    selected = selected_profiles(cfg, "flex")

    assert list(selected) == ["flex"]
    assert selected["flex"].config_dir == str(tmp_path / ".claude-flex")


def test_selected_profiles_refuses_an_unknown_name(tmp_path: Path) -> None:
    """A typo must not deploy nothing and exit 0 — the gate reads the exit code."""
    from lazy_harness.deploy.engine import UnknownProfileError, selected_profiles

    cfg = _two_profiles(tmp_path)

    with pytest.raises(UnknownProfileError, match="tmp-gate"):
        selected_profiles(cfg, "tmp-gate")


def test_unknown_profile_error_names_the_configured_profiles(tmp_path: Path) -> None:
    from lazy_harness.deploy.engine import UnknownProfileError, selected_profiles

    cfg = _two_profiles(tmp_path)

    with pytest.raises(UnknownProfileError) as excinfo:
        selected_profiles(cfg, "tmp-gate")

    message = str(excinfo.value)
    assert "lazy" in message
    assert "flex" in message


def test_global_link_is_deployed_when_no_profile_is_named(tmp_path: Path) -> None:
    from lazy_harness.deploy.engine import deploys_global_link

    assert deploys_global_link(_two_profiles(tmp_path), None) is True


def test_global_link_is_deployed_for_the_default_profile(tmp_path: Path) -> None:
    from lazy_harness.deploy.engine import deploys_global_link

    assert deploys_global_link(_two_profiles(tmp_path), "lazy") is True


def test_global_link_is_left_alone_for_a_non_default_profile(tmp_path: Path) -> None:
    """The link points at the default profile, so a non-default deploy has no
    business rewriting it — that is the bleed `--profile` exists to prevent."""
    from lazy_harness.deploy.engine import deploys_global_link

    assert deploys_global_link(_two_profiles(tmp_path), "flex") is False


def test_deploy_profiles_symlinks_only_the_selected_profile(home_dir: Path) -> None:
    from lazy_harness.core.paths import config_dir
    from lazy_harness.deploy.engine import deploy_profiles

    profiles_src = config_dir() / "profiles"
    for name in ("lazy", "flex"):
        src = profiles_src / name
        src.mkdir(parents=True)
        (src / "CLAUDE.md").write_text(f"# {name}\n")

    deploy_profiles(_two_profiles(home_dir), only="flex")

    assert (home_dir / ".claude-flex" / "CLAUDE.md").is_symlink()
    assert not (home_dir / ".claude-lazy").exists()


def test_deploy_hooks_writes_settings_for_only_the_selected_profile(
    home_dir: Path,
) -> None:
    from lazy_harness.deploy.engine import deploy_hooks

    deploy_hooks(_two_profiles(home_dir), only="flex")

    assert (home_dir / ".claude-flex" / "settings.json").is_file()
    assert not (home_dir / ".claude-lazy" / "settings.json").exists()


def test_deploy_mcp_servers_writes_for_only_the_selected_profile(
    home_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from lazy_harness.deploy import engine

    monkeypatch.setattr(
        engine,
        "_collect_mcp_servers",
        lambda cfg: {"qmd": {"command": "qmd", "args": ["mcp"]}},
    )

    engine.deploy_mcp_servers(_two_profiles(home_dir), only="flex")

    assert (home_dir / ".claude-flex" / ".claude.json").is_file()
    assert not (home_dir / ".claude-lazy" / ".claude.json").exists()


def test_deploy_claude_symlink_skips_a_non_default_profile(home_dir: Path) -> None:
    from lazy_harness.deploy.engine import deploy_claude_symlink

    deploy_claude_symlink(_two_profiles(home_dir), only="flex")

    assert not (home_dir / ".claude").exists()


def test_deploy_claude_symlink_links_nothing_for_a_claude_default_profile(
    home_dir: Path,
) -> None:
    """`~/.claude/CLAUDE.md` would shadow every repository AGENTS.md (ADR-060)."""
    from lazy_harness.deploy.engine import deploy_claude_symlink

    deploy_claude_symlink(_two_profiles(home_dir), only="lazy")

    assert not (home_dir / ".claude").exists()


def test_snapshot_targets_lists_only_the_selected_profile(home_dir: Path) -> None:
    from lazy_harness.deploy.snapshot import snapshot_targets

    targets = snapshot_targets(_two_profiles(home_dir), only="flex")

    assert targets, "narrowing to one profile must not empty the target list"
    assert all(str(p).startswith(str(home_dir / ".claude-flex")) for p in targets), (
        f"targets outside the selected profile: {sorted(str(p) for p in targets)}"
    )


def test_snapshot_targets_for_a_claude_default_profile_hold_no_global_link(
    home_dir: Path,
) -> None:
    """No link is written, so none is snapshotted."""
    from lazy_harness.deploy.snapshot import snapshot_targets

    targets = snapshot_targets(_two_profiles(home_dir), only="lazy")

    assert home_dir / ".claude" not in targets


def test_snapshot_targets_without_a_name_cover_every_profile(home_dir: Path) -> None:
    """Regression: the no-flag surface is unchanged."""
    from lazy_harness.deploy.snapshot import snapshot_targets

    targets = snapshot_targets(_two_profiles(home_dir))

    assert home_dir / ".claude-lazy" / "settings.json" in targets
    assert home_dir / ".claude-flex" / "settings.json" in targets
    assert home_dir / ".claude" not in targets


def test_manifest_from_a_narrowed_snapshot_carries_no_other_profile(
    home_dir: Path, tmp_path: Path
) -> None:
    """The manifest is the artifact a rollback replays; verify it, not the call."""
    from lazy_harness.deploy.snapshot import snapshot_targets, take_snapshot

    cfg = _two_profiles(home_dir)
    manifest_path = take_snapshot(snapshot_targets(cfg, only="flex"), tmp_path / "snap")

    entries = json.loads(manifest_path.read_text())["entries"]
    assert entries
    assert not [e for e in entries if ".claude-lazy" in e["path"]]


def _codex_default(home: Path) -> Config:
    """A config whose default profile runs an agent with no global link."""
    cfg = Config()
    cfg.agent.type = "claude-code"
    cfg.profiles.default = "gate"
    cfg.profiles.items = {
        "gate": ProfileEntry(config_dir=str(home / "codex-home"), agent="codex"),
        "lazy": ProfileEntry(config_dir=str(home / ".claude-lazy")),
    }
    return cfg


def test_a_default_profile_whose_agent_has_no_global_link_moves_no_symlink(
    home_dir: Path,
) -> None:
    """The step 4 contract gate repointed the live `~/.claude` at a Codex home.

    `deploys_global_link` passes here — the narrowed profile *is* the default —
    so the only thing left to stop the write is asking the profile's own agent
    for its link. `CodexAdapter.global_config_link()` returns `None` exactly to
    refuse, and the code resolved `[agent].type` instead, which never asked it.
    """
    from lazy_harness.deploy.engine import deploy_claude_symlink

    deploy_claude_symlink(_codex_default(home_dir), only="gate")

    # `.exists()` alone would pass on a dangling link — the Codex home the gate
    # pointed `~/.claude` at did not exist yet either.
    assert not (home_dir / ".claude").is_symlink(), (
        "a profile whose agent declares no global config link must not create one; "
        f"got ~/.claude -> {(home_dir / '.claude').readlink()}"
    )
    assert not (home_dir / ".claude").exists()


def test_a_claude_code_default_profile_gets_no_link(home_dir: Path) -> None:
    from lazy_harness.deploy.engine import deploy_claude_symlink

    cfg = _codex_default(home_dir)
    cfg.profiles.default = "lazy"

    deploy_claude_symlink(cfg, only="lazy")

    assert not (home_dir / ".claude").exists()


def _dangling_marketplace(home: Path, profile: str) -> Path:
    plugins = home / profile / "plugins"
    (plugins / "marketplaces" / "official").mkdir(parents=True)
    registry = plugins / "known_marketplaces.json"
    registry.write_text(
        json.dumps(
            {"official": {"installLocation": str(home / ".claude/plugins/marketplaces/official")}}
        )
    )
    return registry


def test_deploy_repairs_plugin_paths_left_on_the_removed_global_link(home_dir: Path) -> None:
    from lazy_harness.deploy.engine import repair_plugin_registries

    registry = _dangling_marketplace(home_dir, ".claude-lazy")

    repair_plugin_registries(_two_profiles(home_dir))

    location = json.loads(registry.read_text())["official"]["installLocation"]
    assert location == str(home_dir / ".claude-lazy/plugins/marketplaces/official")


def test_plugin_repair_honours_the_profile_narrowing(home_dir: Path) -> None:
    from lazy_harness.deploy.engine import repair_plugin_registries

    registry = _dangling_marketplace(home_dir, ".claude-lazy")
    before = registry.read_text()

    repair_plugin_registries(_two_profiles(home_dir), only="flex")

    assert registry.read_text() == before


def test_plugin_repair_skips_a_profile_running_another_agent(home_dir: Path) -> None:
    from lazy_harness.deploy.engine import repair_plugin_registries

    registry = _dangling_marketplace(home_dir, ".claude-lazy")
    before = registry.read_text()
    cfg = _two_profiles(home_dir)
    cfg.profiles.items["lazy"].agent = "codex"

    repair_plugin_registries(cfg)

    assert registry.read_text() == before


def test_snapshot_targets_cover_the_plugin_registries_the_deploy_repairs(
    home_dir: Path,
) -> None:
    """The deploy rewrites them, so a rollback has to be able to restore them."""
    from lazy_harness.core.plugin_registry import REGISTRY_FILES
    from lazy_harness.deploy.snapshot import snapshot_targets

    cfg = _two_profiles(home_dir)
    cfg.profiles.items["flex"].agent = "codex"
    for profile in (".claude-lazy", ".claude-flex"):
        for relative in REGISTRY_FILES:
            (home_dir / profile / relative).parent.mkdir(parents=True, exist_ok=True)
            (home_dir / profile / relative).write_text("{}")

    targets = snapshot_targets(cfg)

    for relative in REGISTRY_FILES:
        assert home_dir / ".claude-lazy" / relative in targets
        assert home_dir / ".claude-flex" / relative not in targets


def test_snapshot_leaves_out_a_registry_the_agent_has_not_created(home_dir: Path) -> None:
    """Rollback deletes a target recorded as absent, and Claude Code may create
    the registry after the deploy; the deploy itself never does."""
    from lazy_harness.core.plugin_registry import REGISTRY_FILES
    from lazy_harness.deploy.snapshot import snapshot_targets

    targets = snapshot_targets(_two_profiles(home_dir))

    for relative in REGISTRY_FILES:
        assert home_dir / ".claude-lazy" / relative not in targets

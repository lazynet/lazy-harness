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


def test_deploy_claude_symlink_still_links_the_default_profile(home_dir: Path) -> None:
    from lazy_harness.deploy.engine import deploy_claude_symlink

    deploy_claude_symlink(_two_profiles(home_dir), only="lazy")

    assert (home_dir / ".claude").is_symlink()


def test_snapshot_targets_lists_only_the_selected_profile(home_dir: Path) -> None:
    from lazy_harness.deploy.snapshot import snapshot_targets

    targets = snapshot_targets(_two_profiles(home_dir), only="flex")

    assert targets, "narrowing to one profile must not empty the target list"
    assert all(str(p).startswith(str(home_dir / ".claude-flex")) for p in targets), (
        f"targets outside the selected profile: {sorted(str(p) for p in targets)}"
    )


def test_snapshot_targets_for_the_default_profile_keep_the_global_link(
    home_dir: Path,
) -> None:
    """Narrowed to the default profile, the snapshot must still cover the link —
    `deploy_claude_symlink` rewrites it on that path."""
    from lazy_harness.deploy.snapshot import snapshot_targets

    targets = snapshot_targets(_two_profiles(home_dir), only="lazy")

    assert home_dir / ".claude" in targets


def test_snapshot_targets_without_a_name_cover_every_profile(home_dir: Path) -> None:
    """Regression: the no-flag surface is unchanged."""
    from lazy_harness.deploy.snapshot import snapshot_targets

    targets = snapshot_targets(_two_profiles(home_dir))

    assert home_dir / ".claude-lazy" / "settings.json" in targets
    assert home_dir / ".claude-flex" / "settings.json" in targets
    assert home_dir / ".claude" in targets


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

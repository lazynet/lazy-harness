"""Tests for profile management."""

from __future__ import annotations

from pathlib import Path

import pytest

from lazy_harness.core.config import Config, ProfileEntry, ProfilesConfig, HarnessConfig


def _make_config(tmp_path: Path, profiles: dict[str, ProfileEntry] | None = None) -> tuple[Config, Path]:
    """Helper to create a Config with profiles pointing to tmp dirs."""
    items = profiles or {
        "personal": ProfileEntry(
            config_dir=str(tmp_path / ".claude-personal"),
            roots=["~"],
        ),
    }
    cfg = Config(
        harness=HarnessConfig(version="1"),
        profiles=ProfilesConfig(default="personal", items=items),
    )
    return cfg, tmp_path


def test_list_profiles(tmp_path: Path) -> None:
    from lazy_harness.core.profiles import list_profiles
    cfg, _ = _make_config(tmp_path)
    result = list_profiles(cfg)
    assert len(result) == 1
    assert result[0].name == "personal"
    assert result[0].is_default is True


def test_list_profiles_multiple(tmp_path: Path) -> None:
    from lazy_harness.core.profiles import list_profiles
    cfg, _ = _make_config(tmp_path, {
        "personal": ProfileEntry(config_dir=str(tmp_path / ".claude-personal"), roots=["~"]),
        "work": ProfileEntry(config_dir=str(tmp_path / ".claude-work"), roots=["~/work"]),
    })
    cfg.profiles.default = "personal"
    result = list_profiles(cfg)
    assert len(result) == 2
    names = {p.name for p in result}
    assert names == {"personal", "work"}


def test_add_profile(tmp_path: Path) -> None:
    from lazy_harness.core.profiles import add_profile
    cfg, _ = _make_config(tmp_path)
    add_profile(cfg, "work", str(tmp_path / ".claude-work"), ["~/work"])
    assert "work" in cfg.profiles.items
    assert cfg.profiles.items["work"].config_dir == str(tmp_path / ".claude-work")


def test_add_profile_duplicate(tmp_path: Path) -> None:
    from lazy_harness.core.profiles import add_profile, ProfileError
    cfg, _ = _make_config(tmp_path)
    with pytest.raises(ProfileError, match="already exists"):
        add_profile(cfg, "personal", str(tmp_path / ".claude-personal"), ["~"])


def test_remove_profile(tmp_path: Path) -> None:
    from lazy_harness.core.profiles import remove_profile
    cfg, _ = _make_config(tmp_path, {
        "personal": ProfileEntry(config_dir=str(tmp_path / ".claude-personal"), roots=["~"]),
        "work": ProfileEntry(config_dir=str(tmp_path / ".claude-work"), roots=["~/work"]),
    })
    remove_profile(cfg, "work")
    assert "work" not in cfg.profiles.items


def test_remove_default_profile_fails(tmp_path: Path) -> None:
    from lazy_harness.core.profiles import remove_profile, ProfileError
    cfg, _ = _make_config(tmp_path)
    with pytest.raises(ProfileError, match="default"):
        remove_profile(cfg, "personal")


def test_remove_nonexistent_profile(tmp_path: Path) -> None:
    from lazy_harness.core.profiles import remove_profile, ProfileError
    cfg, _ = _make_config(tmp_path)
    with pytest.raises(ProfileError, match="not found"):
        remove_profile(cfg, "ghost")


def test_resolve_profile_by_cwd(tmp_path: Path) -> None:
    from lazy_harness.core.profiles import resolve_profile
    work_root = tmp_path / "work" / "project"
    work_root.mkdir(parents=True)
    cfg, _ = _make_config(tmp_path, {
        "personal": ProfileEntry(config_dir=str(tmp_path / ".claude-personal"), roots=[str(tmp_path)]),
        "work": ProfileEntry(config_dir=str(tmp_path / ".claude-work"), roots=[str(tmp_path / "work")]),
    })
    result = resolve_profile(cfg, cwd=work_root)
    assert result == "work"


def test_resolve_profile_falls_back_to_default(tmp_path: Path) -> None:
    from lazy_harness.core.profiles import resolve_profile
    cfg, _ = _make_config(tmp_path)
    result = resolve_profile(cfg, cwd=Path("/some/random/path"))
    assert result == "personal"

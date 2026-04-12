"""Profile management — list, add, remove, resolve."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from lazy_harness.core.config import Config, ProfileEntry
from lazy_harness.core.paths import expand_path


class ProfileError(Exception):
    """Raised for profile operation failures."""


@dataclass
class ProfileInfo:
    name: str
    config_dir: Path
    roots: list[str]
    is_default: bool
    exists: bool


def list_profiles(cfg: Config) -> list[ProfileInfo]:
    """Return info about all configured profiles."""
    result: list[ProfileInfo] = []
    for name, entry in cfg.profiles.items.items():
        config_path = expand_path(entry.config_dir)
        result.append(
            ProfileInfo(
                name=name,
                config_dir=config_path,
                roots=entry.roots,
                is_default=(name == cfg.profiles.default),
                exists=config_path.is_dir(),
            )
        )
    return result


def add_profile(cfg: Config, name: str, config_dir: str, roots: list[str]) -> None:
    """Add a new profile to config."""
    if name in cfg.profiles.items:
        raise ProfileError(f"Profile '{name}' already exists")
    cfg.profiles.items[name] = ProfileEntry(config_dir=config_dir, roots=roots)


def remove_profile(cfg: Config, name: str) -> None:
    """Remove a profile from config."""
    if name not in cfg.profiles.items:
        raise ProfileError(f"Profile '{name}' not found")
    if name == cfg.profiles.default:
        raise ProfileError(f"Cannot remove default profile '{name}'. Change default first.")
    del cfg.profiles.items[name]


def resolve_profile(cfg: Config, cwd: Path | None = None) -> str:
    """Resolve which profile to use based on cwd. Longest matching root wins."""
    if cwd is None:
        cwd = Path.cwd()

    cwd_str = str(cwd.resolve())
    best_match = ""
    best_len = 0

    for name, entry in cfg.profiles.items.items():
        for root in entry.roots:
            root_str = str(expand_path(root))
            if cwd_str.startswith(root_str) and len(root_str) > best_len:
                best_match = name
                best_len = len(root_str)

    return best_match if best_match else cfg.profiles.default

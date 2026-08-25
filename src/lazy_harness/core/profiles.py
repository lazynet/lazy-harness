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


PROFILE_SOURCES: tuple[str, ...] = ("explicit", "root-match", "default-fallback")
"""How a profile was decided. `default-fallback` means nothing matched the cwd.

Callers that record which profile an invocation ran under need to distinguish a
match from a guess: a cwd outside every configured root resolves to the default
profile, which is correct only for as long as the default happens to be the
right one.
"""


@dataclass(frozen=True)
class ProfileResolution:
    name: str
    source: str


def resolve_profile_with_source(
    cfg: Config, cwd: Path | None = None, override: str | None = None
) -> ProfileResolution:
    """Resolve the profile and report how it was decided.

    Longest matching root wins. An `override` short-circuits the match and is
    validated here so every caller rejects an unknown name the same way.
    """
    if override is not None:
        if override not in cfg.profiles.items:
            raise ProfileError(f"Unknown profile '{override}'")
        return ProfileResolution(name=override, source="explicit")

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

    if best_match:
        return ProfileResolution(name=best_match, source="root-match")
    return ProfileResolution(name=cfg.profiles.default, source="default-fallback")


def resolve_profile(cfg: Config, cwd: Path | None = None) -> str:
    """Resolve which profile to use based on cwd. Longest matching root wins."""
    return resolve_profile_with_source(cfg, cwd).name

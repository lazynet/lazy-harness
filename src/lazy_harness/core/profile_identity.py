"""Resolves a profile's identity — the source-tree key shared by every profile
of one agent-neutral persona (`personal`, `work`), distinct from the profile
name, which also carries the agent.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from lazy_harness.core.config import Config, ProfileEntry


def profile_identity(name: str, entry: ProfileEntry) -> str:
    """A profile's identity — its declared `identity`, or its own name when unset.

    Every reader of `entry.identity` goes through this helper rather than the
    raw field: an unset identity means "this profile is its own identity",
    which is the pre-identity behaviour every existing profile still gets.
    """
    return entry.identity or name


def profile_source_dir(cfg: Config, name: str, profiles_root: Path | None = None) -> Path:
    """The directory a profile's assets live in, under `profiles/`.

    Two profiles that declare the same `identity` resolve to the same
    directory — that is the point (design section 3). `name` unknown to `cfg`
    resolves to `profiles_root / name`, matching pre-identity behaviour: a
    caller like `lh profile migrate` may target a directory the config no
    longer names.
    """
    from lazy_harness.core.paths import config_dir

    root = profiles_root if profiles_root is not None else config_dir() / "profiles"
    entry = cfg.profiles.items.get(name)
    if entry is None:
        return root / name
    return root / profile_identity(name, entry)

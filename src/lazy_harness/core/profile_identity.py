"""Resolves a profile's identity — the source-tree key shared by every profile
of one agent-neutral persona (`personal`, `work`), distinct from the profile
name, which also carries the agent.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from lazy_harness.core.config import ProfileEntry


def profile_identity(name: str, entry: ProfileEntry) -> str:
    """A profile's identity — its declared `identity`, or its own name when unset.

    Every reader of `entry.identity` goes through this helper rather than the
    raw field: an unset identity means "this profile is its own identity",
    which is the pre-identity behaviour every existing profile still gets.
    """
    return entry.identity or name

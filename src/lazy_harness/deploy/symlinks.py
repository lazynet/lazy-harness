"""Cross-platform symlink management."""

from __future__ import annotations

import os
from pathlib import Path

# `ensure_symlink` found a regular file where the link belongs and moved it
# aside. Distinct from 'created' because the two are not the same news: one
# added a link to an empty slot, the other took a file with contents out of the
# way, and only the caller knows whether those contents mattered.
REPLACED = "replaced"


def backup_path(target: Path) -> Path:
    """Where `ensure_symlink` moves a file or directory it has to displace."""
    return target.with_suffix(target.suffix + ".bak")


def displaced_link_message(label: str, target: Path) -> str:
    return (
        f"  ⚠  {label}: displaced an existing file or directory "
        f"to {backup_path(target).name} to restore the link."
    )


def ensure_symlink(source: Path, target: Path) -> str:
    """Create or update a symlink.

    Returns status: 'created', 'replaced', 'updated', or 'exists'. 'replaced'
    means a file or directory was renamed to `backup_path(target)` to make room —
    the case a third-party installer creates every time it writes this path
    atomically, since a temp file renamed over the target replaces the link
    rather than writing through it.
    """
    if target.is_symlink():
        if target.resolve() == source.resolve():
            return "exists"
        target.unlink()

    displaced = False
    if target.exists():
        target.rename(backup_path(target))
        displaced = True

    target.parent.mkdir(parents=True, exist_ok=True)
    os.symlink(source, target)
    return REPLACED if displaced else "created"

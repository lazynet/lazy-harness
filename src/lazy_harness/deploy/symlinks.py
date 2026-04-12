"""Cross-platform symlink management."""

from __future__ import annotations

import os
from pathlib import Path


def ensure_symlink(source: Path, target: Path) -> str:
    """Create or update a symlink. Returns status: 'created', 'updated', or 'exists'."""
    if target.is_symlink():
        if target.resolve() == source.resolve():
            return "exists"
        target.unlink()

    if target.exists():
        backup = target.with_suffix(target.suffix + ".bak")
        target.rename(backup)

    target.parent.mkdir(parents=True, exist_ok=True)
    os.symlink(source, target)
    return "created"

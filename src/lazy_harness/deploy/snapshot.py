"""Deploy snapshots — the manifest `lh deploy --rollback` replays.

The migration rollback log restores a file by basename, which cannot express
two profiles whose artifacts share one (`~/.claude-lazy/settings.json` and
`~/.claude-flex/settings.json`). A snapshot therefore writes a manifest: one
entry per artifact carrying its absolute destination and a content path unique
per destination rather than per basename.
"""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path
from typing import Any

from lazy_harness import __version__

MANIFEST_FORMAT = "manifest"
MANIFEST_VERSION = 1
ROLLBACK_LOG_NAME = "rollback.json"
CONTENT_DIR = "content"


def _content_name(index: int, path: Path) -> str:
    """A content path unique per destination rather than per basename.

    The index is the entry's position in the manifest, so two profiles'
    `settings.json` land in `0000-settings.json` and `0001-settings.json`. The
    manifest carries the destination, so uniqueness only has to hold inside one
    snapshot — which buys a legible directory over a hashed one.
    """
    return f"{index:04d}-{path.name}"


def _entry_for(index: int, path: Path, snapshot_dir: Path) -> dict[str, Any]:
    if path.is_symlink():
        return {
            "path": str(path),
            "kind": "symlink",
            "content": None,
            "target": os.readlink(path),
        }
    if path.is_file():
        content = f"{CONTENT_DIR}/{_content_name(index, path)}"
        dest = snapshot_dir / content
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, dest)
        return {"path": str(path), "kind": "file", "content": content, "target": None}
    if path.is_dir():
        # `~/.claude` is a real directory on a machine that has never run a
        # deploy, and `deploy_claude_symlink` replaces it with a link. Copying
        # the tree keeps the rollback self-contained instead of depending on the
        # `.bak` rename `ensure_symlink` happens to make.
        content = f"{CONTENT_DIR}/{_content_name(index, path)}"
        shutil.copytree(path, snapshot_dir / content, symlinks=True)
        return {"path": str(path), "kind": "directory", "content": content, "target": None}
    # Nothing is there. Rollback deletes whatever the deploy creates, which is
    # the only way a first deploy on a clean machine is reversible.
    return {"path": str(path), "kind": "absent", "content": None, "target": None}


def take_snapshot(targets: list[Path], snapshot_dir: Path) -> Path:
    """Record the current state of every target, returning the manifest path."""
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    entries = [_entry_for(i, t, snapshot_dir) for i, t in enumerate(targets)]
    manifest = {
        "format": MANIFEST_FORMAT,
        "version": MANIFEST_VERSION,
        "lh_version": __version__,
        "entries": entries,
    }
    path = snapshot_dir / ROLLBACK_LOG_NAME
    path.write_text(json.dumps(manifest, indent=2) + "\n")
    return path

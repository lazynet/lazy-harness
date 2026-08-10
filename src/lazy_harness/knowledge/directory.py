"""Knowledge store layout — resolve paths from the store's own marker."""

from __future__ import annotations

from pathlib import Path

from lazy_harness.core.paths import expand_path
from lazy_harness.knowledge.marker import MARKER_FILENAME, read_marker, write_marker


def ensure_knowledge_dir(root: str | Path) -> Path:
    """Create the store, its marker, and the declared subdirectories."""
    kdir = expand_path(root)
    kdir.mkdir(parents=True, exist_ok=True)
    if not (kdir / MARKER_FILENAME).is_file():
        write_marker(kdir)
    marker = read_marker(kdir)
    (kdir / marker.sessions).mkdir(exist_ok=True)
    (kdir / marker.learnings).mkdir(exist_ok=True)
    return kdir


def sessions_dir(root: Path) -> Path:
    return root / read_marker(root).sessions


def learnings_dir(root: Path) -> Path:
    return root / read_marker(root).learnings


def session_export_path(root: Path, date_str: str, session_id: str) -> Path:
    export_dir = sessions_dir(root) / date_str[:7]
    export_dir.mkdir(parents=True, exist_ok=True)
    return export_dir / f"{date_str}-{session_id[:8]}.md"


def list_sessions(root: Path) -> list[Path]:
    target = sessions_dir(root)
    if not target.is_dir():
        return []
    return sorted(target.rglob("*.md"), reverse=True)

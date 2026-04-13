"""Move project conversation history between profile config dirs.

Each profile keeps `<config_dir>/projects/<encoded-cwd>/` with the JSONL
session files for any project worked on under that profile. This module
provides the pure logic for relocating those directories — used by `lh
profile move`. The CLI handles interactive selection; this layer just
moves bytes safely.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path


class MoveError(Exception):
    """Raised when a move would clobber existing data or fails on disk."""


@dataclass
class MoveResult:
    project: str
    src: Path
    dst: Path
    status: str  # "moved", "skipped-conflict", "skipped-missing"


def list_projects(profile_config_dir: Path) -> list[str]:
    """Return the encoded project dir names under a profile."""
    projects_dir = profile_config_dir / "projects"
    if not projects_dir.is_dir():
        return []
    return sorted(p.name for p in projects_dir.iterdir() if p.is_dir())


def move_project(
    src_profile_dir: Path,
    dst_profile_dir: Path,
    project: str,
    *,
    overwrite: bool = False,
) -> MoveResult:
    """Move a single project dir from src profile to dst profile.

    Idempotent: if the source is missing, returns 'skipped-missing'. If the
    destination already exists and overwrite is False, returns
    'skipped-conflict' instead of touching anything.
    """
    src = src_profile_dir / "projects" / project
    dst = dst_profile_dir / "projects" / project

    if not src.is_dir():
        return MoveResult(project=project, src=src, dst=dst, status="skipped-missing")

    if dst.exists():
        if not overwrite:
            return MoveResult(project=project, src=src, dst=dst, status="skipped-conflict")
        shutil.rmtree(dst)

    dst.parent.mkdir(parents=True, exist_ok=True)
    try:
        shutil.move(str(src), str(dst))
    except OSError as e:
        raise MoveError(f"Failed to move {project}: {e}") from e

    return MoveResult(project=project, src=src, dst=dst, status="moved")


def move_projects(
    src_profile_dir: Path,
    dst_profile_dir: Path,
    projects: list[str],
    *,
    overwrite: bool = False,
) -> list[MoveResult]:
    """Move many projects in order, collecting results. Stops on MoveError."""
    return [
        move_project(src_profile_dir, dst_profile_dir, p, overwrite=overwrite)
        for p in projects
    ]

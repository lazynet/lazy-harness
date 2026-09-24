"""Move project conversation history between profile config dirs.

Each profile keeps `<config_dir>/<sessions>/<encoded-cwd>/` with the JSONL
session files for any project worked on under that profile. This module
provides the pure logic for relocating those directories — used by `lh
profile move`. The CLI handles interactive selection; this layer just
moves bytes safely.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path

from lazy_harness.agents.registry import get_agent
from lazy_harness.agents.session_paths import session_path


class MoveError(Exception):
    """Raised when a move would clobber existing data or fails on disk."""


@dataclass
class MoveResult:
    project: str
    src: Path
    dst: Path
    status: str  # "moved", "skipped-conflict", "skipped-missing"


def list_projects(profile_config_dir: Path, agent: object | None = None) -> list[str]:
    """Return the encoded project dir names under a profile."""
    projects_dir = session_path(agent or get_agent("claude-code"), profile_config_dir, "sessions")
    if projects_dir is None or not projects_dir.is_dir():
        return []
    return sorted(p.name for p in projects_dir.iterdir() if p.is_dir())


def move_project(
    src_profile_dir: Path,
    dst_profile_dir: Path,
    project: str,
    src_agent: object | None = None,
    dst_agent: object | None = None,
    *,
    overwrite: bool = False,
) -> MoveResult:
    """Move a single project dir from src profile to dst profile.

    Idempotent: if the source is missing, returns 'skipped-missing'. If the
    destination already exists and overwrite is False, returns
    'skipped-conflict' instead of touching anything.
    """
    src_sessions = session_path(src_agent or get_agent("claude-code"), src_profile_dir, "sessions")
    dst_sessions = session_path(dst_agent or get_agent("claude-code"), dst_profile_dir, "sessions")
    src = (src_sessions or src_profile_dir) / project
    dst = (dst_sessions or dst_profile_dir) / project

    if src_sessions is None or dst_sessions is None:
        return MoveResult(project=project, src=src, dst=dst, status="skipped-missing")

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
    src_agent: object | None = None,
    dst_agent: object | None = None,
    *,
    overwrite: bool = False,
) -> list[MoveResult]:
    """Move many projects in order, collecting results. Stops on MoveError."""
    return [
        move_project(src_profile_dir, dst_profile_dir, p, src_agent, dst_agent, overwrite=overwrite)
        for p in projects
    ]

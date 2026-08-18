"""The knowledge store's self-describing marker file.

The store declares its own structure in `knowledge.toml` at its root. Consumers
resolve only the root -- from the environment, their own config, or the default --
and read subdirectory names from here. That split keeps the environmental part
(where the store lives, which differs per machine) separate from the global part
(how it is laid out, which must not).
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass
from pathlib import Path

from lazy_harness.core.paths import expand_path

MARKER_FILENAME = "knowledge.toml"
MARKER_VERSION = 1
DEFAULT_ROOT = "~/repos/lazy/lazy-knowledge"
ENV_VAR = "LAZY_KNOWLEDGE_ROOT"


DEFAULT_MEMORY_AREA = "memory"


class MarkerError(Exception):
    """The marker is absent, unreadable, or declares something unusable."""


@dataclass(frozen=True)
class KnowledgeMarker:
    sessions: str
    learnings: str
    # Optional, with a usable default. Bumping the marker version instead would
    # break every existing store at once, for a directory it does not use yet.
    memory: str = "memory"


def _require_relative(name: str, value: str) -> str:
    candidate = Path(value)
    if candidate.is_absolute() or ".." in candidate.parts:
        raise MarkerError(f"{MARKER_FILENAME}: [knowledge].{name} must be relative to the root")
    return value


def read_marker(root: Path) -> KnowledgeMarker:
    """Read and validate the marker at `root`.

    Every failure is loud. A missing field must never read as "" -- that would
    silently land files at the repository root.
    """
    path = root / MARKER_FILENAME
    if not path.is_file():
        raise MarkerError(f"no {MARKER_FILENAME} at {root}")

    try:
        with open(path, "rb") as f:
            raw = tomllib.load(f)
    except (OSError, tomllib.TOMLDecodeError) as e:
        raise MarkerError(f"{path}: unreadable ({e})") from e

    block = raw.get("knowledge", {})
    version = block.get("version")
    if version != MARKER_VERSION:
        raise MarkerError(
            f"{path}: version {version} is not supported (this build expects {MARKER_VERSION})"
        )

    values = {}
    for name in ("sessions", "learnings"):
        value = block.get(name)
        if not isinstance(value, str) or not value:
            raise MarkerError(f"{path}: [knowledge].{name} is missing or empty")
        values[name] = _require_relative(name, value)

    memory = block.get("memory", DEFAULT_MEMORY_AREA)
    if not isinstance(memory, str) or not memory:
        raise MarkerError(f"{path}: [knowledge].memory is declared but empty")
    values["memory"] = _require_relative("memory", memory)

    return KnowledgeMarker(
        sessions=values["sessions"],
        learnings=values["learnings"],
        memory=values["memory"],
    )


def write_marker(root: Path) -> Path:
    """Write a fresh version-1 marker at `root` and return its path."""
    root.mkdir(parents=True, exist_ok=True)
    path = root / MARKER_FILENAME
    path.write_text(
        "[knowledge]\n"
        f"version   = {MARKER_VERSION}\n"
        'sessions  = "sessions"\n'
        'learnings = "learnings"\n'
        f'memory    = "{DEFAULT_MEMORY_AREA}"\n',
        encoding="utf-8",
    )
    return path


def resolve_root(configured: str | None = None) -> Path:
    """Resolve the store root: env var, then configured value, then default."""
    return expand_path(os.environ.get(ENV_VAR) or configured or DEFAULT_ROOT)

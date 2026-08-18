"""Where a project's distilled memory lives.

Twelve places built this path themselves, each appending `/ "memory"` to a
project directory derived from the absolute cwd. That directory belongs to the
agent — it holds the agent's own session transcripts, and its name encodes the
checkout's path — so memory was both a tenant in someone else's directory and
keyed by something that changes when the checkout moves.

Memory now lives in the knowledge store, keyed by the project's own identity.
The store is the only directory the framework already synchronises between
machines, which is what makes the same `MEMORY.md` readable from both.

The agent's project directory is left exactly as it is.
"""

from __future__ import annotations

from pathlib import Path

from lazy_harness.core.project_identity import LOCAL_PREFIX, project_key


def memory_dir_for(
    cwd: Path,
    *,
    knowledge_root: Path | None,
    legacy_project_dir: Path | None = None,
) -> Path:
    """The directory holding `MEMORY.md`, `decisions.jsonl` and `failures.jsonl`.

    Falls back to the legacy location — `<agent project dir>/memory` — when
    there is no usable knowledge store. That difference matters: a machine
    without a store keeps working exactly as before, unshared, rather than
    losing sight of memory it already wrote.
    """
    if knowledge_root is not None:
        try:
            from lazy_harness.knowledge.marker import read_marker

            area = read_marker(knowledge_root).memory
        except Exception:  # noqa: BLE001 — a malformed marker must not take a session down
            area = ""
        if area:
            key = project_key(cwd)
            # A `local/` key means there was no remote to key on. Two machines'
            # unrelated directories would merge under one name, and the store is
            # a git repository that gets pushed — so unshared memory stays where
            # it was rather than being published under a colliding name.
            if key.startswith(f"{LOCAL_PREFIX}/") and legacy_project_dir is not None:
                return legacy_project_dir / "memory"
            resolved = knowledge_root / area
            for part in key.split("/"):
                if part and part not in (".", ".."):
                    resolved = resolved / part
            return resolved

    if legacy_project_dir is not None:
        return legacy_project_dir / "memory"
    raise ValueError("no knowledge store and no legacy project dir to fall back to")


def legacy_memory_dirs(profile_dirs: list[Path]) -> list[Path]:
    """Every `<profile>/projects/<encoded>/memory` that exists.

    The location memory was written to before it had an identity of its own.
    Enumerated separately from the store so nothing disappears from a view
    while a machine is half migrated.
    """
    found: list[Path] = []
    for profile_dir in profile_dirs:
        projects = profile_dir / "projects"
        if not projects.is_dir():
            continue
        for entry in sorted(projects.iterdir()):
            candidate = entry / "memory"
            if candidate.is_dir():
                found.append(candidate)
    return found


def store_memory_dirs(knowledge_root: Path | None) -> list[Path]:
    """Every project directory under the knowledge store's memory area.

    A key is `host/owner/name`, so the leaves are three levels down rather than
    one — walking to a fixed depth would find hosts, not projects.
    """
    if knowledge_root is None:
        return []
    try:
        from lazy_harness.knowledge.marker import read_marker

        area = read_marker(knowledge_root).memory
    except Exception:  # noqa: BLE001 — an unusable store is empty, not fatal
        return []
    root = knowledge_root / area
    if not root.is_dir():
        return []
    return sorted(
        p for p in root.rglob("*") if p.is_dir() and any(f.is_file() for f in p.iterdir())
    )


def all_memory_dirs(
    profile_dirs: list[Path], knowledge_root: Path | None
) -> list[Path]:
    """Both locations, so a half-migrated machine still shows everything."""
    return store_memory_dirs(knowledge_root) + legacy_memory_dirs(profile_dirs)

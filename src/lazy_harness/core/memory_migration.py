"""Move already-written memory to its identity-keyed home.

Nothing here merges. Two machines that both wrote a `MEMORY.md` for one project
have two curated documents; picking one silently is how months of notes vanish
without anybody noticing which half went, and combining them produces a third
that nobody wrote. An occupied target is reported and left alone.

Planning and applying are separate so the plan can be read before any of a
user's data moves.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from pathlib import Path

from lazy_harness.core.memory_store import legacy_memory_dirs
from lazy_harness.core.project_identity import LOCAL_PREFIX, project_key


@dataclass(frozen=True)
class Move:
    source: Path
    target: Path | None
    reason: str = ""


@dataclass
class MigrationResult:
    moved: int = 0
    skipped: list[Move] = field(default_factory=list)
    conflicts: list[Move] = field(default_factory=list)
    failures: list[tuple[Move, str]] = field(default_factory=list)


def decode_project_path(encoded: str) -> Path:
    """The absolute path a legacy project directory name was built from.

    The encoding replaces `/` with `-`, which is ambiguous for any path segment
    containing a hyphen. The result is a candidate to check on disk, never an
    answer to trust.
    """
    return Path("/" + encoded.lstrip("-").replace("-", "/"))


def _checkout_for(encoded: str) -> Path | None:
    """The directory a legacy project name was built from, if it still exists.

    The encoding replaces `/` with `-`, which cannot be reversed: `lazy-harness`
    and `lazy/harness` encode identically. So this walks the filesystem,
    consuming one or more tokens per level and taking the longest name that
    exists.

    Every token has to be consumed. Returning the first directory that happens
    to contain a `.git` walks straight into the wrong answer on a machine whose
    home directory is itself a repository: `-Users-me-repos-x` resolved to
    `/Users/me`, and every project under it collapsed onto one key.
    """
    tokens = [t for t in encoded.lstrip("-").split("-") if t]
    if not tokens:
        return None

    def descend(base: Path, rest: list[str]) -> Path | None:
        if not rest:
            return base
        # Longest first: a directory whose own name contains a hyphen has to
        # win over the shorter prefix that also happens to exist.
        for take in range(len(rest), 0, -1):
            candidate = base / "-".join(rest[:take])
            if not candidate.is_dir():
                continue
            found = descend(candidate, rest[take:])
            if found is not None:
                return found
        return None

    return descend(Path("/"), tokens)


def plan_migration(profile_dirs: list[Path], *, knowledge_root: Path | None) -> list[Move]:
    """What would move, and why anything would not. Touches nothing."""
    from lazy_harness.knowledge.marker import read_marker

    try:
        area = read_marker(knowledge_root).memory if knowledge_root else ""
    except Exception:  # noqa: BLE001
        area = ""

    moves: list[Move] = []
    for legacy in legacy_memory_dirs(profile_dirs):
        encoded = legacy.parent.name
        if not area:
            moves.append(Move(legacy, None, "no usable knowledge store to move into"))
            continue
        checkout = _checkout_for(encoded)
        if checkout is None:
            moves.append(
                Move(legacy, None, "the checkout it was named after is gone; nothing to key on")
            )
            continue
        key = project_key(checkout)
        if key.startswith(f"{LOCAL_PREFIX}/"):
            moves.append(Move(legacy, None, "no git remote; unshared memory stays where it is"))
            continue
        target = knowledge_root / area  # type: ignore[operator]
        for part in key.split("/"):
            target = target / part
        moves.append(Move(legacy, target))
    return moves


def apply_migration(moves: list[Move]) -> MigrationResult:
    """Carry out a plan. An occupied target is a conflict, never an overwrite."""
    result = MigrationResult()
    for move in moves:
        if move.target is None:
            result.skipped.append(move)
            continue
        if move.target.exists() and any(move.target.iterdir()):
            result.conflicts.append(move)
            continue
        try:
            move.target.parent.mkdir(parents=True, exist_ok=True)
            if move.target.is_dir():
                # `shutil.move` puts the source *inside* an existing directory,
                # even an empty one — which lands memory at `<key>/memory/` and
                # leaves every reader looking one level too high.
                move.target.rmdir()
            shutil.move(str(move.source), str(move.target))
            result.moved += 1
        except OSError as e:
            result.failures.append((move, str(e)))
    return result


@dataclass(frozen=True)
class LegacyStatus:
    """What a legacy memory directory is, from the reader's point of view."""

    source: Path
    status: str
    detail: str = ""
    checkout: Path | None = None
    target: Path | None = None


def classify_legacy_memory(
    profile_dirs: list[Path], *, knowledge_root: Path | None
) -> list[LegacyStatus]:
    """Sort legacy memory into leftover, lost, and unmovable. Touches nothing.

    `plan_migration` answers where something would go. It cannot tell a
    harmless leftover from memory nothing reads any more, because it never
    looks at whether the target is already there — and that difference is the
    whole question: `superseded` is safe to delete, `orphaned` is a curated
    document that stopped being loaded when memory moved into the store.
    """
    out: list[LegacyStatus] = []
    for move in plan_migration(profile_dirs, knowledge_root=knowledge_root):
        checkout = _checkout_for(move.source.parent.name)
        if move.target is None:
            out.append(LegacyStatus(move.source, "unkeyable", move.reason, checkout))
            continue
        superseded = move.target.is_dir() and any(move.target.iterdir())
        out.append(
            LegacyStatus(
                move.source,
                "superseded" if superseded else "orphaned",
                checkout=checkout,
                target=move.target,
            )
        )
    return out

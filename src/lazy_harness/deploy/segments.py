"""Which of a profile's assets reach which agent (decision 10, ADR-052).

A profile source directory is read as three ordered layers, lowest precedence
first:

    <profile>/           root — the flat layout that predates segments
    <profile>/shared/    every agent
    <profile>/<agent>/   only the agent this profile runs

The layering is what keeps the migration optional. A profile with no `shared/`
and no agent directory has exactly one layer, so every name appears once and is
linked whole — the pre-segment behaviour, unchanged, rather than a special case
guarding it.

Resolution is pure and answers in two parts: the links to make, and the
collisions to report. Printing belongs to the deployer; a collision that the
resolver resolved silently would be indistinguishable from an asset the user
never had.
"""

from __future__ import annotations

from collections.abc import Collection
from dataclasses import dataclass
from pathlib import Path

SHARED_SEGMENT = "shared"
"""The segment every agent receives. Agent segments are named by the registry."""


@dataclass(frozen=True)
class LinkPlan:
    """One symlink: an absolute source, and where it lands under the config dir."""

    source: Path
    relative: Path


@dataclass(frozen=True)
class Collision:
    """One name carried by more than one segment, and how it was settled."""

    relative: Path
    winner: Path
    shadowed: Path


@dataclass(frozen=True)
class SegmentPlan:
    links: list[LinkPlan]
    collisions: list[Collision]


def _merge(
    sources: list[Path],
    relative: Path,
    links: list[LinkPlan],
    collisions: list[Collision],
) -> None:
    """Resolve one name, `sources` ordered lowest precedence first.

    A name only one segment carries is linked whole, directory or not: walking
    it would cost a link per file and produce the same tree. A name several
    segments carry is walked when they are all directories — this is the merge
    `ensure_symlink` cannot do, since a second directory link replaces the
    first instead of combining it.
    """
    if len(sources) == 1:
        links.append(LinkPlan(source=sources[0], relative=relative))
        return

    if all(source.is_dir() for source in sources):
        children: dict[str, list[Path]] = {}
        for source in sources:
            for child in sorted(source.iterdir()):
                children.setdefault(child.name, []).append(child)
        for name in sorted(children):
            _merge(children[name], relative / name, links, collisions)
        return

    # A file against a file, or a file against a directory: the highest
    # precedence segment wins and every segment it shadows is named.
    winner = sources[-1]
    links.append(LinkPlan(source=winner, relative=relative))
    for shadowed in sources[:-1]:
        collisions.append(Collision(relative=relative, winner=winner, shadowed=shadowed))


def resolve_segments(
    profile_dir: Path,
    agent_name: str,
    *,
    agent_names: Collection[str],
) -> SegmentPlan:
    """The links one profile deploys for one agent, plus the collisions found.

    `agent_names` is the registry's set, passed in rather than imported so the
    resolution stays pure and a caller can test a layout against an agent roster
    that is not the running one. Every name in it is a segment directory, which
    is also what excludes another agent's segment from the root layer.
    """
    if not profile_dir.is_dir():
        return SegmentPlan(links=[], collisions=[])

    # `agent_name` joins the exclusion set even when the registry does not list
    # it: otherwise a directory named after an unregistered agent would be read
    # twice, once as a root entry and once as the agent layer.
    segment_dirs = {*agent_names, SHARED_SEGMENT, agent_name}

    layers: list[dict[str, Path]] = [
        {
            entry.name: entry
            for entry in sorted(profile_dir.iterdir())
            if entry.name not in segment_dirs
        }
    ]
    seen: set[str] = set()
    for segment in (SHARED_SEGMENT, agent_name):
        if not segment or segment in seen:
            continue
        seen.add(segment)
        segment_dir = profile_dir / segment
        if segment_dir.is_dir():
            layers.append({entry.name: entry for entry in sorted(segment_dir.iterdir())})

    merged: dict[str, list[Path]] = {}
    for layer in layers:
        for name, path in layer.items():
            merged.setdefault(name, []).append(path)

    links: list[LinkPlan] = []
    collisions: list[Collision] = []
    for name in sorted(merged):
        _merge(merged[name], Path(name), links, collisions)
    return SegmentPlan(links=links, collisions=collisions)

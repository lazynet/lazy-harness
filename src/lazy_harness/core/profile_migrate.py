"""Move a profile's root assets into segments (`lh profile migrate`, ADR-052).

A layout change is a migration, and this is the half the user runs when they
choose to. Deploy keeps working on an unmigrated profile — the flat root is
still deployed to every agent — so nothing here is required to keep a profile
working. What it buys is that a Codex profile stops receiving Claude Code's
`settings.json`, and the reverse.

**The oracle is the registry, never a typed list.** An entry an adapter names in
`config_targets()` belongs to that agent; everything the registry does not claim
is shared. A hardcoded table would be a second answer to a question the adapters
already answer, and would go stale the first time an adapter gained a file.

**The assembled system docs and their segments stay at the root**, even though
`system_docs()` names them. `sync_agent_md` reads `head.md` / `tail.md` at the
profile root and writes the assembled document there; moving either into a
segment would leave the assembler writing to a path the deploy no longer links.
That agreement between assembler and deployer is the decision, and it is why
`system_docs()` is read here as a *root* marker rather than as an ownership one.

**The segments are renamed in place, though** (ADR-055). ADR-043 shipped the
role names with a read fallback to the stem-keyed spelling, and called that
fallback a migration window rather than a second permanent answer. This is the
command that closes it: `CLAUDE.head.md` → `head.md`, `CLAUDE.tail.md` →
`tail.md`, `_common/<stem>.common.md` → `_common/common.md`. A rename is not a
move — nothing changes segment — so it is a separate list on the plan, printed
separately, and it runs under the same all-or-nothing guard.

`_common/` is the one thing outside the profile directory this command touches,
and the only reason it can is that the rename is the last step of a tree-wide
migration: the shared segment waits until no *other* profile still reads it,
because the profiles share one `_common/` and a sibling left behind would fail
its next sync with `missing _common/<stem>.common.md`. Nothing else
`_`-prefixed is touched: it is shared across profiles and belongs to no single
segment.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from lazy_harness.core.sync_agent_md import (
    COMMON_SEGMENT,
    HEAD_SEGMENT,
    TAIL_SEGMENT,
    legacy_segment_names,
)
from lazy_harness.deploy.segments import SHARED_SEGMENT


class MigrateError(Exception):
    """A migration was refused before anything moved."""


@dataclass(frozen=True)
class Move:
    name: str
    segment: str
    source: Path
    destination: Path
    reason: str


@dataclass(frozen=True)
class Rename:
    """One segment taking its role name. `source` and `destination` are absolute
    because the shared segment lives outside the profile directory."""

    label: str
    destination_label: str
    source: Path
    destination: Path
    reason: str


@dataclass(frozen=True)
class MigrationPlan:
    profile_dir: Path
    moves: list[Move]
    kept: list[tuple[str, str]]
    """(name, why it stays) — printed, because a silent no-op reads as a bug."""

    renames: list[Rename] = field(default_factory=list)


RENAME_HANDLED = "__rename__"
"""Sentinel reason: the entry stays at the root, and `_plan_renames` speaks for
it. Two lines about one file — "stays" and "would be renamed" — read as a
contradiction, so the rename planner is the single voice on the legacy names."""


def _root_names() -> dict[str, str]:
    """Entry names that stay at the profile root, each with its reason."""
    from lazy_harness.agents.registry import get_agent, list_agents

    names = {
        HEAD_SEGMENT: "system-doc segment",
        TAIL_SEGMENT: "system-doc segment",
    }
    for agent_type in list_agents():
        for doc in get_agent(agent_type).system_docs():
            names[doc.parts[0]] = "assembled system doc"
            head, _common, tail = legacy_segment_names(doc.name.removesuffix(".md"))
            names[head] = RENAME_HANDLED
            names[tail] = RENAME_HANDLED
    return names


def _destination_stems() -> list[str]:
    """Every stem the registry's destinations yield, in registration order.

    The stem is what keys the *legacy* segment names, so this is the set of
    spellings a profile directory could be carrying. A profile carrying two of
    them has two files claiming one role, which `apply_migration` refuses.
    """
    from lazy_harness.agents.registry import get_agent, list_agents

    stems: list[str] = []
    for agent_type in list_agents():
        for doc in get_agent(agent_type).system_docs():
            stem = doc.name.removesuffix(".md")
            if stem not in stems:
                stems.append(stem)
    return stems


def _legacy_readers(profile_dir: Path, stem: str) -> list[str]:
    """Sibling profiles still assembled from `_common/<stem>.common.md`.

    A directory carrying `head.md` has migrated and reads the role-named shared
    segment; one carrying only `<stem>.head.md` has not, and renaming the shared
    file would turn its next sync into a `SyncError`. Read from disk rather than
    from `config.toml` on purpose: the tree can hold directories for profiles
    since removed from the config, and those still break the sync run that walks
    the whole tree.
    """
    readers: list[str] = []
    for entry in sorted(profile_dir.parent.iterdir()):
        if entry == profile_dir or not entry.is_dir() or entry.name.startswith("_"):
            continue
        if (entry / HEAD_SEGMENT).is_file():
            continue
        if (entry / legacy_segment_names(stem)[0]).is_file():
            readers.append(entry.name)
    return readers


def _plan_renames(profile_dir: Path, kept: list[tuple[str, str]]) -> list[Rename]:
    """The legacy segments this profile can take the role name for, now.

    Appends to `kept` for each one it cannot, with the reason — a rename that
    silently does not happen is the failure this whole command exists to make
    visible.
    """
    renames: list[Rename] = []
    carried: list[str] = []

    for stem in _destination_stems():
        legacy_head, _, legacy_tail = legacy_segment_names(stem)
        for legacy_name, role in ((legacy_head, HEAD_SEGMENT), (legacy_tail, TAIL_SEGMENT)):
            source = profile_dir / legacy_name
            if not source.is_file():
                continue
            if stem not in carried:
                carried.append(stem)
            destination = profile_dir / role
            if destination.exists() or destination.is_symlink():
                kept.append((legacy_name, f"leftover — {role} is already there"))
                continue
            renames.append(
                Rename(
                    label=legacy_name,
                    destination_label=role,
                    source=source,
                    destination=destination,
                    reason=f"role name for {stem}'s segment",
                )
            )

    common_dir = profile_dir.parent / "_common"
    for stem in carried:
        legacy_common = Path(legacy_segment_names(stem)[1]).name
        source = common_dir / legacy_common
        label = f"_common/{legacy_common}"
        if not source.is_file():
            continue
        readers = _legacy_readers(profile_dir, stem)
        if readers:
            noun = "profile" if len(readers) == 1 else "profiles"
            named = ", ".join(f"'{name}'" for name in readers)
            kept.append((label, f"still read by {noun} {named}"))
            continue
        destination = common_dir / COMMON_SEGMENT
        if destination.exists() or destination.is_symlink():
            kept.append((label, f"leftover — _common/{COMMON_SEGMENT} is already there"))
            continue
        renames.append(
            Rename(
                label=label,
                destination_label=f"_common/{COMMON_SEGMENT}",
                source=source,
                destination=destination,
                reason="role name for the shared segment",
            )
        )
    return renames


def _config_owners() -> dict[str, str]:
    """Root entry name → the agent whose adapter names it.

    Keyed on the first path component, so Copilot's `hooks/lazy-harness.json`
    claims the `hooks` directory. `setdefault` keeps the answer deterministic if
    two adapters ever name one entry — registration order decides, and the plan
    prints which agent won.
    """
    from lazy_harness.agents.base import ConfigPlanner
    from lazy_harness.agents.registry import get_agent, list_agents

    owners: dict[str, str] = {}
    for agent_type in list_agents():
        agent = get_agent(agent_type)
        if not isinstance(agent, ConfigPlanner):
            continue
        for target in agent.config_targets():
            owners.setdefault(target.parts[0], agent_type)
    return owners


def plan_migration(profile_dir: Path) -> MigrationPlan:
    """What `migrate` would move, and what it would leave where it is."""
    from lazy_harness.agents.registry import list_agents

    if not profile_dir.is_dir():
        raise MigrateError(f"No profile content directory at {profile_dir}")

    segment_dirs = {SHARED_SEGMENT, *list_agents()}
    stays = _root_names()
    owners = _config_owners()

    moves: list[Move] = []
    kept: list[tuple[str, str]] = []
    for entry in sorted(profile_dir.iterdir()):
        name = entry.name
        if name.startswith("_"):
            kept.append((name, "shared across profiles"))
            continue
        if name in segment_dirs and entry.is_dir():
            kept.append((name, "already a segment"))
            continue
        reason = stays.get(name)
        if reason == RENAME_HANDLED:
            continue
        if reason is not None:
            kept.append((name, reason))
            continue
        segment = owners.get(name)
        why = f"named by the {segment} adapter" if segment else "claimed by no agent"
        segment = segment or SHARED_SEGMENT
        moves.append(
            Move(
                name=name,
                segment=segment,
                source=entry,
                destination=profile_dir / segment / name,
                reason=why,
            )
        )
    renames = _plan_renames(profile_dir, kept)
    return MigrationPlan(profile_dir=profile_dir, moves=moves, kept=kept, renames=renames)


def apply_migration(plan: MigrationPlan) -> list[Move]:
    """Perform the plan, or refuse it whole.

    Every destination is checked before the first rename, moves and segment
    renames together. A migration that stopped halfway would leave the profile
    split across two layouts with no record of where the boundary fell — worse
    than not having run.
    """
    for move in plan.moves:
        if move.destination.exists() or move.destination.is_symlink():
            raise MigrateError(
                f"{move.destination} already exists; migrating '{move.name}' "
                "would overwrite it. Nothing was moved."
            )
    # Two legacy spellings can claim one role name, and neither exists yet — so
    # the check above sees nothing. Letting the second rename win would delete a
    # segment with no channel saying which one.
    claimed: dict[Path, str] = {}
    for rename in plan.renames:
        if rename.destination.exists() or rename.destination.is_symlink():
            raise MigrateError(
                f"{rename.destination} already exists; renaming "
                f"'{rename.label}' would overwrite it. Nothing was moved."
            )
        first = claimed.get(rename.destination)
        if first is not None:
            raise MigrateError(
                f"'{first}' and '{rename.label}' would both become "
                f"'{rename.destination_label}'. Nothing was moved."
            )
        claimed[rename.destination] = rename.label

    for move in plan.moves:
        move.destination.parent.mkdir(parents=True, exist_ok=True)
        move.source.rename(move.destination)
    for rename in plan.renames:
        rename.source.rename(rename.destination)
    return plan.moves

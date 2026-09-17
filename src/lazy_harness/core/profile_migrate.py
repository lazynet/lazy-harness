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

`_common/` and anything else `_`-prefixed is never touched: it is shared across
profiles and belongs to no single segment.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from lazy_harness.core.sync_agent_md import HEAD_SEGMENT, TAIL_SEGMENT, legacy_segment_names
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
class MigrationPlan:
    profile_dir: Path
    moves: list[Move]
    kept: list[tuple[str, str]]
    """(name, why it stays) — printed, because a silent no-op reads as a bug."""


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
            stem = doc.name.removesuffix(".md")
            head, _common, tail = legacy_segment_names(stem)
            names[head] = "system-doc segment (legacy)"
            names[tail] = "system-doc segment (legacy)"
    return names


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
    return MigrationPlan(profile_dir=profile_dir, moves=moves, kept=kept)


def apply_migration(plan: MigrationPlan) -> list[Move]:
    """Perform the plan, or refuse it whole.

    Every destination is checked before the first rename. A migration that
    stopped halfway would leave the profile split across two layouts with no
    record of where the boundary fell — worse than not having run.
    """
    for move in plan.moves:
        if move.destination.exists() or move.destination.is_symlink():
            raise MigrateError(
                f"{move.destination} already exists; migrating '{move.name}' "
                "would overwrite it. Nothing was moved."
            )
    for move in plan.moves:
        move.destination.parent.mkdir(parents=True, exist_ok=True)
        move.source.rename(move.destination)
    return plan.moves

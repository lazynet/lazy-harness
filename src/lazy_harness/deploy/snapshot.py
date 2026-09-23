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
from lazy_harness.core.config import Config

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


def snapshot_targets(cfg: Config, *, only: str | None = None) -> list[Path]:
    """Every path a deploy owns, derived once so the rollback cannot miss one.

    Mirrors what `deploy/engine.py` writes: the per-profile symlinks named by
    `deploy.segments.resolve_segments` (the same call the deploy makes, so the
    two cannot disagree about which segment reaches which agent), the ownership
    ledger that records them, each profile's native config documents, and the
    agent's global config link. An integration test invokes this and a real
    deploy and asserts they agree — two readers of one config-derived answer.

    Both halves resolve the agent exactly as the deploy does, and the agent is
    per profile. `deploy_config` asks each profile's own planner for
    `config_targets()`, and `deploy_claude_symlink` asks the *default* profile's
    adapter for the link, because the link and its target both belong to that
    profile. Reading `[agent].type` once above the loop instead — which this did
    until ADR-041's `they must move together` was closed — hands a profile
    declaring `agent = "codex"` the other adapter's documents: `.claude.json` and
    `~/.claude` snapshotted although `CodexAdapter` answers `""` and `None`, and
    the `hooks.json` it really writes missed. A rollback then restores or deletes
    artifacts the deploy never wrote, and leaves the one it did.

    `only` narrows it the same way `lh deploy --profile <name>` narrows the
    deploy, through the same `selected_profiles` and `deploys_global_link`, so
    the two readers stay one answer under narrowing too.
    """
    from lazy_harness.agents.base import ConfigPlanner
    from lazy_harness.agents.registry import agent_for_profile, list_agents
    from lazy_harness.core.paths import config_dir, expand_path
    from lazy_harness.core.plugin_registry import REGISTRY_AGENT, REGISTRY_FILES
    from lazy_harness.deploy.engine import deploys_global_link, selected_profiles
    from lazy_harness.deploy.ledger import LEDGER_RELATIVE
    from lazy_harness.deploy.segments import resolve_segments
    from lazy_harness.deploy.skills import SKILL_LEDGER_RELATIVE, plan_skill_projections

    profiles_src = config_dir() / "profiles"
    selected = selected_profiles(cfg, only)
    adapters = {name: agent_for_profile(cfg, name) for name in selected}
    agent_names = list_agents()

    targets: list[Path] = []
    for name, entry in selected.items():
        target_dir = expand_path(entry.config_dir)
        src_dir = profiles_src / name
        agent = adapters[name]
        if src_dir.is_dir():
            # Resolved through the same function the deploy uses, not by listing
            # the source again: a mirror that lists root names targets `shared`
            # and `codex` — directories the deploy never links — while missing
            # every file link it does write inside them.
            plan = resolve_segments(src_dir, agent.name, agent_names=agent_names)
            targets.extend(
                target_dir / link.relative
                for link in plan.links
                if link.relative.parts[0] != "skills"
            )
            targets.append(target_dir / LEDGER_RELATIVE)
        # An adapter that cannot plan writes no config document, so it owns
        # none. The deploy refuses such a profile outright; the snapshot only
        # has to not invent targets for it.
        if isinstance(agent, ConfigPlanner):
            targets.extend(target_dir / relative for relative in agent.config_targets())
        # Only an existing registry: rollback deletes a target recorded absent,
        # the deploy never creates one, and Claude Code may after the snapshot.
        if agent.name == REGISTRY_AGENT:
            targets.extend(
                target_dir / relative
                for relative in REGISTRY_FILES
                if (target_dir / relative).is_file()
            )

    skill_plan = plan_skill_projections(
        selected,
        profiles_src,
        adapters,
        narrowed=only is not None,
    )
    for root_plan in skill_plan.roots:
        if root_plan.replaces_legacy_root:
            targets.append(root_plan.root)
        else:
            targets.extend(root_plan.root / name for name in root_plan.links)
            targets.extend(root_plan.root / name for name in root_plan.owned_before)
        targets.append(root_plan.root.parent / SKILL_LEDGER_RELATIVE)

    default_agent = agent_for_profile(cfg, cfg.profiles.default)
    link_path = default_agent.global_config_link()
    if link_path is not None and deploys_global_link(cfg, only):
        targets.append(link_path)

    seen: set[Path] = set()
    unique: list[Path] = []
    for path in targets:
        if path not in seen:
            seen.add(path)
            unique.append(path)
    return unique

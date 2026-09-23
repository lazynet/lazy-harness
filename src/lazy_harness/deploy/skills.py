"""Plan and apply ADR-059's per-skill native-root projections."""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Collection, Mapping
from dataclasses import dataclass
from pathlib import Path

from lazy_harness.agents.base import AgentAdapter
from lazy_harness.core.config import Config, ProfileEntry
from lazy_harness.core.paths import expand_path
from lazy_harness.core.profile_identity import profile_source_dir
from lazy_harness.deploy.ledger import read_ledger
from lazy_harness.deploy.symlinks import REPLACED, displaced_link_message, ensure_symlink

SKILL_LEDGER_RELATIVE = Path(".lazy-harness/skill-links.json")
_LEDGER_VERSION = 1


class SkillCollisionError(RuntimeError):
    """A native skill name is already claimed by incompatible content."""


class SkillLedgerError(RuntimeError):
    """Skill ownership cannot be established from the stored ledger."""


@dataclass(frozen=True)
class SkillClaim:
    profile: str
    source: Path


@dataclass(frozen=True)
class SkillRootPlan:
    root: Path
    links: dict[str, SkillClaim]
    selected_sources: frozenset[Path]
    owned_before: frozenset[str]
    replaces_legacy_root: bool


@dataclass(frozen=True)
class SkillProjectionPlan:
    roots: tuple[SkillRootPlan, ...]
    omissions: tuple[tuple[str, str], ...]
    narrowed: bool


def _skills_for_profile(profile_dir: Path, agent_name: str) -> dict[str, Path]:
    """Resolve skill directories at root < shared < agent precedence."""
    if not profile_dir.is_dir():
        return {}
    roots = [profile_dir / "skills"]
    roots.extend(profile_dir / segment / "skills" for segment in ("shared", agent_name))
    resolved: dict[str, Path] = {}
    for root in roots:
        if not root.is_dir():
            continue
        for child in sorted(root.iterdir()):
            if child.is_dir():
                resolved[child.name] = child
    return resolved


def _fingerprint(root: Path) -> str:
    digest = hashlib.sha256()
    for current, dirs, files in os.walk(root, followlinks=False):
        current_path = Path(current)
        dirs.sort()
        files.sort()
        relative_dir = current_path.relative_to(root)
        for name in dirs + files:
            path = current_path / name
            relative = (relative_dir / name).as_posix().encode()
            digest.update(relative)
            if path.is_symlink():
                digest.update(b"L")
                digest.update(os.readlink(path).encode())
            elif path.is_file():
                digest.update(b"F")
                digest.update(path.read_bytes())
            else:
                digest.update(b"D")
    return digest.hexdigest()


def _ledger_path(root: Path) -> Path:
    return root.parent / SKILL_LEDGER_RELATIVE


def _read_ledger(root: Path) -> set[str]:
    path = _ledger_path(root)
    if path.parent.is_symlink() or path.is_symlink():
        raise _ledger_error(path, "symlinks are not allowed")
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return set()
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise _ledger_error(path, str(exc)) from exc
    if not isinstance(raw, dict):
        raise _ledger_error(path, "expected an object with version and links")
    if type(raw.get("version")) is not int or raw["version"] != _LEDGER_VERSION:
        raise _ledger_error(path, f"unsupported version {raw.get('version')!r}")
    if not isinstance(raw.get("links"), list):
        raise _ledger_error(path, "links must be a list of skill names")
    for name in raw["links"]:
        if (
            not isinstance(name, str)
            or not name
            or name in {".", ".."}
            or "/" in name
            or "\\" in name
            or "\x00" in name
        ):
            raise _ledger_error(path, f"invalid links entry {name!r}")
    return set(raw["links"])


def _ledger_error(path: Path, reason: str) -> SkillLedgerError:
    return SkillLedgerError(
        f"Cannot read skill ownership ledger {path}: {reason}. "
        "Restore a known-good ledger or repair it after verifying link ownership; "
        "nothing was written."
    )


def _points_into(link: Path, source_root: Path) -> bool:
    if not link.is_symlink():
        return False
    try:
        target = link.readlink()
        absolute = target if target.is_absolute() else link.parent / target
        normalized = Path(os.path.abspath(absolute))
        immediate = normalized.parent.resolve() / normalized.name
        immediate.relative_to(source_root.resolve())
    except (OSError, ValueError):
        return False
    return True


def _points_into_any(link: Path, roots: Collection[Path]) -> bool:
    return any(_points_into(link, root) for root in roots)


def plan_skill_projections(
    cfg: Config,
    profiles: Mapping[str, ProfileEntry],
    profiles_src: Path,
    adapters: Mapping[str, AgentAdapter],
    *,
    narrowed: bool,
) -> SkillProjectionPlan:
    grouped: dict[Path, list[SkillClaim]] = {}
    selected_sources: dict[Path, set[Path]] = {}
    legacy_roots: set[Path] = set()
    omissions: list[tuple[str, str]] = []

    for profile, entry in profiles.items():
        source_dir = profile_source_dir(cfg, profile, profiles_src)
        adapter = adapters[profile]
        skills = _skills_for_profile(source_dir, adapter.name)
        skill_root = getattr(adapter, "skill_root", None)
        root = skill_root(entry.config_dir) if callable(skill_root) else None
        if root is None:
            if skills:
                omissions.append((profile, adapter.name))
            continue
        root = root.parent.resolve() / root.name
        grouped.setdefault(root, [])
        selected_sources.setdefault(root, set()).add(source_dir.resolve())
        config_root = expand_path(entry.config_dir)
        legacy_owned = read_ledger(config_root)
        try:
            relative_root = root.relative_to(config_root)
        except ValueError:
            relative_root = None
        if (
            relative_root is not None
            and legacy_owned is not None
            and relative_root in legacy_owned
            and _points_into(root, source_dir)
        ):
            legacy_roots.add(root)
        grouped[root].extend(
            SkillClaim(profile=profile, source=source) for source in skills.values()
        )

    plans: list[SkillRootPlan] = []
    for root in sorted(grouped, key=str):
        by_name: dict[str, list[SkillClaim]] = {}
        for claim in grouped[root]:
            by_name.setdefault(claim.source.name, []).append(claim)
        links: dict[str, SkillClaim] = {}
        for name in sorted(by_name):
            claims = by_name[name]
            fingerprints = {_fingerprint(claim.source) for claim in claims}
            if len(fingerprints) != 1:
                sources = ", ".join(f"{c.profile}:{c.source}" for c in claims)
                raise SkillCollisionError(
                    f"Skill {name!r} has different content across selected profiles: {sources}. "
                    "Nothing was written."
                )
            links[name] = claims[0]

        owned = _read_ledger(root)
        for name, claim in links.items():
            target = root / name
            if not target.is_symlink() and not target.exists():
                continue
            if root in legacy_roots:
                continue
            managed = name in owned and _points_into(target, profiles_src)
            if not managed:
                raise SkillCollisionError(
                    f"A user-owned entry already claims skill {name!r} at {target}; "
                    "it was not adopted and nothing was written."
                )
            current_source = target.resolve()
            selected = _points_into_any(target, selected_sources[root])
            if not selected and _fingerprint(current_source) != _fingerprint(claim.source):
                raise SkillCollisionError(
                    f"Skill {name!r} conflicts with an unselected managed profile at {target}; "
                    "nothing was written."
                )
            if not selected:
                links[name] = SkillClaim(profile=claim.profile, source=current_source)

        plans.append(
            SkillRootPlan(
                root=root,
                links=links,
                selected_sources=frozenset(selected_sources[root]),
                owned_before=frozenset(owned),
                replaces_legacy_root=root in legacy_roots,
            )
        )
    return SkillProjectionPlan(tuple(plans), tuple(omissions), narrowed)


def apply_skill_projections(plan: SkillProjectionPlan, profiles_src: Path) -> list[str]:
    """Apply a validated plan and return human-readable status lines."""
    output: list[str] = []
    for root_plan in plan.roots:
        root = root_plan.root
        if root_plan.replaces_legacy_root and root.is_symlink():
            root.unlink()
        generated = set(root_plan.links)
        retained: set[str] = set()
        removed: set[str] = set()
        for name in root_plan.owned_before - generated:
            target = root / name
            if not target.is_symlink() or not _points_into(target, profiles_src):
                continue
            if plan.narrowed and not _points_into_any(target, root_plan.selected_sources):
                retained.add(name)
                continue
            target.unlink()
            removed.add(name)
            output.append(f"  ✗ skills/{name} (no longer generated)")

        if generated:
            root.mkdir(parents=True, exist_ok=True)
        for name, claim in root_plan.links.items():
            target = root / name
            status = ensure_symlink(claim.source, target)
            if status == REPLACED:
                output.append(displaced_link_message(f"{claim.profile}/skills/{name}", target))
            else:
                suffix = " (already linked)" if status == "exists" else ""
                output.append(f"  ✓ {claim.profile}/skills/{name}{suffix}")

        ledger = _ledger_path(root)
        final = sorted((set(root_plan.owned_before) - removed) & (generated | retained) | generated)
        if final or ledger.exists() or root_plan.owned_before:
            ledger.parent.mkdir(parents=True, exist_ok=True)
            payload = {"version": _LEDGER_VERSION, "links": final}
            ledger.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return output

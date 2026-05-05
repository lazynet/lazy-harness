"""lh memory — diagnostic commands for the memory stack (ADR-030 G7)."""

from __future__ import annotations

import hashlib
from pathlib import Path

import click

from lazy_harness.core.paths import config_file, expand_path


def enumerate_profile_projects(profile_dir: Path) -> dict[str, dict]:
    """List per-project memory artifacts under `<profile_dir>/projects/`.

    Returns a mapping of project_key → {memory_md_lines, memory_md_sha,
    has_decisions, has_handoff}. Skips any project_key that lacks a
    `MEMORY.md` (it has no curated content yet).
    """
    projects_dir = profile_dir / "projects"
    if not projects_dir.is_dir():
        return {}
    out: dict[str, dict] = {}
    for entry in projects_dir.iterdir():
        if not entry.is_dir():
            continue
        memory_dir = entry / "memory"
        memory_md = memory_dir / "MEMORY.md"
        if not memory_md.is_file():
            continue
        try:
            content_bytes = memory_md.read_bytes()
        except OSError:
            continue
        text = content_bytes.decode("utf-8", errors="replace")
        out[entry.name] = {
            "memory_md_lines": text.count("\n") + (0 if text.endswith("\n") else 1),
            "memory_md_sha": hashlib.sha256(content_bytes).hexdigest()[:12],
            "has_decisions": (memory_dir / "decisions.jsonl").is_file(),
            "has_handoff": (memory_dir / "handoff.md").is_file(),
        }
    return out


def find_cross_profile_divergences(
    profile_data: dict[str, dict[str, dict]],
) -> list[dict]:
    """Find project keys that exist in 2+ profiles with divergent MEMORY.md.

    Returns a list of {project_key, profiles: dict[profile_name, data]} for
    each shared key whose `memory_md_sha` differs across the profiles that
    own it.
    """
    if len(profile_data) < 2:
        return []
    all_keys: set[str] = set()
    for proj in profile_data.values():
        all_keys.update(proj.keys())
    out: list[dict] = []
    for key in sorted(all_keys):
        owners = {name: proj[key] for name, proj in profile_data.items() if key in proj}
        if len(owners) < 2:
            continue
        shas = {entry["memory_md_sha"] for entry in owners.values()}
        if len(shas) > 1:
            out.append({"project_key": key, "profiles": owners})
    return out


@click.group("memory")
def memory() -> None:
    """Diagnostic commands for the memory stack."""


@memory.command("cross-profile-check")
def cross_profile_check() -> None:
    """List per-profile memory artifacts and flag cross-profile divergences."""
    from lazy_harness.core.config import ConfigError, load_config

    cf = config_file()
    if not cf.is_file():
        click.echo(f"No config at {cf} — nothing to check.")
        return
    try:
        cfg = load_config(cf)
    except ConfigError as exc:
        click.echo(f"Config invalid: {exc}", err=True)
        raise SystemExit(1) from exc

    profile_data: dict[str, dict[str, dict]] = {}
    for name, entry in cfg.profiles.items.items():
        config_dir = expand_path(entry.config_dir)
        profile_data[name] = enumerate_profile_projects(config_dir)
        click.echo(f"[{name}] {config_dir} — {len(profile_data[name])} project(s) with MEMORY.md")
        for key in sorted(profile_data[name].keys()):
            stats = profile_data[name][key]
            extras = []
            if stats["has_decisions"]:
                extras.append("decisions")
            if stats["has_handoff"]:
                extras.append("handoff")
            tail = f" [{', '.join(extras)}]" if extras else ""
            click.echo(
                f"  · {key} — {stats['memory_md_lines']} lines, sha {stats['memory_md_sha']}{tail}"
            )

    divergences = find_cross_profile_divergences(profile_data)
    if divergences:
        click.echo()
        click.echo(f"Cross-profile divergences ({len(divergences)}):")
        for d in divergences:
            owners = ", ".join(
                f"{name}=sha:{entry['memory_md_sha']}/lines:{entry['memory_md_lines']}"
                for name, entry in d["profiles"].items()
            )
            click.echo(f"  ⚠ {d['project_key']} → {owners}")
    else:
        click.echo()
        click.echo("No cross-profile divergences detected.")

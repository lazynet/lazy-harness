"""lh memory — diagnostic commands for the memory stack (ADR-030 G7)."""

from __future__ import annotations

import hashlib
from pathlib import Path

import click

from lazy_harness.core.paths import config_file, expand_path
from lazy_harness.knowledge.compound_loop import invoke_claude as _invoke_claude


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


def _read_jsonl_tail(path: Path, last: int) -> list[str]:
    if not path.is_file():
        return []
    try:
        lines = path.read_text().splitlines()
    except OSError:
        return []
    return [line for line in lines[-last:] if line.strip()]


def _build_consolidate_prompt(decisions: list[str], failures: list[str]) -> str:
    sections: list[str] = [
        "You are reviewing append-only episodic logs from a coding agent's session.",
        "Identify recurring patterns and propose additions to the project's curated",
        "MEMORY.md (max 200 lines, distilled rules and conventions). Output only the",
        "additions as markdown bullets — no preamble. Each addition must include the",
        "source decisions/failures that motivate it. Skip anything that is already a",
        "one-off or session-specific.",
    ]
    if decisions:
        sections.append("\n## decisions.jsonl entries")
        sections.extend(decisions)
    if failures:
        sections.append("\n## failures.jsonl entries")
        sections.extend(failures)
    return "\n".join(sections)


@memory.command("consolidate")
@click.option(
    "--memory-dir",
    type=click.Path(file_okay=False, path_type=Path),
    default=None,
    help="Memory directory to read from. Defaults to <cwd>/memory.",
)
@click.option(
    "--last",
    type=int,
    default=50,
    show_default=True,
    help="Tail this many entries from each JSONL.",
)
@click.option(
    "--model",
    default="claude-haiku-4-5-20251001",
    show_default=True,
    help="Headless model for the proposal.",
)
@click.option(
    "--timeout",
    type=int,
    default=120,
    show_default=True,
    help="Claude invocation timeout in seconds.",
)
def consolidate(memory_dir: Path | None, last: int, model: str, timeout: int) -> None:
    """Propose MEMORY.md additions from recent decisions/failures (read-only)."""
    target = memory_dir or (Path.cwd() / "memory")
    decisions = _read_jsonl_tail(target / "decisions.jsonl", last)
    failures = _read_jsonl_tail(target / "failures.jsonl", last)
    if not decisions and not failures:
        click.echo(
            f"No entries in decisions.jsonl/failures.jsonl — nothing to consolidate at {target}."
        )
        return

    prompt = _build_consolidate_prompt(decisions, failures)
    result = _invoke_claude(prompt, model, timeout)
    if not result:
        click.echo("Claude returned empty output. Try again or increase --timeout.")
        return
    click.echo(result)
    click.echo(
        "\n# Above is a proposal — review before pasting into MEMORY.md.\n"
        "# Use LH_MEMORY_SIZE_BYPASS=1 if your edit transiently exceeds 200 lines."
    )

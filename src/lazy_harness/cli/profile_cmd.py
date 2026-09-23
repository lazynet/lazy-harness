"""lh profile — profile management commands."""

from __future__ import annotations

from pathlib import Path

import click
from rich.console import Console
from rich.markup import escape
from rich.table import Table

from lazy_harness.agents.registry import AgentNotFoundError, agent_for_profile, get_agent
from lazy_harness.core.config import Config, ConfigError, load_config, save_config
from lazy_harness.core.envrc import EnvrcResult, write_envrc
from lazy_harness.core.move_projects import (
    MoveError,
    list_projects,
)
from lazy_harness.core.move_projects import (
    move_projects as do_move_projects,
)
from lazy_harness.core.paths import config_dir, config_file, contract_path, expand_path
from lazy_harness.core.profile_identity import profile_source_dir
from lazy_harness.core.profile_migrate import (
    MigrateError,
    apply_migration,
    plan_migration,
)
from lazy_harness.core.profiles import ProfileError, add_profile, list_profiles, remove_profile
from lazy_harness.core.sync_agent_md import SyncError, SyncResult, sync_profiles


def deploy_envrc_for_all_profiles(cfg: Config) -> list[EnvrcResult]:
    """Write a managed .envrc into every root shared by any profile.

    Returns the per-write results so callers (CLI, init, migrate) can render
    them however they like. Raises AgentNotFoundError if the agent
    `agent_for_profile` resolves for any profile is not registered — the
    profile's own `agent`, or `[agent].type` where it declares none.

    Profiles are grouped by root first (D7, specs/backlog.md): two profiles
    with different agents sharing a root must both land in that root's
    `.envrc`, not just whichever profile's write happened last. Two profiles
    with the *same* agent sharing a root collapse onto one `env_var`, which is
    genuinely ambiguous — last one in `cfg.profiles.items` order wins here,
    and `lh doctor` reports the ambiguity rather than this function refusing.
    """
    by_root: dict[Path, dict[str, Path]] = {}
    for name, entry in cfg.profiles.items.items():
        # Resolved per profile, not once above the loop: a profile declaring its
        # own agent otherwise had every root bound to the global agent's env var.
        env_var = agent_for_profile(cfg, name).env_var()
        config_dir = expand_path(entry.config_dir)
        for root in entry.roots:
            by_root.setdefault(expand_path(root), {})[env_var] = config_dir

    results: list[EnvrcResult] = []
    for root, exports in by_root.items():
        for env_var, config_dir in sorted(exports.items()):
            results.append(write_envrc(root, env_var, config_dir))
    return results


@click.group()
def profile() -> None:
    """Manage agent profiles."""


@profile.command("list")
def profile_list() -> None:
    """List all configured profiles."""
    cf = config_file()
    try:
        cfg = load_config(cf)
    except ConfigError as e:
        click.echo(f"Error: {e}", err=True)
        raise SystemExit(1)

    profiles = list_profiles(cfg)
    if not profiles:
        click.echo("No profiles configured. Run: lh init")
        return

    console = Console()
    table = Table(show_header=True, show_lines=False, pad_edge=False)
    table.add_column("Profile", style="bold")
    table.add_column("Config Dir")
    table.add_column("Roots")
    table.add_column("Status")

    for p in profiles:
        name = f"{p.name} (default)" if p.is_default else p.name
        status = "exists" if p.exists else "missing"
        style = "green" if p.exists else "red"
        table.add_row(
            name,
            contract_path(p.config_dir),
            ", ".join(p.roots),
            f"[{style}]{status}[/{style}]",
        )

    console.print(table)


@profile.command("add")
@click.argument("name")
@click.option("--config-dir", required=True, help="Agent config directory for this profile")
@click.option("--roots", default="", help="Comma-separated root paths")
def profile_add(name: str, config_dir: str, roots: str) -> None:
    """Add a new profile."""
    cf = config_file()
    try:
        cfg = load_config(cf)
    except ConfigError as e:
        click.echo(f"Error: {e}", err=True)
        raise SystemExit(1)

    roots_list = [r.strip() for r in roots.split(",") if r.strip()] if roots else []

    try:
        add_profile(cfg, name, config_dir, roots_list)
    except ProfileError as e:
        click.echo(f"Error: {e}", err=True)
        raise SystemExit(1)

    save_config(cfg, cf)
    click.echo(f"Profile '{name}' added.")


@profile.command("move")
@click.option("--from", "src_name", required=True, help="Source profile name")
@click.option("--to", "dst_name", required=True, help="Destination profile name")
@click.option(
    "--projects",
    "project_csv",
    default=None,
    help="Comma-separated project dir names to move. Omit for interactive selection.",
)
@click.option("--all", "move_all", is_flag=True, help="Move every project under the source")
@click.option("--overwrite", is_flag=True, help="Replace existing dest project dirs")
@click.option("--yes", is_flag=True, help="Skip confirmation prompt")
def profile_move(
    src_name: str,
    dst_name: str,
    project_csv: str | None,
    move_all: bool,
    overwrite: bool,
    yes: bool,
) -> None:
    """Move project conversation history between profiles.

    Each profile keeps `<config_dir>/projects/<encoded-cwd>/` per project.
    Reclassifying a project (e.g. moving from `lazy` to `flex`) means moving
    that directory across profile config dirs without losing JSONL history.
    """
    console = Console()
    cf = config_file()
    try:
        cfg = load_config(cf)
    except ConfigError as e:
        console.print(f"[red]Error:[/red] {escape(str(e))}")
        raise SystemExit(1)

    if src_name not in cfg.profiles.items:
        console.print(f"[red]Unknown source profile:[/red] {src_name}")
        raise SystemExit(1)
    if dst_name not in cfg.profiles.items:
        console.print(f"[red]Unknown destination profile:[/red] {dst_name}")
        raise SystemExit(1)
    if src_name == dst_name:
        console.print("[red]Source and destination are the same.[/red]")
        raise SystemExit(1)

    src_dir = expand_path(cfg.profiles.items[src_name].config_dir)
    dst_dir = expand_path(cfg.profiles.items[dst_name].config_dir)

    available = list_projects(src_dir)
    if not available:
        console.print(f"[dim]No projects to move under '{src_name}'.[/dim]")
        return

    if move_all:
        targets = available
    elif project_csv is not None:
        targets = [p.strip() for p in project_csv.split(",") if p.strip()]
        unknown = [p for p in targets if p not in available]
        if unknown:
            console.print(f"[red]Unknown projects:[/red] {', '.join(unknown)}")
            raise SystemExit(1)
    else:
        targets = _interactive_select(console, available)
        if not targets:
            console.print("Nothing to move.")
            return

    console.print(f"[bold]Will move {len(targets)} project(s):[/bold]")
    for p in targets:
        console.print(f"  {p}")
    console.print(f"  [dim]from[/dim] {contract_path(src_dir)}")
    console.print(f"  [dim]to  [/dim] {contract_path(dst_dir)}")

    if not yes and not click.confirm("Proceed?", default=False):
        console.print("Aborted.")
        return

    try:
        results = do_move_projects(src_dir, dst_dir, targets, overwrite=overwrite)
    except MoveError as e:
        console.print(f"[red]{escape(str(e))}[/red]")
        raise SystemExit(1)

    for r in results:
        if r.status == "moved":
            console.print(f"  [green]✓[/green] {r.project}")
        elif r.status == "skipped-conflict":
            console.print(
                f"  [yellow]·[/yellow] {r.project} (already exists at dest, "
                f"use --overwrite to replace)"
            )
        else:
            console.print(f"  [yellow]·[/yellow] {r.project} (not in source)")


def _interactive_select(console: Console, available: list[str]) -> list[str]:
    """Render a numbered list and parse a space-separated selection."""
    console.print("Projects in source profile:")
    for i, name in enumerate(available, start=1):
        console.print(f"  {i}) {name}")
    raw = click.prompt(
        "Which to move? (numbers, 'all', or 'q' to cancel)", default="q", show_default=False
    )
    raw = raw.strip()
    if raw == "q":
        return []
    if raw == "all":
        return list(available)
    selected: list[str] = []
    for tok in raw.split():
        try:
            idx = int(tok) - 1
        except ValueError:
            console.print(f"[yellow]skipping invalid token:[/yellow] {tok}")
            continue
        if 0 <= idx < len(available):
            selected.append(available[idx])
        else:
            console.print(f"[yellow]out of range:[/yellow] {tok}")
    return selected


@profile.command("envrc")
@click.option("--dry-run", is_flag=True, help="Show what would be written without touching files")
def profile_envrc(dry_run: bool) -> None:
    """Generate or update .envrc in every profile root.

    Each .envrc gets a managed block exporting the agent's config-dir env var
    (e.g. CLAUDE_CONFIG_DIR), so plain `claude` invocations inside the root
    auto-pick the right profile via direnv. User-authored content outside the
    block is preserved.
    """
    console = Console()
    cf = config_file()
    try:
        cfg = load_config(cf)
    except ConfigError as e:
        console.print(f"[red]Error:[/red] {escape(str(e))}")
        raise SystemExit(1)

    if dry_run:
        for name, entry in cfg.profiles.items.items():
            # Resolved the same way the real write resolves it. A dry run that
            # names a different env var than the deploy is worse than no dry run.
            try:
                env_var = agent_for_profile(cfg, name).env_var()
            except AgentNotFoundError as e:
                console.print(f"[red]{escape(str(e))}[/red]")
                raise SystemExit(1) from e
            config_dir = expand_path(entry.config_dir)
            for root in entry.roots:
                root_path = expand_path(root)
                console.print(
                    f"[cyan]would write[/cyan] {contract_path(root_path / '.envrc')}"
                    f" → {env_var}={contract_path(config_dir)}"
                )
        return

    try:
        results = deploy_envrc_for_all_profiles(cfg)
    except AgentNotFoundError as e:
        console.print(f"[red]{escape(str(e))}[/red]")
        raise SystemExit(1)

    if not results:
        console.print("No profile roots configured.")
        return

    for r in results:
        style = {"created": "green", "updated": "yellow", "unchanged": "dim"}.get(r.action, "")
        console.print(f"[{style}]{r.action:9}[/{style}] {contract_path(r.path)}")

    needs_allow = [r for r in results if r.action in ("created", "updated")]
    if needs_allow:
        console.print()
        console.print("[bold]Next:[/bold] run [cyan]direnv allow[/cyan] in each updated root:")
        for r in needs_allow:
            console.print(f"  cd {contract_path(r.path.parent)} && direnv allow")


def render_sync_results(results: list[SyncResult], console: Console) -> None:
    """Render system-doc sync results identically for sync and deploy."""
    for result in results:
        style = {
            "written": "green",
            "unchanged": "dim",
            "skipped": "yellow",
            "orphaned": "yellow",
        }.get(result.action, "")
        suffix = f" ({result.reason})" if result.reason else ""
        console.print(
            f"[{style}]{result.action:9}[/{style}] {result.profile} → {result.path.name}{suffix}"
        )


def _profile_sync_system_doc() -> None:
    """Regenerate each profile's system doc from its segmented sources.

    Concatenates `<identity>/head.md` + `_common/common.md` +
    `_common/<agent>.md` + `<identity>/tail.md` for every configured profile
    that carries them, and writes the result to every destination the
    profile's agent loads. A directory under
    `~/.config/lazy-harness/profiles/` no configured profile resolves to is
    reported orphaned and never touched once at least one profile declares
    `identity`; until then it keeps the pre-identity behaviour of being
    synced with the running agent's adapter (M3). Legacy-only and flat
    profile dirs are skipped, not erased; legacy-only results name the
    migrate command that restores them to the supported layout.
    """
    console = Console()
    profiles_dir = config_dir() / "profiles"
    if not profiles_dir.is_dir():
        console.print(f"No profiles directory at {contract_path(profiles_dir)}.")
        return

    try:
        cfg = load_config(config_file())
        agent = get_agent(cfg.agent.type)
    except (ConfigError, AgentNotFoundError) as e:
        console.print(f"[red]Error:[/red] {escape(str(e))}")
        raise SystemExit(1)

    try:
        # `cfg` makes the doc name per profile; `agent` is the fallback for a
        # directory the config does not name, but only while no profile in
        # `cfg` declares `identity` — from then on such a directory is
        # reported orphaned instead (M3).
        results = sync_profiles(profiles_dir, agent, cfg=cfg)
    except SyncError as e:
        console.print(f"[red]Error:[/red] {escape(str(e))}")
        raise SystemExit(1)

    if not results:
        console.print("[dim]No profile dirs found.[/dim]")
        return

    render_sync_results(results, console)


# Renamed from `sync-claude-md` (decision 5, blast-radius design): the
# destinations are no longer Claude Code-specific, so the command name should
# not be either. Registered under both names against the same callback --
# the old name kept as a hidden alias rather than a second implementation, so
# a script or muscle memory typing it keeps working with nothing to drift out
# of sync.
profile_sync_system_doc = profile.command("sync-system-doc")(_profile_sync_system_doc)
profile_sync_claude_md = profile.command("sync-claude-md", hidden=True)(_profile_sync_system_doc)


@profile.command("migrate")
@click.argument("name")
@click.option("--dry-run", is_flag=True, help="Show the plan without moving anything")
def profile_migrate(name: str, dry_run: bool) -> None:
    """Move a profile's root assets into `shared/` and per-agent segments,
    and rename its system-doc segments to their roles.

    An entry an adapter names in its config targets goes to that agent's
    segment; everything the registry does not claim goes to `shared/`. The
    assembled system docs and the segments they are built from stay at the
    profile root, where `lh profile sync-system-doc` writes them — but the
    segments take their role names there: `CLAUDE.head.md` becomes `head.md`,
    `CLAUDE.tail.md` becomes `tail.md`, and `_common/CLAUDE.common.md` becomes
    `_common/common.md` once no other profile still reads it (ADR-055).

    An unmigrated profile still deploys its root to every agent, but its legacy
    segments are not assembled. Migration also stops a Codex profile receiving
    Claude Code's assets, and the reverse.
    """
    console = Console()
    config_path = config_file()
    cfg = load_config(config_path) if config_path.is_file() else Config()
    profile_dir = profile_source_dir(cfg, name, config_dir() / "profiles")

    try:
        plan = plan_migration(profile_dir)
    except MigrateError as e:
        console.print(f"[red]Error:[/red] {escape(str(e))}")
        raise SystemExit(1)

    for entry_name, reason in plan.kept:
        console.print(f"[dim]keep      {escape(entry_name)} ({escape(reason)})[/dim]")

    verb = "would move" if dry_run else "move"
    for move in plan.moves:
        console.print(
            f"[cyan]{verb}[/cyan] {escape(move.name)}"
            f" → {escape(move.segment)}/{escape(move.name)}"
            f" [dim]({escape(move.reason)})[/dim]"
        )

    # Renames are their own verb, not a move with the same source and
    # destination directory: a reader scanning for "what left the root" must not
    # find the segments in that list, because they did not leave it.
    rename_verb = "would rename" if dry_run else "rename"
    for rename in plan.renames:
        console.print(
            f"[cyan]{rename_verb}[/cyan] {escape(rename.label)}"
            f" → {escape(rename.destination_label)}"
            f" [dim]({escape(rename.reason)})[/dim]"
        )

    if not plan.moves and not plan.renames:
        console.print("[green]Already segmented — nothing to move.[/green]")
        return

    if dry_run:
        console.print()
        console.print(
            f"[dim]{len(plan.moves)} entries would move, "
            f"{len(plan.renames)} segments would be renamed. "
            "Re-run without --dry-run.[/dim]"
        )
        return

    try:
        apply_migration(plan)
    except MigrateError as e:
        console.print(f"[red]Refused:[/red] {escape(str(e))}")
        raise SystemExit(1)

    console.print()
    if plan.moves:
        console.print(f"[green]Moved {len(plan.moves)} entries.[/green]")
    if plan.renames:
        console.print(f"[green]Renamed {len(plan.renames)} segments.[/green]")
    console.print("[bold]Next:[/bold] [cyan]lh deploy[/cyan] to relink, then re-add to chezmoi.")


@profile.command("remove")
@click.argument("name")
def profile_remove(name: str) -> None:
    """Remove a profile."""
    cf = config_file()
    try:
        cfg = load_config(cf)
    except ConfigError as e:
        click.echo(f"Error: {e}", err=True)
        raise SystemExit(1)

    try:
        remove_profile(cfg, name)
    except ProfileError as e:
        click.echo(f"Error: {e}", err=True)
        raise SystemExit(1)

    save_config(cfg, cf)
    click.echo(f"Profile '{name}' removed.")

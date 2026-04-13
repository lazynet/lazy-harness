"""lh profile — profile management commands."""

from __future__ import annotations

import click
from rich.console import Console
from rich.table import Table

from lazy_harness.agents.registry import AgentNotFoundError, get_agent
from lazy_harness.core.config import Config, ConfigError, load_config, save_config
from lazy_harness.core.envrc import EnvrcResult, write_envrc
from lazy_harness.core.move_projects import (
    MoveError,
    list_projects,
)
from lazy_harness.core.move_projects import (
    move_projects as do_move_projects,
)
from lazy_harness.core.paths import config_file, contract_path, expand_path
from lazy_harness.core.profiles import ProfileError, add_profile, list_profiles, remove_profile


def deploy_envrc_for_all_profiles(cfg: Config) -> list[EnvrcResult]:
    """Write a managed .envrc into every root of every profile.

    Returns the per-root results so callers (CLI, init, migrate) can render
    them however they like. Raises AgentNotFoundError if cfg.agent.type is
    not registered.
    """
    adapter = get_agent(cfg.agent.type)
    env_var = adapter.env_var()
    results: list[EnvrcResult] = []
    for entry in cfg.profiles.items.values():
        config_dir = expand_path(entry.config_dir)
        for root in entry.roots:
            results.append(write_envrc(expand_path(root), env_var, config_dir))
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
        console.print(f"[red]Error:[/red] {e}")
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
        console.print(f"[red]{e}[/red]")
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
        console.print(f"[red]Error:[/red] {e}")
        raise SystemExit(1)

    if dry_run:
        try:
            adapter = get_agent(cfg.agent.type)
        except AgentNotFoundError as e:
            console.print(f"[red]{e}[/red]")
            raise SystemExit(1)
        env_var = adapter.env_var()
        for entry in cfg.profiles.items.values():
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
        console.print(f"[red]{e}[/red]")
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

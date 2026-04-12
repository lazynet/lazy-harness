"""lh profile — profile management commands."""

from __future__ import annotations

import click
from rich.console import Console
from rich.table import Table

from lazy_harness.core.config import ConfigError, load_config, save_config
from lazy_harness.core.paths import config_file, contract_path
from lazy_harness.core.profiles import ProfileError, add_profile, list_profiles, remove_profile


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

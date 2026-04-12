"""lh profile — profile management commands."""

from __future__ import annotations

import click


@click.group()
def profile() -> None:
    """Manage agent profiles."""


@profile.command("list")
def profile_list() -> None:
    """List all profiles."""
    click.echo("TODO: profile list")


@profile.command("add")
@click.argument("name")
def profile_add(name: str) -> None:
    """Add a new profile."""
    click.echo(f"TODO: add profile {name}")


@profile.command("remove")
@click.argument("name")
def profile_remove(name: str) -> None:
    """Remove a profile."""
    click.echo(f"TODO: remove profile {name}")

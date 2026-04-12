"""lh deploy — deploy profiles, hooks, skills."""

from __future__ import annotations

import click


@click.command("deploy")
def deploy() -> None:
    """Deploy profiles, hooks, and skills."""
    click.echo("TODO: deploy")

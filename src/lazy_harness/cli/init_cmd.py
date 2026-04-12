"""lh init — interactive setup wizard."""

from __future__ import annotations

import click


@click.command("init")
def init_cmd() -> None:
    """Initialize lazy-harness configuration."""
    click.echo("TODO: init wizard")

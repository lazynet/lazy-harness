"""lh doctor — health check."""

from __future__ import annotations

import click


@click.command("doctor")
def doctor() -> None:
    """Check environment health."""
    click.echo("TODO: doctor")

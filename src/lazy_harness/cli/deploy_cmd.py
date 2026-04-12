"""lh deploy — deploy profiles, hooks, skills."""

from __future__ import annotations

import click

from lazy_harness.core.config import ConfigError, load_config
from lazy_harness.core.paths import config_file
from lazy_harness.deploy.engine import deploy_claude_symlink, deploy_profiles


@click.command("deploy")
def deploy() -> None:
    """Deploy profiles, hooks, and skills."""
    cf = config_file()
    try:
        cfg = load_config(cf)
    except ConfigError as e:
        click.echo(f"Error: {e}", err=True)
        raise SystemExit(1)

    click.echo("=== lazy-harness deploy ===\n")

    click.echo("Deploying profiles:")
    deploy_profiles(cfg)
    click.echo()

    click.echo("Setting up ~/.claude symlink:")
    deploy_claude_symlink(cfg)
    click.echo()

    click.echo("Done.")

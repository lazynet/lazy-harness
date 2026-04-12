"""lh init — interactive setup wizard."""

from __future__ import annotations

from pathlib import Path

import click

from lazy_harness.core.config import (
    AgentConfig,
    Config,
    HarnessConfig,
    ProfileEntry,
    ProfilesConfig,
    save_config,
)
from lazy_harness.core.paths import config_dir, config_file


@click.command("init")
@click.option("--profile-name", default=None, help="Default profile name")
@click.option("--profile-config-dir", default=None, help="Config directory for default profile")
@click.option("--agent", default="claude-code", help="Agent type")
@click.option("--non-interactive", is_flag=True, help="Skip interactive prompts")
def init_cmd(
    profile_name: str | None,
    profile_config_dir: str | None,
    agent: str,
    non_interactive: bool,
) -> None:
    """Initialize lazy-harness configuration."""
    cf = config_file()

    if cf.is_file():
        if non_interactive:
            click.echo(f"Config already exists at {cf}. Use --force to overwrite.")
            return
        if not click.confirm(f"Config already exists at {cf}. Overwrite?", default=False):
            return

    if non_interactive:
        name = profile_name or "personal"
        pdir = profile_config_dir or f"~/.claude-{name}"
    else:
        name = click.prompt("Default profile name", default=profile_name or "personal")
        default_dir = profile_config_dir or f"~/.claude-{name}"
        pdir = click.prompt(f"Config dir for '{name}'", default=default_dir)
        agent = click.prompt("Agent type", default=agent)
        click.echo()

    cfg = Config(
        harness=HarnessConfig(version="1"),
        agent=AgentConfig(type=agent),
        profiles=ProfilesConfig(
            default=name,
            items={
                name: ProfileEntry(config_dir=pdir, roots=["~"]),
            },
        ),
    )

    save_config(cfg, cf)
    click.echo(f"Config written to {cf}")

    profiles_dir = config_dir() / "profiles" / name
    profiles_dir.mkdir(parents=True, exist_ok=True)
    click.echo(f"Profile directory created at {profiles_dir}")

    click.echo()
    click.echo("Next steps:")
    click.echo(f"  1. Edit {cf}")
    click.echo(f"  2. lh profile list")
    click.echo(f"  3. lh doctor")

"""lh run — launch the configured agent with profile auto-detection."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import click
from rich.console import Console
from rich.markup import escape

from lazy_harness.agents.registry import AgentNotFoundError, get_agent
from lazy_harness.core.config import ConfigError, load_config
from lazy_harness.core.paths import config_file, expand_path
from lazy_harness.core.profiles import resolve_profile


@click.command(
    "run",
    context_settings={
        "ignore_unknown_options": True,
        "allow_extra_args": True,
    },
)
@click.option("--profile", "profile_override", default=None, help="Force a specific profile")
@click.option("--list", "list_profiles_flag", is_flag=True, help="List profiles and exit")
@click.option("--dry-run", is_flag=True, help="Print the resolved exec invocation without running")
@click.argument("args", nargs=-1, type=click.UNPROCESSED)
def run(
    profile_override: str | None,
    list_profiles_flag: bool,
    dry_run: bool,
    args: tuple[str, ...],
) -> None:
    """Launch the configured agent for the current profile.

    Resolves the profile from the cwd (or --profile), sets the agent's
    config-dir env var, and execs the agent binary with all remaining args.
    """
    console = Console(stderr=True)

    cf = config_file()
    try:
        cfg = load_config(cf)
    except ConfigError as e:
        console.print(f"[red]Error:[/red] {e}")
        raise SystemExit(1)

    if list_profiles_flag:
        for name, entry in cfg.profiles.items.items():
            marker = "*" if name == cfg.profiles.default else " "
            roots = ", ".join(entry.roots) if entry.roots else "—"
            console.print(
                f"{marker} {name:12} {escape(entry.config_dir):30} \\[{escape(roots)}]"
            )
        return

    if not cfg.profiles.items:
        console.print("[red]No profiles configured.[/red] Run [bold]lh init[/bold].")
        raise SystemExit(1)

    if profile_override:
        if profile_override not in cfg.profiles.items:
            console.print(f"[red]Unknown profile:[/red] {profile_override}")
            raise SystemExit(1)
        profile_name = profile_override
    else:
        profile_name = resolve_profile(cfg, Path.cwd())

    entry = cfg.profiles.items[profile_name]
    config_dir = expand_path(entry.config_dir)

    try:
        adapter = get_agent(cfg.agent.type)
    except AgentNotFoundError as e:
        console.print(f"[red]{e}[/red]")
        raise SystemExit(1)

    binary = adapter.resolve_binary()
    if binary is None:
        console.print(f"[red]Cannot locate {cfg.agent.type} binary.[/red]")
        raise SystemExit(1)

    env = os.environ.copy()
    env[adapter.env_var()] = str(config_dir)

    exec_args = [str(binary), *args]

    if dry_run:
        console.print(f"profile: [bold]{escape(profile_name)}[/bold]")
        console.print(f"binary:  {escape(str(binary))}")
        console.print(f"{adapter.env_var()}: {escape(str(config_dir))}")
        console.print(f"argv:    {escape(repr(exec_args))}")
        return

    if sys.stdin.isatty() and not profile_override:
        # Quiet by default to avoid noise in scripts. Only show when interactive
        # and the user did not explicitly pick a profile.
        if profile_name != cfg.profiles.default:
            console.print(f"[dim]lh run: profile '{profile_name}'[/dim]")

    os.execvpe(str(binary), exec_args, env)

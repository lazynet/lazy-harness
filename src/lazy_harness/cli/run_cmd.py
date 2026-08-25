"""lh run — launch the configured agent with profile auto-detection."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import click
from rich.console import Console
from rich.markup import escape

from lazy_harness.agents.launch import LaunchError, resolve_launch
from lazy_harness.core.config import ConfigError, load_config
from lazy_harness.core.paths import config_file, process_exec_path
from lazy_harness.core.profiles import SOURCE_DEFAULT_FALLBACK, root_routing_is_configured


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
        console.print(f"[red]Error:[/red] {escape(str(e))}")
        raise SystemExit(1)

    if list_profiles_flag:
        for name, entry in cfg.profiles.items.items():
            marker = "*" if name == cfg.profiles.default else " "
            roots = ", ".join(entry.roots) if entry.roots else "—"
            console.print(f"{marker} {name:12} {escape(entry.config_dir):30} \\[{escape(roots)}]")
        return

    try:
        plan = resolve_launch(cfg, Path.cwd(), profile_override)
    except LaunchError as e:
        console.print(f"[red]Error:[/red] {escape(str(e))}")
        raise SystemExit(1)

    if plan.profile_source == SOURCE_DEFAULT_FALLBACK and root_routing_is_configured(cfg):
        # Unconditional, and on stderr. This is the one resolution outcome that
        # cannot announce itself later: the agent starts, runs against whatever
        # config dir the default happens to name, and nothing looks broken.
        # A tty check would silence exactly the scheduled callers that need it.
        # soft_wrap keeps the path on one line: without a tty rich wraps at 80
        # columns, and a path broken across lines cannot be grepped out of a log.
        console.print(
            f"[yellow]lh run:[/yellow] no configured root matches "
            f"{escape(str(Path.cwd()))} — using default profile "
            f"'{escape(plan.profile)}'",
            soft_wrap=True,
        )

    profile_name = plan.profile
    adapter = plan.adapter
    config_dir = plan.config_dir
    binary = plan.binary
    env = plan.env

    process_name = adapter.process_name()
    argv0 = process_name or str(binary)
    exec_args = [argv0, *args]

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

    exec_file = process_exec_path(binary, process_name) if process_name else binary
    os.execvpe(str(exec_file), exec_args, env)

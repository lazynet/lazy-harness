"""lh hooks — hook management commands."""

from __future__ import annotations

import click
from rich.console import Console
from rich.table import Table

from lazy_harness.core.config import ConfigError, load_config
from lazy_harness.core.paths import config_file
from lazy_harness.hooks.loader import list_builtin_hooks, resolve_hooks_for_event


@click.group()
def hooks() -> None:
    """Manage hooks."""


@hooks.command("list")
def hooks_list() -> None:
    """List all configured and built-in hooks."""
    console = Console()

    builtins = list_builtin_hooks()
    console.print("[bold]Built-in hooks:[/bold]")
    for name in builtins:
        console.print(f"  {name}")
    console.print()

    cf = config_file()
    if not cf.is_file():
        console.print("No config file. Run: lh init")
        return

    try:
        cfg = load_config(cf)
    except ConfigError as e:
        console.print(f"[red]Error: {e}[/red]")
        return

    if not cfg.hooks:
        console.print("No hooks configured in config.toml.")
        return

    console.print("[bold]Configured hooks:[/bold]")
    table = Table(show_header=True, pad_edge=False)
    table.add_column("Event")
    table.add_column("Scripts")
    table.add_column("Status")

    for event_name, event_cfg in cfg.hooks.items():
        resolved = resolve_hooks_for_event(cfg, event_name)
        resolved_names = {h.name for h in resolved}
        script_list: list[str] = []
        for s in event_cfg.scripts:
            if s in resolved_names:
                script_list.append(f"[green]✓[/green] {s}")
            else:
                script_list.append(f"[red]✗[/red] {s} (not found)")
        table.add_row(
            event_name, "\n".join(script_list), f"{len(resolved)}/{len(event_cfg.scripts)}"
        )

    console.print(table)


@hooks.command("run")
@click.argument("event")
def hooks_run(event: str) -> None:
    """Run hooks for an event (for debugging)."""
    console = Console()

    cf = config_file()
    try:
        cfg = load_config(cf)
    except ConfigError as e:
        console.print(f"[red]Error: {e}[/red]")
        raise SystemExit(1)

    from lazy_harness.hooks.engine import run_hooks_for_event
    from lazy_harness.hooks.loader import resolve_hooks_for_event as resolve_hooks

    hooks_to_run = resolve_hooks(cfg, event)
    if not hooks_to_run:
        console.print(f"No hooks configured for event '{event}'.")
        return

    console.print(f"Running {len(hooks_to_run)} hook(s) for '{event}'...")
    results = run_hooks_for_event(hooks_to_run, event=event, payload={})

    for r in results:
        status = "[green]✓[/green]" if r.exit_code == 0 else "[red]✗[/red]"
        console.print(f"  {status} {r.hook_name} ({r.duration_ms}ms)")
        if r.stderr:
            console.print(f"    stderr: {r.stderr[:200]}")

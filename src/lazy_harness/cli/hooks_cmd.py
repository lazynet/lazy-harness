"""lh hooks — hook management commands."""

from __future__ import annotations

import importlib
import sys

import click
from rich.console import Console
from rich.markup import escape
from rich.table import Table

from lazy_harness.core.config import ConfigError, load_config
from lazy_harness.core.paths import config_file
from lazy_harness.hooks.loader import (
    _BUILTIN_HOOKS,
    list_builtin_hooks,
    resolve_hooks_for_event,
)
from lazy_harness.hooks.runner import resolve_profile, run_hook


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
        console.print(f"[red]Error: {escape(str(e))}[/red]")
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


@click.command("hook")
@click.argument("name")
@click.option(
    "--profile",
    default=None,
    help="Profile this hook runs under. Optional while deployed commands omit it.",
)
def hook_invoke(name: str, profile: str | None) -> None:
    """Invoke a built-in hook by name. Called from settings.json by Claude Code.

    A migrated builtin goes through `hooks.runner.run_hook`, which parses the
    payload through the agent adapter and serialises the decision back; an
    unmigrated one is imported and its `main()` called with no arguments, the
    way this command always has. `BuiltinHookSpec.migrated` is what decides,
    and that branch disappears with the field at step 5 of the design.
    """
    spec = _BUILTIN_HOOKS.get(name)
    if spec is None:
        click.echo(f"Unknown hook: {name}", err=True)
        sys.exit(0)
    if spec.migrated:
        output = run_hook(name, profile=resolve_profile(profile), stdin_text=sys.stdin.read())
        if output.stdout:
            click.echo(output.stdout, nl=False)
        if output.stderr:
            click.echo(output.stderr, nl=False, err=True)
        sys.exit(output.exit_code)
    try:
        # `_BUILTIN_HOOKS` maps to `BuiltinHookSpec`, not to a module path.
        # Passing the record straight to `import_module` raised an
        # `AttributeError` outside the guard below, so this entry point exited
        # 1 with a traceback the first time anything called it.
        module = importlib.import_module(spec.module)
        main_fn = getattr(module, "main", None)
        if main_fn is None:
            click.echo(f"Hook {name} has no main()", err=True)
            sys.exit(0)
        main_fn()
    except SystemExit:
        # The exit code is the hook's verdict, not just its status: Claude Code
        # reads 2 on PreToolUse as "block this tool call". Swallowing it here
        # left `pre-tool-use-security` writing a refusal to stderr while the
        # command ran anyway.
        raise
    except Exception as e:  # noqa: BLE001 — hooks must never bubble up to Claude Code
        # Widened from ImportError: a hook that fails has to degrade, and the
        # narrow clause is what let the registry mistake above escape.
        click.echo(f"Hook {name} raised: {type(e).__name__}: {e}", err=True)
    sys.exit(0)


@hooks.command("run")
@click.argument("event")
@click.option(
    "--profile",
    default=None,
    help="Profile to run the hooks under. Defaults to the running agent's.",
)
def hooks_run(event: str, profile: str | None) -> None:
    """Run hooks for an event (for debugging).

    The same mechanism `lh hook` uses, so what a developer debugs here is what
    the agent will see: migrated builtins go through the runner, and the
    profile resolves through `resolve_profile` on both paths.
    """
    console = Console()

    cf = config_file()
    try:
        cfg = load_config(cf)
    except ConfigError as e:
        console.print(f"[red]Error: {escape(str(e))}[/red]")
        raise SystemExit(1)

    from lazy_harness.hooks.engine import run_hooks_for_event
    from lazy_harness.hooks.loader import resolve_hooks_for_event as resolve_hooks

    hooks_to_run = resolve_hooks(cfg, event)
    if not hooks_to_run:
        console.print(f"No hooks configured for event '{event}'.")
        return

    console.print(f"Running {len(hooks_to_run)} hook(s) for '{event}'...")
    results = run_hooks_for_event(hooks_to_run, event=event, payload={}, profile=profile)

    for r in results:
        status = "[green]✓[/green]" if r.exit_code == 0 else "[red]✗[/red]"
        console.print(f"  {status} {r.hook_name} ({r.duration_ms}ms)")
        if r.stderr:
            console.print(f"    stderr: {r.stderr[:200]}")

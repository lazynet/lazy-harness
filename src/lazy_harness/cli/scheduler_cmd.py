"""lh scheduler — scheduled jobs management."""

from __future__ import annotations

import platform

import click
from rich.console import Console
from rich.markup import escape

from lazy_harness.core.config import ConfigError, load_config
from lazy_harness.core.paths import config_file
from lazy_harness.scheduler.manager import detect_backend, parse_jobs_from_config
from lazy_harness.scheduler.schedule import ScheduleTranslationError


@click.group()
def scheduler() -> None:
    """Manage scheduled jobs."""


def _exit_note(backend: object, label: str) -> str:
    """` (exit N)` for a job whose last run is known; empty when it is not.

    A backend predating `last_exit` has no such attribute, and an unknown
    status is not a success, so both print nothing rather than `exit 0`.
    """
    probe = getattr(backend, "last_exit", None)
    code = probe(label) if callable(probe) else None
    if code is None:
        return ""
    style = "green" if code == 0 else "red"
    return f" [{style}](exit {code})[/{style}]"


@scheduler.command("status")
def scheduler_status() -> None:
    """Show scheduler backend and job status."""
    console = Console()
    cf = config_file()
    try:
        cfg = load_config(cf)
    except ConfigError as e:
        console.print(f"[red]Error: {escape(str(e))}[/red]")
        raise SystemExit(1)
    backend = detect_backend(cfg.scheduler.backend, timezone=cfg.scheduler.timezone)
    backend_name = backend.__class__.__name__.replace("Backend", "").lower()
    console.print(f"[bold]Scheduler backend:[/bold] {backend_name} ({platform.system()})")
    jobs = backend.status()
    if jobs:
        console.print(f"\n[bold]Jobs ({len(jobs)}):[/bold]")
        for job in jobs:
            st = job.get("status", "unknown")
            label = job.get("label", "?")
            style = "green" if st == "loaded" else "red"
            exit_note = _exit_note(backend, label)
            console.print(f"  [{style}]{st}[/{style}] {label}{exit_note}")
    else:
        console.print("\nNo managed jobs found.")
        console.print(escape("Configure jobs in config.toml under [scheduler.jobs]"))


@scheduler.command("install")
def scheduler_install() -> None:
    """Install scheduled jobs for current OS."""
    console = Console()
    cf = config_file()
    try:
        cfg = load_config(cf)
    except ConfigError as e:
        console.print(f"[red]Error: {escape(str(e))}[/red]")
        raise SystemExit(1)
    backend = detect_backend(cfg.scheduler.backend, timezone=cfg.scheduler.timezone)
    jobs = parse_jobs_from_config(cfg)
    if not jobs:
        console.print(escape("No jobs configured. Add jobs in config.toml under [scheduler.jobs]"))
        return
    try:
        installed = backend.install(jobs)
    except NotImplementedError as e:
        console.print(f"[red]Error: {escape(str(e))}[/red]")
        raise SystemExit(1)
    except (RuntimeError, ValueError) as e:
        # A backend refusing to write — no crontab binary, a systemctl that
        # rejected the unit, a command systemd cannot exec. All are the user's
        # to fix and none should reach them as a stack trace.
        console.print(f"[red]Error: {escape(str(e))}[/red]")
        console.print("[dim]Nothing was installed.[/dim]")
        raise SystemExit(1)
    except ScheduleTranslationError as e:
        # `install` validates the whole set before writing, so nothing was
        # installed and the user only has to fix the declaration.
        console.print(f"[red]Error: {escape(str(e))}[/red]")
        console.print("[dim]Nothing was installed. Fix the schedule and run again.[/dim]")
        raise SystemExit(1)
    for label in installed:
        console.print(f"  [green]✓[/green] {label}")


@scheduler.command("uninstall")
def scheduler_uninstall() -> None:
    """Remove all scheduled jobs."""
    console = Console()
    cf = config_file()
    try:
        cfg = load_config(cf)
    except ConfigError as e:
        console.print(f"[red]Error: {escape(str(e))}[/red]")
        raise SystemExit(1)
    backend = detect_backend(cfg.scheduler.backend, timezone=cfg.scheduler.timezone)
    jobs = parse_jobs_from_config(cfg)
    removed = backend.uninstall(jobs)
    if removed:
        for label in removed:
            console.print(f"  [green]✓[/green] Removed {label}")
    else:
        console.print("No jobs to remove.")

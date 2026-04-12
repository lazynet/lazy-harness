"""lh scheduler — scheduled jobs management."""

from __future__ import annotations

import platform

import click
from rich.console import Console

from lazy_harness.core.config import ConfigError, load_config
from lazy_harness.core.paths import config_file
from lazy_harness.scheduler.manager import detect_backend, parse_jobs_from_config


@click.group()
def scheduler() -> None:
    """Manage scheduled jobs."""


@scheduler.command("status")
def scheduler_status() -> None:
    """Show scheduler backend and job status."""
    console = Console()
    cf = config_file()
    try:
        cfg = load_config(cf)
    except ConfigError as e:
        console.print(f"[red]Error: {e}[/red]")
        raise SystemExit(1)
    backend = detect_backend(cfg.scheduler.backend)
    backend_name = backend.__class__.__name__.replace("Backend", "").lower()
    console.print(f"[bold]Scheduler backend:[/bold] {backend_name} ({platform.system()})")
    jobs = backend.status()
    if jobs:
        console.print(f"\n[bold]Jobs ({len(jobs)}):[/bold]")
        for job in jobs:
            st = job.get("status", "unknown")
            label = job.get("label", "?")
            style = "green" if st == "loaded" else "red"
            console.print(f"  [{style}]{st}[/{style}] {label}")
    else:
        console.print("\nNo managed jobs found.")
        console.print("Configure jobs in config.toml under [scheduler.jobs]")


@scheduler.command("install")
def scheduler_install() -> None:
    """Install scheduled jobs for current OS."""
    console = Console()
    cf = config_file()
    try:
        cfg = load_config(cf)
    except ConfigError as e:
        console.print(f"[red]Error: {e}[/red]")
        raise SystemExit(1)
    backend = detect_backend(cfg.scheduler.backend)
    jobs = parse_jobs_from_config(cfg)
    if not jobs:
        console.print("No jobs configured. Add jobs in config.toml under [scheduler.jobs]")
        return
    installed = backend.install(jobs)
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
        console.print(f"[red]Error: {e}[/red]")
        raise SystemExit(1)
    backend = detect_backend(cfg.scheduler.backend)
    jobs = parse_jobs_from_config(cfg)
    removed = backend.uninstall(jobs)
    if removed:
        for label in removed:
            console.print(f"  [green]✓[/green] Removed {label}")
    else:
        console.print("No jobs to remove.")

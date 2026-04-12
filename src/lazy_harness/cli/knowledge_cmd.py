"""lh knowledge — knowledge directory management."""

from __future__ import annotations

import click
from rich.console import Console

from lazy_harness.core.config import ConfigError, load_config
from lazy_harness.core.paths import config_file, contract_path, expand_path
from lazy_harness.knowledge.directory import list_sessions
from lazy_harness.knowledge.qmd import embed, is_qmd_available, sync
from lazy_harness.knowledge.qmd import status as qmd_status


@click.group()
def knowledge() -> None:
    """Manage knowledge directory and QMD."""


@knowledge.command("status")
def knowledge_status() -> None:
    """Show knowledge directory and QMD status."""
    console = Console()
    cf = config_file()
    try:
        cfg = load_config(cf)
    except ConfigError as e:
        console.print(f"[red]Error: {e}[/red]")
        raise SystemExit(1)
    if not cfg.knowledge.path:
        console.print("[red]Knowledge path not configured.[/red]")
        console.print("Set [knowledge].path in config.toml")
        return
    kdir = expand_path(cfg.knowledge.path)
    console.print(f"[bold]Knowledge directory:[/bold] {contract_path(kdir)}")
    if kdir.is_dir():
        console.print("[green]✓[/green] Directory exists")
        sessions = list_sessions(kdir, cfg.knowledge.sessions.subdir)
        console.print(f"  Sessions: {len(sessions)} exported")
    else:
        console.print("[red]✗[/red] Directory missing")
    console.print()
    if is_qmd_available():
        console.print("[green]✓[/green] QMD available")
        result = qmd_status()
        if result.exit_code == 0 and result.stdout:
            for line in result.stdout.strip().splitlines()[:5]:
                console.print(f"  {line}")
    else:
        console.print("[yellow]·[/yellow] QMD not available")


@knowledge.command("sync")
@click.option("--collection", default=None, help="Sync specific collection")
def knowledge_sync(collection: str | None) -> None:
    """Sync QMD index (BM25)."""
    console = Console()
    if not is_qmd_available():
        console.print("[red]QMD not found in PATH[/red]")
        raise SystemExit(1)
    console.print("Syncing QMD index...")
    result = sync(collection=collection)
    if result.exit_code == 0:
        console.print("[green]✓[/green] Sync complete")
        if result.stdout.strip():
            for line in result.stdout.strip().splitlines()[:10]:
                console.print(f"  {line}")
    else:
        console.print(f"[red]✗[/red] Sync failed (exit {result.exit_code})")


@knowledge.command("embed")
@click.option("--collection", default=None, help="Embed specific collection")
def knowledge_embed(collection: str | None) -> None:
    """Run QMD vector embedding."""
    console = Console()
    if not is_qmd_available():
        console.print("[red]QMD not found in PATH[/red]")
        raise SystemExit(1)
    console.print("Running QMD embedding...")
    result = embed(collection=collection)
    if result.exit_code == 0:
        console.print("[green]✓[/green] Embedding complete")
    else:
        console.print(f"[red]✗[/red] Embedding failed (exit {result.exit_code})")

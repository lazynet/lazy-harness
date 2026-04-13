"""lh metrics — ingest agent session JSONLs into the metrics DB."""

from __future__ import annotations

import click
from rich.console import Console

from lazy_harness.core.config import ConfigError, load_config
from lazy_harness.core.paths import config_file, data_dir, expand_path
from lazy_harness.monitoring.db import MetricsDB
from lazy_harness.monitoring.ingest import ingest_all
from lazy_harness.monitoring.pricing import load_pricing


@click.group()
def metrics() -> None:
    """Metrics ingest and inspection."""


@metrics.command("ingest")
@click.option("--dry-run", is_flag=True, help="Parse sessions but do not write to the DB.")
@click.option("--verbose", "-v", is_flag=True, help="Show per-profile counters.")
def metrics_ingest(dry_run: bool, verbose: bool) -> None:
    """Scan every profile's projects/*.jsonl and upsert token stats."""
    console = Console()
    try:
        cfg = load_config(config_file())
    except ConfigError as e:
        console.print(f"[red]Error:[/red] {e}")
        raise SystemExit(1)

    if not cfg.monitoring.enabled:
        console.print("[yellow]monitoring disabled in config; nothing to do.[/yellow]")
        return

    db_path = expand_path(cfg.monitoring.db) if cfg.monitoring.db else data_dir() / "metrics.db"

    from pathlib import Path

    if dry_run:
        console.print(f"[dim]dry-run — target DB would be: {db_path}[/dim]")
        db = MetricsDB(Path(":memory:"))
    else:
        db = MetricsDB(db_path)
    try:
        pricing = load_pricing(cfg.monitoring.pricing or None)
        report = ingest_all(cfg, db, pricing)
    finally:
        db.close()

    console.print(
        f"[green]✓[/green] scanned {report.sessions_scanned} · "
        f"updated {report.sessions_updated} · "
        f"skipped {report.sessions_skipped}"
    )
    if report.errors and verbose:
        for err in report.errors:
            console.print(f"[red]  {err}[/red]")

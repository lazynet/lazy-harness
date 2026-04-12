"""lh status — monitoring dashboard."""

from __future__ import annotations

from datetime import datetime, timedelta

import click
from rich.console import Console

from lazy_harness.core.config import ConfigError, load_config
from lazy_harness.core.paths import config_file, data_dir, expand_path
from lazy_harness.monitoring.dashboard import render_costs, render_overview
from lazy_harness.monitoring.db import MetricsDB


def _get_db(cfg) -> MetricsDB:
    if cfg.monitoring.db:
        db_path = expand_path(cfg.monitoring.db)
    else:
        db_path = data_dir() / "metrics.db"
    return MetricsDB(db_path)


@click.group(invoke_without_command=True)
@click.pass_context
def status(ctx: click.Context) -> None:
    """Monitoring dashboard."""
    if ctx.invoked_subcommand is not None:
        return

    console = Console()
    cf = config_file()
    try:
        cfg = load_config(cf)
    except ConfigError as e:
        console.print(f"[red]Error: {e}[/red]")
        raise SystemExit(1)

    if not cfg.monitoring.enabled:
        console.print("Monitoring is disabled. Enable in config.toml:")
        console.print("  [monitoring]")
        console.print("  enabled = true")
        return

    db = _get_db(cfg)
    try:
        render_overview(db, console)
    finally:
        db.close()


@status.command("costs")
@click.option("--period", default="7d", help="Period: 7d, 30d, month, all")
def status_costs(period: str) -> None:
    """Show cost breakdown."""
    console = Console()
    cf = config_file()
    try:
        cfg = load_config(cf)
    except ConfigError as e:
        console.print(f"[red]Error: {e}[/red]")
        raise SystemExit(1)

    if not cfg.monitoring.enabled:
        console.print("Monitoring is disabled.")
        return

    since = None
    query_period = "all"
    if period.endswith("d"):
        days = int(period[:-1])
        since = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    elif period == "month":
        query_period = datetime.now().strftime("%Y-%m")
    elif period != "all":
        query_period = period

    db = _get_db(cfg)
    try:
        render_costs(db, console, period=query_period, since=since)
    finally:
        db.close()

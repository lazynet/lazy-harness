"""lh metrics — ingest agent session JSONLs into the metrics DB."""

from __future__ import annotations

import time
from pathlib import Path

import click
from rich.console import Console

from lazy_harness.core.config import ConfigError, load_config
from lazy_harness.core.identity import resolve_identity
from lazy_harness.core.paths import config_file, data_dir, expand_path
from lazy_harness.monitoring.db import MetricsDB
from lazy_harness.monitoring.ingest import ingest_all
from lazy_harness.monitoring.pricing import load_pricing
from lazy_harness.monitoring.sink_setup import build_sinks
from lazy_harness.monitoring.sinks.http_remote import HttpRemoteSink


@click.group()
def metrics() -> None:
    """Metrics ingest and inspection."""


@metrics.command("ingest")
@click.option("--dry-run", is_flag=True, help="Parse sessions but do not write to the DB.")
@click.option("--verbose", "-v", is_flag=True, help="Show per-profile counters.")
def metrics_ingest(dry_run: bool, verbose: bool) -> None:
    """Scan every profile's projects/*.jsonl and upsert token stats."""
    console = Console()
    stderr = Console(stderr=True)
    try:
        cfg = load_config(config_file())
    except ConfigError as e:
        console.print(f"[red]Error:[/red] {e}")
        raise SystemExit(1)

    if not cfg.monitoring.enabled:
        console.print("[yellow]monitoring disabled in config; nothing to do.[/yellow]")
        return

    identity = resolve_identity(explicit=cfg.metrics.user_id or None)
    _print_active_sinks(stderr, cfg, identity)

    db_path = expand_path(cfg.monitoring.db) if cfg.monitoring.db else data_dir() / "metrics.db"

    if dry_run:
        console.print(f"[dim]dry-run — target DB would be: {db_path}[/dim]")
        db = MetricsDB(Path(":memory:"))
    else:
        db = MetricsDB(Path(db_path))

    try:
        pricing = load_pricing(cfg.monitoring.pricing or None)
        sinks = build_sinks(cfg.metrics, db=db)
        report = ingest_all(cfg, db, pricing, sinks=sinks)

        for sink in sinks:
            if isinstance(sink, HttpRemoteSink):
                try:
                    sink.drain(batch_size=0)
                except Exception:
                    pass
    finally:
        db.close()

    console.print(
        f"[green]✓[/green] scanned {report.sessions_scanned} · "
        f"updated {report.sessions_updated} · "
        f"skipped {report.sessions_skipped}"
    )
    if report.unknown_models:
        names = ", ".join(sorted(report.unknown_models))
        console.print(
            f"[yellow]![/yellow] no pricing for {names} — "
            f"those sessions were priced at $0. Add rates under "
            f"[bold]\\[monitoring.pricing][/bold] in config.toml."
        )
    if report.errors and verbose:
        for err in report.errors:
            console.print(f"[red]  {err}[/red]")


def _print_active_sinks(console: Console, cfg, identity) -> None:
    url_detail = ""
    for name in cfg.metrics.sinks:
        if name == "http_remote":
            opts = cfg.metrics.sink_configs.get("http_remote")
            if opts:
                url_detail = f" → {opts.options.get('url', '')}"
    sink_list = ", ".join(cfg.metrics.sinks)
    console.print(f"[dim]metrics sinks active: {sink_list}{url_detail}[/dim]")
    console.print(f"[dim]identity: {identity.user_id} (source: {identity.source})[/dim]")


@metrics.command("drain")
def metrics_drain() -> None:
    """Force-drain the outbox for every configured remote sink."""
    console = Console(stderr=True)
    try:
        cfg = load_config(config_file())
    except ConfigError as e:
        console.print(f"[red]Error:[/red] {e}")
        raise SystemExit(1)

    identity = resolve_identity(explicit=cfg.metrics.user_id or None)
    _print_active_sinks(console, cfg, identity)

    db_path = expand_path(cfg.monitoring.db) if cfg.monitoring.db else data_dir() / "metrics.db"
    db = MetricsDB(Path(db_path))
    try:
        sinks = build_sinks(cfg.metrics, db=db)
        total_sent = 0
        total_failed = 0
        for sink in sinks:
            if isinstance(sink, HttpRemoteSink):
                result = sink.drain(batch_size=0)
                total_sent += result.sent
                total_failed += result.failed
    finally:
        db.close()

    Console().print(f"[green]drain complete:[/green] {total_sent} sent, {total_failed} failed")


@metrics.command("status")
def metrics_status() -> None:
    """Show pending/sent counts per remote sink."""
    console = Console()
    try:
        cfg = load_config(config_file())
    except ConfigError as e:
        console.print(f"[red]Error:[/red] {e}")
        raise SystemExit(1)

    db_path = expand_path(cfg.monitoring.db) if cfg.monitoring.db else data_dir() / "metrics.db"
    db = MetricsDB(Path(db_path))
    try:
        totals = db.aggregate_costs(period="all")
        console.print(
            f"[bold]sqlite_local[/bold]  {totals['session_count']} sessions  "
            f"${totals['total_cost']}  {db_path}"
        )

        remote_sinks = [name for name in cfg.metrics.sinks if name != "sqlite_local"]
        if not remote_sinks:
            console.print("No remote sinks configured; nothing is queued for delivery.")
        for name in remote_sinks:
            stats = db.outbox_stats(name)
            console.print(
                f"[bold]{name}[/bold]  pending: {stats['pending']}  "
                f"sending: {stats['sending']}  sent: {stats['sent']}"
            )
    finally:
        db.close()


@metrics.command("loops")
@click.option("--days", type=int, default=None, help="Only count events from the last N days.")
@click.option("--db", "db_override", type=click.Path(path_type=Path), default=None)
def metrics_loops(days: int | None, db_override: Path | None) -> None:
    """Report loop-event counts and the declared-goal rate."""
    console = Console()

    if db_override is not None:
        db_path = db_override
    else:
        try:
            cfg = load_config(config_file())
        except ConfigError:
            cfg = None
        configured = cfg.monitoring.db if cfg and cfg.monitoring.db else None
        db_path = expand_path(configured) if configured else data_dir() / "metrics.db"

    since = None if days is None else time.time() - days * 86400
    counts = MetricsDB(db_path).loop_event_counts(since_ts=since)

    if counts:
        for kind in sorted(counts):
            console.print(f"{kind:<20} {counts[kind]}")
        console.print()

    declared = counts.get("goal_declared", 0)
    considered = declared + counts.get("goal_absent", 0)
    rate = 0 if considered == 0 else round(100 * declared / considered)
    console.print(f"declared rate: {rate}% ({declared}/{considered})")

"""lh status — monitoring dashboard with 9 sub-views."""

from __future__ import annotations

from datetime import datetime, timedelta

import click
from rich.console import Console

from lazy_harness.core.config import Config, ConfigError, load_config
from lazy_harness.core.paths import config_file, data_dir, expand_path
from lazy_harness.monitoring.dashboard import render_costs
from lazy_harness.monitoring.db import MetricsDB
from lazy_harness.monitoring.views import (
    cron as cron_view,
)
from lazy_harness.monitoring.views import (
    hooks as hooks_view,
)
from lazy_harness.monitoring.views import (
    memory as memory_view,
)
from lazy_harness.monitoring.views import (
    overview as overview_view,
)
from lazy_harness.monitoring.views import (
    profiles as profiles_view,
)
from lazy_harness.monitoring.views import (
    projects as projects_view,
)
from lazy_harness.monitoring.views import (
    queue as queue_view,
)
from lazy_harness.monitoring.views import (
    sessions as sessions_view,
)
from lazy_harness.monitoring.views import (
    tokens as tokens_view,
)
from lazy_harness.monitoring.views._helpers import StatusContext


def _load() -> Config:
    cf = config_file()
    try:
        return load_config(cf)
    except ConfigError as e:
        Console().print(f"[red]Error: {e}[/red]")
        raise SystemExit(1)


def _open_db(cfg: Config) -> MetricsDB | None:
    """Open the metrics DB if monitoring is enabled and it exists."""
    if not cfg.monitoring.enabled:
        return None
    db_path = expand_path(cfg.monitoring.db) if cfg.monitoring.db else data_dir() / "metrics.db"
    if not db_path.is_file():
        return None
    return MetricsDB(db_path)


@click.group(invoke_without_command=True)
@click.pass_context
def status(ctx: click.Context) -> None:
    """Monitoring dashboard. With no subcommand, prints the overview."""
    if ctx.invoked_subcommand is not None:
        return
    cfg = _load()
    sctx = StatusContext.build(cfg)
    db = _open_db(cfg)
    try:
        overview_view.render(sctx, db, Console())
    finally:
        if db is not None:
            db.close()


@status.command("overview")
def status_overview() -> None:
    """At-a-glance summary panel."""
    cfg = _load()
    sctx = StatusContext.build(cfg)
    db = _open_db(cfg)
    try:
        overview_view.render(sctx, db, Console())
    finally:
        if db is not None:
            db.close()


@status.command("profiles")
def status_profiles() -> None:
    """Per-profile config, hooks count, MCPs, auth."""
    cfg = _load()
    profiles_view.render(StatusContext.build(cfg), Console())


@status.command("projects")
def status_projects() -> None:
    """Per-project session counts and last activity."""
    cfg = _load()
    projects_view.render(StatusContext.build(cfg), Console())


@status.command("sessions")
@click.option(
    "--period",
    default="month",
    type=click.Choice(["today", "week", "month", "all"]),
    help="Period to summarize",
)
def status_sessions(period: str) -> None:
    """Daily breakdown of sessions, tokens, cost."""
    cfg = _load()
    db = _open_db(cfg)
    if db is None:
        Console().print("[dim]Monitoring DB not available.[/dim]")
        return
    try:
        sessions_view.render(db, Console(), period)
    finally:
        db.close()


@status.command("tokens")
@click.option(
    "--period",
    default="month",
    type=click.Choice(["today", "week", "month", "all"]),
)
@click.option(
    "--by",
    "group_by",
    default="project",
    type=click.Choice(["project", "model", "profile"]),
)
def status_tokens(period: str, group_by: str) -> None:
    """Token / cost breakdown grouped by project, model, or profile."""
    cfg = _load()
    db = _open_db(cfg)
    if db is None:
        Console().print("[dim]Monitoring DB not available.[/dim]")
        return
    try:
        tokens_view.render(db, Console(), period, group_by)
    finally:
        db.close()


@status.command("hooks")
def status_hooks() -> None:
    """Last fired hooks + log health."""
    cfg = _load()
    hooks_view.render(StatusContext.build(cfg), Console())


@status.command("cron")
def status_cron() -> None:
    """Scheduled launchd jobs and their last runs."""
    cfg = _load()
    cron_view.render(StatusContext.build(cfg), Console())


@status.command("queue")
def status_queue() -> None:
    """Compound-loop queue depth + recent worker activity."""
    cfg = _load()
    queue_view.render(StatusContext.build(cfg), Console())


@status.command("memory")
def status_memory() -> None:
    """Per-project decisions/failures/learnings counts."""
    cfg = _load()
    memory_view.render(StatusContext.build(cfg), Console())


@status.command("costs")
@click.option("--period", default="7d", help="Period: 7d, 30d, month, all")
def status_costs(period: str) -> None:
    """Show cost breakdown (legacy view, kept for back-compat)."""
    cfg = _load()
    db = _open_db(cfg)
    if db is None:
        Console().print("[dim]Monitoring DB not available.[/dim]")
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
    try:
        render_costs(db, Console(), period=query_period, since=since)
    finally:
        db.close()

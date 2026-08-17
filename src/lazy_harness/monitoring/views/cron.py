"""`lh status cron` view — scheduled launchd jobs and their last runs."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from rich.console import RenderableType
from rich.table import Table

from lazy_harness.monitoring.views._helpers import (
    StatusContext,
    last_log_timestamp,
    time_ago,
)
from lazy_harness.scheduler.base import JobState


def _last_run_for(label: str) -> str:
    """Heuristic: search common log locations for the most recent timestamp."""
    candidates = [
        Path.home() / ".local" / "share" / "lazy-harness" / "logs" / f"{label}-stdout.log",
        Path.home() / ".local" / "share" / "lazy-harness" / "logs" / f"{label}.log",
        Path.home() / ".local" / "share" / "lazy-harness" / "logs" / f"qmd-{label}.log",
    ]
    for log_path in candidates:
        if not log_path.is_file():
            continue
        ts = last_log_timestamp(log_path)
        if ts:
            return time_ago(ts)
        try:
            mtime = datetime.fromtimestamp(log_path.stat().st_mtime)
            return time_ago(mtime.strftime("%Y-%m-%dT%H:%M:%S"))
        except OSError:
            continue
    return "—"


_STATUS_MARKUP = {
    JobState.LOADED: "[green]loaded[/green]",
    JobState.NOT_LOADED: "[red]not loaded[/red]",
    # Never rendered red: the backend could not check, which says nothing
    # about the job.
    JobState.UNKNOWN: "[yellow]?[/yellow]",
}


def render(ctx: StatusContext) -> RenderableType:
    table = Table(show_header=True, pad_edge=False)
    table.add_column("Agent")
    table.add_column("Schedule")
    table.add_column("Status")
    table.add_column("Last Run")

    backend = ctx.scheduler_backend
    records = backend.discover() if backend is not None else []
    if not records:
        return "[dim]No managed jobs.[/dim]"

    for rec in records:
        status = _STATUS_MARKUP[rec.state]
        if rec.state is JobState.UNKNOWN and rec.detail:
            status = f"{status} [dim]{rec.detail}[/dim]"
        table.add_row(rec.name, rec.schedule, status, _last_run_for(rec.name))

    return table

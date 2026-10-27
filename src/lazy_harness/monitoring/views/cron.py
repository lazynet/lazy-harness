"""`lh status cron` view — scheduled jobs and their last runs."""

from __future__ import annotations

from rich.console import RenderableType
from rich.table import Table

from lazy_harness.monitoring.views._helpers import (
    StatusContext,
    time_ago,
)
from lazy_harness.scheduler.base import JobState
from lazy_harness.scheduler.history import last_run_from_logs


def _last_run_for(label: str) -> str:
    stamp = last_run_from_logs(label)
    return time_ago(stamp.strftime("%Y-%m-%dT%H:%M:%S")) if stamp else "—"


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
        query = getattr(backend, "last_run", None)
        stamp = query(rec.label) if callable(query) else None
        last_run = (
            time_ago(stamp.astimezone().strftime("%Y-%m-%dT%H:%M:%S"))
            if stamp
            else _last_run_for(rec.name)
        )
        table.add_row(rec.name, rec.schedule, status, last_run)

    return table

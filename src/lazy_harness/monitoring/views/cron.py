"""`lh status cron` view — scheduled launchd jobs and their last runs."""

from __future__ import annotations

import plistlib
from datetime import datetime
from pathlib import Path

from rich.console import Console
from rich.table import Table

from lazy_harness.monitoring.views._helpers import (
    StatusContext,
    last_log_timestamp,
    launchctl_loaded,
    time_ago,
)


def _format_schedule(plist_file: Path) -> str:
    """Render a launchd plist's schedule as a short human string."""
    if not plist_file.is_file():
        return "—"
    try:
        with open(plist_file, "rb") as f:
            data = plistlib.load(f)
    except (OSError, plistlib.InvalidFileException):
        return "—"
    interval = data.get("StartInterval")
    if isinstance(interval, int):
        if interval < 3600:
            return f"every {interval // 60}m"
        if interval < 86400:
            return f"every {interval // 3600}h"
        return f"every {interval // 86400}d"
    cal = data.get("StartCalendarInterval")
    if isinstance(cal, dict):
        hour = cal.get("Hour", 0)
        minute = cal.get("Minute", 0)
        return f"daily {hour:02d}:{minute:02d}"
    if isinstance(cal, list):
        first = cal[0] if cal else {}
        hour = first.get("Hour", 0)
        minute = first.get("Minute", 0)
        n = len(cal)
        if n == 7:
            return f"daily {hour:02d}:{minute:02d}"
        if n == 5:
            return f"weekdays {hour:02d}:{minute:02d}"
        return f"{n}x/week {hour:02d}:{minute:02d}"
    return "—"


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


def render(ctx: StatusContext, console: Console) -> None:
    plist_dir = Path.home() / "Library" / "LaunchAgents"
    table = Table(show_header=True, pad_edge=False)
    table.add_column("Agent")
    table.add_column("Schedule")
    table.add_column("Status")
    table.add_column("Last Run")

    if not plist_dir.is_dir():
        console.print("[dim]No LaunchAgents directory.[/dim]")
        return

    plists = sorted(plist_dir.glob(f"{ctx.launchd_prefix}.*.plist"))
    if not plists:
        console.print(f"[dim]No managed jobs (prefix: {ctx.launchd_prefix}).[/dim]")
        return

    for plist_file in plists:
        full_label = plist_file.stem
        short = full_label[len(ctx.launchd_prefix) + 1 :] if "." in full_label else full_label
        loaded = launchctl_loaded(full_label)
        status = "[green]loaded[/green]" if loaded else "[red]not loaded[/red]"
        schedule = _format_schedule(plist_file)
        last_run = _last_run_for(short)
        table.add_row(short, schedule, status, last_run)

    console.print(table)

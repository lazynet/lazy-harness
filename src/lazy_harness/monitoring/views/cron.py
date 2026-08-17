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

_WEEKDAYS = ("Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat")


def _clock(entry: dict) -> str:
    return f"{entry.get('Hour', 0):02d}:{entry.get('Minute', 0):02d}"


def _describe_entry(entry: dict) -> str:
    """Name a StartCalendarInterval entry by the keys it actually carries.

    An absent key means "every", so Weekday and Day are what make an entry
    weekly or monthly. Reading only Hour and Minute reported every shape as
    `daily`, including the weekly and monthly ones.
    """
    if "Weekday" in entry:
        day = _WEEKDAYS[entry["Weekday"] % 7]
        return f"weekly {day} {_clock(entry)}"
    if "Day" in entry:
        return f"monthly day {entry['Day']} {_clock(entry)}"
    if "Hour" not in entry:
        return f"hourly :{entry.get('Minute', 0):02d}"
    return f"daily {_clock(entry)}"


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
        return _describe_entry(cal)
    if isinstance(cal, list):
        first = cal[0] if cal else {}
        n = len(cal)
        # Which key varies across the entries is what the list means. Reading
        # the length alone reported an hour list as a weekday count.
        if n > 1 and "Hour" in first and len({e.get("Hour") for e in cal}) == n:
            return f"{n}x/day {_clock(first)}"
        if n > 1 and len({e.get("Minute") for e in cal}) == n and "Hour" not in first:
            return f"{n}x/hour :{first.get('Minute', 0):02d}"
        if n > 1 and len({e.get("Weekday") for e in cal}) == n:
            return f"{n}x/week {_clock(first)}"
        return _describe_entry(first)
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

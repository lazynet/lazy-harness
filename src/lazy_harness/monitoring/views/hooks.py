"""`lh status hooks` view — last fired hooks + log health."""

from __future__ import annotations

import os
import re
from datetime import datetime

from rich.console import Console
from rich.table import Table

from lazy_harness.monitoring.views._helpers import (
    HOOK_NAMES_DEFAULT,
    StatusContext,
    count_errors_today,
    file_locked,
    format_size,
    last_hook_line,
    last_hook_ts,
    time_ago,
)

HOOK_NAMES = HOOK_NAMES_DEFAULT


def render(ctx: StatusContext, console: Console) -> None:
    today_str = datetime.now().strftime("%Y-%m-%d")

    table = Table(show_header=True, pad_edge=False)
    table.add_column("Hook")
    table.add_column("Last Run")
    table.add_column("Status")
    table.add_column("Project")

    for profile in ctx.profiles:
        if not profile.exists:
            continue
        hooks_log = ctx.logs_dir(profile) / "hooks.log"
        for hook_name in HOOK_NAMES:
            line = last_hook_line(hooks_log, hook_name)
            if not line:
                ts = last_hook_ts(hooks_log, hook_name)
                if not ts:
                    continue  # not present in this profile's log
            else:
                ts = line.split()[0] if line.split() else ""

            cwd_match = re.search(r"cwd=(\S+)", line) if line else None
            project = os.path.basename(cwd_match.group(1)) if cwd_match else "—"

            if ts and ts[:10] == today_str:
                status = "[green]ok[/green]"
            elif ts:
                status = "[yellow]stale[/yellow]"
            else:
                status = "[dim]never[/dim]"

            table.add_row(f"{profile.name}:{hook_name}", time_ago(ts), status, project)

    console.print(table)

    console.print("\n[bold]Log health:[/bold]")
    for profile in ctx.profiles:
        if not profile.exists:
            continue
        logs_dir = ctx.logs_dir(profile)
        for log_name in ("hooks.log", "compound-loop.log"):
            log_path = logs_dir / log_name
            label = f"{profile.name}:{log_name}"
            if not log_path.is_file():
                console.print(f"  {label:<32} [dim]not found[/dim]")
                continue
            errors = count_errors_today(log_path)
            err_style = "red" if errors > 0 else "green"
            console.print(
                f"  {label:<32} size: {format_size(log_path):<7} "
                f"errors today: [{err_style}]{errors}[/{err_style}]"
            )

    for profile in ctx.profiles:
        if not profile.exists:
            continue
        lock_file = ctx.queue_dir(profile) / ".worker.lock"
        if not lock_file.is_file():
            continue
        held = file_locked(lock_file)
        label = f"{profile.name}:worker.lock"
        if held:
            console.print(f"  {label:<32} [yellow]held (worker running)[/yellow]")
        else:
            console.print(f"  {label:<32} [green]free[/green]")

"""`lh status queue` view — compound-loop queue depth + recent worker activity."""

from __future__ import annotations

import re
from datetime import datetime

from rich.console import Console

from lazy_harness.monitoring.views._helpers import StatusContext, time_ago


def render(ctx: StatusContext, console: Console) -> None:
    today_str = datetime.now().strftime("%Y-%m-%d")

    for profile in ctx.profiles:
        if not profile.exists:
            continue
        queue_dir = ctx.queue_dir(profile)
        done_dir = queue_dir / "done"
        pending = sum(1 for _ in queue_dir.glob("*.task")) if queue_dir.is_dir() else 0
        done_total = sum(1 for _ in done_dir.glob("*.task")) if done_dir.is_dir() else 0
        done_today = 0
        if done_dir.is_dir():
            for f in done_dir.glob("*.task"):
                try:
                    mtime = datetime.fromtimestamp(f.stat().st_mtime)
                except OSError:
                    continue
                if mtime.strftime("%Y-%m-%d") == today_str:
                    done_today += 1

        console.print(f"[bold]{profile.name}[/bold]")
        console.print(f"  Pending:    {pending}")
        console.print(f"  Done today: {done_today}")
        console.print(f"  Done total: {done_total}")

        cl_log = ctx.logs_dir(profile) / "compound-loop.log"
        if cl_log.is_file():
            console.print("  [bold]Recent worker activity:[/bold]")
            try:
                lines = cl_log.read_text().splitlines()
            except OSError:
                lines = []
            recent = [
                line
                for line in lines
                if re.search(r"(wrote|error|already processed|skipped)", line, re.IGNORECASE)
            ][-5:]
            for line in recent:
                ts_match = re.match(r"^([\d\-T:.+]+)", line)
                ago = time_ago(ts_match.group(1)) if ts_match else ""
                rest = re.sub(r"^\S+\s*", "", line)
                if re.search(r"error|failed", line, re.IGNORECASE):
                    marker = "[red]✗[/red]"
                else:
                    marker = "[green]✓[/green]"
                console.print(f"  {marker} {ago}  {rest}")
        console.print()

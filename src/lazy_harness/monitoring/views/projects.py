"""`lh status projects` view — per-project session count, last activity, branch."""

from __future__ import annotations

import json
from datetime import datetime

from rich.console import Console
from rich.table import Table

from lazy_harness.monitoring.views._helpers import (
    StatusContext,
    decode_project_name,
    time_ago,
)


def render(ctx: StatusContext, console: Console) -> None:
    table = Table(show_header=True, pad_edge=False)
    table.add_column("Profile", style="bold")
    table.add_column("Project")
    table.add_column("Last Session")
    table.add_column("Sessions", justify="right")
    table.add_column("Branch")

    any_rows = False
    for p in ctx.profiles:
        projects_dir = p.config_dir / "projects"
        if not projects_dir.is_dir():
            continue
        for pdir in sorted(projects_dir.iterdir()):
            if not pdir.is_dir():
                continue
            jsonl_files = sorted(pdir.glob("*.jsonl"))
            session_count = len(jsonl_files)
            last_session = "—"
            branch = "—"
            if jsonl_files:
                latest = max(jsonl_files, key=lambda f: f.stat().st_mtime)
                try:
                    mtime = datetime.fromtimestamp(latest.stat().st_mtime)
                    last_session = time_ago(mtime.strftime("%Y-%m-%dT%H:%M:%S"))
                except OSError:
                    pass
                try:
                    last_line = latest.read_text().splitlines()[-1]
                    data = json.loads(last_line)
                    branch = data.get("gitBranch") or "—"
                except (json.JSONDecodeError, IndexError, OSError):
                    pass
            table.add_row(
                p.name,
                decode_project_name(pdir.name),
                last_session,
                str(session_count),
                branch,
            )
            any_rows = True

    if not any_rows:
        console.print("[dim]No projects yet.[/dim]")
        return
    console.print(table)

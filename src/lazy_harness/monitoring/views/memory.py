"""`lh status memory` view — per-project decisions/failures/learnings counts + recents."""

from __future__ import annotations

import json
import re
from datetime import datetime

from rich.console import Console
from rich.table import Table

from lazy_harness.monitoring.views._helpers import (
    StatusContext,
    decode_project_name,
    time_ago,
)


def _count_jsonl(path):
    if not path.is_file():
        return 0, ""
    try:
        lines = path.read_text().splitlines()
    except OSError:
        return 0, ""
    count = len(lines)
    last_ts = ""
    if lines:
        try:
            last = json.loads(lines[-1])
            last_ts = last.get("ts", last.get("timestamp", "")) or ""
        except json.JSONDecodeError:
            pass
    return count, last_ts


def _learnings_for_project(learnings_dir, encoded_dir: str) -> int:
    if learnings_dir is None or not learnings_dir.is_dir():
        return 0
    month_dir = learnings_dir / datetime.now().strftime("%Y-%m")
    if not month_dir.is_dir():
        return 0
    origin_match = re.search(r"-repos-[^-]+-(.+)$", encoded_dir)
    if not origin_match:
        return 0
    origin_name = origin_match.group(1)
    pattern = re.compile(rf"^origin: {re.escape(origin_name)}$", re.MULTILINE)
    count = 0
    for lf in month_dir.iterdir():
        if not lf.is_file():
            continue
        try:
            if pattern.search(lf.read_text()):
                count += 1
        except OSError:
            pass
    return count


def render(ctx: StatusContext, console: Console) -> None:
    table = Table(show_header=True, pad_edge=False)
    table.add_column("Project")
    table.add_column("Decisions", justify="right")
    table.add_column("Failures", justify="right")
    table.add_column("Last Entry")
    table.add_column("Learnings (this month)", justify="right")

    any_rows = False
    for p in ctx.profiles:
        projects_dir = p.config_dir / "projects"
        if not projects_dir.is_dir():
            continue
        for pdir in sorted(projects_dir.iterdir()):
            if not pdir.is_dir():
                continue
            memory_dir = pdir / "memory"
            if not memory_dir.is_dir():
                continue

            dec_count, dec_ts = _count_jsonl(memory_dir / "decisions.jsonl")
            fail_count, fail_ts = _count_jsonl(memory_dir / "failures.jsonl")
            last_ts = max((t for t in (dec_ts, fail_ts) if t), default="")
            learn_count = _learnings_for_project(ctx.learnings_dir, pdir.name)

            table.add_row(
                decode_project_name(pdir.name),
                str(dec_count),
                str(fail_count),
                time_ago(last_ts),
                str(learn_count),
            )
            any_rows = True

    if not any_rows:
        console.print("[dim]No project memory yet.[/dim]")
        return
    console.print(table)

    _print_recent(ctx, console, "decisions.jsonl", "Recent decisions")
    _print_recent(ctx, console, "failures.jsonl", "Recent failures")


def _print_recent(ctx: StatusContext, console: Console, filename: str, title: str) -> None:
    console.print(f"\n[bold]{title}:[/bold]")
    entries: list[tuple[str, str]] = []
    for p in ctx.profiles:
        projects_dir = p.config_dir / "projects"
        if not projects_dir.is_dir():
            continue
        for jsonl_file in projects_dir.rglob(f"memory/{filename}"):
            try:
                lines = jsonl_file.read_text().splitlines()[-3:]
            except OSError:
                continue
            for line in lines:
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                ts = obj.get("ts", obj.get("timestamp", ""))
                summary = obj.get("summary") or obj.get("decision") or obj.get("error") or ""
                if ts and summary:
                    entries.append((ts, summary))
    entries.sort(key=lambda x: x[0], reverse=True)
    if not entries:
        console.print("  [dim]none[/dim]")
        return
    for ts, summary in entries[:5]:
        console.print(f"  • {summary} ([dim]{time_ago(ts)}[/dim])")

"""`lh status memory` view — per-project decisions/failures/learnings counts + recents."""

from __future__ import annotations

import json
import re
from datetime import datetime

from rich.console import Group, RenderableType
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


def render(ctx: StatusContext) -> RenderableType:
    table = Table(show_header=True, pad_edge=False)
    table.add_column("Project")
    table.add_column("Decisions", justify="right")
    table.add_column("Failures", justify="right")
    table.add_column("Last Entry")
    table.add_column("Learnings (this month)", justify="right")

    any_rows = False
    # Both locations. Memory keyed by project identity lives in the knowledge
    # store; anything not yet migrated — or deliberately unshared — is still
    # under the agent's project dir, and a view that showed only one of them
    # would look like the other half had been deleted.
    from lazy_harness.core.memory_store import all_memory_dirs
    from lazy_harness.hooks.builtins._shared import knowledge_root_for

    for memory_dir in all_memory_dirs(
        [p.config_dir for p in ctx.profiles], knowledge_root_for(ctx.cfg)
    ):
        # A legacy directory is `<encoded-cwd>/memory`; a migrated one is
        # `<host>/<owner>/<name>` and names itself.
        label = memory_dir.parent.name if memory_dir.name == "memory" else memory_dir.name

        dec_count, dec_ts = _count_jsonl(memory_dir / "decisions.jsonl")
        fail_count, fail_ts = _count_jsonl(memory_dir / "failures.jsonl")
        last_ts = max((t for t in (dec_ts, fail_ts) if t), default="")
        learn_count = _learnings_for_project(ctx.learnings_dir, label)

        table.add_row(
            decode_project_name(label),
            str(dec_count),
            str(fail_count),
            time_ago(last_ts),
            str(learn_count),
        )
        any_rows = True

    if not any_rows:
        return "[dim]No project memory yet.[/dim]"
    return Group(
        table,
        *_recent(ctx, "decisions.jsonl", "Recent decisions"),
        *_recent(ctx, "failures.jsonl", "Recent failures"),
    )


def _recent(ctx: StatusContext, filename: str, title: str) -> list[RenderableType]:
    out: list[RenderableType] = [f"\n[bold]{title}:[/bold]"]
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
        out.append("  [dim]none[/dim]")
        return out
    for ts, summary in entries[:5]:
        out.append(f"  • {summary} ([dim]{time_ago(ts)}[/dim])")
    return out

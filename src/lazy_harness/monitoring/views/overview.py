"""`lh status overview` view — single-panel summary.

Composes data from the other views (profiles, sessions/tokens, hooks, queue)
without re-rendering any tables — it's the at-a-glance view.
"""

from __future__ import annotations

from datetime import datetime

from rich.console import Console
from rich.panel import Panel
from rich.text import Text

from lazy_harness.monitoring.db import MetricsDB
from lazy_harness.monitoring.views._helpers import (
    HOOK_NAMES_DEFAULT,
    StatusContext,
    last_hook_ts,
    launchctl_loaded,
)


def _hook_indicator(state: str, name: str) -> Text:
    if state == "ok":
        return Text(f"✓ {name}", style="green")
    if state == "stale":
        return Text(f"· {name}", style="yellow")
    return Text(f"✗ {name}", style="red")


def render(ctx: StatusContext, db: MetricsDB | None, console: Console) -> None:
    today_str = datetime.now().strftime("%Y-%m-%d")
    month_str = datetime.now().strftime("%Y-%m")

    profile_parts = []
    project_parts = []
    for p in ctx.profiles:
        marker = "*" if p.is_default else ""
        profile_parts.append(f"{p.name}{marker}")
        projects_dir = p.config_dir / "projects"
        count = 0
        if projects_dir.is_dir():
            count = sum(1 for d in projects_dir.iterdir() if d.is_dir())
        project_parts.append(f"{p.name}: {count}")

    profile_val = " · ".join(profile_parts)
    project_val = " · ".join(project_parts)

    sessions_today: set[str] = set()
    sessions_month: set[str] = set()
    sessions_total: set[str] = set()
    total_in = 0
    total_out = 0
    total_cost = 0.0

    if db is not None:
        for r in db.query_stats(period="all"):
            sessions_total.add(r["session"])
            if r["date"] == today_str:
                sessions_today.add(r["session"])
            if r["date"].startswith(month_str):
                sessions_month.add(r["session"])
                total_in += r["input"]
                total_out += r["output"]
                total_cost += r["cost"]

    session_val = (
        f"{len(sessions_today)} today · "
        f"{len(sessions_month)} this month · "
        f"{len(sessions_total)} total"
    )
    token_val = (
        f"{_fmt(total_in)} in · {_fmt(total_out)} out · "
        f"${round(total_cost, 2)} ({datetime.now().strftime('%b')})"
    )

    hooks_text = Text()
    for profile in ctx.profiles:
        if not profile.exists:
            continue
        hooks_log = ctx.logs_dir(profile) / "hooks.log"
        for hook_name in HOOK_NAMES_DEFAULT:
            ts = last_hook_ts(hooks_log, hook_name)
            if ts and ts[:10] == today_str:
                state = "ok"
            elif ts:
                state = "stale"
            else:
                continue
            if hooks_text.plain:
                hooks_text.append("  ")
            hooks_text.append_text(_hook_indicator(state, f"{profile.name}:{hook_name}"))
    if not hooks_text.plain:
        hooks_text = Text("none recent", style="dim")

    cron_text = Text()
    from pathlib import Path

    plist_dir = Path.home() / "Library" / "LaunchAgents"
    if plist_dir.is_dir():
        for plist_file in sorted(plist_dir.glob(f"{ctx.launchd_prefix}.*.plist")):
            label = plist_file.stem
            short = label[len(ctx.launchd_prefix) + 1 :] if "." in label else label
            loaded = launchctl_loaded(label)
            if cron_text.plain:
                cron_text.append("  ")
            cron_text.append_text(
                Text(f"{'✓' if loaded else '✗'} {short}", style="green" if loaded else "red")
            )
    if not cron_text.plain:
        cron_text = Text("no managed jobs", style="dim")

    pending = 0
    done_today = 0
    for profile in ctx.profiles:
        if not profile.exists:
            continue
        queue_dir = ctx.queue_dir(profile)
        if queue_dir.is_dir():
            pending += sum(1 for _ in queue_dir.glob("*.task"))
        done_dir = queue_dir / "done"
        if done_dir.is_dir():
            for f in done_dir.glob("*.task"):
                try:
                    if datetime.fromtimestamp(f.stat().st_mtime).strftime("%Y-%m-%d") == today_str:
                        done_today += 1
                except OSError:
                    pass
    queue_val = f"{pending} pending · {done_today} done today"

    items = [
        ("Profiles", profile_val),
        ("Projects", project_val),
        ("Sessions", session_val),
        ("Tokens", token_val),
        ("Hooks", hooks_text),
        ("Cron", cron_text),
        ("Queue", queue_val),
    ]
    panel = _build_panel(items)
    console.print(panel)


def _fmt(n: int) -> str:
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n / 1_000:.1f}K"
    return str(n)


def _build_panel(items: list[tuple[str, object]]) -> Panel:
    max_label = max(len(label) for label, _ in items) if items else 10
    lines: list[Text] = []
    for label, value in items:
        line = Text()
        line.append(f"{label:<{max_label}}  ", style="bold")
        if isinstance(value, Text):
            line.append_text(value)
        else:
            line.append(str(value))
        lines.append(line)
    content = Text("\n").join(lines)
    return Panel(
        content,
        title="lh status",
        title_align="left",
        border_style="bold",
        padding=(0, 1),
    )

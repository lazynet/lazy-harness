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

    profile_order = [p.name for p in ctx.profiles]
    per_profile: dict[str, dict[str, object]] = {
        name: {
            "today": set(),
            "month": set(),
            "total": set(),
            "in": 0,
            "out": 0,
            "cost": 0.0,
        }
        for name in profile_order
    }

    if db is not None:
        for r in db.query_stats(period="all"):
            bucket = per_profile.get(r["profile"])
            if bucket is None:
                continue
            bucket["total"].add(r["session"])  # type: ignore[union-attr]
            if r["date"] == today_str:
                bucket["today"].add(r["session"])  # type: ignore[union-attr]
            if r["date"].startswith(month_str):
                bucket["month"].add(r["session"])  # type: ignore[union-attr]
                bucket["in"] = int(bucket["in"]) + r["input"]
                bucket["out"] = int(bucket["out"]) + r["output"]
                bucket["cost"] = float(bucket["cost"]) + r["cost"]

    month_label = datetime.now().strftime("%b")

    def _sess_line(label: str, today: int, month: int, total: int) -> str:
        return f"{label:<5} {today} today · {month} this month · {total} total"

    def _tok_line(label: str, tin: int, tout: int, cost: float) -> str:
        return (
            f"{label:<5} {_fmt(tin)} in · {_fmt(tout)} out · "
            f"${round(cost, 2)} ({month_label})"
        )

    session_rows: list[str] = []
    token_rows: list[str] = []
    all_today: set[str] = set()
    all_month: set[str] = set()
    all_total: set[str] = set()
    all_in = 0
    all_out = 0
    all_cost = 0.0
    for name in profile_order:
        b = per_profile[name]
        today_set = b["today"]  # type: ignore[assignment]
        month_set = b["month"]  # type: ignore[assignment]
        total_set = b["total"]  # type: ignore[assignment]
        session_rows.append(
            _sess_line(f"{name}:", len(today_set), len(month_set), len(total_set))  # type: ignore[arg-type]
        )
        token_rows.append(
            _tok_line(f"{name}:", int(b["in"]), int(b["out"]), float(b["cost"]))
        )
        all_today |= today_set  # type: ignore[arg-type]
        all_month |= month_set  # type: ignore[arg-type]
        all_total |= total_set  # type: ignore[arg-type]
        all_in += int(b["in"])
        all_out += int(b["out"])
        all_cost += float(b["cost"])

    if len(profile_order) > 1:
        session_rows.append(
            _sess_line("all:", len(all_today), len(all_month), len(all_total))
        )
        token_rows.append(_tok_line("all:", all_in, all_out, all_cost))
    elif not profile_order:
        session_rows.append(_sess_line("", 0, 0, 0))
        token_rows.append(_tok_line("", 0, 0, 0.0))

    session_val = session_rows
    token_val = token_rows

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
        values = value if isinstance(value, list) else [value]
        for idx, v in enumerate(values):
            line = Text()
            shown_label = label if idx == 0 else ""
            line.append(f"{shown_label:<{max_label}}  ", style="bold")
            if isinstance(v, Text):
                line.append_text(v)
            else:
                line.append(str(v))
            lines.append(line)
    content = Text("\n").join(lines)
    return Panel(
        content,
        title="lh status",
        title_align="left",
        border_style="bold",
        padding=(0, 1),
    )

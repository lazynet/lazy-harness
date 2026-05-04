"""lh doctor — environment health check."""

from __future__ import annotations

import os
import shutil
from datetime import UTC, datetime
from pathlib import Path

import click
from rich.console import Console

from lazy_harness.agents.registry import AgentNotFoundError, get_agent
from lazy_harness.core.config import ConfigError, load_config
from lazy_harness.core.paths import config_file, contract_path, expand_path
from lazy_harness.core.profiles import list_profiles
from lazy_harness.monitoring.engram_persist_health import (
    EngramPersistHealth,
    collect_engram_persist_health,
)


def _fmt_age(seconds: float) -> str:
    if seconds < 60:
        return f"{int(seconds)}s ago"
    if seconds < 3600:
        return f"{int(seconds // 60)}m ago"
    if seconds < 86400:
        return f"{int(seconds // 3600)}h ago"
    return f"{int(seconds // 86400)}d ago"


def _fmt_bytes(n: int) -> str:
    if n < 1024:
        return f"{n} B"
    if n < 1024 * 1024:
        return f"{n / 1024:.1f} KB"
    return f"{n / (1024 * 1024):.1f} MB"


def _engram_persist_metrics_path() -> Path:
    base = Path(os.environ.get("CLAUDE_CONFIG_DIR", Path.home() / ".claude"))
    return base / "logs" / "engram_persist_metrics.jsonl"


def _render_engram_persist(console: Console, health: EngramPersistHealth) -> bool:
    icons = {
        "ok": "[green]✓[/green]",
        "warn": "[yellow]![/yellow]",
        "fail": "[red]✗[/red]",
        "missing": "[grey50]·[/grey50]",
    }
    console.print("\n[bold]Engram persist[/bold]")
    if health.state == "missing":
        console.print(f"  {icons['missing']} No runs yet (Stop hook not triggered)")
        return True

    age = health.last_run_age_seconds or 0.0
    age_state = "fail" if age >= 7 * 86400 else ("warn" if age >= 86400 else "ok")
    console.print(f"  {icons[age_state]} Last run {_fmt_age(age)}")

    rate = health.failure_rate or 0.0
    rate_state = "fail" if rate > 0.10 else ("warn" if rate > 0.0 else "ok")
    console.print(
        f"  {icons[rate_state]} Failure rate {rate * 100:.1f}% (last {health.runs_considered} runs)"
    )

    lag = health.cursor_lag_bytes or 0
    lag_state = "fail" if lag >= 64 * 1024 else ("warn" if lag > 0 else "ok")
    console.print(f"  {icons[lag_state]} Cursor lag {_fmt_bytes(lag)}")

    return health.state != "fail"


@click.command("doctor")
def doctor() -> None:
    """Check environment health."""
    console = Console()
    ok = True

    cf = config_file()
    if cf.is_file():
        console.print(f"[green]✓[/green] Config file: {contract_path(cf)}")
    else:
        console.print(f"[red]✗[/red] Config file not found: {contract_path(cf)}")
        console.print("  Run: lh init")
        raise SystemExit(1)

    try:
        cfg = load_config(cf)
    except ConfigError as e:
        console.print(f"[red]✗[/red] Config error: {e}")
        raise SystemExit(1)

    console.print(f"[green]✓[/green] Config version: {cfg.harness.version}")

    try:
        agent = get_agent(cfg.agent.type)
        console.print(f"[green]✓[/green] Agent: {agent.name}")
    except AgentNotFoundError as e:
        console.print(f"[red]✗[/red] Agent: {e}")
        ok = False

    console.print()
    console.print("[bold]Profiles:[/bold]")
    profiles = list_profiles(cfg)
    for p in profiles:
        label = f"{p.name} (default)" if p.is_default else p.name
        if p.exists:
            console.print(f"  [green]✓[/green] {label} — {contract_path(p.config_dir)}")
        else:
            cdir = contract_path(p.config_dir)
            console.print(f"  [red]✗[/red] {label} — {cdir} [red](missing)[/red]")
            ok = False

    if cfg.knowledge.path:
        kp = expand_path(cfg.knowledge.path)
        if kp.is_dir():
            console.print(f"\n[green]✓[/green] Knowledge dir: {contract_path(kp)}")
        else:
            console.print(f"\n[red]✗[/red] Knowledge dir missing: {contract_path(kp)}")
            ok = False

    from lazy_harness.features import collect_feature_statuses

    console.print("\n[bold]Features[/bold]")
    statuses = collect_feature_statuses(cfg)
    icons = {
        "active": "[green]✓[/green]",
        "dormant": "[yellow]·[/yellow]",
        "missing": "[grey50]·[/grey50]",
        "broken": "[red]✗[/red]",
    }
    for s in statuses:
        icon = icons.get(s.state, "?")
        version_part = ""
        if s.installed_version:
            version_part = f" v{s.installed_version}"
            if s.pinned_version and s.installed_version != s.pinned_version:
                version_part += f" [yellow](pin {s.pinned_version})[/yellow]"
        console.print(f"  {icon} {s.name:<10} ({s.section}){version_part}")
        hint = s.install_hint or s.enable_hint
        if hint:
            console.print(f"      [grey50]{hint}[/grey50]")
        if s.state == "broken":
            ok = False

    if shutil.which("ruff") is None:
        console.print(
            "[yellow]![/yellow] ruff not found on PATH. "
            "PostToolUse auto-format hook will no-op until you "
            "run `uv tool install ruff`."
        )

    console.print("\n[bold]Network egress[/bold]")
    remote_urls: list[tuple[str, str]] = []
    for name in cfg.metrics.sinks:
        if name == "sqlite_local":
            continue
        definition = cfg.metrics.sink_configs.get(name)
        if not definition:
            continue
        url = definition.options.get("url", "")
        if url:
            remote_urls.append((name, url))
    if not remote_urls:
        console.print("  [green]local-only[/green] — no remote sinks configured")
    else:
        for name, url in remote_urls:
            console.print(f"  {name} → {url}")

    health = collect_engram_persist_health(_engram_persist_metrics_path(), now=datetime.now(UTC))
    if not _render_engram_persist(console, health):
        ok = False

    console.print()
    if ok:
        console.print("[green]All checks passed.[/green]")
    else:
        console.print("[red]Some checks failed. Review above.[/red]")
        raise SystemExit(1)

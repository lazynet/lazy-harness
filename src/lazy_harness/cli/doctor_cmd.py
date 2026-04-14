"""lh doctor — environment health check."""

from __future__ import annotations

import shutil

import click
from rich.console import Console

from lazy_harness.agents.registry import AgentNotFoundError, get_agent
from lazy_harness.core.config import ConfigError, load_config
from lazy_harness.core.paths import config_file, contract_path, expand_path
from lazy_harness.core.profiles import list_profiles


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

    if cfg.knowledge.search.engine == "qmd":
        if shutil.which("qmd"):
            console.print("[green]✓[/green] QMD: found in PATH")
        else:
            console.print("[yellow]·[/yellow] QMD: not found in PATH (optional)")

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

    console.print()
    if ok:
        console.print("[green]All checks passed.[/green]")
    else:
        console.print("[red]Some checks failed. Review above.[/red]")
        raise SystemExit(1)

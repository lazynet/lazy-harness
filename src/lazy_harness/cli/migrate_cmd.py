from __future__ import annotations

import os
import time
from pathlib import Path

import click
from rich.console import Console

from lazy_harness.core.paths import config_dir as lh_config_dir
from lazy_harness.core.paths import config_file
from lazy_harness.migrate.detector import detect_state
from lazy_harness.migrate.executor import execute_plan
from lazy_harness.migrate.gate import check_dry_run_gate, record_dry_run
from lazy_harness.migrate.planner import build_plan
from lazy_harness.migrate.rollback import apply_rollback_log
from lazy_harness.migrate.state import StepStatus


def _home() -> Path:
    return Path(os.path.expanduser("~"))


def _backups_parent() -> Path:
    return lh_config_dir() / "backups"


def _latest_backup_dir(parent: Path) -> Path | None:
    if not parent.is_dir():
        return None
    subs = sorted([p for p in parent.iterdir() if p.is_dir()], reverse=True)
    return subs[0] if subs else None


@click.command("migrate")
@click.option("--dry-run", "dry_run", is_flag=True, help="Analyze and print the plan without executing.")  # noqa: E501
@click.option("--rollback", "rollback", is_flag=True, help="Undo the last migration using its rollback log.")  # noqa: E501
def migrate(dry_run: bool, rollback: bool) -> None:
    """Migrate an existing Claude Code / lazy-claudecode setup to lazy-harness."""
    console = Console()
    backups_parent = _backups_parent()

    if rollback:
        latest = _latest_backup_dir(backups_parent)
        if latest is None:
            console.print("[red]No backup directory found to roll back.[/red]")
            raise SystemExit(1)
        console.print(f"Rolling back using {latest}")
        messages = apply_rollback_log(latest)
        for m in messages:
            console.print(f"  {m}")
        console.print("[green]Rollback complete.[/green]")
        return

    state = detect_state(home=_home())

    timestamp = time.strftime("%Y-%m-%dT%H-%M-%S")
    backup_dir = backups_parent / timestamp
    plan = build_plan(
        state,
        backup_dir=backup_dir,
        target_config=config_file(),
        knowledge_path=_home() / "Documents" / "lazy-harness-knowledge",
    )

    if dry_run:
        console.print("[bold]Detection summary:[/bold]")
        console.print(f"  lazy-claudecode: {bool(state.lazy_claudecode)}")
        console.print(f"  claude code vanilla: {bool(state.claude_code)}")
        console.print(f"  lazy-harness config: {bool(state.lazy_harness_config)}")
        console.print(f"  deployed scripts: {len(state.deployed_scripts)}")
        console.print(f"  launch agents: {len(state.launch_agents)}")
        console.print(f"  qmd available: {state.qmd_available}")
        console.print()
        console.print(plan.describe())
        record_dry_run(backups_parent)
        console.print()
        console.print("[yellow]Run `lh migrate` within 1 hour to execute this plan.[/yellow]")
        return

    ok, msg = check_dry_run_gate(backups_parent)
    if not ok:
        console.print(f"[red]{msg}[/red]")
        raise SystemExit(1)

    report = execute_plan(plan, dry_run=False)
    failed = [r for r in report.results if r.status == StepStatus.FAILED]
    for r in report.results:
        mark = "✓" if r.status == StepStatus.DONE else "✗"
        console.print(f"  {mark} {r.name} — {r.message}")
    if failed:
        console.print("[red]Migration failed, rollback applied.[/red]")
        raise SystemExit(1)
    console.print("[green]Migration complete.[/green]")

"""lh knowledge — knowledge directory management."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import click
from rich.console import Console

from lazy_harness.core.config import ConfigError, load_config
from lazy_harness.core.logfile import append as log_append
from lazy_harness.core.logfile import default_log_dir
from lazy_harness.core.paths import config_file, contract_path, expand_path
from lazy_harness.knowledge.compound_loop import create_task, should_queue_task
from lazy_harness.knowledge.context_gen import DEFAULT_CONFIG as CONTEXT_GEN_DEFAULT_CONFIG
from lazy_harness.knowledge.context_gen import regenerate as regenerate_contexts
from lazy_harness.knowledge.directory import list_sessions
from lazy_harness.knowledge.qmd import QmdResult, embed, is_qmd_available, sync
from lazy_harness.knowledge.qmd import status as qmd_status
from lazy_harness.knowledge.session_export import export_session

_SUMMARY_KEYWORDS = ("embedded", "indexed", "updated", "vector", "hash")


def _log_qmd_result(name: str, result: QmdResult) -> None:
    log_path = default_log_dir() / f"qmd-{name}.log"
    if result.exit_code == 0:
        summary_lines = [
            line
            for line in result.stdout.strip().splitlines()
            if any(kw in line.lower() for kw in _SUMMARY_KEYWORDS)
        ][:5]
        if summary_lines:
            log_append(log_path, f"{name} OK:")
            for line in summary_lines:
                log_append(log_path, f"  {line}")
        else:
            log_append(log_path, f"{name} OK")
    else:
        log_append(log_path, f"ERROR: qmd {name} failed (exit {result.exit_code})")
        for line in (result.stderr or result.stdout).strip().splitlines()[-5:]:
            log_append(log_path, f"  {line}")


@click.group()
def knowledge() -> None:
    """Manage knowledge directory and QMD."""


@knowledge.command("status")
def knowledge_status() -> None:
    """Show knowledge directory and QMD status."""
    console = Console()
    cf = config_file()
    try:
        cfg = load_config(cf)
    except ConfigError as e:
        console.print(f"[red]Error: {e}[/red]")
        raise SystemExit(1)
    if not cfg.knowledge.path:
        console.print("[red]Knowledge path not configured.[/red]")
        console.print("Set [knowledge].path in config.toml")
        return
    kdir = expand_path(cfg.knowledge.path)
    console.print(f"[bold]Knowledge directory:[/bold] {contract_path(kdir)}")
    if kdir.is_dir():
        console.print("[green]✓[/green] Directory exists")
        sessions = list_sessions(kdir, cfg.knowledge.sessions.subdir)
        console.print(f"  Sessions: {len(sessions)} exported")
    else:
        console.print("[red]✗[/red] Directory missing")
    console.print()
    if is_qmd_available():
        console.print("[green]✓[/green] QMD available")
        result = qmd_status()
        if result.exit_code == 0 and result.stdout:
            for line in result.stdout.strip().splitlines()[:5]:
                console.print(f"  {line}")
    else:
        console.print("[yellow]·[/yellow] QMD not available")


@knowledge.command("sync")
@click.option("--collection", default=None, help="Sync specific collection")
def knowledge_sync(collection: str | None) -> None:
    """Sync QMD index (BM25)."""
    console = Console()
    if not is_qmd_available():
        console.print("[red]QMD not found in PATH[/red]")
        raise SystemExit(1)
    console.print("Syncing QMD index...")
    result = sync(collection=collection)
    _log_qmd_result("sync", result)
    if result.exit_code == 0:
        console.print("[green]✓[/green] Sync complete")
        if result.stdout.strip():
            for line in result.stdout.strip().splitlines()[:10]:
                console.print(f"  {line}")
    else:
        console.print(f"[red]✗[/red] Sync failed (exit {result.exit_code})")
        raise SystemExit(1)


@knowledge.command("context-gen")
@click.option("--dry-run", is_flag=True, help="Show changes without writing")
@click.option(
    "--config",
    "config_path",
    type=click.Path(path_type=Path),
    default=None,
    help="Override path to QMD index.yml",
)
def knowledge_context_gen(dry_run: bool, config_path: Path | None) -> None:
    """Regenerate the auto-updated stats inside QMD collection contexts."""
    console = Console()
    path = config_path or CONTEXT_GEN_DEFAULT_CONFIG
    if not path.is_file():
        console.print(f"[yellow]·[/yellow] No QMD config at {path} — skipping")
        return
    result = regenerate_contexts(path, dry_run=dry_run)
    header = "[cyan]DRY RUN[/cyan] " if dry_run else ""
    if result.updated:
        console.print(f"{header}Updated {len(result.updated)} collections:")
        for item in result.updated:
            console.print(f"  [green]•[/green] {item}")
    else:
        console.print(f"{header}No collections updated.")
    if result.skipped:
        console.print(f"[yellow]Skipped {len(result.skipped)}:[/yellow]")
        for item in result.skipped:
            console.print(f"  [yellow]·[/yellow] {item}")
    if not dry_run and result.updated:
        log_append(default_log_dir() / "qmd-context-gen.log", f"updated {len(result.updated)}")


@knowledge.command("export-session")
@click.argument(
    "session_file",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
)
@click.option(
    "--force",
    is_flag=True,
    help="Bypass interactive-session filter and unchanged-file guard.",
)
def knowledge_export_session(session_file: Path, force: bool) -> None:
    """Export a session JSONL to the knowledge sessions directory.

    Escape hatch for sessions the Stop hook skipped (e.g. non-interactive
    heuristic mis-classified a real session). Use --force to override.
    """
    console = Console()
    cf = config_file()
    try:
        cfg = load_config(cf)
    except ConfigError as e:
        console.print(f"[red]Error: {e}[/red]")
        raise SystemExit(1)
    if not cfg.knowledge.path:
        console.print("[red]Knowledge path not configured.[/red]")
        raise SystemExit(1)
    knowledge_dir = expand_path(cfg.knowledge.path)
    sessions_root = knowledge_dir / cfg.knowledge.sessions.subdir
    sessions_root.mkdir(parents=True, exist_ok=True)

    result, skip_reason = export_session(session_file, sessions_root, force=force)
    if result is not None:
        console.print(f"[green]✓[/green] Exported to {result}")
        return
    console.print(f"[yellow]·[/yellow] Skipped {session_file.name} ({skip_reason})")
    if not force:
        console.print("  Re-run with [cyan]--force[/cyan] to bypass the filter.")


@knowledge.command("handoff-now")
def knowledge_handoff_now() -> None:
    """Force a compound-loop evaluation for the current session now.

    Same semantics as the SessionEnd hook: ignores the debounce and growth
    gates that normally keep the Stop hook cheap. Use before closing a
    session if you want the handoff to reflect the very latest state —
    for example when you finished resolving pending items in the final
    minutes of a session, after the last gated Stop hook fired.
    """
    console = Console()
    cf = config_file()
    try:
        cfg = load_config(cf)
    except ConfigError as e:
        console.print(f"[red]Error: {e}[/red]")
        raise SystemExit(1)

    if not cfg.compound_loop.enabled:
        console.print("[red]compound_loop is disabled in config.toml[/red]")
        raise SystemExit(1)

    claude_dir = Path(os.environ.get("CLAUDE_CONFIG_DIR", Path.home() / ".claude"))
    cwd = Path.cwd()
    encoded = "-" + str(cwd).replace("/", "-").lstrip("-")
    sessions_dir = claude_dir / "projects" / encoded
    queue_dir = claude_dir / "queue"
    log_dir = claude_dir / "logs"

    jsonl_files = [p for p in sessions_dir.glob("*.jsonl") if p.is_file()] \
        if sessions_dir.is_dir() else []
    if not jsonl_files:
        console.print(f"[red]No session JSONL under {contract_path(sessions_dir)}[/red]")
        raise SystemExit(1)
    session_jsonl = max(jsonl_files, key=lambda f: f.stat().st_mtime)
    session_id = session_jsonl.stem

    if not should_queue_task(
        queue_dir=queue_dir,
        session_jsonl=session_jsonl,
        session_id=session_id,
        debounce_seconds=cfg.compound_loop.debounce_seconds,
        min_growth_seconds=cfg.compound_loop.reprocess_min_growth_seconds,
        force=True,
    ):
        console.print("[yellow]·[/yellow] Nothing to do (unexpected under force).")
        return

    memory_dir = sessions_dir / "memory"
    task_file = create_task(
        queue_dir=queue_dir,
        cwd=cwd,
        session_jsonl=session_jsonl,
        session_id=session_id,
        memory_dir=memory_dir,
    )
    console.print(f"[green]✓[/green] queued {task_file.name}")

    worker_log = log_dir / "compound-loop.log"
    try:
        worker_log.parent.mkdir(parents=True, exist_ok=True)
        with open(worker_log, "a") as stdout_f:
            subprocess.Popen(
                [sys.executable, "-m", "lazy_harness.knowledge.compound_loop_worker"],
                stdin=subprocess.DEVNULL,
                stdout=stdout_f,
                stderr=stdout_f,
                start_new_session=True,
                close_fds=True,
            )
    except OSError as e:
        console.print(f"[yellow]·[/yellow] worker spawn failed: {e}")


@knowledge.command("embed")
@click.option("--collection", default=None, help="Embed specific collection")
def knowledge_embed(collection: str | None) -> None:
    """Run QMD vector embedding."""
    console = Console()
    if not is_qmd_available():
        console.print("[red]QMD not found in PATH[/red]")
        raise SystemExit(1)
    console.print("Running QMD embedding...")
    result = embed(collection=collection)
    _log_qmd_result("embed", result)
    if result.exit_code == 0:
        console.print("[green]✓[/green] Embedding complete")
    else:
        console.print(f"[red]✗[/red] Embedding failed (exit {result.exit_code})")
        raise SystemExit(1)

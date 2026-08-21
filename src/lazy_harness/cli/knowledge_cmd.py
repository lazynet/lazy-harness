"""lh knowledge — knowledge directory management."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import click
from rich.console import Console
from rich.markup import escape

from lazy_harness.core.config import Config, ConfigError, load_config
from lazy_harness.core.logfile import append as log_append
from lazy_harness.core.logfile import default_log_dir
from lazy_harness.core.paths import config_file, contract_path, expand_path
from lazy_harness.knowledge.compound_loop import create_task, should_queue_task
from lazy_harness.knowledge.context_gen import DEFAULT_CONFIG as CONTEXT_GEN_DEFAULT_CONFIG
from lazy_harness.knowledge.context_gen import regenerate as regenerate_contexts
from lazy_harness.knowledge.directory import list_sessions, sessions_dir
from lazy_harness.knowledge.marker import MarkerError, resolve_root
from lazy_harness.knowledge.qmd import (
    DEFAULT_EMBED_TIMEOUT,
    QmdResult,
    embed,
    is_qmd_available,
    pending_embeddings,
    sync,
)
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
        console.print(f"[red]Error: {escape(str(e))}[/red]")
        raise SystemExit(1)
    kdir = resolve_root(cfg.knowledge.root or None)
    console.print(f"[bold]Knowledge directory:[/bold] {contract_path(kdir)}")
    if kdir.is_dir():
        console.print("[green]✓[/green] Directory exists")
        try:
            sessions = list_sessions(kdir)
        except MarkerError as e:
            console.print(f"[red]✗[/red] {escape(str(e))}")
        else:
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
        console.print(f"[red]Error: {escape(str(e))}[/red]")
        raise SystemExit(1)
    knowledge_dir = resolve_root(cfg.knowledge.root or None)
    try:
        sessions_root = sessions_dir(knowledge_dir)
    except MarkerError as e:
        console.print(f"[red]{escape(str(e))}[/red]")
        raise SystemExit(1) from e
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
        console.print(f"[red]Error: {escape(str(e))}[/red]")
        raise SystemExit(1)

    if not cfg.compound_loop.enabled:
        console.print("[red]compound_loop is disabled in config.toml[/red]")
        raise SystemExit(1)

    from lazy_harness.agents.registry import get_agent
    from lazy_harness.core.paths import agent_runtime_dir

    agent = get_agent(cfg.agent.type)
    env_val = os.environ.get(agent.env_var()) if agent.env_var() else None
    if env_val:
        agent_dir = Path(env_val)
    else:
        # Prefer the default profile's config dir; otherwise let the adapter
        # resolve its runtime dir (ADR-032 L3 — no hardcoded ~/.claude).
        default_entry = cfg.profiles.items.get(cfg.profiles.default)
        agent_dir = (
            expand_path(default_entry.config_dir) if default_entry else agent_runtime_dir(agent)
        )
    subdirs = agent.session_dirs()
    cwd = Path.cwd()
    encoded = "-" + str(cwd).replace("/", "-").lstrip("-")
    sessions_dir = agent_dir / (subdirs.get("sessions") or "projects") / encoded
    queue_dir = agent_dir / (subdirs.get("queue") or "queue")
    log_dir = agent_dir / (subdirs.get("logs") or "logs")

    jsonl_files = (
        [p for p in sessions_dir.glob("*.jsonl") if p.is_file()] if sessions_dir.is_dir() else []
    )
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
        console.print(f"[yellow]·[/yellow] worker spawn failed: {escape(str(e))}")


@knowledge.command("embed")
@click.option("--collection", default=None, help="Embed specific collection")
@click.option(
    "--timeout",
    type=int,
    default=None,
    help=f"Seconds to allow qmd (default: [knowledge.embed].timeout, {DEFAULT_EMBED_TIMEOUT})",
)
def knowledge_embed(collection: str | None, timeout: int | None) -> None:
    """Run QMD vector embedding.

    A timeout that still drained backlog exits 0. qmd commits per batch, so a
    run cut short has really embedded most of what it reached — and on a
    CPU-only host a burst of ingestion legitimately needs more than one window
    to clear. Reporting that as a failure is how a scheduled job alerts every
    day for a week while the index is in fact catching up.
    """
    console = Console()
    if not is_qmd_available():
        console.print("[red]QMD not found in PATH[/red]")
        raise SystemExit(1)
    limit = timeout if timeout is not None else _configured_embed_timeout()
    before = pending_embeddings()
    console.print("Running QMD embedding...")
    result = embed(collection=collection, timeout=limit)
    _log_qmd_result("embed", result)
    if result.exit_code == 0:
        console.print("[green]✓[/green] Embedding complete")
        return

    # Only a timeout is forgiven, and only against measured progress: a qmd
    # that crashed is a failure however much the previous run had embedded,
    # and an unreadable count is not evidence of anything.
    after = pending_embeddings()
    if result.timed_out and before is not None and after is not None and after < before:
        console.print(
            f"[yellow]·[/yellow] Embedding hit the {limit}s limit with "
            f"{before - after} document(s) embedded and {after} still pending. "
            "Raise [knowledge.embed].timeout or run the job more often."
        )
        return

    console.print(f"[red]✗[/red] Embedding failed (exit {result.exit_code})")
    raise SystemExit(1)


def _configured_embed_timeout() -> int:
    """[knowledge.embed].timeout, falling back to the default on any doubt.

    An unreadable or stale config must not stop the job from embedding — the
    default is a working value everywhere, just a tight one on slow hosts.
    """
    cf = config_file()
    if not cf.is_file():
        return DEFAULT_EMBED_TIMEOUT
    try:
        return load_config(cf).knowledge.embed.timeout
    except ConfigError:
        return DEFAULT_EMBED_TIMEOUT


def _configured_root() -> str | None:
    """Read [knowledge].root from config, tolerating an absent or stale config file."""
    cf = config_file()
    if not cf.is_file():
        return None
    try:
        return load_config(cf).knowledge.root or None
    except ConfigError:
        return None


@knowledge.command("init")
@click.option("--root", default=None, help="Store root (defaults to configured/env/default)")
def knowledge_init(root: str | None) -> None:
    """Create the knowledge store, its marker, and its subdirectories."""
    from lazy_harness.knowledge.directory import ensure_knowledge_dir

    console = Console()
    target = resolve_root(root) if root else resolve_root(_configured_root())
    try:
        created = ensure_knowledge_dir(target)
    except MarkerError as e:
        console.print(f"[red]{escape(str(e))}[/red]")
        raise SystemExit(1) from e
    console.print(f"[green]Knowledge store ready:[/green] {contract_path(created)}")


@knowledge.command("path")
@click.option(
    "--kind",
    type=click.Choice(["root", "sessions", "learnings"]),
    default="root",
    help="Which path to print",
)
def knowledge_path(kind: str) -> None:
    """Print an absolute path inside the knowledge store."""
    from lazy_harness.knowledge.directory import learnings_dir

    console = Console()
    root = resolve_root(_configured_root())
    try:
        if kind == "root":
            target = root
        elif kind == "sessions":
            target = sessions_dir(root)
        else:
            target = learnings_dir(root)
    except MarkerError as e:
        console.print(f"[red]{escape(str(e))}[/red]")
        raise SystemExit(1) from e
    click.echo(str(target))


@knowledge.command("push")
def knowledge_push() -> None:
    """Commit, rebase, and push the knowledge store."""
    from lazy_harness.knowledge.compound_loop import origin_host
    from lazy_harness.knowledge.git_push import push_once

    console = Console()
    root = resolve_root(_configured_root())
    result = push_once(root, host=origin_host())
    line = f"{result.status}: {result.detail}" if result.detail else result.status
    log_append(default_log_dir() / "knowledge-push.log", line)
    console.print(line)
    if result.status in {"invalid", "conflict"}:
        raise SystemExit(1)


@knowledge.group("graph")
def knowledge_graph() -> None:
    """Manage the repos whose code graph is kept fresh."""


def _structure_repos(cfg_path: Path) -> tuple[Config, list[str]]:
    cfg = load_config(cfg_path)
    return cfg, list(cfg.knowledge.structure.repos)


def _write_repo_list(cfg_path: Path, cfg: Config, repos: list[str]) -> None:
    """Persist the graphify repo list under [knowledge.structure].

    Was a hand-rolled single-line rewrite because `save_config` dropped every
    comment and any key this version does not model. It no longer does.

    Takes the already-loaded `cfg`: every caller holds one, and reloading here
    put a second `ConfigError` outside their `try/except`.
    """
    from lazy_harness.core.config import save_config

    cfg.knowledge.structure.repos = list(repos)
    save_config(cfg, cfg_path)


@knowledge_graph.command("add")
@click.argument("repo", type=click.Path(exists=True, file_okay=False, path_type=Path))
def knowledge_graph_add(repo: Path) -> None:
    """Register REPO so its code graph is refreshed on schedule."""
    console = Console()
    resolved = repo.resolve()
    if not (resolved / ".git").exists():
        console.print(f"[red]Error:[/red] {contract_path(resolved)} is not a git repo.")
        raise SystemExit(1)

    cfg_path = config_file()
    try:
        cfg, repos = _structure_repos(cfg_path)
    except ConfigError as e:
        console.print(f"[red]Error:[/red] {escape(str(e))}")
        raise SystemExit(1)

    if str(resolved) in repos:
        console.print(f"[dim]already registered:[/dim] {contract_path(resolved)}")
        return

    repos.append(str(resolved))
    _write_repo_list(cfg_path, cfg, repos)
    console.print(f"[green]registered:[/green] {contract_path(resolved)}")


@knowledge_graph.command("list")
def knowledge_graph_list() -> None:
    """List the repos whose code graph is refreshed on schedule."""
    console = Console()
    try:
        _, repos = _structure_repos(config_file())
    except ConfigError as e:
        console.print(f"[red]Error:[/red] {escape(str(e))}")
        raise SystemExit(1)

    if not repos:
        console.print("No repos registered. Add one with `lh knowledge graph add <path>`.")
        return
    for entry in repos:
        path = expand_path(entry)
        graph = path / "graphify-out" / "graph.json"
        state = "graph" if graph.is_file() else "[yellow]no graph yet[/yellow]"
        console.print(f"  {contract_path(path)}  {state}")


@knowledge_graph.command("update")
def knowledge_graph_update() -> None:
    """Rebuild the code graph for every registered repo.

    A worktree commit never rebuilds the graph (graphify's own post-commit hook
    exits early outside the main checkout), so nothing refreshes it in a
    worktree-first workflow. This is what the scheduler calls instead.
    """
    from lazy_harness.knowledge import graphify

    console = Console()
    try:
        _, repos = _structure_repos(config_file())
    except ConfigError as e:
        console.print(f"[red]Error:[/red] {escape(str(e))}")
        raise SystemExit(1)

    if not repos:
        console.print("No repos registered. Add one with `lh knowledge graph add <path>`.")
        return
    if not graphify.is_graphify_available():
        console.print("[red]Error:[/red] graphify is not on PATH.")
        raise SystemExit(1)

    log_path = default_log_dir() / "graphify-update.log"
    failures = 0
    for entry in repos:
        path = expand_path(entry)
        if not path.is_dir():
            console.print(f"[yellow]skipped[/yellow]  {contract_path(path)} (missing)")
            log_append(log_path, f"skipped: {path} (missing)")
            continue
        result = graphify.run_graphify("update", str(path))
        if result.exit_code == 0:
            console.print(f"[green]updated[/green]  {contract_path(path)}")
            log_append(log_path, f"updated: {path}")
        else:
            failures += 1
            detail = (result.stderr or result.stdout).strip().splitlines()
            last = detail[-1] if detail else ""
            console.print(f"[red]failed [/red]  {contract_path(path)}: {last}")
            log_append(log_path, f"failed: {path}: {last}")

    if failures:
        raise SystemExit(1)

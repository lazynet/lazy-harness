"""lh doctor — environment health check."""

from __future__ import annotations

import shutil
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit

import click
import httpx
from rich.console import Console
from rich.markup import escape

from lazy_harness.agents.base import AgentAdapter
from lazy_harness.agents.registry import AgentNotFoundError, get_agent
from lazy_harness.core.config import CompoundLoopConfig, Config, ConfigError, load_config
from lazy_harness.core.paths import agent_runtime_dir, config_file, contract_path, expand_path
from lazy_harness.core.profiles import list_profiles
from lazy_harness.llm import LLMBackendError, LLMBackendNotFoundError, get_backend
from lazy_harness.llm.openai_compat import OpenAICompatibleBackend
from lazy_harness.monitoring.engram_persist_health import (
    EngramPersistHealth,
    collect_engram_persist_health,
)
from lazy_harness.monitoring.sink_freshness import SinkFreshness, collect_sinks_freshness
from lazy_harness.monitoring.sink_setup import plan_sinks


def _endpoint_origin(url: str) -> str:
    """Scheme and host only.

    An endpoint resolved from an environment variable may carry a token in its
    path, and `lh doctor` output ends up in scrollback and in pasted issues.
    The host is what answers "where does my data go"; the path is not.
    """
    parts = urlsplit(url)
    if not parts.scheme or not parts.netloc:
        return "(set, not shown)"
    return f"{parts.scheme}://{parts.netloc}/…"


def _render_egress(console: Console, cfg: Config) -> bool:
    """Report remote sinks, including ones configured but not activated.

    A sink switched off by an unset variable is silent everywhere else; the
    whole point of naming the variable in config is that its absence is a
    normal state, so doctor has to say which variable it looked for.
    """
    try:
        plans = [p for p in plan_sinks(cfg.metrics) if p.name != "sqlite_local"]
    except ValueError as exc:
        console.print(f"  [red]✗[/red] misconfigured: {escape(str(exc))}")
        return False

    if not plans:
        console.print("  [green]local-only[/green] — no remote sinks configured")
        return True

    for plan in plans:
        if not plan.active:
            console.print(
                f"  {plan.name} → [yellow]configured but inactive[/yellow] — "
                f"${plan.url_env} is unset or empty"
            )
        elif plan.url_env:
            console.print(f"  {plan.name} → {_endpoint_origin(plan.url)} (from ${plan.url_env})")
        else:
            console.print(f"  {plan.name} → {plan.url}")
    return True


def _render_sink_freshness(console: Console, results: list[SinkFreshness]) -> bool:
    """Report whether each active remote sink has enqueued anything recently.

    Silent when there is nothing to check — no active remote sink, or
    monitoring disabled entirely — same as `_render_memory_hygiene` skipping
    when there is no project memory: an absent subsystem is not a degraded one.
    """
    if not results:
        return True

    icons = {
        "ok": "[green]✓[/green]",
        "warn": "[yellow]![/yellow]",
        "fail": "[red]✗[/red]",
        "missing": "[grey50]·[/grey50]",
    }
    console.print("\n[bold]Sink freshness[/bold]")
    ok = True
    for r in results:
        if r.state == "missing":
            console.print(f"  {icons['missing']} {r.name} — no events enqueued yet")
            continue
        age = r.last_enqueued_age_seconds or 0.0
        console.print(f"  {icons[r.state]} {r.name} — last enqueued {_fmt_age(age)}")
        if r.state == "fail":
            ok = False
    return ok


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


def _engram_persist_metrics_path(agent: AgentAdapter) -> Path:
    base = agent_runtime_dir(agent)
    logs_subdir = agent.session_dirs().get("logs") or "logs"
    return base / logs_subdir / "engram_persist_metrics.jsonl"


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

    if health.skips_considered:
        console.print(
            f"  {icons['warn']} {health.skips_considered} skipped "
            "(engram binary not found — set [memory.engram] binary in config.toml)"
        )

    lag = health.cursor_lag_bytes or 0
    lag_state = "fail" if lag >= 64 * 1024 else ("warn" if lag > 0 else "ok")
    console.print(f"  {icons[lag_state]} Cursor lag {_fmt_bytes(lag)}")

    return health.state != "fail"


def _render_llm_backend(console: Console, cl_cfg: CompoundLoopConfig) -> bool:
    """ADR-033: report whether the configured inference backend is usable.

    Reachability problems are warnings (compound-loop is best-effort); only a
    backend name the registry cannot resolve is a hard failure.
    """
    console.print("\n[bold]LLM backend[/bold]")
    try:
        backend = get_backend(cl_cfg)
    except (LLMBackendError, LLMBackendNotFoundError) as e:
        console.print(f"  [red]✗[/red] {escape(str(e))}")
        return False

    if isinstance(backend, OpenAICompatibleBackend):
        url = backend._base_url
        try:
            httpx.get(url, timeout=2)
            console.print(f"  [green]✓[/green] {cl_cfg.backend} reachable at {url}")
        except httpx.HTTPError:
            console.print(
                f"  [yellow]![/yellow] {cl_cfg.backend} not reachable at {url} — "
                "compound-loop inference will fail until the endpoint is up"
            )
        return True

    if shutil.which("claude"):
        console.print("  [green]✓[/green] claude binary on PATH")
    else:
        console.print(
            "  [yellow]![/yellow] claude binary not found on PATH — "
            "install Claude Code or set [compound_loop].backend"
        )
    return True


def _render_memory_hygiene(console: Console, memory_dir: Path, now: datetime | None = None) -> bool:
    """Phase 3d: surface project-memory drift before it silently degrades.

    Skips silently when the cwd has no project memory. Only an over-cap
    MEMORY.md fails the check; everything else is informational/warning.
    """
    if not memory_dir.is_dir():
        return True
    from lazy_harness.cli.memory_cmd import parse_proposals

    now = now or datetime.now(UTC)
    ok = True
    console.print("\n[bold]Memory hygiene[/bold]")

    memory_md = memory_dir / "MEMORY.md"
    if memory_md.is_file():
        from lazy_harness.hooks.builtins.pre_tool_use_memory_size import MAX_BYTES, MAX_LINES

        text = memory_md.read_text()
        line_count = len(text.splitlines())
        byte_count = len(text.encode("utf-8"))
        sizes = (
            f"MEMORY.md {line_count}/{MAX_LINES} lines · "
            f"{byte_count / 1000:.1f}/{MAX_BYTES / 1000:.0f}KB"
        )
        if line_count > MAX_LINES or byte_count > MAX_BYTES:
            console.print(f"  [red]✗[/red] {sizes} — over the hard cap")
            ok = False
        elif line_count >= MAX_LINES * 0.9 or byte_count >= MAX_BYTES * 0.9:
            console.print(f"  [yellow]![/yellow] {sizes} — consolidate soon")
        else:
            console.print(f"  [green]✓[/green] {sizes}")
    else:
        console.print("  [grey50]·[/grey50] No MEMORY.md")

    proposal_file = memory_dir / "claude-md.proposal.md"
    pending = parse_proposals(proposal_file.read_text()) if proposal_file.is_file() else []
    if pending:
        oldest = min(p.timestamp[:10] for p in pending if p.timestamp)
        try:
            age_days = (now.date() - datetime.strptime(oldest, "%Y-%m-%d").date()).days
        except ValueError:
            age_days = 0
        state = "[yellow]![/yellow]" if age_days > 14 else "[green]✓[/green]"
        console.print(
            f"  {state} {len(pending)} pending proposal(s), oldest {age_days}d — "
            "review: lh memory proposals list"
        )
    else:
        console.print("  [green]✓[/green] 0 pending proposals")

    counts = []
    for label, name in (
        ("accepted", "claude-md.accepted.md"),
        ("rejected", "claude-md.rejected.md"),
    ):
        f = memory_dir / name
        n = len(parse_proposals(f.read_text())) if f.is_file() else 0
        counts.append(f"{n} {label}")
    console.print(f"  [grey50]·[/grey50] {' · '.join(counts)}")

    return ok


def _project_memory_dir(agent: AgentAdapter, cfg: Config | None) -> Path:
    """Memory dir for the current project, canonicalised across worktrees."""

    from lazy_harness.hooks.builtins._shared import knowledge_root_for
    from lazy_harness.hooks.builtins._shared import memory_dir as shared_memory_dir

    return shared_memory_dir(
        None,
        agent_dir=agent_runtime_dir(agent),
        sessions_subdir=agent.session_dirs().get("sessions") or "projects",
        cwd=Path.cwd(),
        knowledge_root=knowledge_root_for(cfg),
    )


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
        console.print(f"[red]✗[/red] Config error: {escape(str(e))}")
        raise SystemExit(1)

    console.print(f"[green]✓[/green] Config version: {cfg.harness.version}")

    try:
        agent = get_agent(cfg.agent.type)
        console.print(f"[green]✓[/green] Agent: {agent.name}")
    except AgentNotFoundError as e:
        console.print(f"[red]✗[/red] Agent: {escape(str(e))}")
        agent = get_agent("null")
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

    if cfg.knowledge.root:
        kp = expand_path(cfg.knowledge.root)
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
            # Escaped: the hint's whole job is to name a config section, and
            # rich parses `[memory.engram]` inside an interpolated string as a
            # markup tag and deletes it.
            console.print(f"      [grey50]{escape(hint)}[/grey50]")
        if s.state == "broken":
            ok = False

    if shutil.which("ruff") is None:
        console.print(
            "[yellow]![/yellow] ruff not found on PATH. "
            "PostToolUse auto-format hook will no-op until you "
            "run `uv tool install ruff`."
        )

    console.print("\n[bold]Network egress[/bold]")
    if not _render_egress(console, cfg):
        ok = False

    sinks_freshness = collect_sinks_freshness(cfg, now=datetime.now(UTC))
    if not _render_sink_freshness(console, sinks_freshness):
        ok = False

    if not _render_llm_backend(console, cfg.compound_loop):
        ok = False

    health = collect_engram_persist_health(
        _engram_persist_metrics_path(agent),
        now=datetime.now(UTC),
    )
    if not _render_engram_persist(console, health):
        ok = False

    if not _render_memory_hygiene(console, _project_memory_dir(agent, cfg)):
        ok = False

    console.print()
    if ok:
        console.print("[green]All checks passed.[/green]")
    else:
        console.print("[red]Some checks failed. Review above.[/red]")
        raise SystemExit(1)

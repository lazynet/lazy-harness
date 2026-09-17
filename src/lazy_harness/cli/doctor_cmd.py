"""lh doctor — environment health check."""

from __future__ import annotations

import os
import shutil
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit

import click
import httpx
from rich.console import Console
from rich.markup import escape

from lazy_harness import __version__
from lazy_harness.agents.base import AgentAdapter
from lazy_harness.agents.codex_trust import CodexHookTrust, collect_codex_trust
from lazy_harness.agents.registry import AgentNotFoundError, get_agent
from lazy_harness.agents.session_paths import (
    TranscriptHealth,
    session_path,
    session_subdir,
    transcript_health,
)
from lazy_harness.core.artifact_version import ArtifactVersionReport, is_newer
from lazy_harness.core.config import Config, ConfigError, load_config
from lazy_harness.core.paths import (
    agent_runtime_dir,
    config_dir,
    config_file,
    contract_path,
    expand_path,
)
from lazy_harness.core.profiles import list_profiles
from lazy_harness.core.secrets import secrets_dir_for
from lazy_harness.hooks.event_surface import (
    HookOperationGap,
    UncarriedEventHook,
    collect_hook_operation_gaps,
    collect_uncarried_events,
)
from lazy_harness.hooks.runner import resolve_profile
from lazy_harness.hooks.signal_gaps import HookSignalGap, collect_hook_signal_gaps
from lazy_harness.llm import LLMBackendError, LLMBackendNotFoundError
from lazy_harness.llm.openai_compat import OpenAICompatibleBackend
from lazy_harness.llm.registry import build_backend
from lazy_harness.monitoring.engram_persist_health import (
    EngramPersistHealth,
    collect_engram_persist_health,
)
from lazy_harness.monitoring.sink_freshness import SinkFreshness, collect_sinks_freshness
from lazy_harness.monitoring.sink_setup import plan_sinks


def _now() -> datetime:
    """The clock `Sink freshness` is measured against.

    A seam, not a convenience. The rendered age is a plain elapsed difference
    and `_fmt_age` truncates it, so a test asserting on the seconds bucket is
    otherwise asserting that setup plus everything this command does before it
    reaches the age all fits inside one second — a stopwatch, not a freshness
    check. Tests freeze this and pin `created_ts` to the same instant.
    """
    return datetime.now(UTC)


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
    """Report whether each active remote sink is still being fed, and whether
    what it was fed is actually leaving the machine.

    Silent when there is nothing to check — no active remote sink, or
    monitoring disabled entirely — same as `_render_memory_hygiene` skipping
    when there is no project memory: an absent subsystem is not a degraded one.
    The delivery line follows the same rule at row level. It keys off the
    verdict, not the backlog size: between an enqueue and the drain that
    follows it there is always an untried row, so printing on `undelivered`
    would put a line in every healthy run.
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
        if r.delivery_state != "ok":
            detail = f" ({escape(r.last_error)})" if r.last_error else ""
            # Age before attempts: when a queue stalls while every POST
            # succeeds, "0 failed attempts" is the whole line and it names no
            # problem. The age of the head of the queue is what says "stuck".
            oldest = (
                f"oldest {_fmt_age(r.oldest_undelivered_age_seconds)}, "
                if r.oldest_undelivered_age_seconds is not None
                else ""
            )
            console.print(
                f"  {icons[r.delivery_state]} {r.name} — {r.undelivered} undelivered, "
                f"{oldest}{r.max_attempts} failed attempts{detail}"
            )
        if r.state == "fail" or r.delivery_state == "fail":
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


def _engram_persist_metrics_path(agent: AgentAdapter, cfg: Config | None, profile: str) -> Path:
    """Where `engram-persist` wrote its metrics, for the profile being diagnosed.

    The hook names this file with `agent_dir_for(cfg, event.profile)`. Reading
    it globally reported "No runs yet (Stop hook not triggered)" — the state a
    hook that never fires produces — while the hook was recording every run
    under the profile. `test_doctor_reads_the_engram_metrics_the_hook_writes`
    asserts the two answers against each other.

    An empty profile is "nobody said" and keeps the global answer. That is
    `agent_runtime_dir`'s own contract for an absent `profile_config_dir`,
    not a second rule invented here.
    """
    if profile:
        from lazy_harness.hooks.builtins._shared import agent_dir_for

        agent, base = agent_dir_for(cfg, profile)
    else:
        base = agent_runtime_dir(agent)
    # The fallback stays, and stays visible, because the *writer* has it:
    # `hooks/builtins/session_export.py` names the same `or "logs"`. Deleting
    # it on the reading side alone is how doctor starts looking where the hook
    # does not write. `session_path` is here so the resolution has one
    # spelling; ADR-051 records why the sessions half loses its fallback and
    # this one does not.
    return (session_path(agent, base, "logs") or base / "logs") / "engram_persist_metrics.jsonl"


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


_TRANSCRIPT_LINES = {
    # "has a reader for", never "reads": the verdict is about the adapter
    # implementing `TranscriptReader`, and a consumer can still decline the
    # events it yields. `lh metrics ingest` does exactly that for Codex today
    # (ADR-051), so a line promising the transcripts are being read would be
    # this section contradicting the pipeline it exists to diagnose.
    TranscriptHealth.OK: ("ok", "[green]\u2713[/green]", "{agent} has a reader for {path}"),
    TranscriptHealth.DEGRADED: (
        "unread",
        "[yellow]![/yellow]",
        "{agent} leaves transcripts unread in {path} \u2014 no reader for this agent",
    ),
    TranscriptHealth.NO_DATA: (
        "quiet",
        "[grey50]\u00b7[/grey50]",
        "{agent}: no transcripts in {path}",
    ),
    TranscriptHealth.NO_LOCATION: (
        "none",
        "[grey50]\u00b7[/grey50]",
        "{agent} declares no sessions directory",
    ),
}


def _render_transcripts(console: Console, cfg: Config) -> None:
    """One line per profile: is anything writing transcripts nobody reads?

    Derived from the adapter and the disk, never declared. "Should this agent
    have a reader?" has no configured answer and needs none —
    `TranscriptReader` is `runtime_checkable`, so `isinstance` is the whole
    test and the verdict tracks the code rather than a list someone maintains.

    Nothing here fails `lh doctor`. A Copilot profile with unread transcripts
    is an accurate report of a reader that has not been written yet, not a
    misconfiguration of this machine; the section exists so that the day a
    Claude Code profile reads `unread`, the regression is visible.
    """
    from lazy_harness.agents.registry import agent_for_profile

    console.print("\n[bold]Transcripts[/bold]")
    for p in list_profiles(cfg):
        agent = agent_for_profile(cfg, p.name)
        health = transcript_health(agent, p.config_dir)
        _verdict, icon, template = _TRANSCRIPT_LINES[health]
        sessions = session_path(agent, p.config_dir, "sessions")
        detail = template.format(
            agent=getattr(agent, "name", "unknown"),
            path=contract_path(sessions) if sessions is not None else "",
        )
        # `icon` is the only markup on this line. A profile name or a path
        # holding `[...]` is markup to rich too, and it deletes it silently.
        console.print(f"  {icon} {escape(p.name)} \u2014 {escape(detail)}")


def _render_one_role(console: Console, cfg: Config, role: str) -> bool:
    """Report one role. Returns False only for a hard failure.

    Reachability is a warning — inference is best-effort — while a role naming
    a backend that does not exist is a misconfiguration nothing else reports.
    """
    from lazy_harness.llm.roles import RoleNotFoundError, resolve_role

    try:
        target = resolve_role(cfg, role)
    except RoleNotFoundError as e:
        console.print(f"  [red]✗[/red] {escape(role)}: {escape(str(e))}")
        return False

    try:
        backend = build_backend(type=target.type, base_url=target.base_url, api_key=target.api_key)
    except (LLMBackendError, LLMBackendNotFoundError) as e:
        console.print(f"  [red]✗[/red] {escape(role)}: {escape(str(e))}")
        return False

    suffix = ""
    if target.api_key_env:
        # Names the variable and whether it resolves, never the value.
        resolved = "resolves" if os.environ.get(target.api_key_env) else "NOT SET"
        suffix = f" (key from ${target.api_key_env}: {resolved})"

    if isinstance(backend, OpenAICompatibleBackend):
        url = backend._base_url
        try:
            httpx.get(url, timeout=2)
            console.print(
                f"  [green]✓[/green] {escape(role)} → {target.type} reachable at {url}{suffix}"
            )
        except httpx.HTTPError:
            console.print(
                f"  [yellow]![/yellow] {escape(role)} → {target.type} not reachable at "
                f"{url}{suffix} — inference for this role will fail until the endpoint is up"
            )
        return True

    if shutil.which("claude"):
        console.print(f"  [green]✓[/green] {escape(role)} → claude binary on PATH")
    else:
        console.print(
            f"  [yellow]![/yellow] {escape(role)} → claude binary not found on PATH — "
            "install Claude Code or point the role at another backend"
        )
    return True


def _render_llm_backend(console: Console, cfg: Config) -> bool:
    """ADR-039: report every role in `[llm.roles]`, not one global backend.

    A role table where one entry is broken must not be reported by its
    healthy siblings, so each is resolved and probed on its own.
    """
    console.print("\n[bold]LLM roles[/bold]")

    roles = sorted(cfg.llm.roles)
    if not roles:
        # No table declared: the deprecated single-backend form is still live,
        # and reporting nothing would read as "nothing configured".
        return _render_one_role(console, cfg, "distill")

    return all([_render_one_role(console, cfg, role) for role in roles])


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


def _render_profile_secrets(console: Console, cfg: Config) -> None:
    """Profiles taking their credentials from the ambient environment (ADR-045 D3).

    The launch refuses a secrets file it cannot read; it cannot refuse a file
    that was never written, because exactly one profile is entitled to have
    none — the one the global environment is already set up for. Every *other*
    profile with no file of its own launches under whichever account that
    environment carries, which is the silent wrong-identity launch F2 measured.

    The line names no environment variable and prints nothing out of the file.
    Naming the variable would mean enumerating which variables are credentials
    per agent, and an enumeration that misses one reports "clean" for the
    profile it missed — the statement that needs no list is the one that cannot
    be wrong (ADR-045 A2).
    """
    secrets_dir = secrets_dir_for(cfg)
    inheriting: list[str] = []
    for name in sorted(cfg.profiles.items):
        if name == cfg.profiles.default:
            continue
        try:
            has_own = (secrets_dir / f"{name}.env").is_file()
        except OSError:
            # `is_file()` raises rather than answering False when the directory
            # cannot be traversed. Such a profile is not inheriting quietly —
            # `resolve_launch` refuses it outright — so silence here is the
            # accurate answer rather than the lenient one.
            has_own = True
        if not has_own:
            inheriting.append(name)

    if not inheriting:
        return

    console.print("\n[bold]Profile credentials[/bold]")
    for name in inheriting:
        console.print(
            f"  [yellow]![/yellow] {name} — no {name}.env in "
            f"{contract_path(secrets_dir)}; inherits the ambient environment's credentials"
        )


def _render_artifact_versions(
    console: Console,
    reports: list[ArtifactVersionReport],
    installed_version: str = __version__,
) -> None:
    """Report a deployed artifact written by a newer lazy-harness (decision 9).

    Reporting, not refusing — a hard failure here would turn a stale artifact
    into an unusable machine, which is exactly the silent failure this check
    replaces. Silent when nothing is newer, same rule as
    `_render_sink_freshness`: an absent problem prints nothing.
    """
    newer = [
        r for r in reports if r.lh_version is not None and is_newer(r.lh_version, installed_version)
    ]
    if not newer:
        return
    console.print("\n[bold]Artifact versions[/bold]")
    for r in newer:
        console.print(
            f"  [yellow]![/yellow] {r.profile}/{r.kind} was written by lazy-harness "
            f"{r.lh_version}, newer than the installed {installed_version} "
            f"— {contract_path(r.path)}"
        )


def _render_hook_signals(console: Console, gaps: list[HookSignalGap]) -> None:
    """Name each deployed hook's missing signals, per profile (design step 4).

    Reporting, not failing: the agent is running and the rest of its hooks are
    deployed, so this is a capability gap to close, not a broken machine. Silent
    when there is nothing to say, the same rule as `_render_artifact_versions`.

    The hook itself is *not* installed — `deploy.engine._hook_entries_for` acts
    on this same `gaps_for_profile` answer and leaves it out, naming it as it
    goes. This line is the standing account of why, which the deploy output
    scrolls away.

    The line says the *event is delivered* on purpose. `hook_events()` not
    carrying the event at all is the other unsupported state, and the design
    refuses to collapse the two: that one is resolved by the agent's event
    vocabulary, this one by a `TranscriptReader`. Naming the mechanism is what
    keeps the reader from chasing the wrong one.
    """
    if not gaps:
        return
    console.print("\n[bold]Hook signals[/bold]")
    for gap in gaps:
        missing = ", ".join(escape(s.value) for s in gap.missing)
        cause = (
            f"{escape(gap.agent)}'s TranscriptReader does not deliver it"
            if gap.has_reader
            else f"{escape(gap.agent)} has no TranscriptReader"
        )
        console.print(
            f"  [yellow]![/yellow] {escape(gap.profile)}/{escape(gap.hook)} — "
            f"{escape(gap.event)} is delivered, but the hook needs signal "
            f"{missing} and {cause}"
        )
    console.print(
        "      [dim]Missing signal, not a missing event: deploy leaves the hook out "
        "rather than installing one that would find nothing and pass. "
        "Closed by a TranscriptReader.[/dim]"
    )


def _render_hook_operations(console: Console, gaps: list[HookOperationGap]) -> None:
    """Name each deployed hook whose declared operations this agent's own tool
    map cannot fully produce (design step 10).

    Reporting, not failing — same rule as `_render_hook_signals`: the hook
    installs and the rest of the profile is unaffected, this only says which
    of its declared operations never arrives on a real tool call. Silent when
    there is nothing to say.

    Distinct from a missing signal: this hook never opens a transcript for the
    operation in question, it is asked about a `ToolCall` that this agent's
    own native-tool map never produces. Closed by the agent's tool map, not by
    a `TranscriptReader` and not by this harness.
    """
    if not gaps:
        return
    console.print("\n[bold]Hook operations[/bold]")
    for gap in gaps:
        inert = ", ".join(escape(op.value) for op in gap.inert)
        state = (
            "the hook is inert on this profile"
            if gap.fully_inert
            else "the hook can't see those calls on this profile"
        )
        console.print(
            f"  [yellow]![/yellow] {escape(gap.profile)}/{escape(gap.hook)} — "
            f"{escape(gap.event)} is delivered, but {escape(gap.agent)} maps no native "
            f"tool to {inert}: {state}"
        )
    console.print(
        "      [dim]Operation declared, not one any native tool this agent emits carries: "
        "the hook still installs and runs, it is just never asked about a call of that "
        "kind. Closed by the agent's own tool map, not by this harness.[/dim]"
    )


def _render_uncarried_events(console: Console, gaps: list[UncarriedEventHook]) -> None:
    """Name each deployed hook wired to an event this agent does not carry at
    all (design step 10).

    Distinct from a missing signal or a missing operation, both of which need
    the event delivered in the first place. Reporting, not failing, and silent
    when there is nothing to say — same rule as `_render_hook_operations`.
    """
    if not gaps:
        return
    console.print("\n[bold]Hook events[/bold]")
    for gap in gaps:
        console.print(
            f"  [yellow]![/yellow] {escape(gap.profile)}/{escape(gap.hook)} — wired to "
            f"{escape(gap.event)}, which {escape(gap.agent)} does not deliver at all: "
            f"nothing installs and nothing runs"
        )
    console.print(
        "      [dim]Event absent from hook_events(), not a missing signal: an absent key "
        "means the agent does not deliver that event at all, which is a different "
        "statement from delivering it and ignoring the verdict. Closed by widening the "
        "agent's own event vocabulary, never a TranscriptReader.[/dim]"
    )


def _render_codex_trust(console: Console, reports: list[CodexHookTrust]) -> None:
    """What Codex will refuse to run, and how far that can be established.

    Reporting, never failing, and the reason is not the same as
    `_render_hook_signals`'s: *untrusted is the expected state right after a
    deploy*. The design's own acceptance run is "deploy, confirm the hooks are
    reported untrusted and do not fire, trust them, confirm they fire" — so an
    `lh doctor` that exited 1 on it would paint the documented happy path red
    and teach the reader to ignore the section.

    Silent when no profile runs Codex, and when a Codex profile has no deployed
    `hooks.json`: a line on every run saying a profile has nothing to trust
    trains the reader past the line that matters.

    The vocabulary is deliberately two-thirds of Codex's. Codex decides between
    `Trusted` and `Modified` by comparing the stored hash with one it recomputes,
    and computing that second hash means reimplementing its TOML normalisation —
    silently wrong on any upstream change, with no signal until hooks stop
    firing. So a stored hash is reported as `unknown`, and nothing here is ever
    called trusted.
    """
    if not reports:
        return
    console.print("\n[bold]Codex hook trust[/bold]")
    for report in reports:
        name = escape(report.profile)
        if report.unreadable:
            console.print(
                f"  [yellow]![/yellow] {name} — trust state not readable: "
                f"{escape(report.unreadable)}"
            )
            continue
        if report.untrusted:
            console.print(
                f"  [yellow]![/yellow] {name} — {len(report.untrusted)} of {report.declared} "
                f"deployed {_hooks(len(report.untrusted))} untrusted: "
                f"{escape(', '.join(report.untrusted))}"
            )
        if report.unknown:
            console.print(
                f"  [grey50]·[/grey50] {name} — {len(report.unknown)} "
                f"{_hooks(len(report.unknown))} {_carry(len(report.unknown))} a stored hash; "
                f"whether it still matches is not determinable without Codex's own "
                f"normalisation"
            )
        if report.orphaned:
            console.print(
                f"  [yellow]![/yellow] {name} — {len(report.orphaned)} orphaned trust "
                f"{'entry' if len(report.orphaned) == 1 else 'entries'} for handlers "
                f"{contract_path(report.hooks_file)} no longer declares; the key indexes "
                f"the group's position, so a redeploy that reorders one strands its approval"
            )
        if report.ignored_events:
            console.print(
                f"  [yellow]![/yellow] {name} — {escape(', '.join(report.ignored_events))} "
                f"in {contract_path(report.hooks_file)} "
                f"{'is an event' if len(report.ignored_events) == 1 else 'are events'} "
                f"this Codex does not deliver; nothing is installed for it and nothing warns"
            )
    console.print(
        "      [dim]Codex will not run a hook it has not approved, and says nothing when it "
        "skips one. Approve them in Codex's own review screen — `lh deploy` cannot: the "
        "User config layer it writes to is never Managed.[/dim]"
    )


def _hooks(n: int) -> str:
    return "hook" if n == 1 else "hooks"


def _carry(n: int) -> str:
    return "carries" if n == 1 else "carry"


def _project_memory_dir(agent: AgentAdapter, cfg: Config | None, profile: str) -> Path:
    """Memory dir for the current project, canonicalised across worktrees.

    Shaped exactly like `_engram_persist_metrics_path`, and for the same reason:
    `session-end` names this directory with `agent_dir_for(cfg, event.profile)`,
    so a `doctor` that named it from `[agent].type` reported on a directory
    nothing writes to as soon as the profile ran a second agent.
    `test_doctor_reads_the_memory_dir_the_hook_writes` asserts the two answers
    against each other.

    An empty profile is "nobody said" and keeps the global answer — the same
    contract `agent_runtime_dir` applies to an absent `profile_config_dir`.
    """

    from lazy_harness.hooks.builtins._shared import knowledge_root_for
    from lazy_harness.hooks.builtins._shared import memory_dir as shared_memory_dir

    if profile:
        from lazy_harness.hooks.builtins._shared import agent_dir_for

        agent, base = agent_dir_for(cfg, profile)
    else:
        base = agent_runtime_dir(agent)

    return shared_memory_dir(
        None,
        agent_dir=base,
        sessions_subdir=session_subdir(agent, "sessions"),
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

    _render_transcripts(console, cfg)
    _render_profile_secrets(console, cfg)

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

    sinks_freshness = collect_sinks_freshness(cfg, now=_now())
    if not _render_sink_freshness(console, sinks_freshness):
        ok = False

    if not _render_llm_backend(console, cfg):
        ok = False

    # Resolved once and handed to both: the two diagnostics report on
    # directories the hooks name per profile, and answering "which profile" a
    # second time is how one section can report on a different profile than the
    # other in the same `lh doctor` run.
    active_profile = resolve_profile(None)

    health = collect_engram_persist_health(
        _engram_persist_metrics_path(agent, cfg, active_profile),
        now=datetime.now(UTC),
    )
    if not _render_engram_persist(console, health):
        ok = False

    if not _render_memory_hygiene(console, _project_memory_dir(agent, cfg, active_profile)):
        ok = False

    from lazy_harness.core.artifact_version import collect_artifact_version_reports

    reports = collect_artifact_version_reports(cfg, config_dir() / "profiles")
    _render_artifact_versions(console, reports)
    _render_hook_signals(console, collect_hook_signal_gaps(cfg))
    _render_hook_operations(console, collect_hook_operation_gaps(cfg))
    _render_uncarried_events(console, collect_uncarried_events(cfg))
    _render_codex_trust(console, collect_codex_trust(cfg))

    console.print()
    if ok:
        console.print("[green]All checks passed.[/green]")
    else:
        console.print("[red]Some checks failed. Review above.[/red]")
        raise SystemExit(1)

"""Graph-assist adoption metrics, against the design's kill criteria.

Read-only. Computes §6 of `specs/designs/2026-09-24-graph-assist-design.md`
from each profile's transcripts plus the hook's
`logs/graph_assist_metrics.jsonl`, for every agent, so Codex serves as the
control group beside Claude Code.

Only sessions whose cwd sits in a repository holding
`graphify-out/graph.json` count, the same population as the §1 baseline. A
worktree counts toward its main checkout, which is where the graph lives.

Codex is read in its own dialect: at 0.154.0 its shell calls reach the
transcript as `exec` programs calling `tools.exec_command({"cmd": ...})`, so
the commands are pulled out of the program text rather than off
`ToolCall.command`. That is transcript analysis, not a hook, and the pattern
may need revisiting on a Codex upgrade.
"""

from __future__ import annotations

import json
import math
import re
import shlex
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from lazy_harness.agents.base import Operation, Signal, ToolCall
from lazy_harness.core.config import Config
from lazy_harness.knowledge import graph_assist

GRAPH_TOUCH_KILL = 0.20
PRECISION_KILL = 0.50
LATENCY_KILL_MS = 1500
DEFLECTION_WINDOW = 3

_GRAPHIFY_ACTIONS = frozenset({"query", "path", "explain"})
_CODEX_CMD = re.compile(r'"cmd"\s*:\s*("(?:[^"\\]|\\.)*")')
_GRAPHIFY_MCP = re.compile(r"mcp__(?:plugin_graphify_)?graphify__\w+")


@dataclass(frozen=True)
class Call:
    kind: str
    """`graphify` (an agent asked the graph), `code_grep` (a search over the repo)
    or `other` (any other tool call, kept for session and deflection counts)."""
    ts: datetime | None
    symbol: str | None = None
    """For `code_grep`: the normalised identifier searched, when it is one."""


@dataclass
class SessionRecord:
    agent: str
    session_id: str
    repo: Path
    calls: list[Call] = field(default_factory=list)


@dataclass
class AgentReport:
    agent: str
    sessions: int = 0
    graph_touch: int = 0
    agent_calls: int = 0
    graphify_calls: int = 0
    code_greps: int = 0
    hits: int = 0
    precise_hits: int = 0
    latencies: list[int] = field(default_factory=list)
    deflection_base: int = 0
    deflected: int = 0

    @property
    def p95_latency_ms(self) -> int | None:
        if not self.latencies:
            return None
        ordered = sorted(self.latencies)
        return ordered[max(0, math.ceil(0.95 * len(ordered)) - 1)]


def _is_graphify_command(argv: list[str]) -> bool:
    return (
        len(argv) >= 2 and argv[0].rsplit("/", 1)[-1] == "graphify" and argv[1] in _GRAPHIFY_ACTIONS
    )


def _classify_command(command: str, repo: Path, cwd: Path, ts: datetime | None) -> list[Call]:
    calls: list[Call] = []
    lexer = shlex.shlex(command, posix=True, punctuation_chars=";&|")
    lexer.whitespace_split = True
    try:
        tokens = list(lexer)
    except ValueError:
        tokens = []
    segment: list[str] = []
    for token in [*tokens, ";"]:
        if token in {";", "&&", "||", "&", "|"}:
            if _is_graphify_command(segment):
                calls.append(Call("graphify", ts))
            segment = []
        else:
            segment.append(token)
    pattern = graph_assist.bash_search_pattern(command, repo, cwd)
    if pattern is not None:
        symbol = graph_assist.identifier(pattern)
        calls.append(Call("code_grep", ts, graph_assist.normalise(symbol) if symbol else None))
    return calls


def _codex_program(tool: ToolCall) -> str | None:
    raw = tool.raw_input
    if tool.native_name != "exec" or not isinstance(raw, dict):
        return None
    program = raw.get("input")
    return program if isinstance(program, str) else None


def classify(tool: ToolCall, repo: Path, cwd: Path, ts: datetime | None) -> list[Call]:
    """The graph-relevant calls one transcript tool call makes, in order."""
    if _GRAPHIFY_MCP.fullmatch(tool.native_name):
        return [Call("graphify", ts)]
    if tool.operation is Operation.SEARCH_CODE:
        where = tool.search_path
        if where is not None and not graph_assist.is_inside(cwd / where, repo):
            return []
        symbol = graph_assist.identifier(tool.search_pattern or "")
        return [Call("code_grep", ts, graph_assist.normalise(symbol) if symbol else None)]
    if tool.command is not None:
        return _classify_command(tool.command, repo, cwd, ts)
    program = _codex_program(tool)
    if program is None:
        return []
    calls: list[Call] = []
    for match in _CODEX_CMD.finditer(program):
        try:
            command = json.loads(match.group(1))
        except ValueError:
            continue
        calls.extend(_classify_command(command, repo, cwd, ts))
    calls.extend(Call("graphify", ts) for _ in _GRAPHIFY_MCP.finditer(program))
    return calls


def _parse_ts(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _deflection(session: SessionRecord, hits: list[dict]) -> tuple[int, int]:
    """(hits matched to their search, hits not followed by a re-search).

    A hit is matched to the last `code_grep` of the same symbol at or before
    the hook's timestamp (plus a little slack: the transcript stamps the
    assistant turn, the hook stamps its own run). Deflected means none of the
    next `DEFLECTION_WINDOW` calls searches that symbol again.
    """
    base = deflected = 0
    greps = [(i, c) for i, c in enumerate(session.calls) if c.kind == "code_grep"]
    for hit in hits:
        symbol = graph_assist.normalise(str(hit.get("pattern", "")))
        hit_ts = _parse_ts(hit.get("ts"))
        candidates = [
            i
            for i, c in greps
            if c.symbol == symbol
            and (hit_ts is None or c.ts is None or (c.ts - hit_ts).total_seconds() <= 5)
        ]
        if not candidates:
            continue
        index = candidates[-1]
        base += 1
        following = session.calls[index + 1 : index + 1 + DEFLECTION_WINDOW]
        if not any(c.kind == "code_grep" and c.symbol == symbol for c in following):
            deflected += 1
    return base, deflected


def compute(sessions: Iterable[SessionRecord], metrics: Iterable[dict]) -> dict[str, AgentReport]:
    lines = [m for m in metrics if isinstance(m, dict)]
    hits_by_session: dict[str, list[dict]] = {}
    for line in lines:
        if line.get("outcome") == "hit":
            hits_by_session.setdefault(str(line.get("session_id", "")), []).append(line)

    reports: dict[str, AgentReport] = {}
    for session in sessions:
        report = reports.setdefault(session.agent, AgentReport(agent=session.agent))
        report.sessions += 1
        graphify = sum(c.kind == "graphify" for c in session.calls)
        report.graphify_calls += graphify
        report.code_greps += sum(c.kind == "code_grep" for c in session.calls)
        hits = hits_by_session.get(session.session_id, [])
        report.agent_calls += graphify > 0
        report.graph_touch += graphify > 0 or bool(hits)
        base, deflected = _deflection(session, hits)
        report.deflection_base += base
        report.deflected += deflected

    claude = reports.setdefault("claude-code", AgentReport(agent="claude-code"))
    for line in lines:
        latency = line.get("latency_ms")
        if isinstance(latency, int):
            claude.latencies.append(latency)
        if line.get("outcome") == "hit":
            claude.hits += 1
            claude.precise_hits += line.get("symbol_in_output") is True
    return reports


def _pct(part: int, whole: int) -> float:
    return 100.0 * part / whole if whole else 0.0


def kill_reasons(report: AgentReport) -> list[str]:
    """The §6 kill criteria that trip for Claude Code; empty when none does."""
    reasons: list[str] = []
    if report.sessions and report.graph_touch / report.sessions < GRAPH_TOUCH_KILL:
        reasons.append(f"graph touch {_pct(report.graph_touch, report.sessions):.1f}% < 20%")
    if report.hits and report.precise_hits / report.hits < PRECISION_KILL:
        reasons.append(f"hit precision {_pct(report.precise_hits, report.hits):.1f}% < 50%")
    p95 = report.p95_latency_ms
    if p95 is not None and p95 > LATENCY_KILL_MS:
        reasons.append(f"p95 latency {p95} ms > {LATENCY_KILL_MS} ms")
    return reasons


def render(reports: dict[str, AgentReport], since: datetime | None) -> str:
    window = f"since {since.date().isoformat()}" if since else "all time"
    lines = [f"Graph assist report ({window}; sessions in repos with a graph)"]
    for agent in sorted(reports):
        r = reports[agent]
        total = r.graphify_calls + r.code_greps
        lines += [
            "",
            f"{agent}",
            f"  sessions                 {r.sessions}",
            f"  (a') graph touch         {r.graph_touch}/{r.sessions} = "
            f"{_pct(r.graph_touch, r.sessions):.1f}%",
            f"  (a) agent graphify use   {r.agent_calls}/{r.sessions} = "
            f"{_pct(r.agent_calls, r.sessions):.1f}%",
            f"  (b) graphify vs grep     {r.graphify_calls}/{total} = "
            f"{_pct(r.graphify_calls, total):.1f}%",
        ]
        if agent == "claude-code":
            p95 = r.p95_latency_ms
            lines += [
                f"  hit precision            {r.precise_hits}/{r.hits} = "
                f"{_pct(r.precise_hits, r.hits):.1f}%",
                f"  p95 latency              {'-' if p95 is None else f'{p95} ms'}",
                f"  deflection               {r.deflected}/{r.deflection_base} = "
                f"{_pct(r.deflected, r.deflection_base):.1f}%",
            ]
            reasons = kill_reasons(r)
            # A kill criterion is judged at day 14 of the rollout; before that
            # this line reports the state, not a decision.
            lines.append(
                "  kill criteria            "
                + ("tripped: " + "; ".join(reasons) if reasons else "none tripped")
            )
    return "\n".join(lines)


# --- collection -----------------------------------------------------------------


def _transcript_cwd(path: Path, max_lines: int = 200) -> Path | None:
    """The cwd a transcript recorded: Claude's per-entry `cwd`, Codex's `session_meta`."""
    try:
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            for number, raw in enumerate(handle):
                if number >= max_lines:
                    break
                try:
                    entry = json.loads(raw)
                except ValueError:
                    continue
                if not isinstance(entry, dict):
                    continue
                payload = entry.get("payload")
                for source in (entry, payload if isinstance(payload, dict) else {}):
                    cwd = source.get("cwd")
                    if isinstance(cwd, str) and cwd:
                        return Path(cwd)
    except OSError:
        return None
    return None


def _graph_repo(cwd: Path) -> Path | None:
    for candidate in (cwd, *cwd.parents):
        if graph_assist.graph_path(candidate).is_file():
            return candidate
    return None


def collect(cfg: Config, since: datetime | None) -> tuple[list[SessionRecord], list[dict]]:
    """Every profile's sessions in graph repos, and every metrics line since `since`.

    Each profile is read from its own `config_dir`, never through
    `agent_dir_for`: that resolves the *running* session's directory from
    `CLAUDE_CONFIG_DIR` first, which is right for a hook and made every Claude
    profile read the same transcripts here. Transcripts and metrics files are
    deduplicated by resolved path, for profiles that share a directory.

    A session that made no tool call is skipped: it never had the choice
    between the graph and grep. Measured on 2026-09-25, ~800 of 1 104 Claude
    sessions in graph repos were headless evaluations with no tool call at all.
    """
    from lazy_harness.agents.base import TranscriptIdentity
    from lazy_harness.agents.registry import agent_for_profile
    from lazy_harness.hooks.builtins._shared import transcript_reader

    sessions: list[SessionRecord] = []
    metrics: list[dict] = []
    seen: set[Path] = set()
    for profile, entry in cfg.profiles.items.items():
        agent = agent_for_profile(cfg, profile)
        base = agent.config_dir(entry.config_dir)
        metrics_file = (base / "logs" / "graph_assist_metrics.jsonl").resolve()
        if metrics_file not in seen:
            seen.add(metrics_file)
            metrics += _read_metrics(metrics_file, since)
        reader = transcript_reader(profile, cfg)
        if reader is None:
            continue
        for path in reader.locate_sessions(base, since):
            resolved = path.resolve()
            if resolved in seen:
                continue
            seen.add(resolved)
            cwd = _transcript_cwd(path)
            repo = _graph_repo(cwd) if cwd is not None else None
            if cwd is None or repo is None:
                continue
            session_id = (
                reader.session_identity(path).session_id
                if isinstance(reader, TranscriptIdentity)
                else path.stem
            )
            record = SessionRecord(agent=agent.name, session_id=session_id, repo=repo)
            for event in reader.read(path):
                if event.signal is Signal.TOOL_CALLS and event.tool is not None:
                    found = classify(event.tool, repo, cwd, event.timestamp)
                    record.calls += found or [Call("other", event.timestamp)]
            if record.calls:
                sessions.append(record)
    return sessions, metrics


def _read_metrics(path: Path, since: datetime | None) -> list[dict]:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return []
    lines: list[dict] = []
    for raw in text.splitlines():
        try:
            line = json.loads(raw)
        except ValueError:
            continue
        if not isinstance(line, dict):
            continue
        ts = _parse_ts(line.get("ts"))
        if since is not None and ts is not None and ts < since:
            continue
        lines.append(line)
    return lines

"""PreToolUse hook: answer a code-symbol search from graphify's graph.

Non-blocking, never a verdict. When a `Grep` or a shell `grep`/`rg` looks up an
identifier inside a repository with a fresh `graphify-out/graph.json`, the
definitions, callers and naming documents arrive as `additionalContext` beside
the search result — information where the agent is already looking, instead of
the upstream `graphify hook-guard search` order to go and ask
(`specs/designs/2026-09-24-graph-assist-design.md`).

The search is scoped to the cwd's own checkout, and the graph comes from the
main checkout (`--git-common-dir`), because a worktree has no `graphify-out/`
of its own and is where every code change in a worktree-first repo happens.
The price is line numbers that drift for files the branch has changed; the
file and the symbol stay right.

Every evaluation of a search call appends one line to
`<agent dir>/logs/graph_assist_metrics.jsonl`, which
`lh knowledge graph-assist report` reads against the design's kill criteria. A
shell command that runs no search tool at all is not an evaluation and is not
logged, so the latency percentile measures searches rather than `ls`.
"""

from __future__ import annotations

import json
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path

from lazy_harness.agents.base import HookDecision, HookEvent, Operation, ToolCall
from lazy_harness.core.project_identity import main_repo_root
from lazy_harness.knowledge import graph_assist

# `tests/unit/test_hook_matcher_coverage.py` holds the deployed matcher to this.
INSPECTED_TOOLS = frozenset({"Bash", "Grep"})

_GIT_TIMEOUT_S = 2


def _git(cwd: Path, *args: str) -> str | None:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=_GIT_TIMEOUT_S,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    out = result.stdout.strip()
    return out if result.returncode == 0 and out else None


def _metrics_file(profile: str) -> Path:
    from lazy_harness.core.config import Config, ConfigError, load_config
    from lazy_harness.core.paths import config_file
    from lazy_harness.hooks.builtins._shared import agent_dir_for

    cfg: Config | None = None
    cf = config_file()
    if cf.is_file():
        try:
            cfg = load_config(cf)
        except ConfigError:
            cfg = None
    return agent_dir_for(cfg, profile)[1] / "logs" / "graph_assist_metrics.jsonl"


def _record(event: HookEvent, started: float, **fields: object) -> None:
    line = {
        "ts": datetime.now(UTC).isoformat(timespec="seconds"),
        "session_id": event.session_id,
        "repo": "",
        "pattern": "",
        "outcome": "skip",
        "reason": "",
        "latency_ms": int((time.monotonic() - started) * 1000),
        "definitions": 0,
        "complete": False,
        **fields,
    }
    try:
        path = _metrics_file(event.profile)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(line) + "\n")
    except Exception:  # noqa: BLE001 — measurement must never cost the answer
        pass


def _evaluate(event: HookEvent, native_name: str, raw_input: object) -> tuple[str, dict]:
    """(context to inject, metrics fields). Empty context means stay silent."""
    toplevel = _git(event.cwd, "rev-parse", "--show-toplevel")
    if toplevel is None:
        return "", {"reason": "no_repo"}
    # Two roots: the search is scoped to the checkout the agent is in, and the
    # graph comes from the main checkout, which a worktree shares.
    scope = Path(toplevel)
    root = main_repo_root(scope) or scope
    graph_json = graph_assist.graph_path(root)
    if not graph_json.is_file():
        return "", {"repo": str(root), "reason": "no_graph"}
    head = _git(root, "log", "-1", "--format=%ct")
    if head is not None and graph_json.stat().st_mtime < float(head):
        return "", {"repo": str(root), "reason": "stale"}

    pattern = graph_assist.search_target(native_name, raw_input, scope, event.cwd)
    if pattern is None:
        return "", {"repo": str(root), "reason": "not_search"}
    base = {"repo": str(root), "pattern": pattern}

    entries = graph_assist.load_index(root)
    if entries is None:
        return "", {**base, "reason": "index_building"}
    found = graph_assist.lookup(entries, pattern)
    if found is None:
        return "", {**base, "outcome": "miss", "reason": "miss"}
    label, defs = found
    text = graph_assist.render(label, defs)
    return text, {
        **base,
        "outcome": "hit",
        "reason": "hit",
        "definitions": len(defs),
        # Hit precision's numerator: every definition made it into the text. A
        # hit listing three of forty `main()`s is noise, and this can say so.
        "complete": len(defs) <= graph_assist.MAX_DEFS,
    }


def _tool_input(tool: ToolCall) -> dict[str, str]:
    """The classifier's input, rebuilt from the normalised call."""
    if tool.operation is Operation.SEARCH_CODE:
        fields = {"pattern": tool.search_pattern, "path": tool.search_path}
        return {k: str(v) for k, v in fields.items() if v is not None}
    return {"command": tool.command} if tool.command is not None else {}


def main(event: HookEvent) -> HookDecision:
    tool = event.tool
    if tool is None or tool.native_name not in INSPECTED_TOOLS:
        return HookDecision()
    tool_input = _tool_input(tool)
    if not graph_assist.is_search_call(tool.native_name, tool_input):
        return HookDecision()

    started = time.monotonic()
    try:
        text, fields = _evaluate(event, tool.native_name, tool_input)
    except Exception as exc:  # noqa: BLE001 — an assist that fails stays silent
        _record(event, started, reason=f"error:{type(exc).__name__}")
        return HookDecision()
    _record(event, started, **fields)
    return HookDecision(additional_context=text)

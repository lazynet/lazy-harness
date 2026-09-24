#!/usr/bin/env python3
"""PreCompact hook: preserve context before compaction.

Backs up the session transcript, extracts a working-context summary, writes it
to the project's memory dir, and returns it for the compaction summariser.
Always abstains — there is no verdict to form on this event.

Output is **plain text, never JSON**. Claude Code's `hookSpecificOutput` union
has no PreCompact variant (verified against 2.1.234), so a JSON payload fails
schema validation, marks the hook failed, and its output is discarded. The
PreCompact executor instead collects each successful hook's raw stdout and
hands the joined text to the compaction summariser as `newCustomInstructions`.
`ClaudeCodeAdapter.format_hook_output` special-cases `pre_compact` and writes
`HookDecision.additional_context` as raw text for exactly that reason, which is
why this hook returns it there rather than printing.
"""

from __future__ import annotations

import json
import shutil
from datetime import datetime
from pathlib import Path

from lazy_harness.agents.base import HookDecision, HookEvent

# Claude Code's PreCompact executor collects each successful hook's raw stdout
# and passes the joined text as `newCustomInstructions` to the compaction
# summariser. That is a directive channel, not a context channel, so the
# summary needs framing or it reads as a wall of unexplained assertions.
SUMMARY_PREAMBLE = "Preserve the following working context in the summary:"


def parse_transcript(path: Path) -> tuple[list[str], list[str]]:
    user_msgs: list[str] = []
    files_touched: set[str] = set()

    try:
        for line in path.read_text().splitlines():
            if not line.strip():
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue

            if not isinstance(obj, dict):
                continue
            message = obj.get("message")
            if not isinstance(message, dict):
                continue
            role = message.get("role")
            content = message.get("content")

            if role == "user":
                user_text = ""
                if isinstance(content, str):
                    user_text = content
                elif isinstance(content, list) and all(
                    isinstance(block, dict) and block.get("type") == "text" for block in content
                ):
                    user_text = "\n".join(
                        block["text"] for block in content if isinstance(block.get("text"), str)
                    )
                if len(user_text.strip()) > 15:
                    user_msgs.append(user_text.strip()[:200])

            if role == "assistant" and isinstance(content, list):
                for block in content:
                    if not isinstance(block, dict) or block.get("type") != "tool_use":
                        continue
                    inp = block.get("input", {})
                    if not isinstance(inp, dict):
                        continue
                    for key in ("file_path", "path"):
                        val = inp.get(key, "")
                        if isinstance(val, str) and "/" in val:
                            files_touched.add(val)
    except OSError:
        pass

    return user_msgs, sorted(files_touched)


def build_summary(user_msgs: list[str], files: list[str]) -> str:
    parts: list[str] = []
    if user_msgs:
        parts.append("## Tasks in progress")
        for msg in user_msgs[-5:]:
            parts.append(f"- {msg}")
    if files:
        parts.append("\n## Files worked on")
        for f in files[-10:]:
            parts.append(f"- {f}")
    return "\n".join(parts)


def tail_jsonl_summaries(path: Path, limit: int = 3) -> list[str]:
    if not path.is_file():
        return []
    summaries: list[str] = []
    try:
        for line in path.read_text().splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            summary = obj.get("summary", "")
            if isinstance(summary, str) and summary:
                summaries.append(summary[:200])
    except OSError:
        return []
    return summaries[-limit:]


def build_memory_tails(memory_dir: Path) -> str:
    parts: list[str] = []
    decisions = tail_jsonl_summaries(memory_dir / "decisions.jsonl")
    if decisions:
        parts.append("## Recent decisions")
        for s in decisions:
            parts.append(f"- {s}")
    failures = tail_jsonl_summaries(memory_dir / "failures.jsonl")
    if failures:
        parts.append("\n## Recent failures")
        for s in failures:
            parts.append(f"- {s}")
    return "\n".join(parts)


def main(event: HookEvent) -> HookDecision:
    """Preserve this compaction's working context and hand it back as text.

    Three deletions this migration makes deliberately, all of them the same
    thing: the fallbacks that let this module run as a bare script. Its
    docstring used to say "this hook has to run as a bare script, so nothing
    outside this guard may import from the package", and that stopped being
    true. `deploy/engine.py:136` emits `{binary} hook {name} --profile
    {profile}` for every builtin, so the agent reaches this through `lh hook`;
    `lh hook` reaches `main` only through `hooks.runner`, which imports the
    module from inside the package. A `lazy_harness` that will not import means
    there is no `lh` to run in the first place, and the guarantee those
    fallbacks carried moves to the runner's failure policy (`runner.py:177`),
    which returns exit 0 with a warning for a non-blocking hook. Gone with them:
    `_bootstrap_log`, `_bootstrap_project_dir`, and the `shared_memory_dir is
    None` branch that computed a project dir without `_shared`.

    """
    from lazy_harness.core.config import Config, ConfigError, load_config
    from lazy_harness.core.paths import config_file
    from lazy_harness.hooks.builtins._shared import (
        agent_dir_for,
        existing_transcript,
        knowledge_root_for,
        make_log,
    )
    from lazy_harness.hooks.builtins._shared import memory_dir as shared_memory_dir

    _log = make_log("pre-compact")

    cf = config_file()
    cfg: Config | None = None
    if cf.is_file():
        try:
            cfg = load_config(cf)
        except ConfigError:
            cfg = None

    # Config first, then the directories, then the first log line: every path
    # below is keyed by the agent *this profile* runs, and writing `fired`
    # before that resolves is what sent `context-inject`'s log to the global
    # agent's directory (PR #300). The knowledge root comes from the same
    # `Config` rather than being resolved again — two readers resolving one
    # config-derived path differently is how one of them ends up writing where
    # nothing reads.
    agent, agent_dir = agent_dir_for(cfg, event.profile)
    from lazy_harness.agents.session_paths import session_path, session_subdir

    if session_path(agent, agent_dir, "sessions") is None:
        return HookDecision()
    subdirs = agent.session_dirs()
    log_file = agent_dir / (subdirs.get("logs") or "logs") / "hooks.log"

    # `parse_hook_input` yields `Path("")` — which is `Path(".")`, and truthy —
    # for a payload that names no cwd. This hook encodes the cwd into a
    # directory *name*, so `Path(".")` would make the memory dir `projects/-.`
    # and every checkout on the machine would share one.
    cwd = event.cwd if event.cwd != Path(".") else Path.cwd()
    _log(log_file, f"fired cwd={cwd}")

    # The *declared* transcript, not `existing_transcript` of it:
    # `resolve_project_dir` stats only its parent, so filtering a transcript the
    # agent has named but not yet written would silently fall back to encoding
    # the cwd and read memory from a directory nothing wrote to.
    memory_dir = shared_memory_dir(
        event.transcript_path,
        agent_dir=agent_dir,
        sessions_subdir=session_subdir(agent, "sessions"),
        cwd=cwd,
        knowledge_root=knowledge_root_for(cfg),
    )
    memory_dir.mkdir(parents=True, exist_ok=True)

    summary = ""

    # Filtered here, where the file is opened. `HookEvent.transcript_path` is
    # what the payload named, not what exists; the pre-runner code stat'd it as
    # part of reading the payload, so without this the check would disappear
    # and `shutil.copy2` would raise into the handler below on every compaction
    # of a session whose transcript the agent had not written yet.
    transcript_path = existing_transcript(event.transcript_path)
    if transcript_path is not None:
        backup_dir = agent_dir / "compact-backups"
        backup_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d-%H%M%S")
        proj_name = cwd.name
        backup_file = backup_dir / f"{ts}-{proj_name}.jsonl"
        try:
            shutil.copy2(transcript_path, backup_file)
            _log(log_file, f"backed up transcript to {backup_file.name}")
        except OSError as e:
            _log(log_file, f"backup failed: {e}")

        user_msgs, files = parse_transcript(transcript_path)
        summary = build_summary(user_msgs, files)

    memory_tails = build_memory_tails(memory_dir)
    if memory_tails:
        summary = f"{summary}\n\n{memory_tails}" if summary else memory_tails

    if not summary:
        _log(log_file, "no summary extracted")
        return HookDecision()

    summary_file = memory_dir / "pre-compact-summary.md"
    ts = datetime.now().isoformat()
    try:
        summary_file.write_text(f"<!-- auto-generated by pre-compact hook at {ts} -->\n{summary}\n")
        _log(log_file, f"summary written ({len(summary)} chars)")
    except OSError as e:
        _log(log_file, f"summary write failed: {e}")

    # The adapter appends the trailing newline `print` used to add, so these
    # are the same bytes the summariser received before the migration.
    return HookDecision(additional_context=f"{SUMMARY_PREAMBLE}\n\n{summary}")

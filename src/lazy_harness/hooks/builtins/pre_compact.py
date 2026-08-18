#!/usr/bin/env python3
"""PreCompact hook: preserve context before compaction.

Reads transcript path from stdin JSON, backs up transcript,
extracts working context summary, writes to memory dir.
Always exits 0.

Output is **plain text, never JSON**. Claude Code's `hookSpecificOutput` union
has no PreCompact variant (verified against 2.1.234), so a JSON payload fails
schema validation, marks the hook failed, and its output is discarded. The
PreCompact executor instead collects each successful hook's raw stdout and
hands the joined text to the compaction summariser as `newCustomInstructions`.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
from datetime import datetime
from pathlib import Path

# Claude Code's PreCompact executor collects each successful hook's raw stdout
# and passes the joined text as `newCustomInstructions` to the compaction
# summariser. That is a directive channel, not a context channel, so the
# summary needs framing or it reads as a wall of unexplained assertions.
SUMMARY_PREAMBLE = "Preserve the following working context in the summary:"


def _bootstrap_log(log_file: Path, msg: str) -> None:
    """Stand-in for `_shared.make_log` when lazy_harness is not importable."""
    try:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().astimezone().isoformat(timespec="seconds")
        with open(log_file, "a") as f:
            f.write(f"{ts} pre-compact: {msg}\n")
    except OSError:
        pass


def _bootstrap_project_dir(
    payload: object, *, agent_dir: Path, sessions_subdir: str, cwd: Path
) -> Path:
    """Stand-in for `_shared.resolve_project_dir` when lazy_harness is not importable."""
    encoded = "-" + str(cwd).replace("/", "-").lstrip("-")
    return agent_dir / (sessions_subdir or "projects") / encoded


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

            role = obj.get("role", "")
            content = obj.get("content", "")

            if role == "user" and isinstance(content, str) and len(content.strip()) > 15:
                user_msgs.append(content.strip()[:200])

            if role == "assistant" and isinstance(content, list):
                for block in content:
                    if not isinstance(block, dict) or block.get("type") != "tool_use":
                        continue
                    inp = block.get("input", {})
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


def _resolve_agent_dirs() -> tuple[Path, dict[str, str], Path | None]:
    """(runtime_dir, session_dirs, knowledge_root) for the configured agent.

    The knowledge root is returned rather than resolved again at the call site:
    it comes from the same `Config` this already loads, and two readers
    resolving one config-derived path differently is how one of them ends up
    writing where nothing reads.

    Bootstrap fallback: when lazy_harness is not importable (hook run as a
    bare script) read the Claude Code env var directly, as before ADR-032.
    """
    try:
        from lazy_harness.agents.registry import get_agent
        from lazy_harness.core.config import ConfigError, load_config
        from lazy_harness.core.paths import agent_runtime_dir, config_file
    except ImportError:
        return Path(os.environ.get("CLAUDE_CONFIG_DIR", Path.home() / ".claude")), {}, None

    cfg = None
    cf = config_file()
    if cf.is_file():
        try:
            cfg = load_config(cf)
        except ConfigError:
            cfg = None
    agent = get_agent(cfg.agent.type if cfg is not None else "claude-code")
    from lazy_harness.hooks.builtins._shared import knowledge_root_for

    return agent_runtime_dir(agent), agent.session_dirs(), knowledge_root_for(cfg)


def main() -> None:
    try:
        input_data = json.load(sys.stdin)
    except (json.JSONDecodeError, EOFError, ValueError):
        input_data = {}

    try:
        from lazy_harness.hooks.builtins._shared import make_log
        from lazy_harness.hooks.builtins._shared import memory_dir as shared_memory_dir

        _log = make_log("pre-compact")
    except ImportError:
        # Bootstrap fallback, same contract as _resolve_agent_dirs: this hook
        # has to run as a bare script, so nothing outside this guard may import
        # from the package.
        _log = _bootstrap_log
        shared_memory_dir = None

    cwd = Path.cwd()
    agent_dir, subdirs, knowledge_root = _resolve_agent_dirs()
    log_file = agent_dir / (subdirs.get("logs") or "logs") / "hooks.log"
    _log(log_file, f"fired cwd={cwd}")

    transcript_path_str = ""
    for key in ("transcript_path", "transcriptPath", "input"):
        if key in input_data:
            transcript_path_str = input_data[key]
            break

    if shared_memory_dir is not None:
        memory_dir = shared_memory_dir(
            input_data,
            agent_dir=agent_dir,
            sessions_subdir=subdirs.get("sessions") or "projects",
            cwd=cwd,
            knowledge_root=knowledge_root,
        )
    else:
        memory_dir = (
            _bootstrap_project_dir(
                input_data,
                agent_dir=agent_dir,
                sessions_subdir=subdirs.get("sessions") or "projects",
                cwd=cwd,
            )
            / "memory"
        )
    memory_dir.mkdir(parents=True, exist_ok=True)

    summary = ""

    if transcript_path_str:
        transcript_path = Path(transcript_path_str)
        if transcript_path.is_file():
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

    if summary:
        summary_file = memory_dir / "pre-compact-summary.md"
        ts = datetime.now().isoformat()
        try:
            summary_file.write_text(
                f"<!-- auto-generated by pre-compact hook at {ts} -->\n{summary}\n"
            )
            _log(log_file, f"summary written ({len(summary)} chars)")
        except OSError as e:
            _log(log_file, f"summary write failed: {e}")

        print(f"{SUMMARY_PREAMBLE}\n\n{summary}")
    else:
        _log(log_file, "no summary extracted")


if __name__ == "__main__":
    main()

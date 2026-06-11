#!/usr/bin/env python3
"""PreCompact hook: preserve context before compaction.

Reads transcript path from stdin JSON, backs up transcript,
extracts working context summary, writes to memory dir.
Always exits 0.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
from datetime import datetime
from pathlib import Path

from lazy_harness.hooks.builtins._shared import make_log

_log = make_log("pre-compact")


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


def _resolve_agent_dirs() -> tuple[Path, dict[str, str]]:
    """(runtime_dir, session_dirs) for the configured agent (ADR-032 L3/L4).

    Bootstrap fallback: when lazy_harness is not importable (hook run as a
    bare script) read the Claude Code env var directly, as before ADR-032.
    """
    try:
        from lazy_harness.agents.registry import get_agent
        from lazy_harness.core.config import ConfigError, load_config
        from lazy_harness.core.paths import agent_runtime_dir, config_file
    except ImportError:
        return Path(os.environ.get("CLAUDE_CONFIG_DIR", Path.home() / ".claude")), {}

    cfg = None
    cf = config_file()
    if cf.is_file():
        try:
            cfg = load_config(cf)
        except ConfigError:
            cfg = None
    agent = get_agent(cfg.agent.type if cfg is not None else "claude-code")
    return agent_runtime_dir(agent), agent.session_dirs()


def main() -> None:
    try:
        input_data = json.load(sys.stdin)
    except (json.JSONDecodeError, EOFError, ValueError):
        input_data = {}

    cwd = Path.cwd()
    agent_dir, subdirs = _resolve_agent_dirs()
    log_file = agent_dir / (subdirs.get("logs") or "logs") / "hooks.log"
    _log(log_file, f"fired cwd={cwd}")

    transcript_path_str = ""
    for key in ("transcript_path", "transcriptPath", "input"):
        if key in input_data:
            transcript_path_str = input_data[key]
            break

    encoded = "-" + str(cwd).replace("/", "-").lstrip("-")
    memory_dir = agent_dir / (subdirs.get("sessions") or "projects") / encoded / "memory"
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

        output = {
            "hookSpecificOutput": {
                "hookEventName": "PreCompact",
                "additionalContext": summary,
            }
        }
        print(json.dumps(output))
    else:
        _log(log_file, "no summary extracted")


if __name__ == "__main__":
    main()

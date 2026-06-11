#!/usr/bin/env python3
"""PostCompact hook: re-inject pre-compact summary into post-compact context.

Reads `pre-compact-summary.md` (written by the pre-compact hook) and re-emits
it as `hookSpecificOutput.additionalContext` so Claude Code includes it in the
context window after compaction. Skips silently if the file is missing or its
mtime is older than `_FRESHNESS_WINDOW_SECONDS` (stale from a previous compact).

Always exits 0. Never blocks compaction recovery.
"""

from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

_FRESHNESS_WINDOW_SECONDS = 300


def _bootstrap_log(log_file: Path, msg: str) -> None:
    """Stand-in for `_shared.make_log` when lazy_harness is not importable."""
    try:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().astimezone().isoformat(timespec="seconds")
        with open(log_file, "a") as f:
            f.write(f"{ts} post-compact: {msg}\n")
    except OSError:
        pass


def _strip_html_comments(text: str) -> str:
    return "\n".join(ln for ln in text.splitlines() if not ln.lstrip().startswith("<!--")).strip()


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
        json.load(sys.stdin)
    except (json.JSONDecodeError, EOFError, ValueError):
        pass

    try:
        from lazy_harness.hooks.builtins._shared import make_log

        _log = make_log("post-compact")
    except ImportError:
        # Bootstrap fallback, same contract as _resolve_agent_dirs.
        _log = _bootstrap_log

    cwd = Path.cwd()
    agent_dir, subdirs = _resolve_agent_dirs()
    log_file = agent_dir / (subdirs.get("logs") or "logs") / "hooks.log"

    encoded = "-" + str(cwd).replace("/", "-").lstrip("-")
    sessions_subdir = subdirs.get("sessions") or "projects"
    summary_file = agent_dir / sessions_subdir / encoded / "memory" / "pre-compact-summary.md"

    try:
        st = summary_file.stat()
    except FileNotFoundError:
        _log(log_file, f"fired cwd={cwd} action=skipped reason=missing")
        return
    except OSError as e:
        _log(log_file, f"fired cwd={cwd} action=skipped reason=stat_error err={e}")
        return

    age = time.time() - st.st_mtime
    if age > _FRESHNESS_WINDOW_SECONDS:
        _log(log_file, f"fired cwd={cwd} action=skipped reason=stale age={age:.0f}s")
        return

    try:
        raw = summary_file.read_text()
    except OSError as e:
        _log(log_file, f"fired cwd={cwd} action=skipped reason=read_error err={e}")
        return

    body = _strip_html_comments(raw)
    if not body:
        _log(log_file, f"fired cwd={cwd} action=skipped reason=empty_body")
        return

    output = {
        "hookSpecificOutput": {
            "hookEventName": "PostCompact",
            "additionalContext": body,
        }
    }
    print(json.dumps(output))
    _log(log_file, f"fired cwd={cwd} action=injected summary_chars={len(body)}")


if __name__ == "__main__":
    main()

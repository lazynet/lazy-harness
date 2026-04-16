#!/usr/bin/env python3
"""SessionEnd hook: force a final compound-loop evaluation.

The Stop hook fires after every LLM turn and is gated by `debounce_seconds`
and `reprocess_min_growth_seconds` to bound LLM cost. When the session ends
for real (`/exit`, `/clear`, logout), those gates can silently swallow the
last few minutes of work, leaving `handoff.md` stale.

SessionEnd has no such rate limit — it fires exactly once, on shutdown — so
this hook ignores both gates and always enqueues a task. Still exits 0 on
every path; nothing here may block Claude Code's shutdown.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path


def _log(log_file: Path, msg: str) -> None:
    try:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().astimezone().isoformat(timespec="seconds")
        with open(log_file, "a") as f:
            f.write(f"{ts} session-end: {msg}\n")
    except OSError:
        pass


def _find_latest_session(sessions_dir: Path) -> Path | None:
    if not sessions_dir.is_dir():
        return None
    jsonl_files = [p for p in sessions_dir.glob("*.jsonl") if p.is_file()]
    if not jsonl_files:
        return None
    return max(jsonl_files, key=lambda f: f.stat().st_mtime)


def main() -> None:
    try:
        json.load(sys.stdin)
    except (json.JSONDecodeError, EOFError, ValueError):
        pass

    try:
        from lazy_harness.core.config import Config, ConfigError, load_config
        from lazy_harness.core.paths import config_file
        from lazy_harness.knowledge.compound_loop import create_task, should_queue_task
    except ImportError:
        return

    claude_dir = Path(os.environ.get("CLAUDE_CONFIG_DIR", Path.home() / ".claude"))
    log_dir = claude_dir / "logs"
    queue_dir = claude_dir / "queue"
    log_file = log_dir / "hooks.log"

    _log(log_file, f"fired cwd={Path.cwd()}")

    cf = config_file()
    cfg: Config | None = None
    if cf.is_file():
        try:
            cfg = load_config(cf)
        except ConfigError:
            cfg = None

    if cfg is None or not cfg.compound_loop.enabled:
        _log(log_file, "disabled in config, skipping")
        return

    cwd = Path.cwd()
    encoded = "-" + str(cwd).replace("/", "-").lstrip("-")
    sessions_dir = claude_dir / "projects" / encoded

    session_jsonl = _find_latest_session(sessions_dir)
    if session_jsonl is None:
        _log(log_file, "no session JSONL found")
        return

    session_id = session_jsonl.stem
    short_id = session_id[:8]

    if not should_queue_task(
        queue_dir=queue_dir,
        session_jsonl=session_jsonl,
        session_id=session_id,
        debounce_seconds=cfg.compound_loop.debounce_seconds,
        min_growth_seconds=cfg.compound_loop.reprocess_min_growth_seconds,
        force=True,
    ):
        _log(log_file, f"should_queue_task returned False under force for {short_id}")
        return

    memory_dir = sessions_dir / "memory"
    task_file = create_task(
        queue_dir=queue_dir,
        cwd=cwd,
        session_jsonl=session_jsonl,
        session_id=session_id,
        memory_dir=memory_dir,
    )
    _log(log_file, f"queued {task_file.name} (force)")

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
        _log(log_file, f"worker spawn failed: {e}")


if __name__ == "__main__":
    main()

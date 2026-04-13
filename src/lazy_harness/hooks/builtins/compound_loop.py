#!/usr/bin/env python3
"""Stop hook: queue async session evaluation for compound-loop.

Always exits 0 — a failure here must never block Claude Code's session close.
The hook itself just drops a task file and spawns a detached worker. All the
real work (LLM call, persistence) happens in the worker subprocess.
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
            f.write(f"{ts} compound-loop: {msg}\n")
    except OSError:
        pass


def _rotate_log(log_file: Path, max_bytes: int = 102400, keep_lines: int = 500) -> None:
    try:
        if log_file.is_file() and log_file.stat().st_size > max_bytes:
            lines = log_file.read_text().splitlines()
            log_file.write_text("\n".join(lines[-keep_lines:]) + "\n")
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
        from lazy_harness.knowledge.compound_loop import (
            create_task,
            is_already_processed,
            is_debounced,
        )
    except ImportError:
        return

    claude_dir = Path(os.environ.get("CLAUDE_CONFIG_DIR", Path.home() / ".claude"))
    log_dir = claude_dir / "logs"
    queue_dir = claude_dir / "queue"
    log_file = log_dir / "hooks.log"

    _log(log_file, f"fired cwd={Path.cwd()}")
    _rotate_log(log_file)

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

    if is_debounced(queue_dir, session_id, cfg.compound_loop.debounce_seconds):
        _log(log_file, f"debounce, task already queued for {short_id}")
        return

    if is_already_processed(queue_dir, session_id):
        _log(log_file, f"already processed {short_id}, skipping")
        return

    memory_dir = sessions_dir / "memory"
    task_file = create_task(
        queue_dir=queue_dir,
        cwd=cwd,
        session_jsonl=session_jsonl,
        session_id=session_id,
        memory_dir=memory_dir,
    )
    _log(log_file, f"queued {task_file.name}")

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

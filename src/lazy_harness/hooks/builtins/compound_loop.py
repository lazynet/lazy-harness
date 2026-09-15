#!/usr/bin/env python3
"""Stop hook: queue async session evaluation for compound-loop.

Always abstains — a failure here must never block Claude Code's session close.
The hook itself just drops a task file and spawns a detached worker. All the
real work (LLM call, persistence) happens in the worker subprocess.

It therefore declares no signals: it *locates* a transcript and enqueues its
path, and the worker reads messages and tool calls afterwards, out of process.
Declaring `MESSAGES` here would make `deploy` refuse to install the hook on an
agent whose reader cannot supply a signal this process never touches.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from lazy_harness.agents.base import HookDecision, HookEvent


def _rotate_log(log_file: Path, max_bytes: int = 102400, keep_lines: int = 500) -> None:
    try:
        if log_file.is_file() and log_file.stat().st_size > max_bytes:
            lines = log_file.read_text().splitlines()
            log_file.write_text("\n".join(lines[-keep_lines:]) + "\n")
    except OSError:
        pass


def main(event: HookEvent) -> HookDecision:
    from lazy_harness.core.config import Config, ConfigError, load_config
    from lazy_harness.core.paths import config_file
    from lazy_harness.hooks.builtins._shared import (
        agent_dir_for,
        existing_transcript,
        find_latest_session,
        knowledge_root_for,
        make_log,
    )
    from lazy_harness.hooks.builtins._shared import (
        memory_dir as shared_memory_dir,
    )
    from lazy_harness.knowledge.compound_loop import (
        create_task,
        is_debounced,
        last_processed_mtime,
        should_reprocess,
    )

    _log = make_log("compound-loop")

    # Config first, log second: `agent_dir_for` needs the profile's config to
    # know which directory this hook may write into, and a `fired` line written
    # above it lands in whatever directory the *global* agent names (PR #300).
    cf = config_file()
    cfg: Config | None = None
    if cf.is_file():
        try:
            cfg = load_config(cf)
        except ConfigError:
            cfg = None

    agent, agent_dir = agent_dir_for(cfg, event.profile)
    subdirs = agent.session_dirs()
    log_dir = agent_dir / (subdirs.get("logs") or "logs")
    log_file = log_dir / "hooks.log"
    queue_dir = agent_dir / (subdirs.get("queue") or "queue")

    # A payload naming no cwd parses as `Path("")`, which is `Path(".")`. This
    # hook cannot take that as given the way its siblings can: it derives the
    # agent's project directory by hand below rather than through
    # `project_key`, so `Path(".")` would encode to `-.` and point every queued
    # task at one shared directory that holds no transcripts at all.
    cwd = event.cwd if event.cwd != Path(".") else Path.cwd()

    _log(log_file, f"fired cwd={cwd}")
    _rotate_log(log_file)

    if cfg is None or not cfg.compound_loop.enabled:
        _log(log_file, "disabled in config, skipping")
        return HookDecision()

    # The agent names its project dirs with an encoding that has changed across
    # releases, so prefer the transcript it hands us and only derive a path when
    # the payload omits it.
    declared = event.transcript_path
    session_jsonl = existing_transcript(declared)
    if session_jsonl is None:
        encoded = "-" + str(cwd).replace("/", "-").lstrip("-")
        sessions_dir = agent_dir / (subdirs.get("sessions") or "projects") / encoded
        session_jsonl = find_latest_session(sessions_dir)
    if session_jsonl is None:
        _log(log_file, "no session JSONL found")
        return HookDecision()

    session_id = session_jsonl.stem
    short_id = session_id[:8]

    if is_debounced(queue_dir, session_id, cfg.compound_loop.debounce_seconds):
        _log(log_file, f"debounce, task already queued for {short_id}")
        return HookDecision()

    last_processed = last_processed_mtime(queue_dir, session_id)
    if not should_reprocess(
        session_jsonl, last_processed, cfg.compound_loop.reprocess_min_growth_seconds
    ):
        _log(log_file, f"no new activity since last process for {short_id}")
        return HookDecision()

    memory_dir = shared_memory_dir(
        declared,
        agent_dir=agent_dir,
        sessions_subdir=subdirs.get("sessions") or "projects",
        cwd=cwd,
        knowledge_root=knowledge_root_for(cfg),
    )
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
    return HookDecision()

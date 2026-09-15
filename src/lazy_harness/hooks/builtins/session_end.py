#!/usr/bin/env python3
"""SessionEnd hook: force a final compound-loop evaluation.

The Stop hook fires after every LLM turn and is gated by `debounce_seconds`
and `reprocess_min_growth_seconds` to bound LLM cost. When the session ends
for real (`/exit`, `/clear`, logout), those gates can silently swallow the
last few minutes of work, leaving `handoff.md` stale.

SessionEnd has no such rate limit — it fires exactly once, on shutdown — so
this hook ignores both gates and always enqueues a task. It abstains on every
path; nothing here may block Claude Code's shutdown.

It declares no `Signal`: it *locates* a transcript and enqueues its path, and
the compound-loop worker reads the messages afterwards, out of process.
Declaring `MESSAGES` would make `deploy` refuse to install this hook on an
agent whose reader cannot supply a signal the hook never touches.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from lazy_harness.agents.base import HookDecision, HookEvent


def _loop_db_path() -> Path:
    from lazy_harness.monitoring.db import resolve_db_path

    return resolve_db_path()


def _record_session_closed(event: HookEvent) -> None:
    """Never raises: the compound-loop enqueue below must run regardless."""
    try:
        from lazy_harness.hooks.builtins._shared import project_key
        from lazy_harness.monitoring.db import MetricsDB

        # No `Path.cwd()` fallback here, deliberately: a payload naming no cwd
        # used to reach `project_key` as the empty string and record an
        # unattributed row, and this is a metrics label rather than a path the
        # hook writes to. The enqueue below takes the fallback because a wrong
        # directory there is a queued task pointing at the wrong project.
        MetricsDB(_loop_db_path()).record_loop_event(
            session=event.session_id,
            kind="session_closed",
            project=project_key(event.cwd) if event.cwd != Path(".") else "",
            profile=event.profile,
        )
    except Exception:
        pass


def main(event: HookEvent) -> HookDecision:
    _record_session_closed(event)

    # A hook must degrade gracefully: any exception here must not block
    # Claude Code's shutdown. Catch all exceptions and abstain.
    try:
        _enqueue_compound_loop(event)
    except Exception:
        pass
    return HookDecision()


def _enqueue_compound_loop(event: HookEvent) -> None:
    try:
        from lazy_harness.core.config import Config, ConfigError, load_config
        from lazy_harness.core.paths import config_file
        from lazy_harness.hooks.builtins._shared import (
            agent_dir_for,
            existing_transcript,
            find_latest_session,
            make_log,
            resolve_project_dir,
        )
        from lazy_harness.knowledge.compound_loop import create_task, should_queue_task
    except ImportError:
        # Broken/uninstalled package: silently no-op, never block the agent.
        return

    _log = make_log("session-end")

    # A payload with no `cwd` parses as `Path(".")`. The process directory is
    # what this hook read before the runner, and encoding `.` into the project
    # dir name would point every queued task at one shared garbage directory.
    cwd = event.cwd if event.cwd != Path(".") else Path.cwd()

    cf = config_file()
    cfg: Config | None = None
    if cf.is_file():
        try:
            cfg = load_config(cf)
        except ConfigError:
            cfg = None

    # Per profile, not per machine, and resolved *before* the first log line.
    # The bootstrap this replaces went through a hardcoded
    # `get_agent("claude-code")`, so `fired` landed in whatever directory the
    # global agent named while every line below it landed in the profile's own.
    agent, agent_dir = agent_dir_for(cfg, event.profile)
    subdirs = agent.session_dirs()
    log_dir = agent_dir / (subdirs.get("logs") or "logs")
    log_file = log_dir / "hooks.log"
    queue_dir = agent_dir / (subdirs.get("queue") or "queue")

    _log(log_file, f"fired cwd={cwd}")

    if cfg is None or not cfg.compound_loop.enabled:
        _log(log_file, "disabled in config, skipping")
        return

    declared = event.transcript_path
    session_jsonl = existing_transcript(declared)
    if session_jsonl is None:
        sessions_dir = resolve_project_dir(
            declared,
            agent_dir=agent_dir,
            sessions_subdir=subdirs.get("sessions") or "projects",
            cwd=cwd,
        )
        session_jsonl = find_latest_session(sessions_dir)
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

    from lazy_harness.hooks.builtins._shared import knowledge_root_for
    from lazy_harness.hooks.builtins._shared import memory_dir as shared_memory_dir

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

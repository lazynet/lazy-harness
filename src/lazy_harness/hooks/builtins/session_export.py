#!/usr/bin/env python3
"""Stop hook: export session to knowledge directory.

Finds the most recent session JSONL, exports it to markdown with full
frontmatter (project/profile/session_type), and triggers a QMD index update
scoped to the configured collection.

Decides nothing: it abstains on every branch and writes on no channel the agent
reads. Its whole output is the `hooks.log` line, which is why the byte goldens
in `tests/unit/hooks/builtins/test_session_export_goldens.py` are identical
across all seven branches and the log is asserted beside them.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from lazy_harness.agents.base import HookDecision, HookEvent


def main(event: HookEvent) -> HookDecision:
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
    except ImportError:
        # Broken/uninstalled package: silently no-op, never block the agent.
        return HookDecision()

    _log = make_log("session-export")

    # A payload naming no cwd parses as `Path("")`, which is `Path(".")`. This
    # hook read `Path.cwd()` before the runner, and the project directory it
    # encodes is what decides which session gets exported -- `Path(".")` encodes
    # to the directory `-.`, which holds nobody's sessions. Keep the fallback,
    # as `stop_verify_guard` does.
    cwd = event.cwd if event.cwd != Path(".") else Path.cwd()

    # Config loads before the first line is written, rather than after. The
    # bootstrap resolution this replaces went through a hardcoded
    # `get_agent("claude-code")` with no profile, so both this hook's log lines
    # landed in whatever directory the *global* agent named while the hook ran
    # under `--profile <p>` -- the defect PR #300 fixed for `context-inject`.
    #
    # An absent or unparseable config still resolves globally, and correctly so:
    # the profile -> config_dir mapping lives in the file that did not load.
    # `agent_dir_for`'s docstring owns that limit.
    cf = config_file()
    cfg: Config | None = None
    # Read only where `cfg` stays None, which is exactly the two branches that
    # set it. A `str | None` here would need an `or ""` at the log call and
    # would turn a future third branch into a blank line in the audit trail.
    refusal = "no config file, skipping"
    if cf.is_file():
        try:
            cfg = load_config(cf)
        except ConfigError as e:
            refusal = f"config error: {e}"

    agent, agent_dir = agent_dir_for(cfg, event.profile)
    from lazy_harness.agents.session_paths import session_path, session_subdir

    if session_path(agent, agent_dir, "sessions") is None:
        return HookDecision()
    subdirs = agent.session_dirs()
    log_file = agent_dir / (subdirs.get("logs") or "logs") / "hooks.log"
    _log(log_file, f"fired cwd={cwd}")

    if cfg is None:
        _log(log_file, refusal)
        return HookDecision()

    from lazy_harness.knowledge.directory import sessions_dir as knowledge_sessions_dir
    from lazy_harness.knowledge.marker import MarkerError, resolve_root

    knowledge_dir = resolve_root(cfg.knowledge.root or None)
    try:
        sessions_root = knowledge_sessions_dir(knowledge_dir)
    except MarkerError as e:
        _log(log_file, f"knowledge store unusable, skipping: {e}")
        return HookDecision()

    declared = event.transcript_path
    session_file = existing_transcript(declared)
    if session_file is None:
        sessions_dir = resolve_project_dir(
            declared,
            agent_dir=agent_dir,
            sessions_subdir=session_subdir(agent, "sessions"),
            cwd=cwd,
        )
        if sessions_dir is not None:
            session_file = find_latest_session(sessions_dir)
    if session_file is None:
        _log(log_file, "no session JSONL found")
        return HookDecision()

    try:
        from lazy_harness.knowledge.session_export import export_session

        sessions_root.mkdir(parents=True, exist_ok=True)
        result, skip_reason = export_session(
            session_file,
            sessions_root,
            classify_rules=cfg.knowledge.classify_rules,
        )
        if result:
            _log(log_file, f"exported to {result.name}")
        else:
            _log(log_file, f"skipped {session_file.name} ({skip_reason})")
            return HookDecision()
    except Exception as e:  # noqa: BLE001 — must never bubble up
        _log(log_file, f"export error: {e}")
        return HookDecision()

    if shutil.which("qmd"):
        try:
            subprocess.run(
                ["qmd", "update"],
                capture_output=True,
                timeout=60,
            )
        except (subprocess.TimeoutExpired, OSError) as e:
            _log(log_file, f"qmd update failed: {e}")

    return HookDecision()

#!/usr/bin/env python3
"""Stop hook: export session to knowledge directory.

Finds the most recent session JSONL, exports it to markdown with full
frontmatter (project/profile/session_type), and triggers a QMD index update
scoped to the configured collection. Always exits 0.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path


def main() -> None:
    try:
        json.load(sys.stdin)
    except (json.JSONDecodeError, EOFError, ValueError):
        pass

    try:
        from lazy_harness.agents.registry import get_agent
        from lazy_harness.core.config import ConfigError, load_config
        from lazy_harness.core.paths import agent_runtime_dir, config_file
        from lazy_harness.hooks.builtins._shared import find_latest_session, make_log
    except ImportError:
        # Broken/uninstalled package: silently no-op, never block the agent.
        return

    _log = make_log("session-export")

    # Pre-config bootstrap: the agent type is unknown until config loads, so
    # resolve the log path via the Claude Code adapter (identical to the
    # historical CLAUDE_CONFIG_DIR read). Re-resolved below once config is in.
    boot_dir = agent_runtime_dir(get_agent("claude-code"))
    log_file = boot_dir / "logs" / "hooks.log"
    cwd = Path.cwd()
    _log(log_file, f"fired cwd={cwd}")

    cf = config_file()
    if not cf.is_file():
        _log(log_file, "no config file, skipping")
        return
    try:
        cfg = load_config(cf)
    except ConfigError as e:
        _log(log_file, f"config error: {e}")
        return

    agent = get_agent(cfg.agent.type)
    agent_dir = agent_runtime_dir(agent)
    subdirs = agent.session_dirs()
    log_file = agent_dir / (subdirs.get("logs") or "logs") / "hooks.log"

    if not cfg.knowledge.path:
        _log(log_file, "knowledge.path not set, skipping")
        return

    knowledge_dir = Path(os.path.expanduser(cfg.knowledge.path))
    sessions_root = knowledge_dir / cfg.knowledge.sessions.subdir

    encoded = "-" + str(cwd).replace("/", "-").lstrip("-")
    sessions_dir = agent_dir / (subdirs.get("sessions") or "projects") / encoded
    session_file = find_latest_session(sessions_dir)
    if session_file is None:
        _log(log_file, "no session JSONL found")
        return

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
            return
    except Exception as e:  # noqa: BLE001 — must never bubble up
        _log(log_file, f"export error: {e}")
        return

    if shutil.which("qmd"):
        try:
            subprocess.run(
                ["qmd", "update"],
                capture_output=True,
                timeout=60,
            )
        except (subprocess.TimeoutExpired, OSError) as e:
            _log(log_file, f"qmd update failed: {e}")


if __name__ == "__main__":
    main()

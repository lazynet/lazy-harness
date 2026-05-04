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
from datetime import datetime
from pathlib import Path


def _log(log_file: Path, msg: str) -> None:
    try:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().astimezone().isoformat(timespec="seconds")
        with open(log_file, "a") as f:
            f.write(f"{ts} session-export: {msg}\n")
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

    claude_dir = Path(os.environ.get("CLAUDE_CONFIG_DIR", Path.home() / ".claude"))
    log_file = claude_dir / "logs" / "hooks.log"
    cwd = Path.cwd()
    _log(log_file, f"fired cwd={cwd}")

    try:
        from lazy_harness.core.config import ConfigError, load_config
        from lazy_harness.core.paths import config_file
    except ImportError:
        return

    cf = config_file()
    if not cf.is_file():
        _log(log_file, "no config file, skipping")
        return
    try:
        cfg = load_config(cf)
    except ConfigError as e:
        _log(log_file, f"config error: {e}")
        return

    if not cfg.knowledge.path:
        _log(log_file, "knowledge.path not set, skipping")
        return

    knowledge_dir = Path(os.path.expanduser(cfg.knowledge.path))
    sessions_root = knowledge_dir / cfg.knowledge.sessions.subdir

    encoded = "-" + str(cwd).replace("/", "-").lstrip("-")
    sessions_dir = claude_dir / "projects" / encoded
    session_file = _find_latest_session(sessions_dir)
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

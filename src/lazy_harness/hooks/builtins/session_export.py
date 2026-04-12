#!/usr/bin/env python3
"""Stop hook: export session to knowledge directory.
Finds most recent session JSONL, exports to markdown, triggers QMD update.
Always exits 0.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path


def _find_latest_session(sessions_dir: Path) -> Path | None:
    if not sessions_dir.is_dir():
        return None
    jsonl_files = list(sessions_dir.glob("*.jsonl"))
    if not jsonl_files:
        return None
    return max(jsonl_files, key=lambda f: f.stat().st_mtime)


def main() -> None:
    try:
        json.load(sys.stdin)
    except (json.JSONDecodeError, EOFError):
        pass

    claude_dir = Path(os.environ.get("CLAUDE_CONFIG_DIR", Path.home() / ".claude"))
    knowledge_dir_str = os.environ.get("LH_KNOWLEDGE_DIR", "")
    if not knowledge_dir_str:
        try:
            config_file = Path.home() / ".config" / "lazy-harness" / "config.toml"
            if config_file.is_file():
                import tomllib

                cfg = tomllib.loads(config_file.read_text())
                knowledge_dir_str = cfg.get("knowledge", {}).get("path", "")
        except Exception:
            pass
    if not knowledge_dir_str:
        return

    knowledge_dir = Path(os.path.expanduser(knowledge_dir_str))
    cwd = Path.cwd()
    encoded = "-" + str(cwd).replace("/", "-").lstrip("-")
    sessions_dir = claude_dir / "projects" / encoded
    session_file = _find_latest_session(sessions_dir)
    if not session_file:
        return

    script_dir = Path(__file__).resolve().parent.parent.parent
    sys.path.insert(0, str(script_dir))
    try:
        from lazy_harness.knowledge.session_export import export_session

        output_dir = knowledge_dir / "sessions"
        output_dir.mkdir(parents=True, exist_ok=True)
        result = export_session(session_file, output_dir)
        if result:
            print(f"Exported session to {result}")
            if shutil.which("qmd"):
                import subprocess

                subprocess.run(["qmd", "update"], capture_output=True, timeout=60)
    except Exception as e:
        print(f"Session export error: {e}", file=sys.stderr)


if __name__ == "__main__":
    main()

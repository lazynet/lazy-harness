#!/usr/bin/env python3
"""Stop hook: mirror new JSONL entries into Engram via `engram save`.

Always exits 0 — a failure here must never block Claude Code's Stop chain.
All real work lives in lazy_harness.knowledge.engram_persist.EngramPersister.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


def _resolve_project_key(cwd: Path) -> str:
    """Return canonical Engram project key.

    Prefers `git rev-parse --show-toplevel` basename so that nested cwd
    inside a repo always resolves to the same canonical key. Falls back
    to cwd basename if not in a git repo.
    """
    try:
        proc = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=cwd,
            capture_output=True,
            text=True,
            check=False,
        )
        if proc.returncode == 0:
            top = Path(proc.stdout.strip())
            if top.name:
                return top.name
    except OSError:
        pass
    return cwd.name


def main() -> None:
    payload: dict = {}
    try:
        payload = json.load(sys.stdin) or {}
    except (json.JSONDecodeError, EOFError, ValueError):
        pass

    cwd = Path(payload.get("cwd") or Path.cwd())

    try:
        from lazy_harness.knowledge.engram_persist import EngramPersister
    except ImportError:
        return

    claude_dir = Path(os.environ.get("CLAUDE_CONFIG_DIR", Path.home() / ".claude"))
    encoded = "-" + str(cwd).replace("/", "-").lstrip("-")
    memory_dir = claude_dir / "projects" / encoded / "memory"
    logs_dir = claude_dir / "logs"

    persister = EngramPersister(
        memory_dir=memory_dir,
        logs_dir=logs_dir,
        project_key=_resolve_project_key(cwd),
    )
    try:
        persister.persist_new_entries()
    except Exception:
        # Never propagate. Wrapper guarantees exit 0.
        pass


if __name__ == "__main__":
    main()

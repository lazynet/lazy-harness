"""Tests for built-in session-export hook."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


def test_session_export_hook_exits_zero(tmp_path: Path) -> None:
    hook_path = (
        Path(__file__).parent.parent.parent
        / "src"
        / "lazy_harness"
        / "hooks"
        / "builtins"
        / "session_export.py"
    )
    session_file = tmp_path / "projects" / "-tmp-test" / "abc12345.jsonl"
    session_file.parent.mkdir(parents=True)
    messages = [
        {"type": "permission-mode", "timestamp": "2026-04-12T10:00:00"},
        {"type": "system", "cwd": "/tmp/test", "timestamp": "2026-04-12T10:00:00"},
        {
            "type": "user",
            "message": {"content": "first question here"},
            "timestamp": "2026-04-12T10:00:01",
        },
        {
            "type": "assistant",
            "message": {"content": "first answer here"},
            "timestamp": "2026-04-12T10:00:02",
        },
        {
            "type": "user",
            "message": {"content": "second question"},
            "timestamp": "2026-04-12T10:00:03",
        },
        {
            "type": "assistant",
            "message": {"content": "second answer"},
            "timestamp": "2026-04-12T10:00:04",
        },
    ]
    session_file.write_text("\n".join(json.dumps(m) for m in messages) + "\n")
    knowledge_dir = tmp_path / "knowledge"
    knowledge_dir.mkdir()
    env = {
        "PATH": os.environ.get("PATH", ""),
        "HOME": str(tmp_path),
        "CLAUDE_CONFIG_DIR": str(tmp_path),
        "LH_KNOWLEDGE_DIR": str(knowledge_dir),
    }
    result = subprocess.run(
        [sys.executable, str(hook_path)],
        input="{}",
        capture_output=True,
        text=True,
        cwd="/tmp/test" if Path("/tmp/test").exists() else str(tmp_path),
        timeout=15,
        env=env,
    )
    assert result.returncode == 0


def test_session_export_registered() -> None:
    from lazy_harness.hooks.loader import list_builtin_hooks

    assert "session-export" in list_builtin_hooks()

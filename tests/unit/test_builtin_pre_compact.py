"""Tests for built-in pre-compact hook."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


def test_pre_compact_returns_zero(tmp_path: Path) -> None:
    hook_path = (
        Path(__file__).parent.parent.parent
        / "src"
        / "lazy_harness"
        / "hooks"
        / "builtins"
        / "pre_compact.py"
    )
    transcript = tmp_path / "session.jsonl"
    transcript.write_text(
        json.dumps(
            {"role": "user", "content": "hello world from user", "timestamp": "2026-04-12T10:00:00"}
        )
        + "\n"
        + json.dumps({"role": "assistant", "content": "hi", "timestamp": "2026-04-12T10:00:01"})
        + "\n"
    )

    env = {
        "PATH": os.environ.get("PATH", ""),
        "HOME": str(tmp_path),
        "CLAUDE_CONFIG_DIR": str(tmp_path / ".claude"),
    }
    (tmp_path / ".claude").mkdir()

    result = subprocess.run(
        [sys.executable, str(hook_path)],
        input=json.dumps({"transcript_path": str(transcript)}),
        capture_output=True,
        text=True,
        cwd=str(tmp_path),
        timeout=10,
        env=env,
    )
    assert result.returncode == 0


def test_pre_compact_empty_input(tmp_path: Path) -> None:
    hook_path = (
        Path(__file__).parent.parent.parent
        / "src"
        / "lazy_harness"
        / "hooks"
        / "builtins"
        / "pre_compact.py"
    )
    result = subprocess.run(
        [sys.executable, str(hook_path)],
        input="{}",
        capture_output=True,
        text=True,
        cwd=str(tmp_path),
        timeout=10,
    )
    assert result.returncode == 0

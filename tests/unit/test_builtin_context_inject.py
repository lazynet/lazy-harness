"""Tests for built-in context-inject hook."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def test_context_inject_returns_json(tmp_path: Path) -> None:
    hook_path = (
        Path(__file__).parent.parent.parent
        / "src"
        / "lazy_harness"
        / "hooks"
        / "builtins"
        / "context_inject.py"
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
    output = json.loads(result.stdout)
    assert "hookSpecificOutput" in output
    hso = output["hookSpecificOutput"]
    assert hso["hookEventName"] == "SessionStart"
    assert "additionalContext" in hso


def test_context_inject_includes_git_info(tmp_path: Path) -> None:
    subprocess.run(["git", "init"], cwd=str(tmp_path), capture_output=True)
    subprocess.run(
        ["git", "commit", "--allow-empty", "-m", "init"],
        cwd=str(tmp_path),
        capture_output=True,
        env={
            **__import__("os").environ,
            "GIT_AUTHOR_NAME": "test",
            "GIT_AUTHOR_EMAIL": "t@t",
            "GIT_COMMITTER_NAME": "test",
            "GIT_COMMITTER_EMAIL": "t@t",
        },
    )

    hook_path = (
        Path(__file__).parent.parent.parent
        / "src"
        / "lazy_harness"
        / "hooks"
        / "builtins"
        / "context_inject.py"
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
    output = json.loads(result.stdout)
    ctx = output["hookSpecificOutput"]["additionalContext"]
    assert "Branch:" in ctx or "branch" in ctx.lower()

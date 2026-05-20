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


def _encoded_cwd(cwd: Path) -> str:
    return "-" + str(cwd).replace("/", "-").lstrip("-")


def test_pre_compact_additional_context_includes_decisions_and_failures_tails(
    tmp_path: Path,
) -> None:
    hook_path = (
        Path(__file__).parent.parent.parent
        / "src"
        / "lazy_harness"
        / "hooks"
        / "builtins"
        / "pre_compact.py"
    )

    claude_dir = tmp_path / ".claude"
    memory_dir = claude_dir / "projects" / _encoded_cwd(tmp_path) / "memory"
    memory_dir.mkdir(parents=True)

    (memory_dir / "decisions.jsonl").write_text(
        json.dumps({"ts": "2026-05-01", "summary": "use uv for packaging"})
        + "\n"
        + json.dumps({"ts": "2026-05-10", "summary": "engram for episodic memory"})
        + "\n"
        + json.dumps({"ts": "2026-05-15", "summary": "pyright-lsp in both profiles"})
        + "\n"
    )
    (memory_dir / "failures.jsonl").write_text(
        json.dumps({"ts": "2026-05-02", "summary": "chezmoi TTY error on apply"})
        + "\n"
        + json.dumps({"ts": "2026-05-12", "summary": "worktree.bgIsolation misread as opt-in"})
        + "\n"
    )

    transcript = tmp_path / "session.jsonl"
    transcript.write_text(
        json.dumps(
            {
                "role": "user",
                "content": "working on the precompact hook tail",
                "timestamp": "2026-05-20T10:00:00",
            }
        )
        + "\n"
    )

    env = {
        "PATH": os.environ.get("PATH", ""),
        "HOME": str(tmp_path),
        "CLAUDE_CONFIG_DIR": str(claude_dir),
    }

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
    payload = json.loads(result.stdout)
    ctx = payload["hookSpecificOutput"]["additionalContext"]

    assert "Recent decisions" in ctx
    assert "pyright-lsp in both profiles" in ctx
    assert "engram for episodic memory" in ctx
    assert "Recent failures" in ctx
    assert "worktree.bgIsolation misread as opt-in" in ctx


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

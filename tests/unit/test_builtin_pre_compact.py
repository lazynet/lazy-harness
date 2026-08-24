"""Tests for built-in pre-compact hook."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

# Captured at collection time, before any per-test fixture can patch HOME, so
# it reflects the real machine home regardless of what a test later pins.
_REAL_HOME = Path(os.environ.get("HOME") or Path.home())


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


def test_pre_compact_emits_plain_text_carrying_decisions_and_failures_tails(
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
    # Claude Code 2.1.234's `hookSpecificOutput` union has no PreCompact
    # variant, so JSON here fails schema validation and the hook is marked
    # failed — its output dropped. The executor collects each *successful*
    # hook's raw stdout into `newCustomInstructions` instead, which is why
    # this has to be plain text.
    from lazy_harness.hooks.builtins.pre_compact import SUMMARY_PREAMBLE

    with pytest.raises(json.JSONDecodeError):
        json.loads(result.stdout)
    ctx = result.stdout
    assert ctx.lstrip().startswith(SUMMARY_PREAMBLE)

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
    claude_dir = tmp_path / ".claude"
    claude_dir.mkdir()
    env = {
        "PATH": os.environ.get("PATH", ""),
        "HOME": str(tmp_path),
        "CLAUDE_CONFIG_DIR": str(claude_dir),
    }

    result = subprocess.run(
        [sys.executable, str(hook_path)],
        input="{}",
        capture_output=True,
        text=True,
        cwd=str(tmp_path),
        timeout=10,
        env=env,
    )
    assert result.returncode == 0

    # Effect, not just exit code: the hook always creates the memory dir
    # (even with no transcript), so its presence at the pinned location is
    # proof the run stayed inside the sandbox instead of the real machine.
    memory_dir = claude_dir / "projects" / _encoded_cwd(tmp_path) / "memory"
    assert memory_dir.is_dir()


def test_pre_compact_subprocess_cannot_leak_into_real_machine_home(tmp_path: Path) -> None:
    """Regression test for the leak this hook's tests caused on the real machine.

    `test_pre_compact_empty_input` used to spawn this hook via `subprocess.run`
    without setting `HOME`/`CLAUDE_CONFIG_DIR` in the child's env. The child
    inherited the *developer's real* environment, so `paths._home()` resolved
    to the real machine home and the hook created a project dir under the real
    `~/.claude-lazy` on every run - 170 stray directories accumulated this way.

    This test reproduces that exact call shape (no `env=` kwarg) and asserts
    the hook never touches the real machine home. Before the `_isolate_home_dir`
    guard in conftest.py existed, this failed - the directory below was really
    created on disk.
    """
    hook_path = (
        Path(__file__).parent.parent.parent
        / "src"
        / "lazy_harness"
        / "hooks"
        / "builtins"
        / "pre_compact.py"
    )
    encoded = _encoded_cwd(tmp_path)
    real_leak_target = _REAL_HOME / ".claude" / "projects" / encoded

    result = subprocess.run(
        [sys.executable, str(hook_path)],
        input="{}",
        capture_output=True,
        text=True,
        cwd=str(tmp_path),
        timeout=10,
    )

    assert result.returncode == 0
    assert not real_leak_target.exists(), (
        f"hook subprocess leaked into the real machine home at {real_leak_target}"
    )


def test_pre_compact_routes_paths_through_agent_adapter(tmp_path, monkeypatch) -> None:
    """ADR-032 L3/L4: memory/backup dirs must come from the configured agent
    adapter. With agent.type = "null" the summary must land under ~/.null even
    when CLAUDE_CONFIG_DIR points elsewhere."""
    import io
    import json as _json
    import sys as _sys

    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "decoy-claude"))

    cwd = tmp_path / "proj"
    cwd.mkdir()
    encoded = "-" + str(cwd).replace("/", "-").lstrip("-")

    transcript = tmp_path / "transcript.jsonl"
    transcript.write_text(
        _json.dumps({"role": "user", "content": "please refactor the auth module"}) + "\n"
    )

    cfg_file = tmp_path / "config.toml"
    cfg_file.write_text('[harness]\nversion = "1"\n\n[agent]\ntype = "null"\n')
    from lazy_harness.core import paths as paths_mod
    from lazy_harness.hooks.builtins import pre_compact as hook_mod

    monkeypatch.setattr(paths_mod, "config_file", lambda: cfg_file)
    monkeypatch.chdir(cwd)
    monkeypatch.setattr(
        _sys, "stdin", io.StringIO(_json.dumps({"transcript_path": str(transcript)}))
    )
    hook_mod.main()

    summary_file = home / ".null" / "projects" / encoded / "memory" / "pre-compact-summary.md"
    assert summary_file.is_file()
    assert "please refactor the auth module" in summary_file.read_text()

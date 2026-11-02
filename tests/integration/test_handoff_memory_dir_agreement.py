"""`lh knowledge handoff-now` and the SessionEnd hook queue the same memory_dir.

Two paths answer one question — where does this project's distilled memory
live — so one test invokes both and compares what each wrote into the queue.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
from click.testing import CliRunner

from lazy_harness.agents.base import HookEvent
from lazy_harness.cli.main import cli

SESSION_ID = "deadbeef-feed-cafe-babe-1234abcd0001"


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


def _make_repo(path: Path) -> None:
    path.mkdir(parents=True)
    _git(path, "init", "-q", "-b", "main")
    _git(path, "config", "user.email", "test@example.invalid")
    _git(path, "config", "user.name", "test")
    _git(path, "remote", "add", "origin", "https://github.com/acme/widget.git")
    (path / "f.txt").write_text("x")
    _git(path, "add", "-A")
    _git(path, "commit", "-qm", "init")


def _setup(home_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path]:
    store = tmp_path / "store"
    store.mkdir()
    (store / "knowledge.toml").write_text(
        '[knowledge]\nversion = 1\nsessions = "sessions"\nlearnings = "learnings"\n'
        'memory = "memory"\n'
    )
    config_path = home_dir / ".config" / "lazy-harness" / "config.toml"
    config_path.parent.mkdir(parents=True)
    config_path.write_text(
        f'[harness]\nversion = "1"\n\n[agent]\ntype = "claude-code"\n\n'
        f'[knowledge]\nroot = "{store}"\n\n[compound_loop]\nenabled = true\n'
    )
    claude_dir = tmp_path / "claude"
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(claude_dir))
    monkeypatch.delenv("LAZY_KNOWLEDGE_ROOT", raising=False)
    return store, claude_dir


def _write_session(claude_dir: Path, cwd: Path) -> Path:
    encoded = "-" + str(cwd).replace("/", "-").lstrip("-")
    jsonl = claude_dir / "projects" / encoded / f"{SESSION_ID}.jsonl"
    jsonl.parent.mkdir(parents=True)
    records = [
        {"type": "permission-mode"},
        {"type": "user", "message": {"content": "x" * 250}},
        {"type": "assistant", "message": {"content": "ok"}},
    ]
    jsonl.write_text("".join(json.dumps(r) + "\n" for r in records))
    return jsonl


def _queued_memory_dir(claude_dir: Path) -> Path:
    tasks = list((claude_dir / "queue").glob("*.task"))
    assert len(tasks) == 1, tasks
    fields = dict(line.split("=", 1) for line in tasks[0].read_text().splitlines() if "=" in line)
    tasks[0].unlink()
    return Path(fields["memory_dir"])


def _no_worker(monkeypatch: pytest.MonkeyPatch) -> None:
    """Swallow the detached worker spawn; `subprocess` is one module for git too."""
    real = subprocess.Popen

    def popen(args, *a, **kw):  # type: ignore[no-untyped-def]
        if "lazy_harness.knowledge.compound_loop_worker" in list(args):
            return None
        return real(args, *a, **kw)

    monkeypatch.setattr(subprocess, "Popen", popen)


def _run_handoff_now(claude_dir: Path, cwd: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    _no_worker(monkeypatch)
    monkeypatch.chdir(cwd)
    result = CliRunner().invoke(cli, ["knowledge", "handoff-now"])
    assert result.exit_code == 0, result.output
    return _queued_memory_dir(claude_dir)


def _run_session_end(
    claude_dir: Path, cwd: Path, jsonl: Path, monkeypatch: pytest.MonkeyPatch
) -> Path:
    from lazy_harness.hooks.builtins import session_end

    _no_worker(monkeypatch)
    monkeypatch.chdir(cwd)
    session_end._enqueue_compound_loop(
        HookEvent(
            event="session_end",
            profile="",
            session_id=SESSION_ID,
            cwd=cwd,
            transcript_path=jsonl,
        )
    )
    return _queued_memory_dir(claude_dir)


def test_handoff_now_and_session_end_queue_the_same_memory_dir_from_a_checkout(
    home_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store, claude_dir = _setup(home_dir, tmp_path, monkeypatch)
    repo = tmp_path / "repo"
    _make_repo(repo)
    jsonl = _write_session(claude_dir, repo)

    from_hook = _run_session_end(claude_dir, repo, jsonl, monkeypatch)
    from_cli = _run_handoff_now(claude_dir, repo, monkeypatch)

    assert from_hook == store / "memory" / "github.com" / "acme" / "widget"
    assert from_cli == from_hook


def test_handoff_now_and_session_end_queue_the_same_memory_dir_from_a_worktree(
    home_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store, claude_dir = _setup(home_dir, tmp_path, monkeypatch)
    repo = tmp_path / "repo"
    _make_repo(repo)
    worktree = tmp_path / "repo-wt"
    _git(repo, "worktree", "add", "-q", "-b", "feat", str(worktree))
    jsonl = _write_session(claude_dir, worktree)

    from_hook = _run_session_end(claude_dir, worktree, jsonl, monkeypatch)
    from_cli = _run_handoff_now(claude_dir, worktree, monkeypatch)

    assert from_hook == store / "memory" / "github.com" / "acme" / "widget"
    assert from_cli == from_hook

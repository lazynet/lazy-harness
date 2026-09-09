"""Tests for the compound-loop worker entrypoint."""

from __future__ import annotations

import json
from pathlib import Path

import pytest


def test_worker_routes_dirs_through_agent_adapter(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ADR-032 L3/L4: queue/log dirs must come from the configured agent
    adapter. With agent.type = "null" they must land under ~/.null even when
    CLAUDE_CONFIG_DIR points elsewhere."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    decoy_dir = tmp_path / "decoy-claude"
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(decoy_dir))

    store = tmp_path / "store"
    store.mkdir()
    (store / "knowledge.toml").write_text(
        '[knowledge]\nversion = 1\nsessions = "sessions"\nlearnings = "learnings"\n'
    )
    monkeypatch.setenv("LAZY_KNOWLEDGE_ROOT", str(store))

    cfg_file = tmp_path / "config.toml"
    cfg_file.write_text(
        """
[harness]
version = "1"

[agent]
type = "null"

[compound_loop]
enabled = true
"""
    )
    from lazy_harness.knowledge import compound_loop_worker as worker_mod

    monkeypatch.setattr(worker_mod, "config_file", lambda: cfg_file)

    rc = worker_mod.main()

    assert rc == 0
    assert (home / ".null" / "queue" / "done").is_dir()
    assert (home / ".null" / "logs" / "compound-loop.log").is_file()
    assert not decoy_dir.exists()


def test_worker_falls_back_to_claude_code_on_unknown_agent_type(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An unknown agent.type in config.toml must not kill the worker: it falls
    back to the claude-code adapter and keeps draining the queue."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    claude_dir = tmp_path / "claude"
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(claude_dir))

    store = tmp_path / "store"
    store.mkdir()
    (store / "knowledge.toml").write_text(
        '[knowledge]\nversion = 1\nsessions = "sessions"\nlearnings = "learnings"\n'
    )
    monkeypatch.setenv("LAZY_KNOWLEDGE_ROOT", str(store))

    cfg_file = tmp_path / "config.toml"
    cfg_file.write_text(
        """
[harness]
version = "1"

[agent]
type = "no-such-agent"

[compound_loop]
enabled = true
"""
    )
    from lazy_harness.knowledge import compound_loop_worker as worker_mod

    monkeypatch.setattr(worker_mod, "config_file", lambda: cfg_file)

    rc = worker_mod.main()

    assert rc == 0
    assert (claude_dir / "queue" / "done").is_dir()
    assert (claude_dir / "logs" / "compound-loop.log").is_file()


def test_worker_passes_the_full_config_to_process_task(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ADR-039: the worker no longer pre-resolves a backend — it threads the
    loaded Config straight into process_task, which resolves a role lazily
    per task via run_inference."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))

    store = tmp_path / "store"
    store.mkdir()
    (store / "knowledge.toml").write_text(
        '[knowledge]\nversion = 1\nsessions = "sessions"\nlearnings = "learnings"\n'
    )
    monkeypatch.setenv("LAZY_KNOWLEDGE_ROOT", str(store))

    cfg_file = tmp_path / "config.toml"
    cfg_file.write_text(
        """
[harness]
version = "1"

[agent]
type = "null"

[compound_loop]
enabled = true
backend = "ollama"
"""
    )
    queue_dir = home / ".null" / "queue"
    queue_dir.mkdir(parents=True)
    (queue_dir / "t.task").write_text("session_id=abc\n")

    from lazy_harness.knowledge import compound_loop_worker as worker_mod
    from lazy_harness.knowledge.compound_loop import TaskOutcome

    monkeypatch.setattr(worker_mod, "config_file", lambda: cfg_file)

    captured: dict = {}

    def fake_process_task(task_file, cfg, learnings_dir):  # noqa: ANN001
        captured["cfg"] = cfg
        return TaskOutcome(skipped="stubbed")

    monkeypatch.setattr(worker_mod, "process_task", fake_process_task)

    rc = worker_mod.main()

    assert rc == 0
    assert captured["cfg"].compound_loop.backend == "ollama"


def test_worker_logs_and_exits_zero_when_role_cannot_resolve(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """run_inference never raises: a misconfigured backend must surface as a
    per-task skip logged by the drain loop, not crash the worker."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))

    store = tmp_path / "store"
    store.mkdir()
    (store / "knowledge.toml").write_text(
        '[knowledge]\nversion = 1\nsessions = "sessions"\nlearnings = "learnings"\n'
    )
    monkeypatch.setenv("LAZY_KNOWLEDGE_ROOT", str(store))

    cfg_file = tmp_path / "config.toml"
    cfg_file.write_text(
        """
[harness]
version = "1"

[agent]
type = "null"

[compound_loop]
enabled = true
backend = "no-such-backend"
"""
    )
    session = tmp_path / "sess.jsonl"
    session.write_text(
        "\n".join(
            json.dumps(r)
            for r in [
                {"type": "permission-mode"},
                {"type": "user", "message": {"content": "a" * 250}},
                {"type": "assistant", "message": {"content": "ok"}},
                {"type": "user", "message": {"content": "next step please"}},
                {"type": "assistant", "message": {"content": "done"}},
            ]
        )
        + "\n"
    )
    queue_dir = home / ".null" / "queue"
    queue_dir.mkdir(parents=True)
    (queue_dir / "t.task").write_text(
        f"cwd=/tmp/proj\nsession_jsonl={session}\nsession_id=abcd1234\n"
        f"memory_dir={tmp_path / 'memory'}\ntimestamp=2026-09-09T10:00:00-03:00\n"
    )

    from lazy_harness.knowledge import compound_loop_worker as worker_mod

    monkeypatch.setattr(worker_mod, "config_file", lambda: cfg_file)

    rc = worker_mod.main()

    assert rc == 0
    log = (home / ".null" / "logs" / "compound-loop.log").read_text()
    assert "skipped" in log
    assert (queue_dir / "done" / "t.task").is_file()


def test_resolve_learnings_dir_uses_marker(tmp_path: Path, monkeypatch) -> None:
    from lazy_harness.core.config import Config
    from lazy_harness.knowledge.compound_loop_worker import _resolve_learnings_dir

    monkeypatch.delenv("LAZY_KNOWLEDGE_ROOT", raising=False)
    store = tmp_path / "store"
    store.mkdir()
    (store / "knowledge.toml").write_text(
        '[knowledge]\nversion = 1\nsessions = "sessions"\nlearnings = "lessons"\n',
        encoding="utf-8",
    )
    cfg = Config()
    cfg.knowledge.root = str(store)
    assert _resolve_learnings_dir(cfg) == store / "lessons"


def test_resolve_learnings_dir_ignores_removed_lct_env(tmp_path: Path, monkeypatch) -> None:
    from lazy_harness.core.config import Config
    from lazy_harness.knowledge.compound_loop_worker import _resolve_learnings_dir

    monkeypatch.delenv("LAZY_KNOWLEDGE_ROOT", raising=False)
    monkeypatch.setenv("LCT_LEARNINGS_DIR", str(tmp_path / "old-vault"))
    store = tmp_path / "store"
    store.mkdir()
    (store / "knowledge.toml").write_text(
        '[knowledge]\nversion = 1\nsessions = "sessions"\nlearnings = "learnings"\n',
        encoding="utf-8",
    )
    cfg = Config()
    cfg.knowledge.root = str(store)
    assert _resolve_learnings_dir(cfg) == store / "learnings"


def test_worker_exits_cleanly_when_the_store_has_no_marker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A missing marker is a misconfiguration, not a crash. The queue survives."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv("LAZY_KNOWLEDGE_ROOT", raising=False)

    cfg_file = tmp_path / "config.toml"
    cfg_file.write_text(
        """
[harness]
version = "1"

[agent]
type = "null"

[compound_loop]
enabled = true
"""
    )
    from lazy_harness.knowledge import compound_loop_worker as worker_mod

    monkeypatch.setattr(worker_mod, "config_file", lambda: cfg_file)

    assert worker_mod.main() == 1
    log = (home / ".null" / "logs" / "compound-loop.log").read_text()
    assert "knowledge.toml" in log

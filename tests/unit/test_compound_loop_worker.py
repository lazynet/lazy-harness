"""Tests for the compound-loop worker entrypoint."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

import pytest


def test_done_retention_prunes_only_tasks_older_than_seven_days(tmp_path: Path) -> None:
    from lazy_harness.knowledge.compound_loop import move_to_done
    from lazy_harness.knowledge.compound_loop_worker import _prune_done

    queue_dir = tmp_path / "queue"
    queue_dir.mkdir()
    old_task = queue_dir / "old.task"
    fresh_task = queue_dir / "fresh.task"
    old_task.write_text("session_id=old\n")
    fresh_task.write_text("session_id=fresh\n")
    move_to_done(queue_dir, old_task)
    move_to_done(queue_dir, fresh_task)

    now = time.time()
    eight_days_ago = now - 8 * 24 * 60 * 60
    os.utime(queue_dir / "done" / old_task.name, (eight_days_ago, eight_days_ago))

    assert _prune_done(queue_dir, now=now) == 1
    assert not (queue_dir / "done" / old_task.name).exists()
    assert (queue_dir / "done" / fresh_task.name).is_file()


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
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, expects_deprecated_compound_loop: None
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


def _profile_config(tmp_path: Path) -> Path:
    cfg_file = tmp_path / "config.toml"
    cfg_file.write_text(
        f"""
[harness]
version = "1"

[agent]
type = "claude-code"

[profiles]
default = "alpha"

[profiles.alpha]
config_dir = "{tmp_path / "alpha-home"}"

[compound_loop]
enabled = true
"""
    )
    return cfg_file


def test_the_worker_drains_the_queue_the_producer_writes_to(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The two paths that answer "where is the queue", asserted to agree.

    Every migrated builtin names its directory with `agent_dir_for(cfg,
    event.profile)`. The worker named its own, globally, and nothing compared
    them -- so the producer could move to the profile's directory while the
    consumer kept draining the global one, and every queued task would be
    orphaned with both processes exiting 0. Measured on a real config before
    this test existed: producer `~/.claude-lazy/queue`, worker `~/.claude/queue`.

    `CLAUDE_CONFIG_DIR` is cleared because it outranks the profile's
    `config_dir` (`core/paths.py:150-160`) and pinning it would make both sides
    agree for the wrong reason.
    """
    from lazy_harness.core.config import load_config
    from lazy_harness.hooks.builtins._shared import agent_dir_for
    from lazy_harness.knowledge import compound_loop_worker

    monkeypatch.delenv("CLAUDE_CONFIG_DIR", raising=False)
    cfg_file = _profile_config(tmp_path)
    cfg = load_config(cfg_file)

    producer_agent, producer_dir = agent_dir_for(cfg, "alpha")
    worker_agent, worker_dir = compound_loop_worker._agent_dir_for_profile(cfg, "alpha")

    # Each side names the subdirectory with its *own* adapter, so the comparison
    # covers the directory and the name inside it. Taking one side's subdir for
    # both would agree even when the two adapters differ.
    producer_queue = producer_dir / (producer_agent.session_dirs().get("queue") or "queue")
    worker_queue = worker_dir / (worker_agent.session_dirs().get("queue") or "queue")

    assert worker_queue == producer_queue


def test_the_worker_without_a_profile_resolves_where_it_always_did(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The fallback for a producer that names no profile.

    An empty profile is "nobody said", and `agent_runtime_dir` resolves it
    globally. A worker that resolved per profile regardless would break the
    pair in the other direction, draining a directory nothing writes to.
    """
    from lazy_harness.agents.registry import get_agent
    from lazy_harness.core.config import load_config
    from lazy_harness.core.paths import agent_runtime_dir
    from lazy_harness.knowledge import compound_loop_worker

    monkeypatch.delenv("CLAUDE_CONFIG_DIR", raising=False)
    cfg = load_config(_profile_config(tmp_path))

    assert compound_loop_worker._agent_dir_for_profile(cfg, "")[1] == agent_runtime_dir(
        get_agent("claude-code")
    )


def test_the_worker_names_its_queue_with_the_profiles_own_adapter(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The defect (design step 6): `main` resolved the directory per profile and
    the *subdirectory names inside it* globally.

    `session_dirs()` is the adapter's answer, so a profile running an agent that
    names its queue something other than `queue/` had the producer writing to
    `<profile dir>/<its agent's name>` while the worker created and drained
    `<profile dir>/queue`. Both exit 0 and every queued task is orphaned —
    the same pair `_agent_dir_for_profile` was added to keep together, broken
    one level further down the path.
    """
    from lazy_harness.agents import registry
    from lazy_harness.core.config import load_config
    from lazy_harness.hooks.builtins._shared import agent_dir_for
    from lazy_harness.knowledge import compound_loop_worker

    class _OtherAdapter(registry.NullAdapter):
        @property
        def name(self) -> str:
            return "other"

        def env_var(self) -> str:
            return "OTHER_CONFIG_DIR"

        def session_dirs(self) -> dict[str, str]:
            return {"sessions": "threads", "logs": "journal", "queue": "outbox"}

    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setitem(registry._AGENTS, "other", _OtherAdapter)
    monkeypatch.delenv("CLAUDE_CONFIG_DIR", raising=False)
    monkeypatch.delenv("OTHER_CONFIG_DIR", raising=False)

    profile_home = tmp_path / "alpha-home"
    cfg_file = tmp_path / "config.toml"
    cfg_file.write_text(
        '[harness]\nversion = "1"\n\n[agent]\ntype = "claude-code"\n\n'
        '[profiles]\ndefault = "alpha"\n\n'
        f'[profiles.alpha]\nconfig_dir = "{profile_home}"\nagent = "other"\n'
    )
    # Bound into the worker's own namespace by `from ... import config_file`,
    # so patching `core.paths` leaves the worker reading the real config.
    monkeypatch.setattr(compound_loop_worker, "config_file", lambda: cfg_file)

    cfg = load_config(cfg_file)
    producer_agent, producer_dir = agent_dir_for(cfg, "alpha")
    producer_queue = producer_dir / (producer_agent.session_dirs().get("queue") or "queue")

    compound_loop_worker.main(["--profile", "alpha"])

    assert producer_queue.is_dir(), (
        "the worker did not create the queue the producer writes to; it created "
        f"{sorted(p.name for p in profile_home.iterdir()) if profile_home.is_dir() else []}"
    )


def test_worker_logs_every_named_refusal(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """ADR-062: a declined PRJ write is logged with its reason, next to what
    the task did persist — a silent no-op is indistinguishable from a bug."""
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
        '[harness]\nversion = "1"\n\n[agent]\ntype = "null"\n\n[compound_loop]\nenabled = true\n'
    )
    queue_dir = home / ".null" / "queue"
    queue_dir.mkdir(parents=True)
    (queue_dir / "t.task").write_text("session_id=abc\n")

    from lazy_harness.knowledge import compound_loop_worker as worker_mod
    from lazy_harness.knowledge.compound_loop import TaskOutcome

    monkeypatch.setattr(worker_mod, "config_file", lambda: cfg_file)
    monkeypatch.setattr(
        worker_mod,
        "process_task",
        lambda *a: TaskOutcome(
            wrote=["decisions: 1"], notes=["project_update skipped: no PRJ matches 'x'"]
        ),
    )

    assert worker_mod.main() == 0
    log = (home / ".null" / "logs" / "compound-loop.log").read_text()
    assert "wrote: decisions: 1" in log
    assert "note: project_update skipped: no PRJ matches 'x'" in log

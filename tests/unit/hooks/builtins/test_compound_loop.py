"""Unit tests for the compound_loop Stop hook."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from lazy_harness.agents.base import HookDecision, HookEvent

# Project dir name as the agent encodes it: the space and the `~` in the real
# cwd both collapse to `-`, which a naive `str(cwd).replace("/", "-")` misses.
AGENT_PROJECT_DIR = "-tmp-Mobile-Documents-iCloud-md-obsidian-LazyMind"


def _event(*, cwd: Path, transcript: Path | None = None, profile: str = "") -> HookEvent:
    """A Stop event as the adapter hands it over."""
    return HookEvent(
        event="session_stop",
        profile=profile,
        session_id="0197f0de-cafe-4bad-9001-000000000001",
        cwd=cwd,
        transcript_path=transcript,
    )


@pytest.fixture
def harness(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Path]:
    """A configured harness whose cwd does not round-trip through the naive encoder."""
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "config.toml").write_text(
        "[harness]\nversion = 1\n"
        '[agent]\ntype = "claude-code"\n'
        "[compound_loop]\nenabled = true\ndebounce_seconds = 0\n"
    )
    monkeypatch.setenv("LH_CONFIG_DIR", str(config_dir))

    agent_dir = tmp_path / "agent"
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(agent_dir))

    project_dir = agent_dir / "projects" / AGENT_PROJECT_DIR
    project_dir.mkdir(parents=True)
    transcript = project_dir / "0197f0de-cafe-4bad-9001-000000000001.jsonl"
    transcript.write_text('{"type":"user"}\n')

    # Real cwd contains a space and a `~` — the characters the agent rewrites.
    cwd = tmp_path / "Mobile Documents" / "iCloud~md~obsidian" / "LazyMind"
    cwd.mkdir(parents=True)
    monkeypatch.chdir(cwd)

    return {"transcript": transcript, "project_dir": project_dir, "cwd": cwd}


def test_queues_task_for_transcript_declared_in_payload(
    harness: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The agent tells us the transcript path; recomputing it from cwd loses sessions."""
    from lazy_harness.hooks.builtins import compound_loop as mod
    from lazy_harness.knowledge import compound_loop as knowledge

    fake_create_task = MagicMock(return_value=Path("task-1.task"))
    monkeypatch.setattr(knowledge, "create_task", fake_create_task)
    monkeypatch.setattr(mod.subprocess, "Popen", MagicMock())

    decision = mod.main(_event(cwd=harness["cwd"], transcript=harness["transcript"]))

    assert decision == HookDecision()
    fake_create_task.assert_called_once()
    kwargs = fake_create_task.call_args.kwargs
    assert kwargs["session_jsonl"] == harness["transcript"]
    assert kwargs["memory_dir"] == harness["project_dir"] / "memory"


def test_skips_agent_without_session_directory(
    harness: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    from lazy_harness.hooks.builtins import _shared
    from lazy_harness.hooks.builtins import compound_loop as mod
    from lazy_harness.knowledge import compound_loop as knowledge

    class NoSessionsAgent:
        pass

    create_task = MagicMock()
    monkeypatch.setattr(
        _shared,
        "agent_dir_for",
        lambda *_: (NoSessionsAgent(), harness["project_dir"].parent.parent),
    )
    monkeypatch.setattr(knowledge, "create_task", create_task)

    assert mod.main(_event(cwd=harness["cwd"])) == HookDecision()
    create_task.assert_not_called()


def test_falls_back_to_newest_session_when_payload_has_no_transcript(
    harness: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Agents that omit the transcript still work through the cwd-derived lookup."""
    from lazy_harness.hooks.builtins import compound_loop as mod
    from lazy_harness.knowledge import compound_loop as knowledge

    # Stage a session under the dir the naive encoder computes for this cwd.
    encoded = "-" + str(harness["cwd"]).replace("/", "-").lstrip("-")
    legacy_dir = harness["project_dir"].parent / encoded
    legacy_dir.mkdir(parents=True)
    legacy_transcript = legacy_dir / "0197f0de-cafe-4bad-9001-000000000002.jsonl"
    legacy_transcript.write_text('{"type":"user"}\n')

    fake_create_task = MagicMock(return_value=Path("task-2.task"))
    monkeypatch.setattr(knowledge, "create_task", fake_create_task)
    monkeypatch.setattr(mod.subprocess, "Popen", MagicMock())

    mod.main(_event(cwd=harness["cwd"]))

    fake_create_task.assert_called_once()
    assert fake_create_task.call_args.kwargs["session_jsonl"] == legacy_transcript


def test_an_empty_event_cwd_falls_back_to_the_process_directory(
    harness: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A payload naming no cwd parses as `Path("")`, which is `Path(".")`.

    This hook is the one that cannot survive that: unlike its siblings it
    derives the agent's project directory itself (`"-" + str(cwd).replace(...)`)
    rather than through `project_key`, which resolves a relative path back to
    the real one. `Path(".")` encodes to `-.`, so every session on the machine
    would look for its transcript in one shared directory that holds none, and
    the hook would silently stop queueing anything at all.

    Asserted through the queued task rather than through a log line: the
    failure is a lookup that finds nothing, and a hook that found nothing still
    exits 0 and still writes a log.
    """
    from lazy_harness.hooks.builtins import compound_loop as mod
    from lazy_harness.knowledge import compound_loop as knowledge

    encoded = "-" + str(harness["cwd"]).replace("/", "-").lstrip("-")
    legacy_dir = harness["project_dir"].parent / encoded
    legacy_dir.mkdir(parents=True)
    legacy_transcript = legacy_dir / "0197f0de-cafe-4bad-9001-000000000003.jsonl"
    legacy_transcript.write_text('{"type":"user"}\n')

    fake_create_task = MagicMock(return_value=Path("task-3.task"))
    monkeypatch.setattr(knowledge, "create_task", fake_create_task)
    monkeypatch.setattr(mod.subprocess, "Popen", MagicMock())

    mod.main(_event(cwd=Path("")))

    fake_create_task.assert_called_once()
    kwargs = fake_create_task.call_args.kwargs
    assert kwargs["session_jsonl"] == legacy_transcript
    assert kwargs["cwd"] == harness["cwd"], "the task must name the real project, not '.'"


def test_memory_dir_points_at_the_main_repo_when_running_in_a_worktree(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Distilled memory survives the worktree it was learned in."""
    import subprocess as sp

    from lazy_harness.hooks.builtins import compound_loop as mod
    from lazy_harness.knowledge import compound_loop as knowledge

    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "config.toml").write_text(
        "[harness]\nversion = 1\n"
        '[agent]\ntype = "claude-code"\n'
        "[compound_loop]\nenabled = true\ndebounce_seconds = 0\n"
    )
    monkeypatch.setenv("LH_CONFIG_DIR", str(config_dir))
    agent_dir = tmp_path / "agent"
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(agent_dir))

    repo = tmp_path / "repo"
    repo.mkdir()
    base = ["git", "-c", "user.email=t@t", "-c", "user.name=t"]
    sp.run([*base, "init", "-q"], cwd=repo, check=True, capture_output=True)
    sp.run(
        [*base, "commit", "-q", "--allow-empty", "-m", "i"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    worktree = repo / ".worktrees" / "feat"
    sp.run(
        [*base, "worktree", "add", "-q", str(worktree), "-b", "feat"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    monkeypatch.chdir(worktree)

    wt_project = agent_dir / "projects" / ("-" + str(worktree).replace("/", "-").lstrip("-"))
    wt_project.mkdir(parents=True)
    transcript = wt_project / "0197f0de-cafe-4bad-9001-000000000002.jsonl"
    transcript.write_text('{"type":"user"}\n')

    fake_create_task = MagicMock(return_value=Path("task-1.task"))
    monkeypatch.setattr(knowledge, "create_task", fake_create_task)
    monkeypatch.setattr(mod.subprocess, "Popen", MagicMock())

    mod.main(_event(cwd=worktree, transcript=transcript))

    kwargs = fake_create_task.call_args.kwargs
    assert kwargs["session_jsonl"] == transcript, "sessions still belong to the worktree"
    expected = agent_dir / "projects" / ("-" + str(repo.resolve()).replace("/", "-").lstrip("-"))
    assert kwargs["memory_dir"] == expected / "memory"


def test_a_transcript_the_payload_names_but_disk_does_not_have_is_not_used(
    harness: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    """`transcript_path` is what the payload claimed, not what exists.

    The pre-runner helper stat'd it as part of reading the payload; without the
    explicit check the hook would queue a task naming a file the worker cannot
    open, and the cwd-derived fallback below it would never be reached.
    """
    from lazy_harness.hooks.builtins import compound_loop as mod
    from lazy_harness.knowledge import compound_loop as knowledge

    fake_create_task = MagicMock(return_value=Path("task-4.task"))
    monkeypatch.setattr(knowledge, "create_task", fake_create_task)
    monkeypatch.setattr(mod.subprocess, "Popen", MagicMock())

    decision = mod.main(
        _event(cwd=harness["cwd"], transcript=harness["cwd"] / "not-written-yet.jsonl")
    )

    assert decision == HookDecision()
    fake_create_task.assert_not_called()


def test_the_worker_is_spawned_with_the_profile_that_queued_the_task(
    harness: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The hook queues under `event.profile`; the worker must drain there.

    `compound_loop_worker._agent_dir_for_profile` resolves per profile only
    when one is named on its argv, and falls back to the global directory
    otherwise. Spawning it bare therefore sends it to a queue this hook no
    longer writes to -- both processes exit 0 and every queued task is
    orphaned. Measured on the real config before this assertion existed:
    producer `~/.claude-lazy/queue`, worker `~/.claude/queue`.
    """
    from lazy_harness.hooks.builtins import compound_loop as mod
    from lazy_harness.knowledge import compound_loop as knowledge

    monkeypatch.setattr(knowledge, "create_task", MagicMock(return_value=Path("t.task")))
    popen = MagicMock()
    monkeypatch.setattr(mod.subprocess, "Popen", popen)

    mod.main(_event(cwd=harness["cwd"], transcript=harness["transcript"], profile="alpha"))

    assert popen.called, "the worker was never spawned"
    argv = popen.call_args[0][0]
    assert "--profile" in argv, argv
    assert argv[argv.index("--profile") + 1] == "alpha", argv

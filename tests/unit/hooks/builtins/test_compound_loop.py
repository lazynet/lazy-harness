"""Unit tests for the compound_loop Stop hook."""

from __future__ import annotations

import io
import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

# Project dir name as the agent encodes it: the space and the `~` in the real
# cwd both collapse to `-`, which a naive `str(cwd).replace("/", "-")` misses.
AGENT_PROJECT_DIR = "-tmp-Mobile-Documents-iCloud-md-obsidian-LazyMind"


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
    monkeypatch.setattr(
        "sys.stdin",
        io.StringIO(json.dumps({"transcript_path": str(harness["transcript"])})),
    )

    mod.main()

    fake_create_task.assert_called_once()
    kwargs = fake_create_task.call_args.kwargs
    assert kwargs["session_jsonl"] == harness["transcript"]
    assert kwargs["memory_dir"] == harness["project_dir"] / "memory"


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
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps({"session_id": "abc"})))

    mod.main()

    fake_create_task.assert_called_once()
    assert fake_create_task.call_args.kwargs["session_jsonl"] == legacy_transcript

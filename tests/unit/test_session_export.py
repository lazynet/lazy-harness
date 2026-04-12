"""Tests for session JSONL → markdown export."""

from __future__ import annotations

import json
from pathlib import Path


def _write_session(path: Path, messages: list[dict]) -> None:
    with open(path, "w") as f:
        for msg in messages:
            f.write(json.dumps(msg) + "\n")


def test_export_session_to_markdown(tmp_path: Path) -> None:
    from lazy_harness.knowledge.session_export import export_session

    session_file = tmp_path / "abc12345.jsonl"
    _write_session(
        session_file,
        [
            {"type": "permission-mode", "timestamp": "2026-04-12T10:00:00-03:00"},
            {
                "type": "system",
                "cwd": "/home/user/project",
                "version": "1.0",
                "gitBranch": "main",
                "timestamp": "2026-04-12T10:00:00-03:00",
            },
            {
                "type": "user",
                "message": {"content": "Hello, help me with this"},
                "timestamp": "2026-04-12T10:00:01-03:00",
            },
            {
                "type": "assistant",
                "message": {"content": "Sure, I can help"},
                "timestamp": "2026-04-12T10:00:02-03:00",
            },
            {
                "type": "user",
                "message": {"content": "Thanks for that"},
                "timestamp": "2026-04-12T10:00:03-03:00",
            },
            {
                "type": "assistant",
                "message": {"content": "You're welcome"},
                "timestamp": "2026-04-12T10:00:04-03:00",
            },
        ],
    )
    output_dir = tmp_path / "export"
    output_dir.mkdir()
    result = export_session(session_file, output_dir)
    assert result is not None
    assert result.is_file()
    content = result.read_text()
    assert "---" in content
    assert "Hello, help me with this" in content


def test_export_session_skips_short(tmp_path: Path) -> None:
    from lazy_harness.knowledge.session_export import export_session

    session_file = tmp_path / "short.jsonl"
    _write_session(
        session_file,
        [
            {"type": "permission-mode", "timestamp": "2026-04-12T10:00:00"},
            {"type": "user", "message": {"content": "hi"}, "timestamp": "2026-04-12T10:00:01"},
        ],
    )
    output_dir = tmp_path / "export"
    output_dir.mkdir()
    result = export_session(session_file, output_dir)
    assert result is None


def test_export_session_skips_non_interactive(tmp_path: Path) -> None:
    from lazy_harness.knowledge.session_export import export_session

    session_file = tmp_path / "batch.jsonl"
    _write_session(
        session_file,
        [
            {"type": "system", "cwd": "/tmp", "timestamp": "2026-04-12T10:00:00"},
            {
                "type": "user",
                "message": {"content": "do something"},
                "timestamp": "2026-04-12T10:00:01",
            },
            {
                "type": "assistant",
                "message": {"content": "done"},
                "timestamp": "2026-04-12T10:00:02",
            },
            {"type": "user", "message": {"content": "more"}, "timestamp": "2026-04-12T10:00:03"},
            {"type": "assistant", "message": {"content": "ok"}, "timestamp": "2026-04-12T10:00:04"},
        ],
    )
    output_dir = tmp_path / "export"
    output_dir.mkdir()
    result = export_session(session_file, output_dir)
    assert result is None


def test_export_handles_content_blocks(tmp_path: Path) -> None:
    from lazy_harness.knowledge.session_export import export_session

    session_file = tmp_path / "blocks.jsonl"
    _write_session(
        session_file,
        [
            {"type": "permission-mode", "timestamp": "2026-04-12T10:00:00"},
            {"type": "system", "cwd": "/tmp/proj", "timestamp": "2026-04-12T10:00:00"},
            {
                "type": "user",
                "message": {"content": "first question"},
                "timestamp": "2026-04-12T10:00:01",
            },
            {
                "type": "assistant",
                "message": {"content": [{"type": "text", "text": "answer one"}]},
                "timestamp": "2026-04-12T10:00:02",
            },
            {
                "type": "user",
                "message": {"content": "second question"},
                "timestamp": "2026-04-12T10:00:03",
            },
            {
                "type": "assistant",
                "message": {"content": [{"type": "text", "text": "answer two"}]},
                "timestamp": "2026-04-12T10:00:04",
            },
        ],
    )
    output_dir = tmp_path / "export"
    output_dir.mkdir()
    result = export_session(session_file, output_dir)
    assert result is not None
    content = result.read_text()
    assert "answer one" in content
    assert "answer two" in content

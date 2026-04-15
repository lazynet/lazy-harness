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
    result, reason = export_session(session_file, output_dir)
    assert reason is None
    assert result is not None
    assert result.is_file()
    content = result.read_text()
    assert "---" in content
    assert "Hello, help me with this" in content


def test_export_session_reports_skip_reason(tmp_path: Path) -> None:
    # The hook needs to distinguish short vs unchanged vs non-interactive
    # skips in its log output. export_session returns (path, reason).
    from lazy_harness.knowledge.session_export import export_session

    short_file = tmp_path / "short.jsonl"
    _write_session(
        short_file,
        [
            {"type": "permission-mode", "timestamp": "2026-04-12T10:00:00"},
            {"type": "user", "message": {"content": "hi"}, "timestamp": "2026-04-12T10:00:01"},
        ],
    )
    non_interactive = tmp_path / "batch.jsonl"
    _write_session(
        non_interactive,
        [
            {"type": "system", "cwd": "/tmp", "timestamp": "2026-04-12T10:00:00"},
            {"type": "user", "message": {"content": "a"}, "timestamp": "2026-04-12T10:00:01"},
            {"type": "assistant", "message": {"content": "b"}, "timestamp": "2026-04-12T10:00:02"},
            {"type": "user", "message": {"content": "c"}, "timestamp": "2026-04-12T10:00:03"},
            {"type": "assistant", "message": {"content": "d"}, "timestamp": "2026-04-12T10:00:04"},
        ],
    )
    output_dir = tmp_path / "export"
    output_dir.mkdir()

    short_path, short_reason = export_session(short_file, output_dir)
    assert short_path is None
    assert short_reason == "short"

    ni_path, ni_reason = export_session(non_interactive, output_dir)
    assert ni_path is None
    assert ni_reason == "non-interactive"


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
    result, reason = export_session(session_file, output_dir)
    assert result is None
    assert reason == "short"


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
    result, reason = export_session(session_file, output_dir)
    assert result is None
    assert reason == "non-interactive"


def test_export_adds_profile_and_session_type(tmp_path: Path) -> None:
    from lazy_harness.knowledge.session_export import export_session

    session_file = tmp_path / "abc12345.jsonl"
    _write_session(
        session_file,
        [
            {"type": "permission-mode", "timestamp": "2026-04-12T10:00:00-03:00"},
            {
                "type": "system",
                "cwd": "/Users/lazynet/repos/lazy/lazy-claudecode",
                "timestamp": "2026-04-12T10:00:00-03:00",
            },
            {"type": "user", "message": {"content": "hi"}, "timestamp": "2026-04-12T10:00:01-03:00"},
            {"type": "assistant", "message": {"content": "ok"}, "timestamp": "2026-04-12T10:00:02-03:00"},
            {"type": "user", "message": {"content": "next"}, "timestamp": "2026-04-12T10:00:03-03:00"},
            {"type": "assistant", "message": {"content": "done"}, "timestamp": "2026-04-12T10:00:04-03:00"},
        ],
    )
    output_dir = tmp_path / "export"
    output_dir.mkdir()
    result, reason = export_session(session_file, output_dir)
    assert reason is None
    assert result is not None
    content = result.read_text()
    assert "profile: personal" in content
    assert "session_type: personal" in content


def test_export_classifies_flex_as_work(tmp_path: Path) -> None:
    from lazy_harness.knowledge.session_export import export_session

    session_file = tmp_path / "xyz.jsonl"
    _write_session(
        session_file,
        [
            {"type": "permission-mode", "timestamp": "2026-04-12T10:00:00-03:00"},
            {"type": "system", "cwd": "/Users/lazynet/repos/flex/ydi-mgmt", "timestamp": "2026-04-12T10:00:00-03:00"},
            {"type": "user", "message": {"content": "hi"}, "timestamp": "2026-04-12T10:00:01-03:00"},
            {"type": "assistant", "message": {"content": "ok"}, "timestamp": "2026-04-12T10:00:02-03:00"},
            {"type": "user", "message": {"content": "next"}, "timestamp": "2026-04-12T10:00:03-03:00"},
            {"type": "assistant", "message": {"content": "done"}, "timestamp": "2026-04-12T10:00:04-03:00"},
        ],
    )
    output_dir = tmp_path / "export"
    output_dir.mkdir()
    result, reason = export_session(session_file, output_dir)
    assert reason is None
    assert result is not None
    content = result.read_text()
    assert "profile: work" in content
    assert "session_type: work" in content


def test_export_falls_back_to_decoded_project_dir(tmp_path: Path, monkeypatch) -> None:
    # When meta has no cwd, session_file.parent.name should be decoded.
    from lazy_harness.knowledge import session_export as se

    # Simulate the encoded project dir as parent
    encoded_parent = tmp_path / "-tmp-some-fake-repo"
    encoded_parent.mkdir()
    session_file = encoded_parent / "sess1.jsonl"
    _write_session(
        session_file,
        [
            {"type": "permission-mode", "timestamp": "2026-04-12T10:00:00"},
            # No system record → no cwd
            {"type": "user", "message": {"content": "a"}, "timestamp": "2026-04-12T10:00:01"},
            {"type": "assistant", "message": {"content": "b"}, "timestamp": "2026-04-12T10:00:02"},
            {"type": "user", "message": {"content": "c"}, "timestamp": "2026-04-12T10:00:03"},
            {"type": "assistant", "message": {"content": "d"}, "timestamp": "2026-04-12T10:00:04"},
        ],
    )
    output_dir = tmp_path / "export"
    output_dir.mkdir()
    result, reason = se.export_session(session_file, output_dir)
    assert reason is None
    assert result is not None
    content = result.read_text()
    # The decoded path won't exist, so _decode_project_dir falls back to naive
    assert "cwd: /tmp/some/fake/repo" in content


def test_export_accepts_last_prompt_as_interactive_marker(tmp_path: Path) -> None:
    # Regression: session c94df89e had 40 user + 52 assistant messages and a
    # `last-prompt` record but no `permission-mode`, so the old heuristic
    # wrongly classified it as non-interactive and skipped the export.
    from lazy_harness.knowledge.session_export import export_session

    session_file = tmp_path / "c94df89e.jsonl"
    _write_session(
        session_file,
        [
            {
                "type": "system",
                "cwd": "/tmp/proj",
                "timestamp": "2026-04-15T17:00:00-03:00",
            },
            {"type": "last-prompt", "timestamp": "2026-04-15T17:00:00-03:00"},
            {
                "type": "user",
                "message": {"content": "real question"},
                "timestamp": "2026-04-15T17:00:01-03:00",
            },
            {
                "type": "assistant",
                "message": {"content": "real answer"},
                "timestamp": "2026-04-15T17:00:02-03:00",
            },
            {
                "type": "user",
                "message": {"content": "follow up"},
                "timestamp": "2026-04-15T17:00:03-03:00",
            },
            {
                "type": "assistant",
                "message": {"content": "follow up answer"},
                "timestamp": "2026-04-15T17:00:04-03:00",
            },
        ],
    )
    output_dir = tmp_path / "export"
    output_dir.mkdir()
    result, reason = export_session(session_file, output_dir)
    assert reason is None
    assert result is not None
    assert result.is_file()
    assert "real question" in result.read_text()


def test_export_session_force_bypasses_non_interactive(tmp_path: Path) -> None:
    # `force=True` is the CLI escape hatch: export even when the heuristic
    # would classify the session as non-interactive, and ignore the unchanged
    # guard. It still rejects genuinely empty sessions (min_messages=1).
    from lazy_harness.knowledge.session_export import export_session

    session_file = tmp_path / "batch.jsonl"
    _write_session(
        session_file,
        [
            {"type": "system", "cwd": "/tmp/proj", "timestamp": "2026-04-15T17:00:00"},
            {"type": "user", "message": {"content": "q1"}, "timestamp": "2026-04-15T17:00:01"},
            {"type": "assistant", "message": {"content": "a1"}, "timestamp": "2026-04-15T17:00:02"},
            {"type": "user", "message": {"content": "q2"}, "timestamp": "2026-04-15T17:00:03"},
            {"type": "assistant", "message": {"content": "a2"}, "timestamp": "2026-04-15T17:00:04"},
        ],
    )
    output_dir = tmp_path / "export"
    output_dir.mkdir()

    # Without force: skipped as non-interactive.
    result, reason = export_session(session_file, output_dir)
    assert result is None
    assert reason == "non-interactive"

    # With force: exported.
    result, reason = export_session(session_file, output_dir, force=True)
    assert reason is None
    assert result is not None
    assert result.is_file()

    # Re-running with force still re-exports (unchanged guard bypassed).
    result2, reason2 = export_session(session_file, output_dir, force=True)
    assert reason2 is None
    assert result2 is not None


def test_export_session_force_rejects_empty(tmp_path: Path) -> None:
    from lazy_harness.knowledge.session_export import export_session

    session_file = tmp_path / "empty.jsonl"
    session_file.write_text("")
    output_dir = tmp_path / "export"
    output_dir.mkdir()
    result, reason = export_session(session_file, output_dir, force=True)
    assert result is None
    assert reason == "short"


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
    result, reason = export_session(session_file, output_dir)
    assert reason is None
    assert result is not None
    content = result.read_text()
    assert "answer one" in content
    assert "answer two" in content

"""Unit tests for pre_tool_use_memory_size hook (ADR-030 G2)."""

from __future__ import annotations

import io
import json
from pathlib import Path

import pytest


def test_main_exits_zero_for_non_edit_write_tool(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from lazy_harness.hooks.builtins import pre_tool_use_memory_size as mod

    monkeypatch.setattr("sys.stdin", io.StringIO('{"tool_name": "Bash", "tool_input": {}}'))
    with pytest.raises(SystemExit) as exc_info:
        mod.main()
    assert exc_info.value.code == 0


def test_main_silent_for_non_memory_md_path(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from lazy_harness.hooks.builtins import pre_tool_use_memory_size as mod

    payload = {
        "tool_name": "Write",
        "tool_input": {
            "file_path": "/tmp/some-other.md",
            "content": "x\n" * 500,
        },
    }
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(payload)))
    with pytest.raises(SystemExit) as exc_info:
        mod.main()
    assert exc_info.value.code == 0
    assert capsys.readouterr().out == ""


def test_main_warns_when_write_pushes_memory_md_over_threshold(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from lazy_harness.hooks.builtins import pre_tool_use_memory_size as mod

    payload = {
        "tool_name": "Write",
        "tool_input": {
            "file_path": "/home/user/.claude/projects/foo/memory/MEMORY.md",
            "content": "line\n" * 250,
        },
    }
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(payload)))
    with pytest.raises(SystemExit) as exc_info:
        mod.main()
    assert exc_info.value.code == 0

    captured = capsys.readouterr()
    output = json.loads(captured.out)
    assert output["hookSpecificOutput"]["hookEventName"] == "PreToolUse"
    assert "MEMORY.md" in output["hookSpecificOutput"]["systemMessage"]
    assert "200" in output["hookSpecificOutput"]["systemMessage"]


def test_main_silent_when_write_keeps_memory_md_under_threshold(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from lazy_harness.hooks.builtins import pre_tool_use_memory_size as mod

    payload = {
        "tool_name": "Write",
        "tool_input": {
            "file_path": "/home/user/.claude/projects/foo/memory/MEMORY.md",
            "content": "line\n" * 50,
        },
    }
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(payload)))
    with pytest.raises(SystemExit) as exc_info:
        mod.main()
    assert exc_info.value.code == 0
    assert capsys.readouterr().out == ""


def test_main_warns_when_edit_pushes_existing_memory_md_over_threshold(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    from lazy_harness.hooks.builtins import pre_tool_use_memory_size as mod

    memory_dir = tmp_path / "memory"
    memory_dir.mkdir()
    memory_file = memory_dir / "MEMORY.md"
    memory_file.write_text("existing\n" * 195)

    big_addition = "new line\n" * 30
    payload = {
        "tool_name": "Edit",
        "tool_input": {
            "file_path": str(memory_file),
            "old_string": "existing\n",
            "new_string": "existing\n" + big_addition,
        },
    }
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(payload)))
    with pytest.raises(SystemExit) as exc_info:
        mod.main()
    assert exc_info.value.code == 0

    captured = capsys.readouterr()
    assert captured.out, "expected warning JSON on stdout"
    output = json.loads(captured.out)
    assert "MEMORY.md" in output["hookSpecificOutput"]["systemMessage"]


def test_bypass_env_var_silences_warning(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from lazy_harness.hooks.builtins import pre_tool_use_memory_size as mod

    payload = {
        "tool_name": "Write",
        "tool_input": {
            "file_path": "/home/user/.claude/projects/foo/memory/MEMORY.md",
            "content": "line\n" * 500,
        },
    }
    monkeypatch.setenv("LH_MEMORY_SIZE_BYPASS", "1")
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(payload)))
    with pytest.raises(SystemExit) as exc_info:
        mod.main()
    assert exc_info.value.code == 0
    assert capsys.readouterr().out == ""


def test_main_silent_when_edit_target_does_not_exist(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    from lazy_harness.hooks.builtins import pre_tool_use_memory_size as mod

    nonexistent = tmp_path / "memory" / "MEMORY.md"
    payload = {
        "tool_name": "Edit",
        "tool_input": {
            "file_path": str(nonexistent),
            "old_string": "x",
            "new_string": "y",
        },
    }
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(payload)))
    with pytest.raises(SystemExit) as exc_info:
        mod.main()
    assert exc_info.value.code == 0
    assert capsys.readouterr().out == ""

"""Tests for the Read-size PreToolUse hook."""

from __future__ import annotations

import io
import json
from pathlib import Path

import pytest


def _run(monkeypatch: pytest.MonkeyPatch, payload: dict, capsys) -> str:
    from lazy_harness.hooks.builtins import pre_tool_use_read_size as mod

    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(payload)))
    with pytest.raises(SystemExit) as exc:
        mod.main()
    assert exc.value.code == 0
    return capsys.readouterr().out


def test_warns_on_a_whole_file_read_of_a_large_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    big = tmp_path / "main.yaml"
    big.write_text("key: value\n" * 3000)

    out = _run(
        monkeypatch,
        {"tool_name": "Read", "tool_input": {"file_path": str(big)}},
        capsys,
    )

    assert out.strip(), "hook stayed silent on a 3000-line whole-file read"
    payload = json.loads(out)
    message = payload["hookSpecificOutput"]["systemMessage"]
    assert "3000" in message
    assert payload["hookSpecificOutput"]["hookEventName"] == "PreToolUse"


def test_stays_silent_when_the_read_is_already_bounded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    """A caller that passed limit/offset already did the right thing."""
    big = tmp_path / "main.yaml"
    big.write_text("key: value\n" * 3000)

    out = _run(
        monkeypatch,
        {"tool_name": "Read", "tool_input": {"file_path": str(big), "limit": 200}},
        capsys,
    )

    assert out.strip() == ""


def test_stays_silent_on_a_small_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    small = tmp_path / "notes.md"
    small.write_text("line\n" * 50)

    out = _run(
        monkeypatch,
        {"tool_name": "Read", "tool_input": {"file_path": str(small)}},
        capsys,
    )

    assert out.strip() == ""


def test_stays_silent_for_other_tools(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    big = tmp_path / "main.yaml"
    big.write_text("key: value\n" * 3000)

    out = _run(
        monkeypatch,
        {"tool_name": "Grep", "tool_input": {"file_path": str(big)}},
        capsys,
    )

    assert out.strip() == ""


def test_stays_silent_when_the_file_is_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    out = _run(
        monkeypatch,
        {"tool_name": "Read", "tool_input": {"file_path": str(tmp_path / "nope.txt")}},
        capsys,
    )

    assert out.strip() == ""

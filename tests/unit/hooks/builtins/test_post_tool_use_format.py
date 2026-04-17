"""Unit tests for post_tool_use_format hook."""

from __future__ import annotations

import io
import subprocess
from unittest.mock import MagicMock

import pytest


def test_runs_ruff_format_on_python_edit(monkeypatch: pytest.MonkeyPatch) -> None:
    from lazy_harness.hooks.builtins import post_tool_use_format as mod

    fake_run = MagicMock(return_value=subprocess.CompletedProcess([], returncode=0))
    monkeypatch.setattr("subprocess.run", fake_run)
    monkeypatch.setattr(
        "sys.stdin",
        io.StringIO(
            '{"tool_name": "Edit", "tool_input": {"file_path": "/abs/foo.py"}}'
        ),
    )

    with pytest.raises(SystemExit) as exc_info:
        mod.main()

    assert exc_info.value.code == 0
    fake_run.assert_called_once()
    args, kwargs = fake_run.call_args
    assert args[0] == ["ruff", "format", "/abs/foo.py"]
    assert kwargs.get("check") is False
    assert kwargs.get("timeout") == 10


def test_runs_ruff_format_on_python_write(monkeypatch: pytest.MonkeyPatch) -> None:
    from lazy_harness.hooks.builtins import post_tool_use_format as mod

    fake_run = MagicMock(return_value=subprocess.CompletedProcess([], returncode=0))
    monkeypatch.setattr("subprocess.run", fake_run)
    monkeypatch.setattr(
        "sys.stdin",
        io.StringIO(
            '{"tool_name": "Write", "tool_input": {"file_path": "/abs/bar.py"}}'
        ),
    )
    with pytest.raises(SystemExit) as exc_info:
        mod.main()
    assert exc_info.value.code == 0
    fake_run.assert_called_once()


def test_skips_non_python_files(monkeypatch: pytest.MonkeyPatch) -> None:
    from lazy_harness.hooks.builtins import post_tool_use_format as mod

    fake_run = MagicMock()
    monkeypatch.setattr("subprocess.run", fake_run)
    monkeypatch.setattr(
        "sys.stdin",
        io.StringIO(
            '{"tool_name": "Edit", "tool_input": {"file_path": "/abs/readme.md"}}'
        ),
    )
    with pytest.raises(SystemExit) as exc_info:
        mod.main()
    assert exc_info.value.code == 0
    fake_run.assert_not_called()


def test_skips_non_edit_tools(monkeypatch: pytest.MonkeyPatch) -> None:
    from lazy_harness.hooks.builtins import post_tool_use_format as mod

    fake_run = MagicMock()
    monkeypatch.setattr("subprocess.run", fake_run)
    monkeypatch.setattr(
        "sys.stdin",
        io.StringIO('{"tool_name": "Read", "tool_input": {"file_path": "/a.py"}}'),
    )
    with pytest.raises(SystemExit) as exc_info:
        mod.main()
    assert exc_info.value.code == 0
    fake_run.assert_not_called()


def test_exits_zero_on_malformed_stdin(monkeypatch: pytest.MonkeyPatch) -> None:
    from lazy_harness.hooks.builtins import post_tool_use_format as mod

    fake_run = MagicMock()
    monkeypatch.setattr("subprocess.run", fake_run)
    monkeypatch.setattr("sys.stdin", io.StringIO("not json"))
    with pytest.raises(SystemExit) as exc_info:
        mod.main()
    assert exc_info.value.code == 0
    fake_run.assert_not_called()


def test_exits_zero_when_ruff_not_installed(monkeypatch: pytest.MonkeyPatch) -> None:
    from lazy_harness.hooks.builtins import post_tool_use_format as mod

    def raise_fnf(*_: object, **__: object) -> subprocess.CompletedProcess[str]:
        raise FileNotFoundError("ruff not found")

    monkeypatch.setattr("subprocess.run", raise_fnf)
    monkeypatch.setattr(
        "sys.stdin",
        io.StringIO('{"tool_name": "Edit", "tool_input": {"file_path": "/a.py"}}'),
    )
    with pytest.raises(SystemExit) as exc_info:
        mod.main()
    assert exc_info.value.code == 0


def test_exits_zero_when_ruff_times_out(monkeypatch: pytest.MonkeyPatch) -> None:
    from lazy_harness.hooks.builtins import post_tool_use_format as mod

    def raise_timeout(*_: object, **__: object) -> subprocess.CompletedProcess[str]:
        raise subprocess.TimeoutExpired(cmd="ruff", timeout=10)

    monkeypatch.setattr("subprocess.run", raise_timeout)
    monkeypatch.setattr(
        "sys.stdin",
        io.StringIO('{"tool_name": "Edit", "tool_input": {"file_path": "/a.py"}}'),
    )
    with pytest.raises(SystemExit) as exc_info:
        mod.main()
    assert exc_info.value.code == 0

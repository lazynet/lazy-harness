"""Tests for Engram CLI wrapper."""

from __future__ import annotations

from unittest.mock import patch


def test_engram_available_returns_bool() -> None:
    from lazy_harness.memory.engram import is_engram_available

    result = is_engram_available()
    assert isinstance(result, bool)


def test_engram_build_command_basic() -> None:
    from lazy_harness.memory.engram import _build_command

    cmd = _build_command("status")
    assert cmd == ["engram", "status"]


def test_engram_build_command_with_project() -> None:
    from lazy_harness.memory.engram import _build_command

    cmd = _build_command("search", project="lazy-harness")
    assert cmd == ["engram", "search", "--project", "lazy-harness"]


def test_engram_run_returns_result() -> None:
    from lazy_harness.memory.engram import EngramResult, run_engram

    with patch("subprocess.run") as mock_run:
        mock_run.return_value = type("R", (), {"returncode": 0, "stdout": "OK", "stderr": ""})()
        result = run_engram("status")
        assert isinstance(result, EngramResult)
        assert result.exit_code == 0
        assert result.stdout == "OK"


def test_engram_run_handles_missing_binary() -> None:
    from lazy_harness.memory.engram import run_engram

    with patch("subprocess.run", side_effect=FileNotFoundError):
        result = run_engram("status")
        assert result.exit_code == -1
        assert "engram not found" in result.stderr


def test_engram_mcp_server_config_shape() -> None:
    from lazy_harness.memory.engram import mcp_server_config

    entry = mcp_server_config()
    assert entry["command"] == "engram"
    assert entry["args"] == ["mcp"]


def test_engram_pinned_version_constant() -> None:
    from lazy_harness.memory import engram

    assert engram.PINNED_VERSION == "1.15.4"


def test_engram_check_version_matches_pin() -> None:
    from lazy_harness.memory.engram import check_version

    with patch("subprocess.run") as mock_run:
        mock_run.return_value = type(
            "R", (), {"returncode": 0, "stdout": "engram 1.15.4\n", "stderr": ""}
        )()
        matches, current = check_version()
        assert matches is True
        assert current == "1.15.4"


def test_engram_check_version_mismatch() -> None:
    from lazy_harness.memory.engram import check_version

    with patch("subprocess.run") as mock_run:
        mock_run.return_value = type(
            "R", (), {"returncode": 0, "stdout": "engram 1.16.0\n", "stderr": ""}
        )()
        matches, current = check_version()
        assert matches is False
        assert current == "1.16.0"


def test_engram_check_version_missing_binary() -> None:
    from lazy_harness.memory.engram import check_version

    with patch("subprocess.run", side_effect=FileNotFoundError):
        matches, current = check_version()
        assert matches is False
        assert current == ""

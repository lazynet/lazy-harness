"""Tests for Graphify CLI wrapper."""

from __future__ import annotations

from unittest.mock import patch


def test_graphify_available_returns_bool() -> None:
    from lazy_harness.knowledge.graphify import is_graphify_available

    result = is_graphify_available()
    assert isinstance(result, bool)


def test_graphify_build_command_basic() -> None:
    from lazy_harness.knowledge.graphify import _build_command

    cmd = _build_command("query")
    assert cmd == ["graphify", "query"]


def test_graphify_build_command_with_target() -> None:
    from lazy_harness.knowledge.graphify import _build_command

    cmd = _build_command("build", target=".")
    assert cmd == ["graphify", "build", "."]


def test_graphify_run_returns_result() -> None:
    from lazy_harness.knowledge.graphify import GraphifyResult, run_graphify

    with patch("subprocess.run") as mock_run:
        mock_run.return_value = type("R", (), {"returncode": 0, "stdout": "OK", "stderr": ""})()
        result = run_graphify("status")
        assert isinstance(result, GraphifyResult)
        assert result.exit_code == 0
        assert result.stdout == "OK"


def test_graphify_run_handles_missing_binary() -> None:
    from lazy_harness.knowledge.graphify import run_graphify

    with patch("subprocess.run", side_effect=FileNotFoundError):
        result = run_graphify("status")
        assert result.exit_code == -1
        assert "graphify not found" in result.stderr


def test_graphify_mcp_server_config_shape() -> None:
    from lazy_harness.knowledge.graphify import mcp_server_config

    entry = mcp_server_config()
    assert entry["command"] == "graphify"
    assert entry["args"] == ["mcp"]


def test_graphify_pinned_version_constant() -> None:
    from lazy_harness.knowledge import graphify

    assert graphify.PINNED_VERSION == "0.6.9"


def test_graphify_check_version_matches_pin() -> None:
    from lazy_harness.knowledge.graphify import check_version

    with patch("subprocess.run") as mock_run:
        mock_run.return_value = type(
            "R", (), {"returncode": 0, "stdout": "graphify 0.6.9\n", "stderr": ""}
        )()
        matches, current = check_version()
        assert matches is True
        assert current == "0.6.9"


def test_graphify_check_version_mismatch() -> None:
    from lazy_harness.knowledge.graphify import check_version

    with patch("subprocess.run") as mock_run:
        mock_run.return_value = type(
            "R", (), {"returncode": 0, "stdout": "graphify 0.7.0\n", "stderr": ""}
        )()
        matches, current = check_version()
        assert matches is False
        assert current == "0.7.0"


def test_graphify_check_version_missing_binary() -> None:
    from lazy_harness.knowledge.graphify import check_version

    with patch("subprocess.run", side_effect=FileNotFoundError):
        matches, current = check_version()
        assert matches is False
        assert current == ""

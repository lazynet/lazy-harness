"""Tests for QMD CLI wrapper."""

from __future__ import annotations

from unittest.mock import patch


def test_qmd_available() -> None:
    from lazy_harness.knowledge.qmd import is_qmd_available

    result = is_qmd_available()
    assert isinstance(result, bool)


def test_qmd_sync_command() -> None:
    from lazy_harness.knowledge.qmd import _build_command

    cmd = _build_command("update")
    assert cmd == ["qmd", "update"]


def test_qmd_sync_with_collection() -> None:
    from lazy_harness.knowledge.qmd import _build_command

    cmd = _build_command("update", collection="my-collection")
    assert cmd == ["qmd", "update", "--collection", "my-collection"]


def test_qmd_embed_command() -> None:
    from lazy_harness.knowledge.qmd import _build_command

    cmd = _build_command("embed")
    assert cmd == ["qmd", "embed"]


def test_qmd_run_returns_result() -> None:
    from lazy_harness.knowledge.qmd import QmdResult, run_qmd

    with patch("subprocess.run") as mock_run:
        mock_run.return_value = type("R", (), {"returncode": 0, "stdout": "OK", "stderr": ""})()
        result = run_qmd("status")
        assert isinstance(result, QmdResult)
        assert result.exit_code == 0
        assert result.stdout == "OK"


def test_qmd_mcp_server_config_shape() -> None:
    from lazy_harness.knowledge.qmd import mcp_server_config

    entry = mcp_server_config()
    assert entry["command"] == "qmd"
    assert entry["args"] == ["mcp"]

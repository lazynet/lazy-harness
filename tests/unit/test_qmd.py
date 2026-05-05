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


def test_qmd_hit_dataclass_fields() -> None:
    from lazy_harness.knowledge.qmd import QmdHit

    hit = QmdHit(file="qmd://col/path.md", title="Sample", score=0.91)
    assert hit.file == "qmd://col/path.md"
    assert hit.title == "Sample"
    assert hit.score == 0.91


def test_qmd_query_parses_json_output_into_hits() -> None:
    import json as _json

    from lazy_harness.knowledge.qmd import query

    payload = _json.dumps(
        [
            {"file": "qmd://a.md", "title": "A", "score": 0.9, "snippet": "..."},
            {"file": "qmd://b.md", "title": "B", "score": 0.8, "snippet": "..."},
            {"file": "qmd://c.md", "title": "C", "score": 0.7, "snippet": "..."},
            {"file": "qmd://d.md", "title": "D", "score": 0.6, "snippet": "..."},
        ]
    )
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = type("R", (), {"returncode": 0, "stdout": payload, "stderr": ""})()
        hits = query("foo", limit=3)
    assert len(hits) == 3
    assert hits[0].title == "A"
    assert hits[0].score == 0.9
    assert hits[2].title == "C"


def test_qmd_query_returns_empty_when_qmd_missing() -> None:
    from lazy_harness.knowledge.qmd import query

    with patch("subprocess.run", side_effect=FileNotFoundError("no qmd")):
        hits = query("foo")
    assert hits == []


def test_qmd_query_returns_empty_on_invalid_json() -> None:
    from lazy_harness.knowledge.qmd import query

    with patch("subprocess.run") as mock_run:
        mock_run.return_value = type(
            "R", (), {"returncode": 0, "stdout": "not json", "stderr": ""}
        )()
        hits = query("foo")
    assert hits == []


def test_qmd_query_returns_empty_on_nonzero_exit() -> None:
    from lazy_harness.knowledge.qmd import query

    with patch("subprocess.run") as mock_run:
        mock_run.return_value = type("R", (), {"returncode": 1, "stdout": "", "stderr": "boom"})()
        hits = query("foo")
    assert hits == []


def test_qmd_query_returns_empty_on_timeout() -> None:
    import subprocess as _subprocess

    from lazy_harness.knowledge.qmd import query

    with patch(
        "subprocess.run",
        side_effect=_subprocess.TimeoutExpired(cmd=["qmd"], timeout=5),
    ):
        hits = query("foo", timeout=5)
    assert hits == []

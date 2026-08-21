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


def test_qmd_run_marks_a_timeout_as_such() -> None:
    """A timeout must be distinguishable from every other -1.

    `run_qmd` returns `exit_code=-1` for a timeout AND for a missing binary,
    so a caller that wants to treat "ran out of time but made progress" as
    success cannot tell the two apart from the exit code alone.
    """
    import subprocess as _subprocess

    from lazy_harness.knowledge.qmd import run_qmd

    with patch(
        "subprocess.run",
        side_effect=_subprocess.TimeoutExpired(cmd=["qmd", "embed"], timeout=600),
    ):
        result = run_qmd("embed", timeout=600)
    assert result.exit_code == -1
    assert result.timed_out is True
    assert "600s" in result.stderr


def test_qmd_run_missing_binary_is_not_a_timeout() -> None:
    from lazy_harness.knowledge.qmd import run_qmd

    with patch("subprocess.run", side_effect=FileNotFoundError("no qmd")):
        result = run_qmd("embed")
    assert result.exit_code == -1
    assert result.timed_out is False


def test_qmd_embed_honours_an_explicit_timeout() -> None:
    from lazy_harness.knowledge.qmd import embed

    with patch("lazy_harness.knowledge.qmd.run_qmd") as mock_run:
        embed(timeout=3600)
    assert mock_run.call_args.kwargs["timeout"] == 3600


def test_qmd_pending_embeddings_parses_status_output() -> None:
    from lazy_harness.knowledge.qmd import pending_embeddings

    status_text = (
        "QMD Status\n"
        "\n"
        "Index: /home/u/.cache/qmd/index.sqlite\n"
        "Size:  205.6 MB\n"
        "\n"
        "Documents\n"
        "  Total:    5391 files indexed\n"
        "  Vectors:  25779 embedded\n"
        "  Pending:  119 need embedding (run 'qmd embed')\n"
        "  Updated:  1d ago\n"
    )
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = type(
            "R", (), {"returncode": 0, "stdout": status_text, "stderr": ""}
        )()
        assert pending_embeddings() == 119


def test_qmd_pending_embeddings_is_zero_when_status_omits_the_line() -> None:
    """qmd drops the Pending line entirely once nothing is outstanding."""
    from lazy_harness.knowledge.qmd import pending_embeddings

    status_text = "QMD Status\n\nDocuments\n  Total:    10 files indexed\n  Vectors:  10 embedded\n"
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = type(
            "R", (), {"returncode": 0, "stdout": status_text, "stderr": ""}
        )()
        assert pending_embeddings() == 0


def test_qmd_pending_embeddings_is_unknown_when_status_fails() -> None:
    """Unknown is not zero: a failed probe must not read as "nothing pending"."""
    from lazy_harness.knowledge.qmd import pending_embeddings

    with patch("subprocess.run") as mock_run:
        mock_run.return_value = type("R", (), {"returncode": 1, "stdout": "", "stderr": "boom"})()
        assert pending_embeddings() is None

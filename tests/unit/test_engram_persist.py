"""Tests for knowledge.engram_persist — EngramPersister core logic."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

from lazy_harness.knowledge.engram_persist import EngramPersister, PersistResult


def test_persister_can_be_instantiated_with_required_args(tmp_path: Path) -> None:
    memory_dir = tmp_path / "memory"
    logs_dir = tmp_path / "logs"
    memory_dir.mkdir()
    logs_dir.mkdir()

    persister = EngramPersister(
        memory_dir=memory_dir,
        logs_dir=logs_dir,
        project_key="lazy-harness",
        engram_bin="/usr/bin/false",  # never invoked in this test
    )

    assert persister.memory_dir == memory_dir
    assert persister.logs_dir == logs_dir
    assert persister.project_key == "lazy-harness"


def test_persist_returns_zero_counts_when_no_jsonl_files_present(tmp_path: Path) -> None:
    memory_dir = tmp_path / "memory"
    logs_dir = tmp_path / "logs"
    memory_dir.mkdir()
    logs_dir.mkdir()

    persister = EngramPersister(
        memory_dir=memory_dir,
        logs_dir=logs_dir,
        project_key="lazy-harness",
        engram_bin="/usr/bin/false",
    )

    result: PersistResult = persister.persist_new_entries()

    assert result.saved_ok == 0
    assert result.saved_failed == 0
    assert result.skipped_malformed == 0
    assert result.entries_seen == {"decision": 0, "failure": 0}


def test_load_cursor_returns_zero_offsets_when_file_missing(tmp_path: Path) -> None:
    from lazy_harness.knowledge.engram_persist import _load_cursor

    cursor = _load_cursor(tmp_path / "engram_cursor.json")

    assert cursor == {"decisions_offset": 0, "failures_offset": 0}


def test_load_cursor_reads_valid_json(tmp_path: Path) -> None:
    from lazy_harness.knowledge.engram_persist import _load_cursor

    cursor_path = tmp_path / "engram_cursor.json"
    cursor_path.write_text(
        '{"version": 1, "decisions_offset": 4523, "failures_offset": 1820, '
        '"updated_at": "2026-05-04T11:25:00Z"}'
    )

    cursor = _load_cursor(cursor_path)

    assert cursor["decisions_offset"] == 4523
    assert cursor["failures_offset"] == 1820


def test_load_cursor_resets_on_corrupt_json(tmp_path: Path) -> None:
    from lazy_harness.knowledge.engram_persist import _load_cursor

    cursor_path = tmp_path / "engram_cursor.json"
    cursor_path.write_text("not valid json {{{")

    cursor = _load_cursor(cursor_path)

    assert cursor == {"decisions_offset": 0, "failures_offset": 0}


def test_load_cursor_resets_on_missing_keys(tmp_path: Path) -> None:
    from lazy_harness.knowledge.engram_persist import _load_cursor

    cursor_path = tmp_path / "engram_cursor.json"
    cursor_path.write_text('{"version": 1}')

    cursor = _load_cursor(cursor_path)

    assert cursor == {"decisions_offset": 0, "failures_offset": 0}


def test_load_cursor_resets_on_non_int_values(tmp_path: Path) -> None:
    from lazy_harness.knowledge.engram_persist import _load_cursor

    cursor_path = tmp_path / "engram_cursor.json"
    cursor_path.write_text(
        '{"version": 1, "decisions_offset": "not-a-number", "failures_offset": 0}'
    )

    cursor = _load_cursor(cursor_path)

    assert cursor == {"decisions_offset": 0, "failures_offset": 0}


def test_save_cursor_writes_atomically(tmp_path: Path) -> None:
    from lazy_harness.knowledge.engram_persist import _save_cursor

    cursor_path = tmp_path / "engram_cursor.json"

    _save_cursor(cursor_path, decisions_offset=100, failures_offset=200)

    data = json.loads(cursor_path.read_text())
    assert data["decisions_offset"] == 100
    assert data["failures_offset"] == 200
    assert data["version"] == 1
    assert "updated_at" in data
    # No leftover tempfiles in the parent dir
    leftover = [p for p in tmp_path.iterdir() if p.is_file() and p.suffix == ".tmp"]
    assert leftover == []


def _seed_jsonl(memory_dir: Path, kind: str, entries: list[dict]) -> Path:
    filename = "decisions.jsonl" if kind == "decision" else "failures.jsonl"
    path = memory_dir / filename
    path.write_text("\n".join(json.dumps(e) for e in entries) + "\n")
    return path


def _persister(tmp_path: Path, engram_bin: str | None = None) -> EngramPersister:
    memory_dir = tmp_path / "memory"
    logs_dir = tmp_path / "logs"
    memory_dir.mkdir()
    logs_dir.mkdir()
    if engram_bin is None:
        engram_bin_path = tmp_path / "engram"
        engram_bin_path.write_text("")  # placeholder; mock intercepts subprocess
        engram_bin = str(engram_bin_path)
    return EngramPersister(
        memory_dir=memory_dir,
        logs_dir=logs_dir,
        project_key="lazy-harness",
        engram_bin=engram_bin,
    )


def test_persists_new_decision_entries_via_engram_save(tmp_path: Path) -> None:
    persister = _persister(tmp_path)
    entries = [
        {
            "ts": "2026-05-04T11:00:00Z",
            "type": "decision",
            "summary": "Use CLI not MCP for hook",
            "rationale": "Independence from server state",
        }
    ]
    _seed_jsonl(persister.memory_dir, "decision", entries)

    with patch("lazy_harness.knowledge.engram_persist.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        result = persister.persist_new_entries()

    assert result.saved_ok == 1
    assert result.saved_failed == 0
    mock_run.assert_called_once()
    args = mock_run.call_args.args[0]
    assert args[0] == persister.engram_bin
    assert args[1] == "save"
    assert args[2] == "Use CLI not MCP for hook"
    assert json.loads(args[3]) == entries[0]
    assert "--type" in args and args[args.index("--type") + 1] == "decision"
    assert "--project" in args and args[args.index("--project") + 1] == "lazy-harness"
    assert "--scope" in args and args[args.index("--scope") + 1] == "project"


def test_persists_failure_entries_with_failure_type(tmp_path: Path) -> None:
    persister = _persister(tmp_path)
    entries = [
        {
            "ts": "2026-05-04T11:00:00Z",
            "type": "failure",
            "summary": "Worker lock not refreshed",
            "root_cause": "Missing touch() in heartbeat path",
        }
    ]
    _seed_jsonl(persister.memory_dir, "failure", entries)

    with patch("lazy_harness.knowledge.engram_persist.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        persister.persist_new_entries()

    args = mock_run.call_args.args[0]
    assert args[args.index("--type") + 1] == "failure"


def test_title_falls_back_when_summary_missing(tmp_path: Path) -> None:
    persister = _persister(tmp_path)
    entries = [
        {"ts": "2026-05-04T11:00:00Z", "type": "decision"}  # no summary
    ]
    _seed_jsonl(persister.memory_dir, "decision", entries)

    with patch("lazy_harness.knowledge.engram_persist.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        persister.persist_new_entries()

    args = mock_run.call_args.args[0]
    assert args[2] == "decision@2026-05-04T11:00:00Z"


def test_title_truncated_to_max_chars(tmp_path: Path) -> None:
    persister = _persister(tmp_path)
    long = "x" * 500
    entries = [{"ts": "2026-05-04T11:00:00Z", "type": "decision", "summary": long}]
    _seed_jsonl(persister.memory_dir, "decision", entries)

    with patch("lazy_harness.knowledge.engram_persist.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        persister.persist_new_entries()

    args = mock_run.call_args.args[0]
    assert len(args[2]) == 200  # TITLE_MAX_CHARS


def test_advances_cursor_only_on_successful_save(tmp_path: Path) -> None:
    persister = _persister(tmp_path)
    entries = [{"ts": "T1", "type": "decision", "summary": "first"}]
    _seed_jsonl(persister.memory_dir, "decision", entries)

    with patch("lazy_harness.knowledge.engram_persist.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="boom")
        result = persister.persist_new_entries()

    assert result.saved_ok == 0
    assert result.saved_failed == 1
    cursor_file = persister.memory_dir / "engram_cursor.json"
    if cursor_file.is_file():
        cursor = json.loads(cursor_file.read_text())
        assert cursor["decisions_offset"] == 0  # never advanced


def test_skips_already_persisted_entries_on_second_run(tmp_path: Path) -> None:
    persister = _persister(tmp_path)
    entries = [
        {"ts": "T1", "type": "decision", "summary": "first"},
        {"ts": "T2", "type": "decision", "summary": "second"},
    ]
    _seed_jsonl(persister.memory_dir, "decision", entries)

    with patch("lazy_harness.knowledge.engram_persist.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        persister.persist_new_entries()
        first_call_count = mock_run.call_count
        # Second run with no new entries
        result = persister.persist_new_entries()

    assert first_call_count == 2
    assert result.saved_ok == 0
    assert mock_run.call_count == 2  # no additional calls


def test_handles_malformed_jsonl_line_between_valid_lines(tmp_path: Path) -> None:
    persister = _persister(tmp_path)
    valid_a = json.dumps({"ts": "T1", "type": "decision", "summary": "a"})
    valid_b = json.dumps({"ts": "T2", "type": "decision", "summary": "b"})
    bad = "{ this is not json"
    (persister.memory_dir / "decisions.jsonl").write_text(
        valid_a + "\n" + bad + "\n" + valid_b + "\n"
    )

    with patch("lazy_harness.knowledge.engram_persist.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        result = persister.persist_new_entries()

    assert result.saved_ok == 2
    assert result.skipped_malformed == 1
    # Both valid entries saved, malformed line counted; cursor at EOF.
    cursor = json.loads((persister.memory_dir / "engram_cursor.json").read_text())
    assert cursor["decisions_offset"] == (persister.memory_dir / "decisions.jsonl").stat().st_size


def test_breaks_inner_loop_on_save_failure(tmp_path: Path) -> None:
    persister = _persister(tmp_path)
    entries = [
        {"ts": "T1", "type": "decision", "summary": "first"},
        {"ts": "T2", "type": "decision", "summary": "second"},
        {"ts": "T3", "type": "decision", "summary": "third"},
    ]
    _seed_jsonl(persister.memory_dir, "decision", entries)

    side_effects = [
        MagicMock(returncode=0, stdout="", stderr=""),
        MagicMock(returncode=1, stdout="", stderr="boom"),
        MagicMock(returncode=0, stdout="", stderr=""),
    ]

    with patch(
        "lazy_harness.knowledge.engram_persist.subprocess.run",
        side_effect=side_effects,
    ) as mock_run:
        result = persister.persist_new_entries()

    assert result.saved_ok == 1
    assert result.saved_failed == 1
    # Third entry NOT attempted in this run
    assert mock_run.call_count == 2


def test_resets_cursor_when_offset_exceeds_file_size(tmp_path: Path) -> None:
    persister = _persister(tmp_path)
    entries = [{"ts": "T1", "type": "decision", "summary": "first"}]
    _seed_jsonl(persister.memory_dir, "decision", entries)

    # Pre-seed a cursor that points past EOF (truncation simulation)
    (persister.memory_dir / "engram_cursor.json").write_text(
        json.dumps(
            {
                "version": 1,
                "decisions_offset": 9999,
                "failures_offset": 0,
                "updated_at": "2026-05-04T00:00:00Z",
            }
        )
    )

    with patch("lazy_harness.knowledge.engram_persist.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        result = persister.persist_new_entries()

    assert result.saved_ok == 1


def test_handles_missing_engram_binary_gracefully(tmp_path: Path) -> None:
    memory_dir = tmp_path / "memory"
    logs_dir = tmp_path / "logs"
    memory_dir.mkdir()
    logs_dir.mkdir()
    entries = [{"ts": "T1", "type": "decision", "summary": "x"}]
    _seed_jsonl(memory_dir, "decision", entries)

    persister = EngramPersister(
        memory_dir=memory_dir,
        logs_dir=logs_dir,
        project_key="lazy-harness",
        engram_bin="/nonexistent/engram-binary-xyz",
    )

    with patch("lazy_harness.knowledge.engram_persist.subprocess.run") as mock_run:
        result = persister.persist_new_entries()

    mock_run.assert_not_called()
    assert result.saved_ok == 0
    log_path = logs_dir / "engram_persist.log"
    assert log_path.is_file()
    assert "engram binary not on PATH" in log_path.read_text()


def test_failures_and_decisions_have_independent_cursors(tmp_path: Path) -> None:
    persister = _persister(tmp_path)
    decisions = [{"ts": "D1", "type": "decision", "summary": "d"}]
    failures = [{"ts": "F1", "type": "failure", "summary": "f"}]
    _seed_jsonl(persister.memory_dir, "decision", decisions)
    _seed_jsonl(persister.memory_dir, "failure", failures)

    with patch("lazy_harness.knowledge.engram_persist.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        persister.persist_new_entries()

    cursor = json.loads((persister.memory_dir / "engram_cursor.json").read_text())
    decisions_size = (persister.memory_dir / "decisions.jsonl").stat().st_size
    failures_size = (persister.memory_dir / "failures.jsonl").stat().st_size
    assert cursor["decisions_offset"] == decisions_size
    assert cursor["failures_offset"] == failures_size

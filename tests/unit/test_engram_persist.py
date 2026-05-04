"""Tests for knowledge.engram_persist — EngramPersister core logic."""

from __future__ import annotations

import json
from pathlib import Path

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

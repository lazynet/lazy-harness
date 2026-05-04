"""Tests for knowledge.engram_persist — EngramPersister core logic."""

from __future__ import annotations

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

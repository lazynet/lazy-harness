"""The engram cursor belongs to the machine, not to the shared store.

Offsets index `decisions.jsonl` / `failures.jsonl`, which travel between
machines through the knowledge store's git remote. The database they feed —
`~/.engram/engram.db` — does not. A cursor pulled from another machine
therefore claims entries this machine's database never saw, and they are
skipped for good.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

from lazy_harness.knowledge.engram_persist import EngramPersister

_ENTRY = {
    "ts": "2026-08-18T11:00:00Z",
    "type": "decision",
    "summary": "Keep the cursor on the machine that owns the database",
    "rationale": "A shared cursor skips entries the local database never saw",
}


def _dirs(tmp_path: Path) -> tuple[Path, Path, Path]:
    memory_dir = tmp_path / "memory"
    logs_dir = tmp_path / "logs"
    cursor_dir = tmp_path / "agent" / "engram-cursors" / "github.com" / "lazynet" / "repo"
    memory_dir.mkdir(parents=True)
    logs_dir.mkdir(parents=True)
    return memory_dir, logs_dir, cursor_dir


def _seed(memory_dir: Path) -> None:
    (memory_dir / "decisions.jsonl").write_text(json.dumps(_ENTRY) + "\n")


def _persister(memory_dir: Path, logs_dir: Path, cursor_dir: Path) -> EngramPersister:
    return EngramPersister(
        memory_dir=memory_dir,
        logs_dir=logs_dir,
        project_key="repo",
        engram_bin="/bin/echo",
        cursor_dir=cursor_dir,
    )


def test_cursor_is_written_to_the_cursor_dir(tmp_path: Path) -> None:
    memory_dir, logs_dir, cursor_dir = _dirs(tmp_path)
    _seed(memory_dir)
    persister = _persister(memory_dir, logs_dir, cursor_dir)

    with patch("lazy_harness.knowledge.engram_persist.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        persister.persist_new_entries()

    assert (cursor_dir / "engram_cursor.json").is_file()
    assert not (memory_dir / "engram_cursor.json").exists()


def test_a_cursor_in_the_shared_store_does_not_override_the_local_one(
    tmp_path: Path,
) -> None:
    """The failing case: another machine pushed a cursor past our entries."""
    memory_dir, logs_dir, cursor_dir = _dirs(tmp_path)
    _seed(memory_dir)
    entry_bytes = len(json.dumps(_ENTRY) + "\n")
    # What the other machine pushed: everything already consumed.
    (memory_dir / "engram_cursor.json").write_text(
        json.dumps(
            {
                "version": 1,
                "decisions_offset": entry_bytes,
                "failures_offset": 0,
                "updated_at": "2026-08-18T14:13:57Z",
            }
        )
    )
    # What this machine actually consumed: nothing.
    cursor_dir.mkdir(parents=True)
    (cursor_dir / "engram_cursor.json").write_text(
        json.dumps({"version": 1, "decisions_offset": 0, "failures_offset": 0})
    )
    persister = _persister(memory_dir, logs_dir, cursor_dir)

    with patch("lazy_harness.knowledge.engram_persist.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        result = persister.persist_new_entries()

    assert result.saved_ok == 1


def test_a_legacy_cursor_is_adopted_when_no_local_one_exists(tmp_path: Path) -> None:
    """Migration: the first run after the move must not reprocess everything."""
    memory_dir, logs_dir, cursor_dir = _dirs(tmp_path)
    _seed(memory_dir)
    entry_bytes = len(json.dumps(_ENTRY) + "\n")
    (memory_dir / "engram_cursor.json").write_text(
        json.dumps({"version": 1, "decisions_offset": entry_bytes, "failures_offset": 0})
    )
    persister = _persister(memory_dir, logs_dir, cursor_dir)

    with patch("lazy_harness.knowledge.engram_persist.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        result = persister.persist_new_entries()

    assert result.saved_ok == 0
    assert (cursor_dir / "engram_cursor.json").is_file()


def test_cursor_dir_defaults_to_the_memory_dir(tmp_path: Path) -> None:
    """Callers that pass no cursor_dir keep writing exactly where they did."""
    memory_dir, logs_dir, _ = _dirs(tmp_path)
    _seed(memory_dir)
    persister = EngramPersister(
        memory_dir=memory_dir,
        logs_dir=logs_dir,
        project_key="repo",
        engram_bin="/bin/echo",
    )

    with patch("lazy_harness.knowledge.engram_persist.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        persister.persist_new_entries()

    assert (memory_dir / "engram_cursor.json").is_file()

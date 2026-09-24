"""One cursor per project per machine, and a bounded catch-up per run.

Every profile on a machine reads the same `decisions.jsonl` from the knowledge
store and saves into the same `~/.engram/engram.db`, but each kept its own
cursor. A profile's first run therefore re-uploaded the whole history the
other profiles had already mirrored — 405 entries in one profile, 930 in the
other, the second freezing `Stop` for 145 s.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from lazy_harness.knowledge.engram_persist import EngramPersister


def _entry(i: int) -> dict[str, str]:
    return {"ts": f"2026-09-23T10:{i:02d}:00Z", "type": "decision", "summary": f"entry {i}"}


def _seed(memory_dir: Path, count: int, *, padding: int = 0) -> list[int]:
    """Write `count` decisions and return the byte offset after each line."""
    memory_dir.mkdir(parents=True, exist_ok=True)
    offsets: list[int] = []
    total = 0
    lines = []
    for i in range(count):
        entry = _entry(i)
        if padding:
            entry["detail"] = "x" * padding
        line = json.dumps(entry) + "\n"
        lines.append(line)
        total += len(line.encode())
        offsets.append(total)
    (memory_dir / "decisions.jsonl").write_text("".join(lines))
    return offsets


def _write_cursor(directory: Path, decisions: object, failures: object = 0) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "engram_cursor.json").write_text(
        json.dumps({"version": 1, "decisions_offset": decisions, "failures_offset": failures})
    )


def _read_cursor(directory: Path) -> dict[str, int]:
    return json.loads((directory / "engram_cursor.json").read_text())


def _run(persister: EngramPersister):
    with patch("lazy_harness.knowledge.engram_persist.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        return persister.persist_new_entries()


# --- Cap per run -----------------------------------------------------------


def test_a_catch_up_stops_at_the_per_run_cap(tmp_path: Path) -> None:
    memory_dir = tmp_path / "memory"
    offsets = _seed(memory_dir, 7)
    cursor_dir = tmp_path / "cursor"
    persister = EngramPersister(
        memory_dir=memory_dir,
        logs_dir=tmp_path / "logs",
        project_key="repo",
        engram_bin="/bin/echo",
        cursor_dir=cursor_dir,
        max_saves_per_run=3,
    )

    result = _run(persister)

    assert result.saved_ok == 3
    assert result.save_cap_reached is True
    assert result.cursor_advanced is True
    # The cursor covers exactly what was saved, not what was read.
    assert _read_cursor(cursor_dir)["decisions_offset"] == offsets[2]


def test_failed_cursor_write_does_not_report_catch_up(tmp_path: Path) -> None:
    memory_dir = tmp_path / "memory"
    _seed(memory_dir, 7)
    persister = EngramPersister(
        memory_dir=memory_dir,
        logs_dir=tmp_path / "logs",
        project_key="repo",
        engram_bin="/bin/echo",
        cursor_dir=tmp_path / "cursor",
        max_saves_per_run=3,
    )

    with patch("lazy_harness.knowledge.engram_persist._save_cursor", return_value=None):
        result = _run(persister)

    assert result.saved_ok == 3
    assert result.save_cap_reached is True
    assert result.cursor_advanced is False
    assert result.cursor_lag_bytes["decision"] == (memory_dir / "decisions.jsonl").stat().st_size


def test_the_remainder_drains_on_later_runs(tmp_path: Path) -> None:
    memory_dir = tmp_path / "memory"
    offsets = _seed(memory_dir, 7)
    cursor_dir = tmp_path / "cursor"
    persister = EngramPersister(
        memory_dir=memory_dir,
        logs_dir=tmp_path / "logs",
        project_key="repo",
        engram_bin="/bin/echo",
        cursor_dir=cursor_dir,
        max_saves_per_run=3,
    )

    saved = [_run(persister).saved_ok for _ in range(4)]

    assert saved == [3, 3, 1, 0]
    assert _read_cursor(cursor_dir)["decisions_offset"] == offsets[-1]


def test_the_cap_spans_both_files(tmp_path: Path) -> None:
    """A run is bounded in total, not per file — the Stop hook waits on the sum."""
    memory_dir = tmp_path / "memory"
    _seed(memory_dir, 2)
    (memory_dir / "failures.jsonl").write_text(
        "".join(json.dumps(_entry(i)) + "\n" for i in range(5))
    )
    persister = EngramPersister(
        memory_dir=memory_dir,
        logs_dir=tmp_path / "logs",
        project_key="repo",
        engram_bin="/bin/echo",
        cursor_dir=tmp_path / "cursor",
        max_saves_per_run=4,
    )

    assert _run(persister).saved_ok == 4


def test_the_default_cap_bounds_a_large_backlog(tmp_path: Path) -> None:
    from lazy_harness.knowledge.engram_persist import MAX_SAVES_PER_RUN

    memory_dir = tmp_path / "memory"
    _seed(memory_dir, MAX_SAVES_PER_RUN + 5)
    persister = EngramPersister(
        memory_dir=memory_dir,
        logs_dir=tmp_path / "logs",
        project_key="repo",
        engram_bin="/bin/echo",
        cursor_dir=tmp_path / "cursor",
    )

    assert _run(persister).saved_ok == MAX_SAVES_PER_RUN


def test_doctor_classifies_a_real_capped_run_and_a_stalled_cursor(tmp_path: Path) -> None:
    from datetime import UTC, datetime

    from lazy_harness.knowledge.engram_persist import MAX_SAVES_PER_RUN
    from lazy_harness.monitoring.engram_persist_health import collect_engram_persist_health

    memory_dir = tmp_path / "memory"
    _seed(memory_dir, MAX_SAVES_PER_RUN + 5, padding=15_000)
    persister = EngramPersister(
        memory_dir=memory_dir,
        logs_dir=tmp_path / "logs",
        project_key="repo",
        engram_bin="/bin/echo",
        cursor_dir=tmp_path / "cursor",
    )
    metrics = persister.logs_dir / "engram_persist_metrics.jsonl"

    _run(persister)
    progressing = collect_engram_persist_health(metrics, now=datetime.now(UTC))
    assert progressing.cursor_lag_bytes is not None
    assert progressing.cursor_lag_bytes >= 64 * 1024
    assert progressing.state == "warn"
    assert progressing.catching_up is True

    (persister.cursor_dir / "engram_cursor.json").unlink()
    with patch("lazy_harness.knowledge.engram_persist._save_cursor", return_value=None):
        _run(persister)
    stalled = collect_engram_persist_health(metrics, now=datetime.now(UTC))
    assert stalled.cursor_lag_bytes == (memory_dir / "decisions.jsonl").stat().st_size
    assert stalled.state == "fail"
    assert stalled.catching_up is False


# --- Carry-over from per-profile cursors -----------------------------------


def test_a_new_shared_cursor_adopts_the_furthest_profile_cursor(tmp_path: Path) -> None:
    """Migration: the profile that got furthest already put those rows in the DB."""
    memory_dir = tmp_path / "memory"
    offsets = _seed(memory_dir, 5)
    behind = tmp_path / "profile-a"
    ahead = tmp_path / "profile-b"
    _write_cursor(behind, offsets[0])
    _write_cursor(ahead, offsets[3])
    shared = tmp_path / "shared"
    persister = EngramPersister(
        memory_dir=memory_dir,
        logs_dir=tmp_path / "logs",
        project_key="repo",
        engram_bin="/bin/echo",
        cursor_dir=shared,
        adopt_cursor_dirs=(behind, ahead),
    )

    result = _run(persister)

    assert result.saved_ok == 1
    assert _read_cursor(shared)["decisions_offset"] == offsets[4]


def test_adoption_takes_the_max_of_each_offset_independently(tmp_path: Path) -> None:
    memory_dir = tmp_path / "memory"
    offsets = _seed(memory_dir, 3)
    (memory_dir / "failures.jsonl").write_text(
        "".join(json.dumps(_entry(i)) + "\n" for i in range(3))
    )
    a = tmp_path / "profile-a"
    b = tmp_path / "profile-b"
    _write_cursor(a, offsets[2], 0)
    _write_cursor(b, 0, offsets[2])
    persister = EngramPersister(
        memory_dir=memory_dir,
        logs_dir=tmp_path / "logs",
        project_key="repo",
        engram_bin="/bin/echo",
        cursor_dir=tmp_path / "shared",
        adopt_cursor_dirs=(a, b),
    )

    assert _run(persister).saved_ok == 0


def test_an_existing_shared_cursor_is_not_overridden_by_profile_cursors(
    tmp_path: Path,
) -> None:
    """Adoption happens once; afterwards the shared cursor is the only truth."""
    memory_dir = tmp_path / "memory"
    offsets = _seed(memory_dir, 4)
    shared = tmp_path / "shared"
    _write_cursor(shared, offsets[0])
    stale_ahead = tmp_path / "profile-a"
    _write_cursor(stale_ahead, offsets[3])
    persister = EngramPersister(
        memory_dir=memory_dir,
        logs_dir=tmp_path / "logs",
        project_key="repo",
        engram_bin="/bin/echo",
        cursor_dir=shared,
        adopt_cursor_dirs=(stale_ahead,),
    )

    assert _run(persister).saved_ok == 3


@pytest.mark.parametrize(
    "raw",
    ["null", "[]", "42", '"x"', '{"decisions_offset": [1], "failures_offset": 0}', "{not json"],
)
def test_a_malformed_profile_cursor_is_ignored_during_adoption(tmp_path: Path, raw: str) -> None:
    memory_dir = tmp_path / "memory"
    offsets = _seed(memory_dir, 3)
    broken = tmp_path / "broken"
    broken.mkdir()
    (broken / "engram_cursor.json").write_text(raw)
    good = tmp_path / "good"
    _write_cursor(good, offsets[1])
    persister = EngramPersister(
        memory_dir=memory_dir,
        logs_dir=tmp_path / "logs",
        project_key="repo",
        engram_bin="/bin/echo",
        cursor_dir=tmp_path / "shared",
        adopt_cursor_dirs=(broken, good),
    )

    assert _run(persister).saved_ok == 1


def test_profile_cursors_win_over_a_cursor_in_the_shared_store(tmp_path: Path) -> None:
    """The store's copy may come from another machine; a profile cursor is ours."""
    memory_dir = tmp_path / "memory"
    offsets = _seed(memory_dir, 3)
    _write_cursor(memory_dir, offsets[2])
    local = tmp_path / "profile-a"
    _write_cursor(local, offsets[0])
    persister = EngramPersister(
        memory_dir=memory_dir,
        logs_dir=tmp_path / "logs",
        project_key="repo",
        engram_bin="/bin/echo",
        cursor_dir=tmp_path / "shared",
        adopt_cursor_dirs=(local,),
    )

    assert _run(persister).saved_ok == 2

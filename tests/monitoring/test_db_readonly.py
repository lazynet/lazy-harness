"""`MetricsDB.open_readonly` — a read path for diagnostics (`lh doctor`,
selftest) that never issues a write statement against an existing metrics
DB (no CREATE/ALTER, no journal-mode change) and never weakens SQLite
consistency to work around a restrictive environment: it reads via
`mode=ro` only, and reports `MetricsDBUnavailable` — never a silently
stale read — when that cannot open the file.
"""

from __future__ import annotations

import errno
import os
import sqlite3
from pathlib import Path

import pytest

from lazy_harness.monitoring.db import MetricsDB, MetricsDBUnavailable, looks_like_permission_denied


def _chmod_dir(path: Path, mode: int) -> None:
    os.chmod(path, mode)


@pytest.fixture
def restore_perms():
    """Restores directory permissions after a test locks one down, so
    pytest's own tmp_path cleanup does not trip over a read-only dir."""
    locked: list[Path] = []
    yield locked
    for d in locked:
        os.chmod(d, 0o700)


def test_missing_file_raises_unavailable_not_permission_denied(tmp_path: Path) -> None:
    missing = tmp_path / "nope.db"

    with pytest.raises(MetricsDBUnavailable) as exc_info:
        MetricsDB.open_readonly(missing)

    assert exc_info.value.permission_denied is False
    assert exc_info.value.not_found is True


def test_directory_at_db_path_is_a_genuine_diagnostic_not_an_empty_store(tmp_path: Path) -> None:
    """A directory sitting where the DB file should be is a misconfigured
    path, not "no DB created yet" — `not_found` must stay `False` so a
    caller (`lh doctor`) reports it as a real finding instead of silently
    falling back to an empty in-memory store."""
    db_path = tmp_path / "m.db"
    db_path.mkdir()

    with pytest.raises(MetricsDBUnavailable) as exc_info:
        MetricsDB.open_readonly(db_path)

    assert exc_info.value.not_found is False
    assert exc_info.value.permission_denied is False


def test_notadirectory_path_component_is_a_genuine_diagnostic_not_an_empty_store(
    tmp_path: Path,
) -> None:
    """A path component that should be a directory but is a plain file
    raises `NotADirectoryError` from `stat()` — also a misconfigured path,
    not an absent one."""
    not_a_dir = tmp_path / "not_a_dir"
    not_a_dir.write_text("x")
    db_path = not_a_dir / "m.db"

    with pytest.raises(MetricsDBUnavailable) as exc_info:
        MetricsDB.open_readonly(db_path)

    assert exc_info.value.not_found is False
    assert exc_info.value.permission_denied is False


def test_reads_a_db_whose_path_contains_uri_special_characters(tmp_path: Path) -> None:
    """A bare f-string URI mis-parses `#`/`?` in a filename: `#` starts a URI
    fragment, silently dropping `?mode=ro` and everything after the `#` from
    the path SQLite actually opens — measured to open a *different*,
    truncated path in default read/write/create mode, planting a stray
    empty file next to the real one instead of raising."""
    db_dir = tmp_path / "weird"
    db_dir.mkdir()
    db_path = db_dir / "m#weird?.db"
    writer = MetricsDB(db_path)
    writer.record_launch(profile="flex", agent="codex", entry="exec")
    writer.close()

    reader = MetricsDB.open_readonly(db_path)
    try:
        counts = reader.launch_counts()
    finally:
        reader.close()

    assert counts == {("flex", "codex", "exec"): 1}
    # A fresh read of a WAL-mode db legitimately creates `-wal`/`-shm`
    # side-cars when the directory allows it (ordinary SQLite behaviour,
    # not a defect this test cares about) — what matters here is that no
    # *wrongly named* file appeared from the URI being cut at `#`/`?`.
    assert "m" not in {p.name for p in db_dir.iterdir()}
    assert db_path.name in {p.name for p in db_dir.iterdir()}


def test_reads_an_existing_db_without_touching_it(tmp_path: Path) -> None:
    """No CREATE/ALTER/journal-mode write happens on a read-only open —
    the file's bytes and mtime are exactly what the write path left."""
    db_path = tmp_path / "m.db"
    writer = MetricsDB(db_path)
    writer.record_launch(profile="flex", agent="codex", entry="exec")
    writer.close()
    # Force a checkpoint so the db file itself (not the -wal side-car)
    # carries the row this test asserts on, and remove the side-cars so a
    # write attempt during open_readonly would be unmistakable (it would
    # have to recreate them).
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    conn.execute("PRAGMA journal_mode=DELETE")
    conn.close()
    for suffix in ("-wal", "-shm"):
        side_car = Path(str(db_path) + suffix)
        if side_car.exists():
            side_car.unlink()

    before_bytes = db_path.read_bytes()
    before_mtime_ns = db_path.stat().st_mtime_ns

    reader = MetricsDB.open_readonly(db_path)
    try:
        counts = reader.launch_counts()
    finally:
        reader.close()

    assert counts == {("flex", "codex", "exec"): 1}
    assert db_path.read_bytes() == before_bytes
    assert db_path.stat().st_mtime_ns == before_mtime_ns
    assert not Path(str(db_path) + "-wal").exists()
    assert not Path(str(db_path) + "-shm").exists()


def test_opens_a_non_wal_db_under_a_readonly_directory(
    tmp_path: Path, restore_perms: list[Path]
) -> None:
    """The write path fails here (`PRAGMA journal_mode=WAL` needs to create
    a `-wal` file); the read-only path must not, because it never asks."""
    db_dir = tmp_path / "metrics"
    db_dir.mkdir()
    db_path = db_dir / "m.db"
    writer = MetricsDB(db_path)
    writer.record_launch(profile="flex", agent="codex", entry="exec")
    writer.close()
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    conn.execute("PRAGMA journal_mode=DELETE")
    conn.close()
    for suffix in ("-wal", "-shm"):
        side_car = Path(str(db_path) + suffix)
        if side_car.exists():
            side_car.unlink()

    _chmod_dir(db_dir, 0o500)
    restore_perms.append(db_dir)

    with pytest.raises(sqlite3.OperationalError):
        MetricsDB(db_path)

    reader = MetricsDB.open_readonly(db_path)
    try:
        counts = reader.launch_counts()
    finally:
        reader.close()

    assert counts == {("flex", "codex", "exec"): 1}


def test_reads_committed_wal_data_that_has_not_been_checkpointed(tmp_path: Path) -> None:
    """A row committed to the WAL but not yet checkpointed back into the
    main db file must still be visible — the reason `mode=ro`, never
    `immutable=1`, is the only mode this method uses."""
    db_path = tmp_path / "m.db"
    writer = MetricsDB(db_path)
    writer.record_launch(profile="flex", agent="codex", entry="exec")
    # Deliberately not closed: closing triggers SQLite's on-close
    # checkpoint, which is exactly the state this test needs to avoid.

    reader = MetricsDB.open_readonly(db_path)
    try:
        counts = reader.launch_counts()
    finally:
        reader.close()
        writer.close()

    assert counts == {("flex", "codex", "exec"): 1}


def test_reports_unavailable_rather_than_falling_back_when_a_readonly_directory_has_no_wal_sidecars(
    tmp_path: Path, restore_perms: list[Path]
) -> None:
    """The realistic steady state: every writer closes its own connection
    (checkpointing and removing `-wal`/`-shm`), so the next open of that
    still-WAL-mode file has no side-cars to reuse, and creating them needs
    directory write access. `open_readonly` must report that as
    `MetricsDBUnavailable(permission_denied=True)` — never silently widen
    to `immutable=1`, which would return data that might already be stale
    by the time the caller reads it back."""
    db_dir = tmp_path / "metrics"
    db_dir.mkdir()
    db_path = db_dir / "m.db"
    writer = MetricsDB(db_path)
    writer.record_launch(profile="flex", agent="codex", entry="exec")
    writer.close()
    assert not Path(str(db_path) + "-wal").exists()
    assert not Path(str(db_path) + "-shm").exists()

    _chmod_dir(db_dir, 0o500)
    restore_perms.append(db_dir)

    with pytest.raises(MetricsDBUnavailable) as exc_info:
        MetricsDB.open_readonly(db_path)

    assert exc_info.value.permission_denied is True
    assert exc_info.value.not_found is False
    # No connection attempt may have left anything behind, immutable or not.
    assert sorted(p.name for p in db_dir.iterdir()) == ["m.db"]


def test_mode_ro_failure_never_attempts_an_immutable_connection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Regression: exactly one `sqlite3.connect` call, and its URI never
    carries `immutable=1` — there is no second, weaker attempt to fall
    back to after a `mode=ro` open fails."""
    db_path = tmp_path / "m.db"
    MetricsDB(db_path).close()

    seen_uris: list[str] = []

    def spy_connect(database: str, **kwargs: object):
        seen_uris.append(database)
        raise sqlite3.OperationalError("attempt to write a readonly database")

    monkeypatch.setattr(sqlite3, "connect", spy_connect)

    with pytest.raises(MetricsDBUnavailable):
        MetricsDB.open_readonly(db_path)

    assert len(seen_uris) == 1
    assert "immutable" not in seen_uris[0]


def test_corrupt_file_raises_unavailable_not_permission_denied(tmp_path: Path) -> None:
    corrupt = tmp_path / "corrupt.db"
    corrupt.write_text("not a sqlite database")

    with pytest.raises(MetricsDBUnavailable) as exc_info:
        MetricsDB.open_readonly(corrupt)

    assert exc_info.value.permission_denied is False
    assert exc_info.value.not_found is False


def test_repeated_failed_diagnosis_does_not_leak_file_descriptors(tmp_path: Path) -> None:
    """A `MetricsDBUnavailable` raised after `connect()` succeeded (the
    corrupt-file case) must close that connection first — `lh doctor`
    calling this in a loop across profiles must not exhaust descriptors."""
    corrupt = tmp_path / "corrupt.db"
    corrupt.write_text("not a sqlite database")

    for _ in range(200):
        with pytest.raises(MetricsDBUnavailable):
            MetricsDB.open_readonly(corrupt)


def test_stat_permission_errno_is_classified_as_permission_denied(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def raise_eacces(self: Path, *, follow_symlinks: bool = True):
        raise OSError(errno.EACCES, "Permission denied")

    monkeypatch.setattr(Path, "stat", raise_eacces)

    with pytest.raises(MetricsDBUnavailable) as exc_info:
        MetricsDB.open_readonly(tmp_path / "m.db")

    assert exc_info.value.permission_denied is True
    assert exc_info.value.not_found is False


def test_stat_non_permission_errno_is_not_classified_as_permission_denied(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def raise_enametoolong(self: Path, *, follow_symlinks: bool = True):
        raise OSError(errno.ENAMETOOLONG, "File name too long")

    monkeypatch.setattr(Path, "stat", raise_enametoolong)

    with pytest.raises(MetricsDBUnavailable) as exc_info:
        MetricsDB.open_readonly(tmp_path / "m.db")

    assert exc_info.value.permission_denied is False
    assert exc_info.value.not_found is False


def test_stat_filenotfound_is_reported_as_not_found_not_permission_denied(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def raise_enoent(self: Path, *, follow_symlinks: bool = True):
        raise FileNotFoundError(errno.ENOENT, "No such file or directory")

    monkeypatch.setattr(Path, "stat", raise_enoent)

    with pytest.raises(MetricsDBUnavailable) as exc_info:
        MetricsDB.open_readonly(tmp_path / "m.db")

    assert exc_info.value.permission_denied is False
    assert exc_info.value.not_found is True


def test_permission_error_from_stat_is_not_misread_as_missing_via_is_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The exact failure mode measured on Python 3.14: `Path.is_file()`
    catches `PermissionError` internally and returns `False`, which is
    indistinguishable from "never created". Mocking the underlying
    `stat()` (not `is_file()`) proves `open_readonly` does not route
    through that predicate at all — a permission failure is classified as
    `permission_denied`, never silently folded into `not_found`."""

    def raise_eacces(self: Path, *, follow_symlinks: bool = True):
        raise PermissionError(errno.EACCES, "denied")

    monkeypatch.setattr(Path, "stat", raise_eacces)

    with pytest.raises(MetricsDBUnavailable) as exc_info:
        MetricsDB.open_readonly(tmp_path / "m.db")

    assert exc_info.value.permission_denied is True
    assert exc_info.value.not_found is False


def test_permission_denied_file_is_classified_as_unverifiable(
    tmp_path: Path, restore_perms: list[Path]
) -> None:
    db_path = tmp_path / "m.db"
    writer = MetricsDB(db_path)
    writer.close()
    os.chmod(db_path, 0o000)
    restore_perms.append(db_path)

    with pytest.raises(MetricsDBUnavailable) as exc_info:
        MetricsDB.open_readonly(db_path)

    assert exc_info.value.permission_denied is True
    assert exc_info.value.not_found is False


def test_readonly_connection_refuses_writes(tmp_path: Path) -> None:
    """A read-only open really is read-only, not merely a caller convention."""
    db_path = tmp_path / "m.db"
    MetricsDB(db_path).close()

    reader = MetricsDB.open_readonly(db_path)
    try:
        with pytest.raises(sqlite3.OperationalError):
            reader.record_launch(profile="flex", agent="codex", entry="exec")
    finally:
        reader.close()


@pytest.mark.parametrize(
    "message",
    [
        "unable to open database file",
        "attempt to write a readonly database",
        "UNABLE TO OPEN DATABASE FILE",
    ],
)
def test_looks_like_permission_denied_matches_known_markers(message: str) -> None:
    assert looks_like_permission_denied(message) is True


@pytest.mark.parametrize(
    "message", ["no such table: launches", "disk I/O error", "database is locked"]
)
def test_looks_like_permission_denied_rejects_structural_errors(message: str) -> None:
    assert looks_like_permission_denied(message) is False

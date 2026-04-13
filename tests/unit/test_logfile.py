"""Tests for append-only log file with rotation."""

from __future__ import annotations

from pathlib import Path


def test_append_creates_parent(tmp_path: Path) -> None:
    from lazy_harness.core.logfile import append

    log_path = tmp_path / "nested" / "deep" / "test.log"
    append(log_path, "hello")

    assert log_path.is_file()
    assert "hello" in log_path.read_text()


def test_append_prefixes_timestamp(tmp_path: Path) -> None:
    from lazy_harness.core.logfile import append

    log_path = tmp_path / "test.log"
    append(log_path, "some message")
    content = log_path.read_text()

    # Expected format: [YYYY-MM-DD HH:MM:SS] some message
    assert content.startswith("[")
    assert "] some message\n" in content


def test_append_accumulates_lines(tmp_path: Path) -> None:
    from lazy_harness.core.logfile import append

    log_path = tmp_path / "test.log"
    append(log_path, "first")
    append(log_path, "second")
    append(log_path, "third")

    lines = log_path.read_text().splitlines()
    assert len(lines) == 3
    assert "first" in lines[0]
    assert "second" in lines[1]
    assert "third" in lines[2]


def test_rotation_trims_to_tail(tmp_path: Path) -> None:
    from lazy_harness.core.logfile import append

    log_path = tmp_path / "test.log"
    # Write many lines with a tiny max_bytes so rotation kicks in
    for i in range(200):
        append(log_path, f"line-{i:04d}", max_bytes=512, tail_lines=10)

    lines = log_path.read_text().splitlines()
    # After rotation we keep only the tail; last append after rotation adds one more line
    assert len(lines) <= 11
    # The most recent line must be preserved
    assert "line-0199" in lines[-1]
    # The oldest kept line should be recent, not from the start
    assert "line-0000" not in log_path.read_text()


def test_rotation_skipped_when_under_threshold(tmp_path: Path) -> None:
    from lazy_harness.core.logfile import append

    log_path = tmp_path / "test.log"
    for i in range(5):
        append(log_path, f"line-{i}", max_bytes=10_000, tail_lines=2)

    lines = log_path.read_text().splitlines()
    assert len(lines) == 5


def test_append_silent_on_unwritable_path(tmp_path: Path) -> None:
    from lazy_harness.core.logfile import append

    # Use a path that cannot exist (parent is a file, not a dir)
    blocker = tmp_path / "blocker"
    blocker.write_text("I am a file")
    log_path = blocker / "child.log"

    # Must not raise
    append(log_path, "hello")


def test_default_log_dir_under_home() -> None:
    from lazy_harness.core.logfile import default_log_dir

    d = default_log_dir()
    assert d.name == "logs"
    assert d.parent.name == "lazy-harness"

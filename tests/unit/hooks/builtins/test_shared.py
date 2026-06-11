"""Tests for shared builtin-hook helpers."""

from __future__ import annotations

import os
import time
from pathlib import Path


def test_make_log_writes_prefixed_line_and_creates_parents(tmp_path: Path) -> None:
    from lazy_harness.hooks.builtins._shared import make_log

    log_file = tmp_path / "logs" / "hooks.log"
    _log = make_log("session-end")
    _log(log_file, "fired cwd=/tmp/x")

    content = log_file.read_text()
    assert content.endswith(" session-end: fired cwd=/tmp/x\n")
    # Timestamp prefix present (ISO format with seconds).
    ts = content.split(" session-end: ")[0]
    assert "T" in ts


def test_make_log_swallows_oserror(tmp_path: Path) -> None:
    from lazy_harness.hooks.builtins._shared import make_log

    blocker = tmp_path / "not-a-dir"
    blocker.write_text("file in the way")
    _log = make_log("pre-compact")
    # Parent of log_file is a regular file → mkdir/open raise; must not bubble.
    _log(blocker / "hooks.log", "must not raise")


def test_find_latest_session_returns_none_for_missing_dir(tmp_path: Path) -> None:
    from lazy_harness.hooks.builtins._shared import find_latest_session

    assert find_latest_session(tmp_path / "nope") is None


def test_find_latest_session_returns_none_when_no_jsonl(tmp_path: Path) -> None:
    from lazy_harness.hooks.builtins._shared import find_latest_session

    (tmp_path / "notes.md").write_text("x")
    assert find_latest_session(tmp_path) is None


def test_find_latest_session_picks_most_recent_jsonl(tmp_path: Path) -> None:
    from lazy_harness.hooks.builtins._shared import find_latest_session

    old = tmp_path / "old.jsonl"
    new = tmp_path / "new.jsonl"
    old.write_text("{}\n")
    new.write_text("{}\n")
    past = time.time() - 600
    os.utime(old, (past, past))

    assert find_latest_session(tmp_path) == new

import os
import time
from pathlib import Path

from lazy_harness.migrate.gate import (
    DRY_RUN_TTL_SECONDS,
    check_dry_run_gate,
    record_dry_run,
)


def test_gate_fails_when_no_marker(tmp_path: Path):
    ok, msg = check_dry_run_gate(tmp_path)
    assert ok is False
    assert "dry-run" in msg.lower()


def test_gate_passes_when_marker_fresh(tmp_path: Path):
    record_dry_run(tmp_path)
    ok, msg = check_dry_run_gate(tmp_path)
    assert ok is True


def test_gate_fails_when_marker_stale(tmp_path: Path):
    record_dry_run(tmp_path)
    marker = tmp_path / ".last-dry-run"
    stale = time.time() - DRY_RUN_TTL_SECONDS - 10
    os.utime(marker, (stale, stale))
    ok, msg = check_dry_run_gate(tmp_path)
    assert ok is False
    assert "stale" in msg.lower() or "expired" in msg.lower()

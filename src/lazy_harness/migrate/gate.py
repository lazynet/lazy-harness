from __future__ import annotations

import time
from pathlib import Path

DRY_RUN_TTL_SECONDS = 60 * 60  # 1 hour
MARKER_NAME = ".last-dry-run"


def record_dry_run(backup_parent: Path) -> Path:
    """Write the dry-run marker file with the current timestamp."""
    backup_parent.mkdir(parents=True, exist_ok=True)
    marker = backup_parent / MARKER_NAME
    marker.write_text(str(time.time()))
    return marker


def check_dry_run_gate(backup_parent: Path) -> tuple[bool, str]:
    """Return (ok, message). ok=True means a recent dry-run was found."""
    marker = backup_parent / MARKER_NAME
    if not marker.is_file():
        return False, "No dry-run marker found. Run `lh migrate --dry-run` first."
    age = time.time() - marker.stat().st_mtime
    if age > DRY_RUN_TTL_SECONDS:
        return False, "Dry-run marker is stale (>1 hour). Re-run `lh migrate --dry-run`."
    return True, "dry-run gate passed"

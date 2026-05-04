"""Deterministic mirror of decisions.jsonl/failures.jsonl into Engram.

Invoked from a Stop-hook wrapper after compound_loop.py has written its
new JSONL entries. Reads from a per-file byte cursor, calls `engram save`
once per new entry, advances the cursor only on success. Emits run-level
metrics to engram_persist_metrics.jsonl and errors to engram_persist.log.

Exit semantics belong to the wrapper. This module never calls sys.exit.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

SLOW_SAVE_THRESHOLD_MS: int = 500
TITLE_MAX_CHARS: int = 200

EntryKind = Literal["decision", "failure"]

_FILES: dict[EntryKind, str] = {
    "decision": "decisions.jsonl",
    "failure": "failures.jsonl",
}

_CURSOR_FILENAME: str = "engram_cursor.json"
_METRICS_FILENAME: str = "engram_persist_metrics.jsonl"
_ERROR_LOG_FILENAME: str = "engram_persist.log"


def _load_cursor(cursor_path: Path) -> dict[str, int]:
    """Load cursor offsets, resetting to zero on missing/corrupt/incomplete files."""
    default: dict[str, int] = {"decisions_offset": 0, "failures_offset": 0}
    if not cursor_path.is_file():
        return default
    try:
        data = json.loads(cursor_path.read_text())
    except (json.JSONDecodeError, OSError):
        return default
    if not isinstance(data, dict):
        return default
    if "decisions_offset" not in data or "failures_offset" not in data:
        return default
    try:
        return {
            "decisions_offset": int(data["decisions_offset"]),
            "failures_offset": int(data["failures_offset"]),
        }
    except (TypeError, ValueError):
        return default


def _save_cursor(cursor_path: Path, decisions_offset: int, failures_offset: int) -> None:
    """Atomic write: tempfile in same dir + os.replace."""
    cursor_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": 1,
        "decisions_offset": decisions_offset,
        "failures_offset": failures_offset,
        "updated_at": datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z"),
    }
    fd, tmp_name = tempfile.mkstemp(prefix=".engram_cursor.", suffix=".tmp", dir=cursor_path.parent)
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(payload, f)
        os.replace(tmp_name, cursor_path)
    except OSError:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        # Fail soft: cursor write failure means at-least-once becomes
        # at-least-twice on the next run, which is acceptable.


@dataclass
class PersistResult:
    saved_ok: int = 0
    saved_failed: int = 0
    skipped_malformed: int = 0
    entries_seen: dict[str, int] = field(default_factory=lambda: {"decision": 0, "failure": 0})
    cursor_lag_bytes: dict[str, int] = field(default_factory=lambda: {"decision": 0, "failure": 0})
    duration_ms: int = 0
    subprocess_ms: int = 0


def _build_title(entry: dict) -> str:
    raw = entry.get("summary") or ""
    if not raw or not isinstance(raw, str):
        kind = entry.get("type", "entry")
        ts = entry.get("ts", "unknown")
        return f"{kind}@{ts}"
    return raw[:TITLE_MAX_CHARS]


def _save_entry(
    engram_bin: str, entry: dict, kind: EntryKind, project_key: str
) -> tuple[bool, int]:
    """Invoke `engram save`. Returns (success, elapsed_ms)."""
    title = _build_title(entry)
    content = json.dumps(entry, sort_keys=True)
    cmd = [
        engram_bin,
        "save",
        title,
        content,
        "--type",
        kind,
        "--project",
        project_key,
        "--scope",
        "project",
    ]
    start = time.monotonic()
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    except OSError:
        return False, int((time.monotonic() - start) * 1000)
    elapsed_ms = int((time.monotonic() - start) * 1000)
    return proc.returncode == 0, elapsed_ms


class EngramPersister:
    def __init__(
        self,
        memory_dir: Path,
        logs_dir: Path,
        project_key: str,
        engram_bin: str | None = None,
        slow_save_threshold_ms: int = SLOW_SAVE_THRESHOLD_MS,
    ) -> None:
        self.memory_dir = memory_dir
        self.logs_dir = logs_dir
        self.project_key = project_key
        self.engram_bin = engram_bin if engram_bin is not None else shutil.which("engram")
        self.slow_save_threshold_ms = slow_save_threshold_ms

    def persist_new_entries(self) -> PersistResult:
        result = PersistResult()
        run_start = time.monotonic()

        if self.engram_bin is None:
            result.duration_ms = int((time.monotonic() - run_start) * 1000)
            return result

        cursor_path = self.memory_dir / _CURSOR_FILENAME
        cursor = _load_cursor(cursor_path)

        for kind in ("decision", "failure"):
            file_path = self.memory_dir / _FILES[kind]
            offset_key = f"{kind}s_offset"
            offset = cursor[offset_key]

            if not file_path.is_file():
                continue

            file_size = file_path.stat().st_size
            if offset > file_size:
                offset = 0  # truncated; reset (proper test in Task 4)

            with file_path.open("rb") as f:
                f.seek(offset)
                while True:
                    line_bytes = f.readline()
                    if not line_bytes:
                        break
                    if not line_bytes.endswith(b"\n"):
                        # Partial line at EOF — not yet finalised by writer.
                        break
                    result.entries_seen[kind] += 1
                    raw = line_bytes.decode("utf-8", errors="replace").rstrip("\n")
                    try:
                        entry = json.loads(raw)
                    except json.JSONDecodeError:
                        result.skipped_malformed += 1
                        offset = f.tell()
                        cursor[offset_key] = offset
                        _save_cursor(
                            cursor_path,
                            decisions_offset=cursor["decisions_offset"],
                            failures_offset=cursor["failures_offset"],
                        )
                        continue

                    ok, elapsed_ms = _save_entry(self.engram_bin, entry, kind, self.project_key)
                    result.subprocess_ms += elapsed_ms
                    if ok:
                        result.saved_ok += 1
                        offset = f.tell()
                        cursor[offset_key] = offset
                        _save_cursor(
                            cursor_path,
                            decisions_offset=cursor["decisions_offset"],
                            failures_offset=cursor["failures_offset"],
                        )
                    else:
                        result.saved_failed += 1
                        # Do NOT advance cursor; break to avoid pile-up this run.
                        break

            # Compute lag against final file size for metrics.
            result.cursor_lag_bytes[kind] = max(0, file_path.stat().st_size - offset)

        result.duration_ms = int((time.monotonic() - run_start) * 1000)
        return result

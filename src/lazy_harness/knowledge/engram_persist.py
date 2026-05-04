"""Deterministic mirror of decisions.jsonl/failures.jsonl into Engram.

Invoked from a Stop-hook wrapper after compound_loop.py has written its
new JSONL entries. Reads from a per-file byte cursor, calls `engram save`
once per new entry, advances the cursor only on success. Emits run-level
metrics to engram_persist_metrics.jsonl and errors to engram_persist.log.

Exit semantics belong to the wrapper. This module never calls sys.exit.
"""

from __future__ import annotations

import json  # noqa: F401
import os  # noqa: F401
import shutil
import subprocess  # noqa: F401
import tempfile  # noqa: F401
import time  # noqa: F401
from dataclasses import dataclass, field
from datetime import datetime, timezone  # noqa: F401
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


@dataclass
class PersistResult:
    saved_ok: int = 0
    saved_failed: int = 0
    skipped_malformed: int = 0
    entries_seen: dict[str, int] = field(default_factory=lambda: {"decision": 0, "failure": 0})
    cursor_lag_bytes: dict[str, int] = field(default_factory=lambda: {"decision": 0, "failure": 0})
    duration_ms: int = 0
    subprocess_ms: int = 0


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
        return PersistResult()

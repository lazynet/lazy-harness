"""Deterministic mirror of decisions.jsonl/failures.jsonl into Engram.

Invoked from a Stop-hook wrapper after compound_loop.py has written its
new JSONL entries. Reads from a per-file byte cursor, calls `engram save`
once per new entry, advances the cursor on success, or past an entry that
used up its attempts into engram_quarantine.jsonl. Emits run-level metrics
to engram_persist_metrics.jsonl and errors to engram_persist.log.

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
SAVE_TIMEOUT_SECONDS: int = 30
ERROR_MAX_CHARS: int = 1000
# A catch-up runs inside `Stop`, which the session waits on: 930 entries at
# ~150 ms each froze one for 145 s. The remainder drains on later runs.
MAX_SAVES_PER_RUN: int = 25
# Failed `engram save` exits an entry may take, one per run, before it moves
# to the quarantine sidecar. Without a bound one entry that always fails
# blocks every entry after it in that file, forever.
MAX_ATTEMPTS_PER_ENTRY: int = 5

EntryKind = Literal["decision", "failure"]

_FILES: dict[EntryKind, str] = {
    "decision": "decisions.jsonl",
    "failure": "failures.jsonl",
}

_CURSOR_FILENAME: str = "engram_cursor.json"
_METRICS_FILENAME: str = "engram_persist_metrics.jsonl"
_ERROR_LOG_FILENAME: str = "engram_persist.log"
_QUARANTINE_FILENAME: str = "engram_quarantine.jsonl"


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


def _load_retries(cursor_path: Path) -> dict[str, dict[str, int]]:
    """Failed attempts at the entry each file is stuck on, keyed by kind.

    Anything unreadable starts the count over: the worst case is a few more
    attempts before an entry is quarantined.
    """
    try:
        data = json.loads(cursor_path.read_text())
    except (json.JSONDecodeError, OSError):
        return {}
    raw = data.get("retries") if isinstance(data, dict) else None
    if not isinstance(raw, dict):
        return {}
    retries: dict[str, dict[str, int]] = {}
    for kind, state in raw.items():
        if kind not in _FILES or not isinstance(state, dict):
            continue
        offset, attempts = state.get("offset"), state.get("attempts")
        if isinstance(offset, int) and isinstance(attempts, int):
            retries[kind] = {"offset": offset, "attempts": attempts}
    return retries


def _save_cursor(
    cursor_path: Path,
    decisions_offset: int,
    failures_offset: int,
    retries: dict[str, dict[str, int]] | None = None,
) -> None:
    """Atomic write: tempfile in same dir + os.replace."""
    cursor_path.parent.mkdir(parents=True, exist_ok=True)
    payload: dict[str, object] = {
        "version": 1,
        "decisions_offset": decisions_offset,
        "failures_offset": failures_offset,
        "updated_at": datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z"),
    }
    if retries:
        payload["retries"] = retries
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


def _adopt_cursor(candidates: list[Path], *, fallback: Path) -> dict[str, int]:
    """The furthest offset any of `candidates` reached, per file.

    Every candidate fed the same database, so an entry one of them saved is
    already there. `fallback` — the copy in the synced store, which may come
    from another machine — is read only when no candidate exists.
    """
    existing = [c for c in candidates if c.is_file()]
    if not existing:
        return _load_cursor(fallback)
    loaded = [_load_cursor(c) for c in existing]
    return {key: max(c[key] for c in loaded) for key in ("decisions_offset", "failures_offset")}


@dataclass
class PersistResult:
    saved_ok: int = 0
    saved_failed: int = 0
    skipped_malformed: int = 0
    entries_seen: dict[str, int] = field(default_factory=lambda: {"decision": 0, "failure": 0})
    cursor_lag_bytes: dict[str, int] = field(default_factory=lambda: {"decision": 0, "failure": 0})
    cursor_advanced: bool = False
    save_cap_reached: bool = False
    duration_ms: int = 0
    subprocess_ms: int = 0
    quarantined: int = 0
    quarantined_total: int = 0


def _append_error_log(logs_dir: Path, message: str) -> None:
    try:
        logs_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().astimezone().isoformat(timespec="seconds")
        with (logs_dir / _ERROR_LOG_FILENAME).open("a") as f:
            f.write(f"{ts} engram-persist: {message}\n")
    except OSError:
        pass


def _append_quarantine(path: Path, record: dict[str, object]) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except OSError:
        pass


def _count_lines(path: Path) -> int:
    try:
        with path.open("rb") as f:
            return sum(1 for line in f if line.strip())
    except OSError:
        return 0


def _build_title(entry: dict) -> str:
    raw = entry.get("summary") or ""
    if not raw or not isinstance(raw, str):
        kind = entry.get("type", "entry")
        ts = entry.get("ts", "unknown")
        return f"{kind}@{ts}"
    return raw[:TITLE_MAX_CHARS]


def _one_line(stderr: str, stdout: str) -> str:
    """Both streams on one line, keeping the tail when it is too long.

    The log is read a line at a time, and engram prints an update banner
    ahead of its error: logged verbatim, the timestamped line carried the
    banner and the error sat on a later, unlabelled line. A CLI puts its
    error last, so truncation drops the head.
    """
    parts = []
    for name, text in (("stderr", stderr), ("stdout", stdout)):
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        if lines:
            parts.append(f"{name}: " + " | ".join(lines))
    message = " ;; ".join(parts) or "no output"
    if len(message) > ERROR_MAX_CHARS:
        message = "..." + message[-ERROR_MAX_CHARS:]
    return message


def _save_entry(
    engram_bin: str, entry: dict, kind: EntryKind, project_key: str
) -> tuple[bool, int, str, int]:
    """Invoke `engram save`. Returns (success, elapsed_ms, error, returncode)."""
    title = _build_title(entry)
    content = json.dumps(entry, sort_keys=True)
    # A summary starting with `--` was read as an unknown flag, and it failed
    # every run. engram only honours `--` after its flags: placed before
    # them it counts the flags as positionals too.
    cmd = [
        engram_bin,
        "save",
        "--type",
        kind,
        "--project",
        project_key,
        "--scope",
        "project",
        "--",
        title,
        content,
    ]
    start = time.monotonic()
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, check=False, timeout=SAVE_TIMEOUT_SECONDS
        )
    except subprocess.TimeoutExpired as e:
        return False, int((time.monotonic() - start) * 1000), str(e), -1
    except OSError as e:
        return False, int((time.monotonic() - start) * 1000), str(e), -1
    elapsed_ms = int((time.monotonic() - start) * 1000)
    return (
        proc.returncode == 0,
        elapsed_ms,
        _one_line(proc.stderr or "", proc.stdout or ""),
        proc.returncode,
    )


class EngramPersister:
    def __init__(
        self,
        memory_dir: Path,
        logs_dir: Path,
        project_key: str,
        engram_bin: str | None = None,
        slow_save_threshold_ms: int = SLOW_SAVE_THRESHOLD_MS,
        cursor_dir: Path | None = None,
        adopt_cursor_dirs: tuple[Path, ...] = (),
        max_saves_per_run: int = MAX_SAVES_PER_RUN,
    ) -> None:
        self.memory_dir = memory_dir
        self.logs_dir = logs_dir
        self.project_key = project_key
        # The offsets index files that travel between machines; the database
        # they feed does not. Keeping the cursor beside the JSONL published it,
        # and a machine that pulled someone else's cursor skipped every entry
        # between the two. None keeps the old location for callers that have
        # no machine-local directory to offer.
        self.cursor_dir = cursor_dir
        # Cursors this one replaces. Read once, when `cursor_dir` holds none yet.
        self.adopt_cursor_dirs = adopt_cursor_dirs
        self.max_saves_per_run = max_saves_per_run
        self.engram_bin = engram_bin if engram_bin is not None else shutil.which("engram")
        self.slow_save_threshold_ms = slow_save_threshold_ms

    def persist_new_entries(self) -> PersistResult:
        result = PersistResult()
        run_start = time.monotonic()

        if self.engram_bin is None or not Path(self.engram_bin).exists():
            _append_error_log(
                self.logs_dir,
                "engram binary not on PATH; skipping run (no-op)",
            )
            result.duration_ms = int((time.monotonic() - run_start) * 1000)
            # Emitted as its own event, never as a run: a skip that counted as a
            # successful run is why a 35%-no-op hook still reported 0% failures.
            _emit_skip_metric(self.logs_dir, self.project_key, "binary_not_found")
            return result

        cursor_path = (self.cursor_dir or self.memory_dir) / _CURSOR_FILENAME
        cursor = _load_cursor(cursor_path)
        if not cursor_path.is_file():
            # First run after the move: adopt what the old location knew, so a
            # machine that was up to date does not resave its whole history.
            cursor = _adopt_cursor(
                [d / _CURSOR_FILENAME for d in self.adopt_cursor_dirs],
                fallback=self.memory_dir / _CURSOR_FILENAME,
            )
            # Write it through immediately rather than on the next save. The
            # shared copy is on its way out of the store, and a cursor that
            # only ever exists there resets to zero the day it goes.
            _save_cursor(cursor_path, cursor["decisions_offset"], cursor["failures_offset"])

        start_cursor = _load_cursor(cursor_path)
        retries = _load_retries(cursor_path)
        quarantine_path = cursor_path.parent / _QUARANTINE_FILENAME
        attempted = 0
        for kind in ("decision", "failure"):
            file_path = self.memory_dir / _FILES[kind]
            offset_key = f"{kind}s_offset"
            offset = cursor[offset_key]

            if not file_path.is_file():
                continue

            file_size = file_path.stat().st_size
            if offset > file_size:
                offset = 0  # truncated; reset

            with file_path.open("rb") as f:
                f.seek(offset)
                while True:
                    line_bytes = f.readline()
                    if not line_bytes:
                        break
                    if not line_bytes.endswith(b"\n"):
                        # Partial line at EOF — not yet finalised by writer.
                        break
                    if attempted >= self.max_saves_per_run:
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
                            retries=retries,
                        )
                        continue

                    attempted += 1
                    ok, elapsed_ms, error, rc = _save_entry(
                        self.engram_bin, entry, kind, self.project_key
                    )
                    result.subprocess_ms += elapsed_ms
                    if ok:
                        result.saved_ok += 1
                        retries.pop(kind, None)
                        offset = f.tell()
                        cursor[offset_key] = offset
                        _save_cursor(
                            cursor_path,
                            decisions_offset=cursor["decisions_offset"],
                            failures_offset=cursor["failures_offset"],
                            retries=retries,
                        )
                        if elapsed_ms >= self.slow_save_threshold_ms:
                            _emit_slow_save(
                                self.logs_dir,
                                kind,
                                elapsed_ms,
                                _build_title(entry),
                            )
                    else:
                        result.saved_failed += 1
                        _append_error_log(
                            self.logs_dir,
                            f"engram save returned {rc} for {kind} entry "
                            f"at offset={offset}: {error}",
                        )
                        if rc < 0:
                            # A timeout or a binary that never started says
                            # nothing about the entry, so it uses no attempt.
                            break
                        previous = retries.get(kind)
                        attempts = (
                            previous["attempts"] + 1
                            if previous and previous["offset"] == offset
                            else 1
                        )
                        if attempts < MAX_ATTEMPTS_PER_ENTRY:
                            retries[kind] = {"offset": offset, "attempts": attempts}
                            _save_cursor(
                                cursor_path,
                                decisions_offset=cursor["decisions_offset"],
                                failures_offset=cursor["failures_offset"],
                                retries=retries,
                            )
                            # Do NOT advance cursor; break to avoid pile-up this run.
                            break
                        _append_quarantine(
                            quarantine_path,
                            {
                                "ts": datetime.now(UTC)
                                .isoformat(timespec="seconds")
                                .replace("+00:00", "Z"),
                                "project_key": self.project_key,
                                "kind": kind,
                                "file": str(file_path),
                                "offset": offset,
                                "attempts": attempts,
                                "returncode": rc,
                                "error": error,
                                "line": raw,
                            },
                        )
                        _append_error_log(
                            self.logs_dir,
                            f"quarantined {kind} entry at offset={offset} after "
                            f"{attempts} attempts: {quarantine_path}",
                        )
                        result.quarantined += 1
                        retries.pop(kind, None)
                        offset = f.tell()
                        cursor[offset_key] = offset
                        _save_cursor(
                            cursor_path,
                            decisions_offset=cursor["decisions_offset"],
                            failures_offset=cursor["failures_offset"],
                            retries=retries,
                        )

        persisted = _load_cursor(cursor_path)
        result.cursor_advanced = any(
            persisted[key] > start_cursor[key] for key in ("decisions_offset", "failures_offset")
        )
        result.save_cap_reached = attempted >= self.max_saves_per_run
        result.quarantined_total = _count_lines(quarantine_path)
        for kind in ("decision", "failure"):
            file_path = self.memory_dir / _FILES[kind]
            if file_path.is_file():
                result.cursor_lag_bytes[kind] = max(
                    0, file_path.stat().st_size - persisted[f"{kind}s_offset"]
                )

        result.duration_ms = int((time.monotonic() - run_start) * 1000)
        _emit_run_metric(self.logs_dir, result, self.project_key, self.engram_bin)
        return result


def _engram_version(engram_bin: str) -> str:
    try:
        proc = subprocess.run(
            [engram_bin, "version"],
            capture_output=True,
            text=True,
            check=False,
            timeout=2,
        )
        if proc.returncode == 0:
            # Output like "engram v1.15.4"
            tokens = proc.stdout.strip().split()
            return tokens[-1] if tokens else "unknown"
    except (OSError, subprocess.TimeoutExpired):
        pass
    return "unknown"


def _hook_version() -> str:
    try:
        from lazy_harness import __version__

        return __version__
    except Exception:
        return "unknown"


def _emit_slow_save(logs_dir: Path, kind: EntryKind, ms: int, title: str) -> None:
    record = {
        "ts": datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "event": "slow_save",
        "ms": ms,
        "type": kind,
        "title_prefix": title[:60],
    }
    try:
        logs_dir.mkdir(parents=True, exist_ok=True)
        with (logs_dir / _METRICS_FILENAME).open("a") as f:
            f.write(json.dumps(record) + "\n")
    except OSError:
        pass


def _emit_skip_metric(logs_dir: Path, project_key: str, reason: str) -> None:
    """Record a run that never happened, so health checks can see the gap."""
    record = {
        "ts": datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "event": "skip",
        "reason": reason,
        "project_key": project_key,
        "hook_version": _hook_version(),
    }
    try:
        logs_dir.mkdir(parents=True, exist_ok=True)
        with (logs_dir / _METRICS_FILENAME).open("a") as f:
            f.write(json.dumps(record) + "\n")
    except OSError:
        pass


def _emit_run_metric(
    logs_dir: Path,
    result: PersistResult,
    project_key: str,
    engram_bin: str,
) -> None:
    record = {
        "ts": datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "event": "run",
        "duration_ms": result.duration_ms,
        "subprocess_ms": result.subprocess_ms,
        "entries_seen": {
            "decisions": result.entries_seen["decision"],
            "failures": result.entries_seen["failure"],
        },
        "saved_ok": result.saved_ok,
        "saved_failed": result.saved_failed,
        "skipped_malformed": result.skipped_malformed,
        "cursor_lag_bytes": {
            "decisions": result.cursor_lag_bytes["decision"],
            "failures": result.cursor_lag_bytes["failure"],
        },
        "cursor_advanced": result.cursor_advanced,
        "save_cap_reached": result.save_cap_reached,
        "quarantined": result.quarantined,
        "quarantined_total": result.quarantined_total,
        "project_key": project_key,
        "engram_version": _engram_version(engram_bin),
        "hook_version": _hook_version(),
    }
    try:
        logs_dir.mkdir(parents=True, exist_ok=True)
        with (logs_dir / _METRICS_FILENAME).open("a") as f:
            f.write(json.dumps(record) + "\n")
    except OSError:
        pass

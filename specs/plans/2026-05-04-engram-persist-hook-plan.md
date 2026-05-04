# Engram persist built-in hook — implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a built-in `engram-persist` hook that runs on every `Stop` event, after `compound_loop.py`, and mirrors every new entry in `decisions.jsonl`/`failures.jsonl` to Engram via `engram save` (CLI subprocess), with exactly-once semantics enforced by per-file byte cursors.

**Architecture:** Thin builtin wrapper (`hooks/builtins/engram_persist.py`) reads the CC payload from stdin, resolves directories, and delegates to `EngramPersister` in `knowledge/engram_persist.py`. The persister loads a cursor file, walks new lines from each JSONL, invokes `engram save` per entry, and advances the cursor only on `rc=0`. Run-summary metrics and slow-save events go to a JSONL log; errors go to a separate text log. Hook exits 0 unconditionally — never blocks the Stop chain.

**Tech Stack:** Python 3.11+ stdlib only (`json`, `os`, `shutil`, `subprocess`, `tempfile`, `time`, `pathlib`, `datetime`, `dataclasses`, `typing`). pytest with `unittest.mock.patch` for subprocess mocking. No new dependencies.

**Spec:** `specs/designs/2026-05-04-engram-persist-hook-design.md`
**Related ADRs:** ADR-006 (hooks-subprocess-json), ADR-008 (compound-loop-insight-capture), ADR-027 (memory-stack-overview), ADR-029 (engram-persist-deterministic-mirror — created in this plan).

---

## File Structure

| File | Purpose | Status |
|------|---------|--------|
| `src/lazy_harness/knowledge/engram_persist.py` | Core logic: `EngramPersister`, cursor I/O, subprocess invocation, metrics emission | Create |
| `src/lazy_harness/hooks/builtins/engram_persist.py` | Thin wrapper: reads stdin, resolves dirs, runs persister, exits 0 | Create |
| `src/lazy_harness/hooks/loader.py` | Register `"engram-persist"` in `_BUILTIN_HOOKS` | Modify (1 line) |
| `tests/unit/test_engram_persist.py` | Unit tests for `EngramPersister` (subprocess mocked) | Create |
| `tests/unit/test_builtin_engram_persist.py` | Subprocess-level tests for the wrapper using a stub `engram` shim | Create |
| `specs/adrs/029-engram-persist-deterministic-mirror.md` | New ADR | Create |
| `specs/adrs/README.md` | Append index entry for ADR-029 | Modify |

---

## Setup: Worktree

The repo's non-negotiable #1 is "worktrees for every code change". Create the worktree before Task 1.

- [ ] **Step S1: Create worktree and feature branch**

Run from the main checkout (`~/repos/lazy/lazy-harness/`):

```bash
git worktree add .worktrees/engram-persist -b feat/engram-persist-hook main
cd .worktrees/engram-persist
```

Expected: new dir `.worktrees/engram-persist/` containing the working tree on branch `feat/engram-persist-hook`. The spec written on `main` (`specs/designs/2026-05-04-engram-persist-hook-design.md`) must already be committed before this step — if it is uncommitted, commit it on `main` first via the doc short path:

```bash
git -C ~/repos/lazy/lazy-harness add specs/designs/2026-05-04-engram-persist-hook-design.md specs/plans/2026-05-04-engram-persist-hook-plan.md
git -C ~/repos/lazy/lazy-harness commit -m "docs: spec + plan for engram-persist hook (ADR-029)"
```

After committing, create the worktree from the latest `main`. All subsequent work happens in the worktree.

---

## Task 1: Skeleton — knowledge module + builtin wrapper + registration

**Files:**
- Create: `src/lazy_harness/knowledge/engram_persist.py`
- Create: `src/lazy_harness/hooks/builtins/engram_persist.py`
- Modify: `src/lazy_harness/hooks/loader.py`
- Test: `tests/unit/test_engram_persist.py`

**Why first:** lays the module structure, registers the hook so `lh hook list` and the hook resolver can see it, and lands a single trivial test ("instantiation does not crash"). Subsequent tasks can build on a green baseline.

- [ ] **Step 1.1: Write the failing test**

Create `tests/unit/test_engram_persist.py`:

```python
"""Tests for knowledge.engram_persist — EngramPersister core logic."""

from __future__ import annotations

from pathlib import Path

from lazy_harness.knowledge.engram_persist import EngramPersister, PersistResult


def test_persister_can_be_instantiated_with_required_args(tmp_path: Path) -> None:
    memory_dir = tmp_path / "memory"
    logs_dir = tmp_path / "logs"
    memory_dir.mkdir()
    logs_dir.mkdir()

    persister = EngramPersister(
        memory_dir=memory_dir,
        logs_dir=logs_dir,
        project_key="lazy-harness",
        engram_bin="/usr/bin/false",  # never invoked in this test
    )

    assert persister.memory_dir == memory_dir
    assert persister.logs_dir == logs_dir
    assert persister.project_key == "lazy-harness"


def test_persist_returns_zero_counts_when_no_jsonl_files_present(tmp_path: Path) -> None:
    memory_dir = tmp_path / "memory"
    logs_dir = tmp_path / "logs"
    memory_dir.mkdir()
    logs_dir.mkdir()

    persister = EngramPersister(
        memory_dir=memory_dir,
        logs_dir=logs_dir,
        project_key="lazy-harness",
        engram_bin="/usr/bin/false",
    )

    result: PersistResult = persister.persist_new_entries()

    assert result.saved_ok == 0
    assert result.saved_failed == 0
    assert result.skipped_malformed == 0
    assert result.entries_seen == {"decision": 0, "failure": 0}
```

- [ ] **Step 1.2: Run the tests and confirm they fail with ImportError**

```bash
cd .worktrees/engram-persist
uv run pytest tests/unit/test_engram_persist.py -v
```

Expected: `ImportError` or `ModuleNotFoundError` on `lazy_harness.knowledge.engram_persist`.

- [ ] **Step 1.3: Create the knowledge module skeleton**

Create `src/lazy_harness/knowledge/engram_persist.py`:

```python
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
from datetime import datetime, timezone
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
    entries_seen: dict[str, int] = field(
        default_factory=lambda: {"decision": 0, "failure": 0}
    )
    cursor_lag_bytes: dict[str, int] = field(
        default_factory=lambda: {"decision": 0, "failure": 0}
    )
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
```

- [ ] **Step 1.4: Create the builtin wrapper skeleton**

Create `src/lazy_harness/hooks/builtins/engram_persist.py`:

```python
#!/usr/bin/env python3
"""Stop hook: mirror new JSONL entries into Engram via `engram save`.

Always exits 0 — a failure here must never block Claude Code's Stop chain.
All real work lives in lazy_harness.knowledge.engram_persist.EngramPersister.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path


def _resolve_project_key(cwd: Path) -> str:
    return cwd.name


def main() -> None:
    payload: dict = {}
    try:
        payload = json.load(sys.stdin) or {}
    except (json.JSONDecodeError, EOFError, ValueError):
        pass

    cwd = Path(payload.get("cwd") or Path.cwd())

    try:
        from lazy_harness.knowledge.engram_persist import EngramPersister
    except ImportError:
        return

    claude_dir = Path(os.environ.get("CLAUDE_CONFIG_DIR", Path.home() / ".claude"))
    encoded = "-" + str(cwd).replace("/", "-").lstrip("-")
    memory_dir = claude_dir / "projects" / encoded / "memory"
    logs_dir = claude_dir / "logs"

    persister = EngramPersister(
        memory_dir=memory_dir,
        logs_dir=logs_dir,
        project_key=_resolve_project_key(cwd),
    )
    try:
        persister.persist_new_entries()
    except Exception:
        # Never propagate. Wrapper guarantees exit 0.
        pass


if __name__ == "__main__":
    main()
```

- [ ] **Step 1.5: Register the hook in the loader**

Modify `src/lazy_harness/hooks/loader.py`. In the `_BUILTIN_HOOKS` dict, add the `engram-persist` entry in alphabetical order (between `context-inject` and `post-compact`):

```python
_BUILTIN_HOOKS: dict[str, str] = {
    "compound-loop": "lazy_harness.hooks.builtins.compound_loop",
    "context-inject": "lazy_harness.hooks.builtins.context_inject",
    "engram-persist": "lazy_harness.hooks.builtins.engram_persist",
    "post-compact": "lazy_harness.hooks.builtins.post_compact",
    "post-tool-use-format": "lazy_harness.hooks.builtins.post_tool_use_format",
    "pre-compact": "lazy_harness.hooks.builtins.pre_compact",
    "pre-tool-use-security": "lazy_harness.hooks.builtins.pre_tool_use_security",
    "session-end": "lazy_harness.hooks.builtins.session_end",
    "session-export": "lazy_harness.hooks.builtins.session_export",
}
```

- [ ] **Step 1.6: Run the tests and confirm they pass**

```bash
uv run pytest tests/unit/test_engram_persist.py -v
```

Expected: 2 passed.

- [ ] **Step 1.7: Run the existing loader tests**

```bash
uv run pytest tests/unit/ -k "loader or hook" -v
```

Expected: all existing tests still pass; the registration does not break anything.

- [ ] **Step 1.8: Commit**

```bash
git add src/lazy_harness/knowledge/engram_persist.py \
        src/lazy_harness/hooks/builtins/engram_persist.py \
        src/lazy_harness/hooks/loader.py \
        tests/unit/test_engram_persist.py
git commit -m "feat(hooks): scaffold engram-persist builtin and persister"
```

---

## Task 2: Cursor management

**Files:**
- Modify: `src/lazy_harness/knowledge/engram_persist.py`
- Modify: `tests/unit/test_engram_persist.py`

**Why next:** the cursor is the linchpin of the at-least-once contract. All later tests depend on cursors working correctly.

- [ ] **Step 2.1: Write failing tests for cursor I/O**

Append to `tests/unit/test_engram_persist.py`:

```python
def test_load_cursor_returns_zero_offsets_when_file_missing(tmp_path: Path) -> None:
    from lazy_harness.knowledge.engram_persist import _load_cursor

    cursor = _load_cursor(tmp_path / "engram_cursor.json")

    assert cursor == {"decisions_offset": 0, "failures_offset": 0}


def test_load_cursor_reads_valid_json(tmp_path: Path) -> None:
    from lazy_harness.knowledge.engram_persist import _load_cursor

    cursor_path = tmp_path / "engram_cursor.json"
    cursor_path.write_text(
        '{"version": 1, "decisions_offset": 4523, "failures_offset": 1820, '
        '"updated_at": "2026-05-04T11:25:00Z"}'
    )

    cursor = _load_cursor(cursor_path)

    assert cursor["decisions_offset"] == 4523
    assert cursor["failures_offset"] == 1820


def test_load_cursor_resets_on_corrupt_json(tmp_path: Path) -> None:
    from lazy_harness.knowledge.engram_persist import _load_cursor

    cursor_path = tmp_path / "engram_cursor.json"
    cursor_path.write_text("not valid json {{{")

    cursor = _load_cursor(cursor_path)

    assert cursor == {"decisions_offset": 0, "failures_offset": 0}


def test_load_cursor_resets_on_missing_keys(tmp_path: Path) -> None:
    from lazy_harness.knowledge.engram_persist import _load_cursor

    cursor_path = tmp_path / "engram_cursor.json"
    cursor_path.write_text('{"version": 1}')

    cursor = _load_cursor(cursor_path)

    assert cursor == {"decisions_offset": 0, "failures_offset": 0}


def test_save_cursor_writes_atomically(tmp_path: Path) -> None:
    from lazy_harness.knowledge.engram_persist import _save_cursor

    cursor_path = tmp_path / "engram_cursor.json"

    _save_cursor(cursor_path, decisions_offset=100, failures_offset=200)

    data = json.loads(cursor_path.read_text())
    assert data["decisions_offset"] == 100
    assert data["failures_offset"] == 200
    assert data["version"] == 1
    assert "updated_at" in data
    # No leftover tempfiles in the parent dir
    assert not any(p.name.startswith("tmp") for p in tmp_path.iterdir() if p.is_file())
```

The test file imports `json` already; if not, add `import json` to the top.

- [ ] **Step 2.2: Run tests and confirm they fail**

```bash
uv run pytest tests/unit/test_engram_persist.py -v
```

Expected: 4 new tests fail with `ImportError` on `_load_cursor` / `_save_cursor`.

- [ ] **Step 2.3: Implement cursor I/O**

In `src/lazy_harness/knowledge/engram_persist.py`, add helpers near the top (below the constants, above `PersistResult`):

```python
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


def _save_cursor(
    cursor_path: Path, decisions_offset: int, failures_offset: int
) -> None:
    """Atomic write: tempfile in same dir + os.replace."""
    cursor_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": 1,
        "decisions_offset": decisions_offset,
        "failures_offset": failures_offset,
        "updated_at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace(
            "+00:00", "Z"
        ),
    }
    fd, tmp_name = tempfile.mkstemp(
        prefix=".engram_cursor.", suffix=".tmp", dir=cursor_path.parent
    )
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(payload, f)
        os.replace(tmp_name, cursor_path)
    except OSError:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise
```

The tempfile prefix is dotted (`.engram_cursor.`) so the assertion in the test (no `tmp*` files leftover) passes — the file uses a leading dot, then `engram_cursor.`, then the random suffix; once `os.replace` succeeds, the tempfile is gone.

- [ ] **Step 2.4: Run tests and confirm they pass**

```bash
uv run pytest tests/unit/test_engram_persist.py -v
```

Expected: 6 passed.

- [ ] **Step 2.5: Commit**

```bash
git add src/lazy_harness/knowledge/engram_persist.py tests/unit/test_engram_persist.py
git commit -m "feat(engram-persist): add cursor load/save helpers with corruption recovery"
```

---

## Task 3: Engram save invocation — happy path for both kinds

**Files:**
- Modify: `src/lazy_harness/knowledge/engram_persist.py`
- Modify: `tests/unit/test_engram_persist.py`

- [ ] **Step 3.1: Write failing tests for the save call**

Append to `tests/unit/test_engram_persist.py`:

```python
from unittest.mock import MagicMock, patch


def _seed_jsonl(memory_dir: Path, kind: str, entries: list[dict]) -> Path:
    filename = "decisions.jsonl" if kind == "decision" else "failures.jsonl"
    path = memory_dir / filename
    path.write_text("\n".join(json.dumps(e) for e in entries) + "\n")
    return path


def _persister(tmp_path: Path, engram_bin: str = "/fake/engram") -> EngramPersister:
    memory_dir = tmp_path / "memory"
    logs_dir = tmp_path / "logs"
    memory_dir.mkdir()
    logs_dir.mkdir()
    return EngramPersister(
        memory_dir=memory_dir,
        logs_dir=logs_dir,
        project_key="lazy-harness",
        engram_bin=engram_bin,
    )


def test_persists_new_decision_entries_via_engram_save(tmp_path: Path) -> None:
    persister = _persister(tmp_path)
    entries = [
        {
            "ts": "2026-05-04T11:00:00Z",
            "type": "decision",
            "summary": "Use CLI not MCP for hook",
            "rationale": "Independence from server state",
        }
    ]
    _seed_jsonl(persister.memory_dir, "decision", entries)

    with patch(
        "lazy_harness.knowledge.engram_persist.subprocess.run"
    ) as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        result = persister.persist_new_entries()

    assert result.saved_ok == 1
    assert result.saved_failed == 0
    mock_run.assert_called_once()
    args = mock_run.call_args.args[0]
    assert args[0] == "/fake/engram"
    assert args[1] == "save"
    assert args[2] == "Use CLI not MCP for hook"
    assert json.loads(args[3]) == entries[0]
    assert "--type" in args and args[args.index("--type") + 1] == "decision"
    assert "--project" in args and args[args.index("--project") + 1] == "lazy-harness"
    assert "--scope" in args and args[args.index("--scope") + 1] == "project"


def test_persists_failure_entries_with_failure_type(tmp_path: Path) -> None:
    persister = _persister(tmp_path)
    entries = [
        {
            "ts": "2026-05-04T11:00:00Z",
            "type": "failure",
            "summary": "Worker lock not refreshed",
            "root_cause": "Missing touch() in heartbeat path",
        }
    ]
    _seed_jsonl(persister.memory_dir, "failure", entries)

    with patch(
        "lazy_harness.knowledge.engram_persist.subprocess.run"
    ) as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        persister.persist_new_entries()

    args = mock_run.call_args.args[0]
    assert args[args.index("--type") + 1] == "failure"


def test_title_falls_back_when_summary_missing(tmp_path: Path) -> None:
    persister = _persister(tmp_path)
    entries = [
        {"ts": "2026-05-04T11:00:00Z", "type": "decision"}  # no summary
    ]
    _seed_jsonl(persister.memory_dir, "decision", entries)

    with patch(
        "lazy_harness.knowledge.engram_persist.subprocess.run"
    ) as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        persister.persist_new_entries()

    args = mock_run.call_args.args[0]
    assert args[2] == "decision@2026-05-04T11:00:00Z"


def test_title_truncated_to_max_chars(tmp_path: Path) -> None:
    persister = _persister(tmp_path)
    long = "x" * 500
    entries = [{"ts": "2026-05-04T11:00:00Z", "type": "decision", "summary": long}]
    _seed_jsonl(persister.memory_dir, "decision", entries)

    with patch(
        "lazy_harness.knowledge.engram_persist.subprocess.run"
    ) as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        persister.persist_new_entries()

    args = mock_run.call_args.args[0]
    assert len(args[2]) == 200  # TITLE_MAX_CHARS
```

- [ ] **Step 3.2: Run tests and confirm they fail**

```bash
uv run pytest tests/unit/test_engram_persist.py -v
```

Expected: the new tests fail (subprocess.run is never called because `persist_new_entries` returns the dataclass with zero counts).

- [ ] **Step 3.3: Implement the save loop and helpers**

Replace the placeholder body of `persist_new_entries` and add helpers in `src/lazy_harness/knowledge/engram_persist.py`:

```python
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
```

Now rewrite `EngramPersister.persist_new_entries`:

```python
    def persist_new_entries(self) -> PersistResult:
        result = PersistResult()
        run_start = time.monotonic()

        if self.engram_bin is None or not Path(self.engram_bin).exists():
            # Handled in a later task. For now: return zeros.
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
                    line_start = f.tell()
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

                    ok, elapsed_ms = _save_entry(
                        self.engram_bin, entry, kind, self.project_key
                    )
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
```

- [ ] **Step 3.4: Run tests and confirm they pass**

```bash
uv run pytest tests/unit/test_engram_persist.py -v
```

Expected: 10 passed (6 from Task 2 + 4 new). The earlier `test_persist_returns_zero_counts_when_no_jsonl_files_present` still passes because the loop simply skips both files.

- [ ] **Step 3.5: Commit**

```bash
git add src/lazy_harness/knowledge/engram_persist.py tests/unit/test_engram_persist.py
git commit -m "feat(engram-persist): mirror new JSONL entries to engram via subprocess"
```

---

## Task 4: Cursor advancement semantics

**Files:**
- Modify: `tests/unit/test_engram_persist.py`

The behaviour is already implemented in Task 3, but the contract tests need to lock it in.

- [ ] **Step 4.1: Add the semantics tests**

Append to `tests/unit/test_engram_persist.py`:

```python
def test_advances_cursor_only_on_successful_save(tmp_path: Path) -> None:
    persister = _persister(tmp_path)
    entries = [{"ts": "T1", "type": "decision", "summary": "first"}]
    _seed_jsonl(persister.memory_dir, "decision", entries)

    with patch(
        "lazy_harness.knowledge.engram_persist.subprocess.run"
    ) as mock_run:
        mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="boom")
        result = persister.persist_new_entries()

    assert result.saved_ok == 0
    assert result.saved_failed == 1
    cursor_file = persister.memory_dir / "engram_cursor.json"
    if cursor_file.is_file():
        cursor = json.loads(cursor_file.read_text())
        assert cursor["decisions_offset"] == 0  # never advanced


def test_skips_already_persisted_entries_on_second_run(tmp_path: Path) -> None:
    persister = _persister(tmp_path)
    entries = [
        {"ts": "T1", "type": "decision", "summary": "first"},
        {"ts": "T2", "type": "decision", "summary": "second"},
    ]
    _seed_jsonl(persister.memory_dir, "decision", entries)

    with patch(
        "lazy_harness.knowledge.engram_persist.subprocess.run"
    ) as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        persister.persist_new_entries()
        first_call_count = mock_run.call_count
        # Second run with no new entries
        result = persister.persist_new_entries()

    assert first_call_count == 2
    assert result.saved_ok == 0
    assert mock_run.call_count == 2  # no additional calls


def test_handles_malformed_jsonl_line_between_valid_lines(tmp_path: Path) -> None:
    persister = _persister(tmp_path)
    valid_a = json.dumps({"ts": "T1", "type": "decision", "summary": "a"})
    valid_b = json.dumps({"ts": "T2", "type": "decision", "summary": "b"})
    bad = "{ this is not json"
    (persister.memory_dir / "decisions.jsonl").write_text(
        valid_a + "\n" + bad + "\n" + valid_b + "\n"
    )

    with patch(
        "lazy_harness.knowledge.engram_persist.subprocess.run"
    ) as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        result = persister.persist_new_entries()

    assert result.saved_ok == 2
    assert result.skipped_malformed == 1
    # Both valid entries saved, malformed line counted; cursor at EOF.
    cursor = json.loads((persister.memory_dir / "engram_cursor.json").read_text())
    assert cursor["decisions_offset"] == (
        persister.memory_dir / "decisions.jsonl"
    ).stat().st_size


def test_breaks_inner_loop_on_save_failure(tmp_path: Path) -> None:
    persister = _persister(tmp_path)
    entries = [
        {"ts": "T1", "type": "decision", "summary": "first"},
        {"ts": "T2", "type": "decision", "summary": "second"},
        {"ts": "T3", "type": "decision", "summary": "third"},
    ]
    _seed_jsonl(persister.memory_dir, "decision", entries)

    side_effects = [
        MagicMock(returncode=0, stdout="", stderr=""),
        MagicMock(returncode=1, stdout="", stderr="boom"),
        MagicMock(returncode=0, stdout="", stderr=""),
    ]

    with patch(
        "lazy_harness.knowledge.engram_persist.subprocess.run",
        side_effect=side_effects,
    ) as mock_run:
        result = persister.persist_new_entries()

    assert result.saved_ok == 1
    assert result.saved_failed == 1
    # Third entry NOT attempted in this run
    assert mock_run.call_count == 2


def test_resets_cursor_when_offset_exceeds_file_size(tmp_path: Path) -> None:
    persister = _persister(tmp_path)
    entries = [{"ts": "T1", "type": "decision", "summary": "first"}]
    _seed_jsonl(persister.memory_dir, "decision", entries)

    # Pre-seed a cursor that points past EOF (truncation simulation)
    (persister.memory_dir / "engram_cursor.json").write_text(
        json.dumps(
            {
                "version": 1,
                "decisions_offset": 9999,
                "failures_offset": 0,
                "updated_at": "2026-05-04T00:00:00Z",
            }
        )
    )

    with patch(
        "lazy_harness.knowledge.engram_persist.subprocess.run"
    ) as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        result = persister.persist_new_entries()

    assert result.saved_ok == 1


def test_failures_and_decisions_have_independent_cursors(tmp_path: Path) -> None:
    persister = _persister(tmp_path)
    decisions = [{"ts": "D1", "type": "decision", "summary": "d"}]
    failures = [{"ts": "F1", "type": "failure", "summary": "f"}]
    _seed_jsonl(persister.memory_dir, "decision", decisions)
    _seed_jsonl(persister.memory_dir, "failure", failures)

    with patch(
        "lazy_harness.knowledge.engram_persist.subprocess.run"
    ) as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        persister.persist_new_entries()

    cursor = json.loads((persister.memory_dir / "engram_cursor.json").read_text())
    decisions_size = (persister.memory_dir / "decisions.jsonl").stat().st_size
    failures_size = (persister.memory_dir / "failures.jsonl").stat().st_size
    assert cursor["decisions_offset"] == decisions_size
    assert cursor["failures_offset"] == failures_size
```

- [ ] **Step 4.2: Run tests and confirm they pass**

```bash
uv run pytest tests/unit/test_engram_persist.py -v
```

Expected: 16 passed.

- [ ] **Step 4.3: Commit**

```bash
git add tests/unit/test_engram_persist.py
git commit -m "test(engram-persist): lock in cursor advancement and recovery contract"
```

---

## Task 5: Missing engram binary — silent no-op

**Files:**
- Modify: `src/lazy_harness/knowledge/engram_persist.py`
- Modify: `tests/unit/test_engram_persist.py`

- [ ] **Step 5.1: Write failing test**

Append to `tests/unit/test_engram_persist.py`:

```python
def test_handles_missing_engram_binary_gracefully(tmp_path: Path) -> None:
    memory_dir = tmp_path / "memory"
    logs_dir = tmp_path / "logs"
    memory_dir.mkdir()
    logs_dir.mkdir()
    entries = [{"ts": "T1", "type": "decision", "summary": "x"}]
    _seed_jsonl(memory_dir, "decision", entries)

    persister = EngramPersister(
        memory_dir=memory_dir,
        logs_dir=logs_dir,
        project_key="lazy-harness",
        engram_bin=None,  # binary not on PATH
    )

    with patch("lazy_harness.knowledge.engram_persist.subprocess.run") as mock_run:
        result = persister.persist_new_entries()

    mock_run.assert_not_called()
    assert result.saved_ok == 0
    # Warning written to error log
    log_path = logs_dir / "engram_persist.log"
    assert log_path.is_file()
    assert "engram binary not on PATH" in log_path.read_text()
```

- [ ] **Step 5.2: Run test and confirm it fails**

```bash
uv run pytest tests/unit/test_engram_persist.py::test_handles_missing_engram_binary_gracefully -v
```

Expected: FAIL — log file is not created today.

- [ ] **Step 5.3: Implement error logging on missing binary**

In `src/lazy_harness/knowledge/engram_persist.py`, add a helper near the other helpers:

```python
def _append_error_log(logs_dir: Path, message: str) -> None:
    try:
        logs_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().astimezone().isoformat(timespec="seconds")
        with (logs_dir / _ERROR_LOG_FILENAME).open("a") as f:
            f.write(f"{ts} engram-persist: {message}\n")
    except OSError:
        pass
```

Update the early-return branch in `persist_new_entries`:

```python
        if self.engram_bin is None or not Path(self.engram_bin).exists():
            _append_error_log(
                self.logs_dir,
                "engram binary not on PATH; skipping run (no-op)",
            )
            result.duration_ms = int((time.monotonic() - run_start) * 1000)
            return result
```

- [ ] **Step 5.4: Run tests and confirm they pass**

```bash
uv run pytest tests/unit/test_engram_persist.py -v
```

Expected: 17 passed.

- [ ] **Step 5.5: Commit**

```bash
git add src/lazy_harness/knowledge/engram_persist.py tests/unit/test_engram_persist.py
git commit -m "feat(engram-persist): no-op gracefully when engram binary absent"
```

---

## Task 6: Project key resolution

**Files:**
- Modify: `src/lazy_harness/hooks/builtins/engram_persist.py`
- Modify: `tests/unit/test_engram_persist.py`

- [ ] **Step 6.1: Write failing tests for `_resolve_project_key`**

Append to `tests/unit/test_engram_persist.py`:

```python
def test_resolve_project_key_uses_git_toplevel_basename(tmp_path: Path, monkeypatch) -> None:
    from lazy_harness.hooks.builtins.engram_persist import _resolve_project_key

    repo_root = tmp_path / "repos" / "lazy" / "lazy-harness"
    repo_root.mkdir(parents=True)
    (repo_root / ".git").mkdir()  # bare marker; we will mock subprocess

    def fake_run(cmd, **kwargs):
        if cmd[:3] == ["git", "rev-parse", "--show-toplevel"]:
            return MagicMock(returncode=0, stdout=str(repo_root) + "\n", stderr="")
        return MagicMock(returncode=128, stdout="", stderr="not a git repo")

    monkeypatch.setattr(
        "lazy_harness.hooks.builtins.engram_persist.subprocess.run", fake_run
    )

    nested_cwd = repo_root / "src" / "lazy_harness"
    nested_cwd.mkdir(parents=True)
    assert _resolve_project_key(nested_cwd) == "lazy-harness"


def test_resolve_project_key_falls_back_to_cwd_basename(tmp_path: Path, monkeypatch) -> None:
    from lazy_harness.hooks.builtins.engram_persist import _resolve_project_key

    def fake_run(cmd, **kwargs):
        return MagicMock(returncode=128, stdout="", stderr="not a git repo")

    monkeypatch.setattr(
        "lazy_harness.hooks.builtins.engram_persist.subprocess.run", fake_run
    )

    cwd = tmp_path / "lazy-harness"
    cwd.mkdir()
    assert _resolve_project_key(cwd) == "lazy-harness"
```

- [ ] **Step 6.2: Run tests and confirm they fail**

```bash
uv run pytest tests/unit/test_engram_persist.py::test_resolve_project_key_uses_git_toplevel_basename -v
```

Expected: FAIL — current `_resolve_project_key` only uses `cwd.name` and ignores git.

- [ ] **Step 6.3: Implement git-aware resolution**

In `src/lazy_harness/hooks/builtins/engram_persist.py`, replace the `_resolve_project_key` function and add the missing import at the top:

```python
import subprocess


def _resolve_project_key(cwd: Path) -> str:
    """Return canonical Engram project key.

    Prefers `git rev-parse --show-toplevel` basename so that nested cwd
    inside a repo always resolves to the same canonical key. Falls back
    to cwd basename if not in a git repo.
    """
    try:
        proc = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=cwd,
            capture_output=True,
            text=True,
            check=False,
        )
        if proc.returncode == 0:
            top = Path(proc.stdout.strip())
            if top.name:
                return top.name
    except OSError:
        pass
    return cwd.name
```

- [ ] **Step 6.4: Run tests and confirm they pass**

```bash
uv run pytest tests/unit/test_engram_persist.py -v
```

Expected: 19 passed.

- [ ] **Step 6.5: Commit**

```bash
git add src/lazy_harness/hooks/builtins/engram_persist.py tests/unit/test_engram_persist.py
git commit -m "feat(engram-persist): canonical project key from git toplevel basename"
```

---

## Task 7: Run-summary metrics emission

**Files:**
- Modify: `src/lazy_harness/knowledge/engram_persist.py`
- Modify: `tests/unit/test_engram_persist.py`

- [ ] **Step 7.1: Write failing test**

Append to `tests/unit/test_engram_persist.py`:

```python
def test_metrics_run_line_emitted_with_required_fields(tmp_path: Path) -> None:
    persister = _persister(tmp_path)
    entries = [{"ts": "T1", "type": "decision", "summary": "x"}]
    _seed_jsonl(persister.memory_dir, "decision", entries)

    with patch(
        "lazy_harness.knowledge.engram_persist.subprocess.run"
    ) as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        persister.persist_new_entries()

    metrics_path = persister.logs_dir / "engram_persist_metrics.jsonl"
    assert metrics_path.is_file()
    lines = metrics_path.read_text().strip().splitlines()
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert record["event"] == "run"
    assert record["saved_ok"] == 1
    assert record["saved_failed"] == 0
    assert record["skipped_malformed"] == 0
    assert record["entries_seen"] == {"decisions": 1, "failures": 0}
    assert record["cursor_lag_bytes"] == {"decisions": 0, "failures": 0}
    assert record["project_key"] == "lazy-harness"
    assert "duration_ms" in record
    assert "subprocess_ms" in record
    assert "ts" in record
    assert "engram_version" in record
    assert "hook_version" in record


def test_metrics_not_emitted_when_engram_binary_missing(tmp_path: Path) -> None:
    memory_dir = tmp_path / "memory"
    logs_dir = tmp_path / "logs"
    memory_dir.mkdir()
    logs_dir.mkdir()
    persister = EngramPersister(
        memory_dir=memory_dir,
        logs_dir=logs_dir,
        project_key="lazy-harness",
        engram_bin=None,
    )
    persister.persist_new_entries()

    assert not (logs_dir / "engram_persist_metrics.jsonl").exists()
```

- [ ] **Step 7.2: Run tests and confirm they fail**

```bash
uv run pytest tests/unit/test_engram_persist.py -k "metrics" -v
```

Expected: FAIL — metrics file is not written today.

- [ ] **Step 7.3: Implement metrics emission**

In `src/lazy_harness/knowledge/engram_persist.py`, add helpers near the bottom:

```python
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


def _emit_run_metric(
    logs_dir: Path,
    result: PersistResult,
    project_key: str,
    engram_bin: str,
) -> None:
    record = {
        "ts": datetime.now(timezone.utc)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z"),
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
```

In `EngramPersister.persist_new_entries`, just before `return result`, add:

```python
        _emit_run_metric(self.logs_dir, result, self.project_key, self.engram_bin)
```

The early-return for missing binary deliberately does **not** emit a metrics line (matches `test_metrics_not_emitted_when_engram_binary_missing`).

- [ ] **Step 7.4: Run tests and confirm they pass**

```bash
uv run pytest tests/unit/test_engram_persist.py -v
```

Expected: 21 passed.

- [ ] **Step 7.5: Commit**

```bash
git add src/lazy_harness/knowledge/engram_persist.py tests/unit/test_engram_persist.py
git commit -m "feat(engram-persist): per-run metrics line in engram_persist_metrics.jsonl"
```

---

## Task 8: Slow-save event emission with injectable threshold

**Files:**
- Modify: `src/lazy_harness/knowledge/engram_persist.py`
- Modify: `tests/unit/test_engram_persist.py`

- [ ] **Step 8.1: Write failing tests**

Append to `tests/unit/test_engram_persist.py`:

```python
def test_slow_save_event_emitted_above_threshold(tmp_path: Path) -> None:
    memory_dir = tmp_path / "memory"
    logs_dir = tmp_path / "logs"
    memory_dir.mkdir()
    logs_dir.mkdir()
    entries = [{"ts": "T1", "type": "decision", "summary": "slow one"}]
    _seed_jsonl(memory_dir, "decision", entries)

    persister = EngramPersister(
        memory_dir=memory_dir,
        logs_dir=logs_dir,
        project_key="lazy-harness",
        engram_bin="/fake/engram",
        slow_save_threshold_ms=10,  # injected low threshold
    )

    def slow_run(*args, **kwargs):
        time.sleep(0.05)  # 50ms > 10ms threshold
        return MagicMock(returncode=0, stdout="", stderr="")

    with patch(
        "lazy_harness.knowledge.engram_persist.subprocess.run",
        side_effect=slow_run,
    ):
        persister.persist_new_entries()

    metrics = (logs_dir / "engram_persist_metrics.jsonl").read_text().strip().splitlines()
    slow_lines = [json.loads(line) for line in metrics if json.loads(line).get("event") == "slow_save"]
    assert len(slow_lines) == 1
    assert slow_lines[0]["type"] == "decision"
    assert slow_lines[0]["ms"] >= 10
    assert slow_lines[0]["title_prefix"].startswith("slow one")


def test_slow_save_event_not_emitted_below_threshold(tmp_path: Path) -> None:
    memory_dir = tmp_path / "memory"
    logs_dir = tmp_path / "logs"
    memory_dir.mkdir()
    logs_dir.mkdir()
    entries = [{"ts": "T1", "type": "decision", "summary": "fast one"}]
    _seed_jsonl(memory_dir, "decision", entries)

    persister = EngramPersister(
        memory_dir=memory_dir,
        logs_dir=logs_dir,
        project_key="lazy-harness",
        engram_bin="/fake/engram",
        slow_save_threshold_ms=10_000,  # very high threshold
    )

    with patch(
        "lazy_harness.knowledge.engram_persist.subprocess.run"
    ) as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        persister.persist_new_entries()

    metrics = (logs_dir / "engram_persist_metrics.jsonl").read_text().strip().splitlines()
    slow_lines = [line for line in metrics if json.loads(line).get("event") == "slow_save"]
    assert slow_lines == []
```

Note: the test imports `time` already from the top of the file (added in Task 3 as part of the helper file). Add `import time` at the top of the test file if it is not already there.

- [ ] **Step 8.2: Run tests and confirm they fail**

```bash
uv run pytest tests/unit/test_engram_persist.py -k "slow_save" -v
```

Expected: FAIL — no slow_save events are emitted today.

- [ ] **Step 8.3: Implement slow-save emission**

In `src/lazy_harness/knowledge/engram_persist.py`, add a helper:

```python
def _emit_slow_save(
    logs_dir: Path, kind: EntryKind, ms: int, title: str
) -> None:
    record = {
        "ts": datetime.now(timezone.utc)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z"),
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
```

In `EngramPersister.persist_new_entries`, after the `_save_entry` call inside the inner loop, when `ok` is true:

```python
                    if ok:
                        result.saved_ok += 1
                        offset = f.tell()
                        cursor[offset_key] = offset
                        _save_cursor(
                            cursor_path,
                            decisions_offset=cursor["decisions_offset"],
                            failures_offset=cursor["failures_offset"],
                        )
                        if elapsed_ms >= self.slow_save_threshold_ms:
                            _emit_slow_save(
                                self.logs_dir,
                                kind,
                                elapsed_ms,
                                _build_title(entry),
                            )
```

- [ ] **Step 8.4: Run tests and confirm they pass**

```bash
uv run pytest tests/unit/test_engram_persist.py -v
```

Expected: 23 passed.

- [ ] **Step 8.5: Commit**

```bash
git add src/lazy_harness/knowledge/engram_persist.py tests/unit/test_engram_persist.py
git commit -m "feat(engram-persist): emit slow_save events above injectable threshold"
```

---

## Task 9: Error log on save failure

**Files:**
- Modify: `src/lazy_harness/knowledge/engram_persist.py`
- Modify: `tests/unit/test_engram_persist.py`

- [ ] **Step 9.1: Write failing test**

Append to `tests/unit/test_engram_persist.py`:

```python
def test_error_log_written_on_save_failure(tmp_path: Path) -> None:
    persister = _persister(tmp_path)
    entries = [{"ts": "T1", "type": "decision", "summary": "doomed"}]
    _seed_jsonl(persister.memory_dir, "decision", entries)

    with patch(
        "lazy_harness.knowledge.engram_persist.subprocess.run"
    ) as mock_run:
        mock_run.return_value = MagicMock(
            returncode=1, stdout="", stderr="database is locked"
        )
        persister.persist_new_entries()

    log_path = persister.logs_dir / "engram_persist.log"
    content = log_path.read_text()
    assert "engram save returned 1" in content
    assert "database is locked" in content
    assert "decision" in content
```

- [ ] **Step 9.2: Run test and confirm it fails**

```bash
uv run pytest tests/unit/test_engram_persist.py::test_error_log_written_on_save_failure -v
```

Expected: FAIL — error log path is created but does not contain the expected lines.

- [ ] **Step 9.3: Implement error logging**

Modify `_save_entry` in `src/lazy_harness/knowledge/engram_persist.py` to return stderr too:

```python
def _save_entry(
    engram_bin: str, entry: dict, kind: EntryKind, project_key: str
) -> tuple[bool, int, str, int]:
    """Returns (success, elapsed_ms, stderr, returncode)."""
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
    except OSError as e:
        return False, int((time.monotonic() - start) * 1000), str(e), -1
    elapsed_ms = int((time.monotonic() - start) * 1000)
    return proc.returncode == 0, elapsed_ms, proc.stderr or "", proc.returncode
```

Update the call site in `persist_new_entries`:

```python
                    ok, elapsed_ms, stderr, rc = _save_entry(
                        self.engram_bin, entry, kind, self.project_key
                    )
                    result.subprocess_ms += elapsed_ms
                    if ok:
                        # ...same as before, ending with slow_save check
                        ...
                    else:
                        result.saved_failed += 1
                        _append_error_log(
                            self.logs_dir,
                            f"engram save returned {rc} for {kind} entry "
                            f"at offset={offset}: {stderr.strip()}",
                        )
                        break
```

- [ ] **Step 9.4: Run tests and confirm they pass**

```bash
uv run pytest tests/unit/test_engram_persist.py -v
```

Expected: 24 passed.

- [ ] **Step 9.5: Commit**

```bash
git add src/lazy_harness/knowledge/engram_persist.py tests/unit/test_engram_persist.py
git commit -m "feat(engram-persist): error log on engram save non-zero exit"
```

---

## Task 10: Builtin wrapper integration test

**Files:**
- Create: `tests/unit/test_builtin_engram_persist.py`

The pattern matches `tests/unit/test_builtin_post_compact.py`: invoke the wrapper as a real subprocess with a stub `engram` shim earlier on `PATH`.

- [ ] **Step 10.1: Write failing test**

Create `tests/unit/test_builtin_engram_persist.py`:

```python
"""Subprocess-level tests for the engram-persist builtin wrapper."""

from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
from pathlib import Path

HOOK_PATH = (
    Path(__file__).parent.parent.parent
    / "src"
    / "lazy_harness"
    / "hooks"
    / "builtins"
    / "engram_persist.py"
)


def _make_engram_shim(shim_dir: Path, exit_code: int = 0) -> Path:
    shim_dir.mkdir(parents=True, exist_ok=True)
    shim = shim_dir / "engram"
    log = shim_dir / "engram_invocations.log"
    shim.write_text(
        f"#!/usr/bin/env python3\n"
        f"import sys\n"
        f"with open({str(log)!r}, 'a') as f:\n"
        f"    f.write(' '.join(sys.argv) + '\\n')\n"
        f"# A 'version' subcommand is needed by the metrics path:\n"
        f"if len(sys.argv) > 1 and sys.argv[1] == 'version':\n"
        f"    print('engram v0.0.0-shim')\n"
        f"    sys.exit(0)\n"
        f"sys.exit({exit_code})\n"
    )
    shim.chmod(shim.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    return shim


def test_wrapper_reads_stdin_and_invokes_engram(tmp_path: Path) -> None:
    claude_dir = tmp_path / "claude"
    cwd = tmp_path / "lazy-harness"
    cwd.mkdir()
    encoded = "-" + str(cwd).replace("/", "-").lstrip("-")
    memory_dir = claude_dir / "projects" / encoded / "memory"
    memory_dir.mkdir(parents=True)

    entry = {"ts": "T1", "type": "decision", "summary": "hello"}
    (memory_dir / "decisions.jsonl").write_text(json.dumps(entry) + "\n")

    shim_dir = tmp_path / "shimbin"
    _make_engram_shim(shim_dir, exit_code=0)

    env = os.environ.copy()
    env["CLAUDE_CONFIG_DIR"] = str(claude_dir)
    env["PATH"] = str(shim_dir) + os.pathsep + env.get("PATH", "")

    result = subprocess.run(
        [sys.executable, str(HOOK_PATH)],
        input=json.dumps({"cwd": str(cwd)}),
        capture_output=True,
        text=True,
        env=env,
        cwd=str(cwd),
    )

    assert result.returncode == 0, result.stderr
    log = (shim_dir / "engram_invocations.log").read_text()
    assert " save hello " in log


def test_wrapper_exits_zero_when_engram_save_fails(tmp_path: Path) -> None:
    claude_dir = tmp_path / "claude"
    cwd = tmp_path / "lazy-harness"
    cwd.mkdir()
    encoded = "-" + str(cwd).replace("/", "-").lstrip("-")
    memory_dir = claude_dir / "projects" / encoded / "memory"
    memory_dir.mkdir(parents=True)

    entry = {"ts": "T1", "type": "decision", "summary": "doomed"}
    (memory_dir / "decisions.jsonl").write_text(json.dumps(entry) + "\n")

    shim_dir = tmp_path / "shimbin"
    _make_engram_shim(shim_dir, exit_code=1)

    env = os.environ.copy()
    env["CLAUDE_CONFIG_DIR"] = str(claude_dir)
    env["PATH"] = str(shim_dir) + os.pathsep + env.get("PATH", "")

    result = subprocess.run(
        [sys.executable, str(HOOK_PATH)],
        input=json.dumps({"cwd": str(cwd)}),
        capture_output=True,
        text=True,
        env=env,
        cwd=str(cwd),
    )

    assert result.returncode == 0, result.stderr
```

- [ ] **Step 10.2: Run tests and verify**

```bash
uv run pytest tests/unit/test_builtin_engram_persist.py -v
```

Expected: 2 passed. The wrapper already supports the contract (Task 1 implemented stdin reading; Task 5 short-circuits cleanly on missing binary; Task 9 logs save failures and exits 0 because the wrapper's outer `try/except` swallows everything).

If the test fails, adjust the wrapper — the most likely culprit is a missing `slow_save_threshold_ms` argument when `EngramPersister` is instantiated (it has a default, so no change should be needed, but verify).

- [ ] **Step 10.3: Commit**

```bash
git add tests/unit/test_builtin_engram_persist.py
git commit -m "test(engram-persist): subprocess-level integration with engram shim"
```

---

## Task 11: ADR-029 + index update

**Files:**
- Create: `specs/adrs/029-engram-persist-deterministic-mirror.md`
- Modify: `specs/adrs/README.md`

- [ ] **Step 11.1: Write the ADR**

Create `specs/adrs/029-engram-persist-deterministic-mirror.md`:

```markdown
# ADR-029: Deterministic Engram mirror via Stop hook

**Status:** accepted
**Date:** 2026-05-04
**Supersedes:** —
**Superseded by:** —
**Related:** ADR-006 (hooks-subprocess-json), ADR-008 (compound-loop-insight-capture), ADR-027 (memory-stack-overview)

## Context

The five-layer memory model (ADR-027) names Engram as the episodic-raw layer and documents a Stop-time persistence path for it. Until this ADR, no hook in the harness invoked Engram: the documented behaviour was inoperative. An audit on 2026-05-04 confirmed the gap (10 of 11 Engram projects had a single bootstrap observation and zero sessions).

## Decision

Add a built-in `engram-persist` hook to the `Stop` chain, after `compound_loop.py`. On every Stop event, the hook reads new entries from `decisions.jsonl` and `failures.jsonl` since the last persisted byte cursor and mirrors each entry into Engram via `engram save` (CLI subprocess, not the MCP server). The cursor advances only on successful save, giving at-least-once semantics with no duplicate emission under normal operation.

The hook forces `--project <basename>` derived from `git rev-parse --show-toplevel` to prevent the project-key fragmentation observed in the audit (`lazy-harness` vs `lazynet/lazy-harness`). It is fail-soft: missing binary is a no-op with one warning, save failures keep the cursor unchanged for retry on the next Stop.

## Consequences

**Positive**
- Engram becomes a deterministic episodic store fed by every Stop, matching the doc.
- Existing JSONL artifacts remain the human-reviewable source of truth; Engram is a 1:1 mirror with full search.
- Cursor + at-least-once semantics make the hook safe to retry, including across restarts.

**Negative**
- Stop chain runs an extra subprocess per Stop. With 1–3 entries per Stop at 50–200ms each, expect 50–600ms added latency. Slow-save events flag regressions above a 500ms threshold.
- Backfill on first run mirrors every entry currently in JSONL (one-time cost).
- Existing fragmented Engram projects need a one-time `engram projects consolidate --all` before opt-in.

## Alternatives considered

1. **Per-session summary at SessionEnd**: lower volume but loses granular searchability; needs new aggregation logic. Rejected — does not match the JSONL artifacts.
2. **MCP-based persistence (`mem_save` tool from the agent)**: requires the agent to remember to call it; observed empirically to be unreliable. Rejected — defeats the determinism goal.
3. **Extending `compound_loop.py` to also push to Engram**: mixes two concerns (insight evaluation and storage mirror) into one module. Rejected — separate hook keeps responsibilities clean and tests focused.

## Implementation

See `specs/designs/2026-05-04-engram-persist-hook-design.md` and `specs/plans/2026-05-04-engram-persist-hook-plan.md`.
```

- [ ] **Step 11.2: Update the ADR index**

Open `specs/adrs/README.md` and add an entry for ADR-029 in the index list, in numeric order. Match the formatting used by ADR-028.

```bash
uv run python -c "
import re, pathlib
p = pathlib.Path('specs/adrs/README.md')
text = p.read_text()
"
```

In practice: open the file, find the row for ADR-028, and append a similar row beneath it referencing `029-engram-persist-deterministic-mirror.md` with a one-line summary like "Deterministic Engram mirror via Stop hook (engram-persist)".

- [ ] **Step 11.3: Commit**

```bash
git add specs/adrs/029-engram-persist-deterministic-mirror.md specs/adrs/README.md
git commit -m "docs(adr): ADR-029 deterministic Engram mirror via Stop hook"
```

---

## Task 12: Pre-commit gate, lint, mkdocs build

**Files:** none new — verification only.

- [ ] **Step 12.1: Run the full TDD-check suite**

```bash
uv run pytest -v
uv run ruff check src tests
uv run --group docs mkdocs build --strict
```

Expected: all three pristine. ruff in particular may flag `from __future__ import annotations` ordering or unused imports in the new test file — fix inline if so.

- [ ] **Step 12.2: If anything fails, fix and add a follow-up commit**

If a fix is needed, the commit must be a new commit (never amend a prior commit per repo non-negotiable #3). Use the `fix:` prefix:

```bash
git commit -m "fix(engram-persist): <one-line description of the fix>"
```

- [ ] **Step 12.3: Push the branch and open a PR**

```bash
gh auth switch --user lazynet  # per memory: dual-account workflow
git push -u origin feat/engram-persist-hook
gh pr create \
  --title "feat(hooks): engram-persist deterministic Stop-time mirror" \
  --body "$(cat <<'EOF'
## Summary
- Adds built-in `engram-persist` hook to mirror new entries from `decisions.jsonl` / `failures.jsonl` into Engram via `engram save` on every Stop event.
- Cursor file (`engram_cursor.json`) gives at-least-once semantics with no duplicate emission under normal operation.
- Per-run metrics in `logs/engram_persist_metrics.jsonl`; slow-save events emitted above an injectable 500ms threshold; errors logged separately to `engram_persist.log`.
- Spec: `specs/designs/2026-05-04-engram-persist-hook-design.md`
- ADR: `specs/adrs/029-engram-persist-deterministic-mirror.md`

## Test plan
- [x] `uv run pytest` — green
- [x] `uv run ruff check src tests` — clean
- [x] `uv run --group docs mkdocs build --strict` — clean
- [ ] Manual: enable in `~/.config/lazy-harness/config.toml` (`[hooks.session_stop].scripts += ["engram-persist"]`), run `lh deploy hooks`, trigger a Stop, verify a new `run` line in `~/.claude-lazy/logs/engram_persist_metrics.jsonl` and matching observations in `engram search "<recent decision>" --project lazy-harness`.

`lh doctor` integration is intentionally deferred to a follow-up PR.
EOF
)"
```

After PR is created, switch back to the personal account if needed:

```bash
gh auth switch --user mvago-flx  # restore default per memory
```

---

## Self-Review Checklist (run after writing the plan)

- **Spec coverage**: every section of `specs/designs/2026-05-04-engram-persist-hook-design.md` mapped to a task above:
  - Decision / Why per-entry / Why Stop / Project key — Task 6, ADR (Task 11)
  - Cursor strategy — Tasks 2, 4
  - Save success advances cursor — Tasks 3, 4
  - CLI invocation contract (title fallback, type from filename, project from cwd) — Tasks 3, 6
  - Cursor file format — Task 2
  - Run-summary metrics — Task 7
  - Slow-save events with injectable threshold — Task 8
  - Errors text log — Tasks 5, 9
  - Error handling matrix — Tasks 4, 5, 9 cover all rows; OSError on stdin is silently ignored by the wrapper (Task 1)
  - Unit test list — Tasks 1–9 cover all 14 unit cases
  - Integration test list — Task 10 covers both
  - Migration path documented — Task 11 (ADR Consequences) and PR description (Task 12)
  - Out-of-scope items called out — `lh doctor` integration explicitly deferred (Task 12 PR description)
- **Placeholder scan**: no `TBD`, no "implement later", every code block contains real code.
- **Type consistency**: `EntryKind = Literal["decision", "failure"]` consistent across all tasks. `PersistResult.entries_seen` keyed by singular `"decision"` / `"failure"` internally; metrics line keys translated to plural `"decisions"` / `"failures"` deliberately (Task 7).
- **No over-engineering**: env-var override for slow-save threshold is mentioned in spec but **not** implemented (deferred per spec); `lh doctor` integration deferred per spec; settings.json template not auto-shipped per spec.

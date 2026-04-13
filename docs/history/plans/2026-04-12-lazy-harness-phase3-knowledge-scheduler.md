# lazy-harness Phase 3: Knowledge + Scheduler — Implementation Plan

> **Archived.** This document was authored in `lazy-claudecode` before the rename and migration to `lazy-harness`. Preserved for historical context. References to files and paths may be stale.


> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add knowledge directory management (session export, QMD integration) and cross-platform scheduler (launchd/systemd/cron) to lazy-harness, completing the core feature set.

**Architecture:** Knowledge module manages a markdown directory for session exports and learnings, wraps QMD CLI for search/sync/embed. Scheduler module abstracts job scheduling across macOS (launchd), Linux (systemd timers), and fallback (cron). Session export becomes a built-in Stop hook that writes to the knowledge directory.

**Tech Stack:** Python 3.11+, click, rich, subprocess (QMD CLI wrapper), plistlib (launchd), pytest

**Spec:** `docs/superpowers/specs/2026-04-12-lazy-harness-product-design.md`

---

## File Map

### New files

```
src/lazy_harness/
├── knowledge/
│   ├── __init__.py
│   ├── directory.py           # Knowledge dir management (ensure, list, paths)
│   ├── qmd.py                 # QMD CLI wrapper (sync, embed, search)
│   └── session_export.py      # Parse session JSONL → markdown export
├── scheduler/
│   ├── __init__.py
│   ├── base.py                # SchedulerBackend protocol
│   ├── launchd.py             # macOS LaunchAgents
│   ├── systemd.py             # Linux systemd timers
│   ├── cron.py                # Fallback cron
│   └── manager.py             # Auto-detect + dispatch
├── hooks/builtins/
│   └── session_export.py      # Stop hook: export session + QMD update
├── cli/
│   ├── knowledge_cmd.py       # `lh knowledge sync|embed|search`
│   └── scheduler_cmd.py       # `lh scheduler install|status|uninstall`
tests/
├── unit/
│   ├── test_knowledge_dir.py
│   ├── test_session_export.py
│   ├── test_qmd.py
│   ├── test_scheduler_launchd.py
│   └── test_scheduler_manager.py
└── integration/
    ├── test_knowledge_cmd.py
    └── test_scheduler_cmd.py
```

### Modified files

```
src/lazy_harness/core/config.py       # Add SchedulerJobConfig to scheduler section
src/lazy_harness/hooks/loader.py      # Register session-export built-in
src/lazy_harness/cli/main.py          # Register knowledge + scheduler commands
```

---

## Task 1: Knowledge directory management

**Files:**
- Create: `src/lazy_harness/knowledge/__init__.py`
- Create: `src/lazy_harness/knowledge/directory.py`
- Test: `tests/unit/test_knowledge_dir.py`

- [ ] **Step 1: Write failing tests**

`tests/unit/test_knowledge_dir.py`:

```python
"""Tests for knowledge directory management."""

from __future__ import annotations

from pathlib import Path


def test_ensure_knowledge_dir(tmp_path: Path) -> None:
    from lazy_harness.knowledge.directory import ensure_knowledge_dir

    kdir = tmp_path / "knowledge"
    result = ensure_knowledge_dir(str(kdir))
    assert result.is_dir()
    assert (result / "sessions").is_dir()
    assert (result / "learnings").is_dir()


def test_ensure_knowledge_dir_existing(tmp_path: Path) -> None:
    from lazy_harness.knowledge.directory import ensure_knowledge_dir

    kdir = tmp_path / "knowledge"
    kdir.mkdir()
    (kdir / "sessions").mkdir()
    result = ensure_knowledge_dir(str(kdir))
    assert result.is_dir()
    assert (result / "learnings").is_dir()


def test_session_export_path(tmp_path: Path) -> None:
    from lazy_harness.knowledge.directory import session_export_path

    kdir = tmp_path / "knowledge"
    kdir.mkdir()
    result = session_export_path(kdir, "sessions", "2026-04-12", "abc12345")
    assert str(result).endswith("2026-04-12-abc12345.md")
    assert "2026-04" in str(result)


def test_list_sessions(tmp_path: Path) -> None:
    from lazy_harness.knowledge.directory import list_sessions

    sessions_dir = tmp_path / "knowledge" / "sessions" / "2026-04"
    sessions_dir.mkdir(parents=True)
    (sessions_dir / "2026-04-12-abc12345.md").write_text("# test\n")
    (sessions_dir / "2026-04-11-def67890.md").write_text("# test\n")

    result = list_sessions(tmp_path / "knowledge", "sessions")
    assert len(result) == 2
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd ~/repos/lazy/lazy-harness
uv run pytest tests/unit/test_knowledge_dir.py -v
```

- [ ] **Step 3: Implement knowledge directory**

`src/lazy_harness/knowledge/__init__.py` — empty.

`src/lazy_harness/knowledge/directory.py`:

```python
"""Knowledge directory management — ensure structure, list content, resolve paths."""

from __future__ import annotations

from pathlib import Path

from lazy_harness.core.paths import expand_path


def ensure_knowledge_dir(path: str, subdirs: list[str] | None = None) -> Path:
    """Ensure knowledge directory exists with standard subdirectories."""
    kdir = expand_path(path)
    kdir.mkdir(parents=True, exist_ok=True)
    for subdir in subdirs or ["sessions", "learnings"]:
        (kdir / subdir).mkdir(exist_ok=True)
    return kdir


def session_export_path(
    knowledge_dir: Path, subdir: str, date_str: str, session_id: str
) -> Path:
    """Resolve the export path for a session markdown file."""
    year_month = date_str[:7]  # YYYY-MM
    export_dir = knowledge_dir / subdir / year_month
    export_dir.mkdir(parents=True, exist_ok=True)
    return export_dir / f"{date_str}-{session_id[:8]}.md"


def list_sessions(knowledge_dir: Path, subdir: str = "sessions") -> list[Path]:
    """List all session markdown files, sorted by name (newest first)."""
    sessions_dir = knowledge_dir / subdir
    if not sessions_dir.is_dir():
        return []
    files = sorted(sessions_dir.rglob("*.md"), reverse=True)
    return files
```

- [ ] **Step 4: Run tests, commit**

```bash
uv run pytest tests/unit/test_knowledge_dir.py -v
git add src/lazy_harness/knowledge/ tests/unit/test_knowledge_dir.py
git commit -m "feat: knowledge directory management"
```

---

## Task 2: Session export (JSONL → markdown)

**Files:**
- Create: `src/lazy_harness/knowledge/session_export.py`
- Test: `tests/unit/test_session_export.py`

- [ ] **Step 1: Write failing tests**

`tests/unit/test_session_export.py`:

```python
"""Tests for session JSONL → markdown export."""

from __future__ import annotations

import json
from pathlib import Path


def _write_session(path: Path, messages: list[dict]) -> None:
    with open(path, "w") as f:
        for msg in messages:
            f.write(json.dumps(msg) + "\n")


def test_export_session_to_markdown(tmp_path: Path) -> None:
    from lazy_harness.knowledge.session_export import export_session

    session_file = tmp_path / "abc12345.jsonl"
    _write_session(session_file, [
        {"type": "permission-mode", "timestamp": "2026-04-12T10:00:00-03:00"},
        {"type": "system", "cwd": "/home/user/project", "version": "1.0", "gitBranch": "main", "timestamp": "2026-04-12T10:00:00-03:00"},
        {"type": "user", "message": {"content": "Hello, help me with this"}, "timestamp": "2026-04-12T10:00:01-03:00"},
        {"type": "assistant", "message": {"content": "Sure, I can help"}, "timestamp": "2026-04-12T10:00:02-03:00"},
        {"type": "user", "message": {"content": "Thanks for that"}, "timestamp": "2026-04-12T10:00:03-03:00"},
        {"type": "assistant", "message": {"content": "You're welcome"}, "timestamp": "2026-04-12T10:00:04-03:00"},
    ])

    output_dir = tmp_path / "export"
    output_dir.mkdir()
    result = export_session(session_file, output_dir)
    assert result is not None
    assert result.is_file()
    content = result.read_text()
    assert "---" in content  # frontmatter
    assert "Hello, help me with this" in content
    assert "Sure, I can help" in content


def test_export_session_skips_short(tmp_path: Path) -> None:
    from lazy_harness.knowledge.session_export import export_session

    session_file = tmp_path / "short.jsonl"
    _write_session(session_file, [
        {"type": "permission-mode", "timestamp": "2026-04-12T10:00:00"},
        {"type": "user", "message": {"content": "hi"}, "timestamp": "2026-04-12T10:00:01"},
    ])

    output_dir = tmp_path / "export"
    output_dir.mkdir()
    result = export_session(session_file, output_dir)
    assert result is None


def test_export_session_skips_non_interactive(tmp_path: Path) -> None:
    from lazy_harness.knowledge.session_export import export_session

    session_file = tmp_path / "batch.jsonl"
    _write_session(session_file, [
        {"type": "system", "cwd": "/tmp", "timestamp": "2026-04-12T10:00:00"},
        {"type": "user", "message": {"content": "do something"}, "timestamp": "2026-04-12T10:00:01"},
        {"type": "assistant", "message": {"content": "done"}, "timestamp": "2026-04-12T10:00:02"},
        {"type": "user", "message": {"content": "more"}, "timestamp": "2026-04-12T10:00:03"},
        {"type": "assistant", "message": {"content": "ok"}, "timestamp": "2026-04-12T10:00:04"},
    ])

    output_dir = tmp_path / "export"
    output_dir.mkdir()
    result = export_session(session_file, output_dir)
    assert result is None


def test_export_handles_content_blocks(tmp_path: Path) -> None:
    from lazy_harness.knowledge.session_export import export_session

    session_file = tmp_path / "blocks.jsonl"
    _write_session(session_file, [
        {"type": "permission-mode", "timestamp": "2026-04-12T10:00:00"},
        {"type": "system", "cwd": "/tmp/proj", "timestamp": "2026-04-12T10:00:00"},
        {"type": "user", "message": {"content": "first question"}, "timestamp": "2026-04-12T10:00:01"},
        {"type": "assistant", "message": {"content": [{"type": "text", "text": "answer one"}]}, "timestamp": "2026-04-12T10:00:02"},
        {"type": "user", "message": {"content": "second question"}, "timestamp": "2026-04-12T10:00:03"},
        {"type": "assistant", "message": {"content": [{"type": "text", "text": "answer two"}]}, "timestamp": "2026-04-12T10:00:04"},
    ])

    output_dir = tmp_path / "export"
    output_dir.mkdir()
    result = export_session(session_file, output_dir)
    assert result is not None
    content = result.read_text()
    assert "answer one" in content
    assert "answer two" in content
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/unit/test_session_export.py -v
```

- [ ] **Step 3: Implement session export**

`src/lazy_harness/knowledge/session_export.py`:

```python
"""Session JSONL → markdown export."""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any


def _parse_session_jsonl(filepath: Path) -> tuple[dict[str, str], list[dict[str, str]]]:
    """Parse a session JSONL file into metadata and message list."""
    meta: dict[str, str] = {}
    messages: list[dict[str, str]] = []
    first_timestamp = ""
    is_interactive = False

    for line in filepath.read_text().splitlines():
        if not line.strip():
            continue
        try:
            d = json.loads(line)
        except json.JSONDecodeError:
            continue

        msg_type = d.get("type", "")
        ts = d.get("timestamp", "")
        if not first_timestamp and ts:
            first_timestamp = ts

        if msg_type == "permission-mode":
            is_interactive = True
            continue

        if msg_type == "system" and not meta:
            meta = {
                "cwd": d.get("cwd", ""),
                "version": d.get("version", ""),
                "branch": d.get("gitBranch", ""),
                "timestamp": ts,
            }
            continue

        if msg_type in ("user", "assistant"):
            msg = d.get("message", {})
            content = msg.get("content", "")
            texts: list[str] = []
            if isinstance(content, str) and content.strip():
                texts.append(content.strip())
            elif isinstance(content, list):
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "text":
                        text = block.get("text", "").strip()
                        if text:
                            texts.append(text)
            if texts:
                role = "User" if msg_type == "user" else "Claude"
                messages.append({"role": role, "text": "\n\n".join(texts), "timestamp": ts})

    if not meta.get("timestamp"):
        meta["timestamp"] = first_timestamp

    return meta, messages if is_interactive else []


def _extract_project(cwd: str) -> str:
    """Extract project name from cwd by walking up to find .git."""
    if not cwd:
        return ""
    check = cwd
    while check and check != "/":
        if os.path.isdir(os.path.join(check, ".git")):
            return os.path.basename(check)
        check = os.path.dirname(check)
    return os.path.basename(cwd) or ""


def export_session(
    session_file: Path,
    output_dir: Path,
    min_messages: int = 4,
) -> Path | None:
    """Export a session JSONL to markdown. Returns output path or None if skipped."""
    meta, messages = _parse_session_jsonl(session_file)

    if len(messages) < min_messages:
        return None

    session_id = session_file.stem
    cwd = meta.get("cwd", "")
    project = _extract_project(cwd)

    ts = meta.get("timestamp", "")
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        date_str = dt.strftime("%Y-%m-%d %H:%M")
        date_prefix = dt.strftime("%Y-%m-%d")
    except (ValueError, OSError):
        date_str = ts[:16] if ts else "unknown"
        date_prefix = ts[:10] if len(ts) >= 10 else "unknown"

    year_month = date_prefix[:7]
    export_dir = output_dir / year_month
    export_dir.mkdir(parents=True, exist_ok=True)
    output_file = export_dir / f"{date_prefix}-{session_id[:8]}.md"

    with open(output_file, "w") as out:
        out.write(f"---\ntype: claude-session\nsession_id: {session_id}\n")
        out.write(f"date: {date_str}\ncwd: {cwd}\n")
        out.write(f"project: {project}\n")
        out.write(f"branch: {meta.get('branch', '')}\n")
        out.write(f"claude_version: {meta.get('version', '')}\n")
        out.write(f"messages: {len(messages)}\n---\n\n")
        out.write(f"# Session {date_str} — {project or 'unknown'}\n\n")
        out.write(f"**CWD**: `{cwd}` | **Project**: {project}\n\n---\n\n")
        for msg in messages:
            out.write(f"## {msg['role']}\n\n{msg['text']}\n\n")

    return output_file
```

- [ ] **Step 4: Run tests, commit**

```bash
uv run pytest tests/unit/test_session_export.py -v
git add src/lazy_harness/knowledge/session_export.py tests/unit/test_session_export.py
git commit -m "feat: session JSONL to markdown export"
```

---

## Task 3: QMD CLI wrapper

**Files:**
- Create: `src/lazy_harness/knowledge/qmd.py`
- Test: `tests/unit/test_qmd.py`

- [ ] **Step 1: Write failing tests**

`tests/unit/test_qmd.py`:

```python
"""Tests for QMD CLI wrapper."""

from __future__ import annotations

import shutil
from pathlib import Path
from unittest.mock import patch


def test_qmd_available() -> None:
    from lazy_harness.knowledge.qmd import is_qmd_available

    # This test reflects actual system state
    result = is_qmd_available()
    assert isinstance(result, bool)


def test_qmd_sync_command() -> None:
    from lazy_harness.knowledge.qmd import _build_command

    cmd = _build_command("update")
    assert cmd == ["qmd", "update"]


def test_qmd_sync_with_collection() -> None:
    from lazy_harness.knowledge.qmd import _build_command

    cmd = _build_command("update", collection="my-collection")
    assert cmd == ["qmd", "update", "--collection", "my-collection"]


def test_qmd_embed_command() -> None:
    from lazy_harness.knowledge.qmd import _build_command

    cmd = _build_command("embed")
    assert cmd == ["qmd", "embed"]


def test_qmd_run_returns_result() -> None:
    from lazy_harness.knowledge.qmd import QmdResult, run_qmd

    with patch("subprocess.run") as mock_run:
        mock_run.return_value = type("R", (), {"returncode": 0, "stdout": "OK", "stderr": ""})()
        result = run_qmd("status")
        assert isinstance(result, QmdResult)
        assert result.exit_code == 0
        assert result.stdout == "OK"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/unit/test_qmd.py -v
```

- [ ] **Step 3: Implement QMD wrapper**

`src/lazy_harness/knowledge/qmd.py`:

```python
"""QMD CLI wrapper — sync, embed, search."""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass


@dataclass
class QmdResult:
    exit_code: int
    stdout: str
    stderr: str


def is_qmd_available() -> bool:
    """Check if qmd CLI is available in PATH."""
    return shutil.which("qmd") is not None


def _build_command(action: str, collection: str | None = None) -> list[str]:
    """Build a qmd CLI command."""
    cmd = ["qmd", action]
    if collection:
        cmd.extend(["--collection", collection])
    return cmd


def run_qmd(
    action: str,
    collection: str | None = None,
    timeout: int = 300,
) -> QmdResult:
    """Run a qmd command and return the result."""
    cmd = _build_command(action, collection)
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return QmdResult(
            exit_code=result.returncode,
            stdout=result.stdout,
            stderr=result.stderr,
        )
    except subprocess.TimeoutExpired:
        return QmdResult(exit_code=-1, stdout="", stderr=f"QMD timed out after {timeout}s")
    except FileNotFoundError:
        return QmdResult(exit_code=-1, stdout="", stderr="qmd not found in PATH")


def sync(collection: str | None = None, timeout: int = 300) -> QmdResult:
    """Run qmd update (BM25 index sync)."""
    return run_qmd("update", collection=collection, timeout=timeout)


def embed(collection: str | None = None, timeout: int = 600) -> QmdResult:
    """Run qmd embed (vector embedding)."""
    return run_qmd("embed", collection=collection, timeout=timeout)


def status() -> QmdResult:
    """Run qmd status."""
    return run_qmd("status", timeout=30)
```

- [ ] **Step 4: Run tests, commit**

```bash
uv run pytest tests/unit/test_qmd.py -v
git add src/lazy_harness/knowledge/qmd.py tests/unit/test_qmd.py
git commit -m "feat: QMD CLI wrapper (sync, embed, status)"
```

---

## Task 4: Session export built-in hook + register in loader

**Files:**
- Create: `src/lazy_harness/hooks/builtins/session_export.py`
- Modify: `src/lazy_harness/hooks/loader.py` (register session-export)
- Test: `tests/unit/test_builtin_session_export.py`

- [ ] **Step 1: Write failing tests**

`tests/unit/test_builtin_session_export.py`:

```python
"""Tests for built-in session-export hook."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


def test_session_export_hook_exits_zero(tmp_path: Path) -> None:
    hook_path = (
        Path(__file__).parent.parent.parent
        / "src" / "lazy_harness" / "hooks" / "builtins" / "session_export.py"
    )
    # Create a minimal session JSONL
    session_file = tmp_path / "projects" / "-tmp-test" / "abc12345.jsonl"
    session_file.parent.mkdir(parents=True)
    messages = [
        {"type": "permission-mode", "timestamp": "2026-04-12T10:00:00"},
        {"type": "system", "cwd": "/tmp/test", "timestamp": "2026-04-12T10:00:00"},
        {"type": "user", "message": {"content": "first question here"}, "timestamp": "2026-04-12T10:00:01"},
        {"type": "assistant", "message": {"content": "first answer here"}, "timestamp": "2026-04-12T10:00:02"},
        {"type": "user", "message": {"content": "second question"}, "timestamp": "2026-04-12T10:00:03"},
        {"type": "assistant", "message": {"content": "second answer"}, "timestamp": "2026-04-12T10:00:04"},
    ]
    session_file.write_text("\n".join(json.dumps(m) for m in messages) + "\n")

    knowledge_dir = tmp_path / "knowledge"
    knowledge_dir.mkdir()

    env = {
        "PATH": os.environ.get("PATH", ""),
        "HOME": str(tmp_path),
        "CLAUDE_CONFIG_DIR": str(tmp_path),
        "LH_KNOWLEDGE_DIR": str(knowledge_dir),
    }

    result = subprocess.run(
        [sys.executable, str(hook_path)],
        input="{}",
        capture_output=True,
        text=True,
        cwd="/tmp/test",
        timeout=15,
        env=env,
    )
    assert result.returncode == 0


def test_session_export_registered() -> None:
    from lazy_harness.hooks.loader import list_builtin_hooks

    assert "session-export" in list_builtin_hooks()
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/unit/test_builtin_session_export.py -v
```

- [ ] **Step 3: Implement session export hook**

`src/lazy_harness/hooks/builtins/session_export.py`:

```python
#!/usr/bin/env python3
"""Stop hook: export session to knowledge directory.

Finds the most recent session JSONL for the current project,
exports it to markdown in the knowledge directory, and triggers QMD update.
Always exits 0.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path


def _find_latest_session(sessions_dir: Path) -> Path | None:
    """Find the most recently modified JSONL in the project's session dir."""
    if not sessions_dir.is_dir():
        return None
    jsonl_files = list(sessions_dir.glob("*.jsonl"))
    if not jsonl_files:
        return None
    return max(jsonl_files, key=lambda f: f.stat().st_mtime)


def main() -> None:
    try:
        json.load(sys.stdin)
    except (json.JSONDecodeError, EOFError):
        pass

    claude_dir = Path(os.environ.get("CLAUDE_CONFIG_DIR", Path.home() / ".claude"))
    knowledge_dir_str = os.environ.get("LH_KNOWLEDGE_DIR", "")

    if not knowledge_dir_str:
        # Try to read from config
        try:
            config_file = Path.home() / ".config" / "lazy-harness" / "config.toml"
            if config_file.is_file():
                import tomllib

                cfg = tomllib.loads(config_file.read_text())
                knowledge_dir_str = cfg.get("knowledge", {}).get("path", "")
        except Exception:
            pass

    if not knowledge_dir_str:
        return

    knowledge_dir = Path(os.path.expanduser(knowledge_dir_str))
    sessions_subdir = "sessions"

    cwd = Path.cwd()
    encoded = "-" + str(cwd).replace("/", "-").lstrip("-")
    sessions_dir = claude_dir / "projects" / encoded

    session_file = _find_latest_session(sessions_dir)
    if not session_file:
        return

    # Import the export function
    script_dir = Path(__file__).resolve().parent.parent.parent
    sys.path.insert(0, str(script_dir))

    try:
        from lazy_harness.knowledge.session_export import export_session

        output_dir = knowledge_dir / sessions_subdir
        output_dir.mkdir(parents=True, exist_ok=True)
        result = export_session(session_file, output_dir)
        if result:
            print(f"Exported session to {result}")

            # Trigger QMD update if available
            if shutil.which("qmd"):
                import subprocess

                subprocess.run(
                    ["qmd", "update"],
                    capture_output=True,
                    timeout=60,
                )
    except Exception as e:
        print(f"Session export error: {e}", file=sys.stderr)


if __name__ == "__main__":
    main()
```

Update `src/lazy_harness/hooks/loader.py` — add `"session-export"` to `_BUILTIN_HOOKS`:

```python
_BUILTIN_HOOKS: dict[str, str] = {
    "context-inject": "lazy_harness.hooks.builtins.context_inject",
    "pre-compact": "lazy_harness.hooks.builtins.pre_compact",
    "session-export": "lazy_harness.hooks.builtins.session_export",
}
```

- [ ] **Step 4: Run tests, commit**

```bash
uv run pytest tests/unit/test_builtin_session_export.py -v
git add src/lazy_harness/hooks/builtins/session_export.py src/lazy_harness/hooks/loader.py tests/unit/test_builtin_session_export.py
git commit -m "feat: built-in session-export Stop hook"
```

---

## Task 5: `lh knowledge` CLI commands

**Files:**
- Create: `src/lazy_harness/cli/knowledge_cmd.py`
- Modify: `src/lazy_harness/cli/main.py` (register knowledge command)
- Test: `tests/integration/test_knowledge_cmd.py`

- [ ] **Step 1: Write failing tests**

`tests/integration/test_knowledge_cmd.py`:

```python
"""Integration tests for lh knowledge commands."""

from __future__ import annotations

from pathlib import Path

from click.testing import CliRunner

from lazy_harness.cli.main import cli
from lazy_harness.core.config import (
    Config,
    HarnessConfig,
    KnowledgeConfig,
    save_config,
)


def _setup_config(home_dir: Path) -> Path:
    config_path = home_dir / ".config" / "lazy-harness" / "config.toml"
    knowledge_dir = home_dir / "knowledge"
    knowledge_dir.mkdir()
    cfg = Config(
        harness=HarnessConfig(version="1"),
        knowledge=KnowledgeConfig(path=str(knowledge_dir)),
    )
    save_config(cfg, config_path)
    return config_path


def test_knowledge_status(home_dir: Path) -> None:
    _setup_config(home_dir)
    runner = CliRunner()
    result = runner.invoke(cli, ["knowledge", "status"])
    assert result.exit_code == 0
    assert "knowledge" in result.output.lower()


def test_knowledge_no_path(home_dir: Path) -> None:
    config_path = home_dir / ".config" / "lazy-harness" / "config.toml"
    cfg = Config(harness=HarnessConfig(version="1"))
    save_config(cfg, config_path)
    runner = CliRunner()
    result = runner.invoke(cli, ["knowledge", "status"])
    assert "not configured" in result.output.lower() or result.exit_code != 0
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/integration/test_knowledge_cmd.py -v
```

- [ ] **Step 3: Implement knowledge CLI**

`src/lazy_harness/cli/knowledge_cmd.py`:

```python
"""lh knowledge — knowledge directory management."""

from __future__ import annotations

import click
from rich.console import Console

from lazy_harness.core.config import ConfigError, load_config
from lazy_harness.core.paths import config_file, contract_path, expand_path
from lazy_harness.knowledge.directory import ensure_knowledge_dir, list_sessions
from lazy_harness.knowledge.qmd import is_qmd_available, status as qmd_status, sync, embed


@click.group()
def knowledge() -> None:
    """Manage knowledge directory and QMD."""


@knowledge.command("status")
def knowledge_status() -> None:
    """Show knowledge directory and QMD status."""
    console = Console()
    cf = config_file()
    try:
        cfg = load_config(cf)
    except ConfigError as e:
        console.print(f"[red]Error: {e}[/red]")
        raise SystemExit(1)

    if not cfg.knowledge.path:
        console.print("[red]Knowledge path not configured.[/red]")
        console.print("Set [knowledge].path in config.toml")
        return

    kdir = expand_path(cfg.knowledge.path)
    console.print(f"[bold]Knowledge directory:[/bold] {contract_path(kdir)}")

    if kdir.is_dir():
        console.print("[green]✓[/green] Directory exists")
        sessions = list_sessions(kdir, cfg.knowledge.sessions.subdir)
        console.print(f"  Sessions: {len(sessions)} exported")
    else:
        console.print("[red]✗[/red] Directory missing")

    console.print()
    if is_qmd_available():
        console.print("[green]✓[/green] QMD available")
        result = qmd_status()
        if result.exit_code == 0 and result.stdout:
            for line in result.stdout.strip().splitlines()[:5]:
                console.print(f"  {line}")
    else:
        console.print("[yellow]·[/yellow] QMD not available")


@knowledge.command("sync")
@click.option("--collection", default=None, help="Sync specific collection")
def knowledge_sync(collection: str | None) -> None:
    """Sync QMD index (BM25)."""
    console = Console()
    if not is_qmd_available():
        console.print("[red]QMD not found in PATH[/red]")
        raise SystemExit(1)

    console.print("Syncing QMD index...")
    result = sync(collection=collection)
    if result.exit_code == 0:
        console.print("[green]✓[/green] Sync complete")
        if result.stdout.strip():
            for line in result.stdout.strip().splitlines()[:10]:
                console.print(f"  {line}")
    else:
        console.print(f"[red]✗[/red] Sync failed (exit {result.exit_code})")
        if result.stderr:
            console.print(f"  {result.stderr[:200]}")


@knowledge.command("embed")
@click.option("--collection", default=None, help="Embed specific collection")
def knowledge_embed(collection: str | None) -> None:
    """Run QMD vector embedding."""
    console = Console()
    if not is_qmd_available():
        console.print("[red]QMD not found in PATH[/red]")
        raise SystemExit(1)

    console.print("Running QMD embedding...")
    result = embed(collection=collection)
    if result.exit_code == 0:
        console.print("[green]✓[/green] Embedding complete")
    else:
        console.print(f"[red]✗[/red] Embedding failed (exit {result.exit_code})")
```

Add to `src/lazy_harness/cli/main.py` in `register_commands()`:

```python
    from lazy_harness.cli.knowledge_cmd import knowledge
    cli.add_command(knowledge, "knowledge")
```

- [ ] **Step 4: Run tests, commit**

```bash
uv run pytest tests/integration/test_knowledge_cmd.py -v
git add src/lazy_harness/cli/knowledge_cmd.py src/lazy_harness/cli/main.py tests/integration/test_knowledge_cmd.py
git commit -m "feat: lh knowledge status/sync/embed commands"
```

---

## Task 6: Scheduler — base protocol + launchd backend

**Files:**
- Create: `src/lazy_harness/scheduler/__init__.py`
- Create: `src/lazy_harness/scheduler/base.py`
- Create: `src/lazy_harness/scheduler/launchd.py`
- Test: `tests/unit/test_scheduler_launchd.py`

- [ ] **Step 1: Write failing tests**

`tests/unit/test_scheduler_launchd.py`:

```python
"""Tests for scheduler backends."""

from __future__ import annotations

from pathlib import Path


def test_scheduler_job_dataclass() -> None:
    from lazy_harness.scheduler.base import SchedulerJob

    job = SchedulerJob(name="qmd-sync", schedule="*/30 * * * *", command="lh knowledge sync")
    assert job.name == "qmd-sync"
    assert job.schedule == "*/30 * * * *"
    assert job.command == "lh knowledge sync"


def test_launchd_generate_plist(tmp_path: Path) -> None:
    from lazy_harness.scheduler.base import SchedulerJob
    from lazy_harness.scheduler.launchd import LaunchdBackend

    backend = LaunchdBackend(label_prefix="com.lazy-harness")
    job = SchedulerJob(name="qmd-sync", schedule="*/30 * * * *", command="lh knowledge sync")
    plist_path = backend.generate_plist(job, tmp_path)
    assert plist_path.is_file()
    assert plist_path.name == "com.lazy-harness.qmd-sync.plist"
    content = plist_path.read_text()
    assert "com.lazy-harness.qmd-sync" in content
    assert "lh" in content


def test_launchd_parse_interval_minutes() -> None:
    from lazy_harness.scheduler.launchd import _cron_to_interval

    assert _cron_to_interval("*/30 * * * *") == 1800
    assert _cron_to_interval("*/5 * * * *") == 300
    assert _cron_to_interval("0 * * * *") == 3600


def test_launchd_list_jobs(tmp_path: Path) -> None:
    from lazy_harness.scheduler.base import SchedulerJob
    from lazy_harness.scheduler.launchd import LaunchdBackend

    backend = LaunchdBackend(label_prefix="com.lazy-harness")
    job = SchedulerJob(name="test-job", schedule="*/10 * * * *", command="echo hi")
    backend.generate_plist(job, tmp_path)
    jobs = backend.list_jobs(tmp_path)
    assert len(jobs) == 1
    assert jobs[0] == "com.lazy-harness.test-job"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/unit/test_scheduler_launchd.py -v
```

- [ ] **Step 3: Implement scheduler base + launchd**

`src/lazy_harness/scheduler/__init__.py` — empty.

`src/lazy_harness/scheduler/base.py`:

```python
"""Scheduler base types and protocol."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, runtime_checkable


@dataclass
class SchedulerJob:
    name: str
    schedule: str  # cron expression
    command: str


@runtime_checkable
class SchedulerBackend(Protocol):
    def install(self, jobs: list[SchedulerJob]) -> list[str]:
        """Install scheduled jobs. Returns list of installed job labels."""
        ...

    def uninstall(self, jobs: list[SchedulerJob]) -> list[str]:
        """Remove scheduled jobs. Returns list of removed job labels."""
        ...

    def status(self) -> list[dict[str, str]]:
        """Return status of all managed jobs."""
        ...
```

`src/lazy_harness/scheduler/launchd.py`:

```python
"""macOS LaunchAgents scheduler backend."""

from __future__ import annotations

import plistlib
import re
import subprocess
from pathlib import Path

from lazy_harness.scheduler.base import SchedulerJob


def _cron_to_interval(cron_expr: str) -> int:
    """Convert simple cron expressions to StartInterval seconds.

    Supports: */N * * * * (every N minutes), 0 * * * * (hourly).
    Falls back to 3600 for complex expressions.
    """
    parts = cron_expr.strip().split()
    if len(parts) < 5:
        return 3600

    minute_part = parts[0]

    # */N pattern
    match = re.match(r"\*/(\d+)", minute_part)
    if match:
        return int(match.group(1)) * 60

    # 0 * * * * = hourly
    if minute_part == "0" and parts[1] == "*":
        return 3600

    return 3600


class LaunchdBackend:
    def __init__(self, label_prefix: str = "com.lazy-harness") -> None:
        self._prefix = label_prefix

    def _label(self, job: SchedulerJob) -> str:
        return f"{self._prefix}.{job.name}"

    def generate_plist(self, job: SchedulerJob, output_dir: Path) -> Path:
        """Generate a launchd plist file for a job."""
        label = self._label(job)
        interval = _cron_to_interval(job.schedule)

        # Split command into program arguments
        cmd_parts = job.command.split()

        plist: dict = {
            "Label": label,
            "ProgramArguments": cmd_parts,
            "StartInterval": interval,
            "RunAtLoad": True,
            "StandardErrorPath": str(
                Path.home() / ".local" / "share" / "lazy-harness" / "logs" / f"{job.name}-stderr.log"
            ),
            "EnvironmentVariables": {
                "PATH": "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin",
            },
        }

        plist_path = output_dir / f"{label}.plist"
        with open(plist_path, "wb") as f:
            plistlib.dump(plist, f)

        return plist_path

    def install(self, jobs: list[SchedulerJob]) -> list[str]:
        """Install LaunchAgents for all jobs."""
        agents_dir = Path.home() / "Library" / "LaunchAgents"
        agents_dir.mkdir(parents=True, exist_ok=True)

        installed: list[str] = []
        for job in jobs:
            plist_path = self.generate_plist(job, agents_dir)
            label = self._label(job)

            # Unload if already loaded
            subprocess.run(
                ["launchctl", "unload", str(plist_path)],
                capture_output=True,
            )
            # Load
            subprocess.run(
                ["launchctl", "load", str(plist_path)],
                capture_output=True,
            )
            installed.append(label)

        return installed

    def uninstall(self, jobs: list[SchedulerJob]) -> list[str]:
        """Remove LaunchAgents for all jobs."""
        agents_dir = Path.home() / "Library" / "LaunchAgents"
        removed: list[str] = []

        for job in jobs:
            label = self._label(job)
            plist_path = agents_dir / f"{label}.plist"

            if plist_path.is_file():
                subprocess.run(
                    ["launchctl", "unload", str(plist_path)],
                    capture_output=True,
                )
                plist_path.unlink()
                removed.append(label)

        return removed

    def list_jobs(self, search_dir: Path | None = None) -> list[str]:
        """List managed plist files."""
        agents_dir = search_dir or Path.home() / "Library" / "LaunchAgents"
        if not agents_dir.is_dir():
            return []
        return [
            f.stem
            for f in agents_dir.glob(f"{self._prefix}.*.plist")
        ]

    def status(self) -> list[dict[str, str]]:
        """Return status of managed LaunchAgents."""
        jobs = self.list_jobs()
        result: list[dict[str, str]] = []
        for label in jobs:
            try:
                proc = subprocess.run(
                    ["launchctl", "list", label],
                    capture_output=True,
                    text=True,
                )
                status = "loaded" if proc.returncode == 0 else "not loaded"
            except (FileNotFoundError, OSError):
                status = "unknown"
            result.append({"label": label, "status": status})
        return result
```

- [ ] **Step 4: Run tests, commit**

```bash
uv run pytest tests/unit/test_scheduler_launchd.py -v
git add src/lazy_harness/scheduler/ tests/unit/test_scheduler_launchd.py
git commit -m "feat: scheduler base protocol + launchd backend"
```

---

## Task 7: Scheduler manager (auto-detect) + systemd/cron stubs

**Files:**
- Create: `src/lazy_harness/scheduler/systemd.py`
- Create: `src/lazy_harness/scheduler/cron.py`
- Create: `src/lazy_harness/scheduler/manager.py`
- Test: `tests/unit/test_scheduler_manager.py`

- [ ] **Step 1: Write failing tests**

`tests/unit/test_scheduler_manager.py`:

```python
"""Tests for scheduler manager (auto-detect)."""

from __future__ import annotations

import platform
from unittest.mock import patch


def test_detect_backend_macos() -> None:
    from lazy_harness.scheduler.manager import detect_backend

    with patch("platform.system", return_value="Darwin"):
        backend = detect_backend()
        assert backend.__class__.__name__ == "LaunchdBackend"


def test_detect_backend_linux() -> None:
    from lazy_harness.scheduler.manager import detect_backend

    with patch("platform.system", return_value="Linux"):
        with patch("shutil.which", return_value="/usr/bin/systemctl"):
            backend = detect_backend()
            assert backend.__class__.__name__ == "SystemdBackend"


def test_detect_backend_linux_no_systemd() -> None:
    from lazy_harness.scheduler.manager import detect_backend

    with patch("platform.system", return_value="Linux"):
        with patch("shutil.which", return_value=None):
            backend = detect_backend()
            assert backend.__class__.__name__ == "CronBackend"


def test_parse_jobs_from_config() -> None:
    from lazy_harness.core.config import Config, HarnessConfig, SchedulerConfig
    from lazy_harness.scheduler.manager import parse_jobs_from_config

    cfg = Config(
        harness=HarnessConfig(version="1"),
        scheduler=SchedulerConfig(backend="auto"),
    )
    # With the scheduler_jobs dict added to config
    jobs = parse_jobs_from_config(cfg)
    assert isinstance(jobs, list)
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/unit/test_scheduler_manager.py -v
```

- [ ] **Step 3: Implement manager + stubs**

`src/lazy_harness/scheduler/systemd.py`:

```python
"""Linux systemd timers scheduler backend (stub for v1)."""

from __future__ import annotations

from lazy_harness.scheduler.base import SchedulerJob


class SystemdBackend:
    """Systemd timer backend — creates .service + .timer unit files."""

    def install(self, jobs: list[SchedulerJob]) -> list[str]:
        # TODO: Phase 4 — implement systemd timer creation
        return [f"lazy-harness-{j.name}" for j in jobs]

    def uninstall(self, jobs: list[SchedulerJob]) -> list[str]:
        return []

    def status(self) -> list[dict[str, str]]:
        return []
```

`src/lazy_harness/scheduler/cron.py`:

```python
"""Cron scheduler backend (fallback)."""

from __future__ import annotations

from lazy_harness.scheduler.base import SchedulerJob


class CronBackend:
    """Cron backend — manages entries in user's crontab."""

    def install(self, jobs: list[SchedulerJob]) -> list[str]:
        # TODO: Phase 4 — implement crontab management
        return [f"cron-{j.name}" for j in jobs]

    def uninstall(self, jobs: list[SchedulerJob]) -> list[str]:
        return []

    def status(self) -> list[dict[str, str]]:
        return []
```

`src/lazy_harness/scheduler/manager.py`:

```python
"""Scheduler manager — auto-detect backend + parse jobs from config."""

from __future__ import annotations

import platform
import shutil

from lazy_harness.core.config import Config
from lazy_harness.scheduler.base import SchedulerJob
from lazy_harness.scheduler.cron import CronBackend
from lazy_harness.scheduler.launchd import LaunchdBackend
from lazy_harness.scheduler.systemd import SystemdBackend


def detect_backend(override: str | None = None) -> LaunchdBackend | SystemdBackend | CronBackend:
    """Auto-detect the scheduler backend for the current platform."""
    if override and override != "auto":
        backends = {
            "launchd": LaunchdBackend,
            "systemd": SystemdBackend,
            "cron": CronBackend,
        }
        cls = backends.get(override)
        if cls:
            return cls()

    system = platform.system()
    if system == "Darwin":
        return LaunchdBackend()
    if system == "Linux":
        if shutil.which("systemctl"):
            return SystemdBackend()
        return CronBackend()
    return CronBackend()


def parse_jobs_from_config(cfg: Config) -> list[SchedulerJob]:
    """Parse scheduler jobs from config.toml.

    Jobs are defined in [scheduler.jobs.<name>] sections:
        [scheduler.jobs.qmd_sync]
        schedule = "*/30 * * * *"
        command = "lh knowledge sync"
    """
    jobs: list[SchedulerJob] = []
    scheduler_raw = getattr(cfg, "_raw_scheduler_jobs", {})
    # For now, return empty — jobs will be added when config supports them
    return jobs
```

- [ ] **Step 4: Run tests, commit**

```bash
uv run pytest tests/unit/test_scheduler_manager.py -v
git add src/lazy_harness/scheduler/ tests/unit/test_scheduler_manager.py
git commit -m "feat: scheduler manager with auto-detect + systemd/cron stubs"
```

---

## Task 8: `lh scheduler` CLI commands

**Files:**
- Create: `src/lazy_harness/cli/scheduler_cmd.py`
- Modify: `src/lazy_harness/cli/main.py` (register scheduler command)
- Test: `tests/integration/test_scheduler_cmd.py`

- [ ] **Step 1: Write failing tests**

`tests/integration/test_scheduler_cmd.py`:

```python
"""Integration tests for lh scheduler commands."""

from __future__ import annotations

from pathlib import Path

from click.testing import CliRunner

from lazy_harness.cli.main import cli
from lazy_harness.core.config import Config, HarnessConfig, SchedulerConfig, save_config


def _setup_config(home_dir: Path) -> Path:
    config_path = home_dir / ".config" / "lazy-harness" / "config.toml"
    cfg = Config(
        harness=HarnessConfig(version="1"),
        scheduler=SchedulerConfig(backend="auto"),
    )
    save_config(cfg, config_path)
    return config_path


def test_scheduler_status(home_dir: Path) -> None:
    _setup_config(home_dir)
    runner = CliRunner()
    result = runner.invoke(cli, ["scheduler", "status"])
    assert result.exit_code == 0
    assert "scheduler" in result.output.lower() or "backend" in result.output.lower()
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/integration/test_scheduler_cmd.py -v
```

- [ ] **Step 3: Implement scheduler CLI**

`src/lazy_harness/cli/scheduler_cmd.py`:

```python
"""lh scheduler — scheduled jobs management."""

from __future__ import annotations

import platform

import click
from rich.console import Console

from lazy_harness.core.config import ConfigError, load_config
from lazy_harness.core.paths import config_file
from lazy_harness.scheduler.manager import detect_backend


@click.group()
def scheduler() -> None:
    """Manage scheduled jobs."""


@scheduler.command("status")
def scheduler_status() -> None:
    """Show scheduler backend and job status."""
    console = Console()
    cf = config_file()
    try:
        cfg = load_config(cf)
    except ConfigError as e:
        console.print(f"[red]Error: {e}[/red]")
        raise SystemExit(1)

    backend = detect_backend(cfg.scheduler.backend)
    backend_name = backend.__class__.__name__.replace("Backend", "").lower()
    console.print(f"[bold]Scheduler backend:[/bold] {backend_name} ({platform.system()})")

    jobs = backend.status()
    if jobs:
        console.print(f"\n[bold]Jobs ({len(jobs)}):[/bold]")
        for job in jobs:
            status = job.get("status", "unknown")
            label = job.get("label", "?")
            style = "green" if status == "loaded" else "red"
            console.print(f"  [{style}]{status}[/{style}] {label}")
    else:
        console.print("\nNo managed jobs found.")
        console.print("Configure jobs in config.toml under [scheduler.jobs]")


@scheduler.command("install")
def scheduler_install() -> None:
    """Install scheduled jobs for current OS."""
    console = Console()
    cf = config_file()
    try:
        cfg = load_config(cf)
    except ConfigError as e:
        console.print(f"[red]Error: {e}[/red]")
        raise SystemExit(1)

    backend = detect_backend(cfg.scheduler.backend)
    console.print(f"Backend: {backend.__class__.__name__}")

    from lazy_harness.scheduler.manager import parse_jobs_from_config

    jobs = parse_jobs_from_config(cfg)
    if not jobs:
        console.print("No jobs configured. Add jobs in config.toml under [scheduler.jobs]")
        return

    installed = backend.install(jobs)
    for label in installed:
        console.print(f"  [green]✓[/green] {label}")


@scheduler.command("uninstall")
def scheduler_uninstall() -> None:
    """Remove all scheduled jobs."""
    console = Console()
    cf = config_file()
    try:
        cfg = load_config(cf)
    except ConfigError as e:
        console.print(f"[red]Error: {e}[/red]")
        raise SystemExit(1)

    backend = detect_backend(cfg.scheduler.backend)
    from lazy_harness.scheduler.manager import parse_jobs_from_config

    jobs = parse_jobs_from_config(cfg)
    removed = backend.uninstall(jobs)
    if removed:
        for label in removed:
            console.print(f"  [green]✓[/green] Removed {label}")
    else:
        console.print("No jobs to remove.")
```

Add to `src/lazy_harness/cli/main.py` in `register_commands()`:

```python
    from lazy_harness.cli.scheduler_cmd import scheduler
    cli.add_command(scheduler, "scheduler")
```

- [ ] **Step 4: Run tests, commit**

```bash
uv run pytest tests/integration/test_scheduler_cmd.py -v
git add src/lazy_harness/cli/scheduler_cmd.py src/lazy_harness/cli/main.py tests/integration/test_scheduler_cmd.py
git commit -m "feat: lh scheduler status/install/uninstall commands"
```

---

## Task 9: Full test suite + lint + tag v0.3.0

- [ ] **Step 1: Run all tests**

```bash
cd ~/repos/lazy/lazy-harness
uv run pytest -v
```

Expected: all tests PASS.

- [ ] **Step 2: Run linter and formatter**

```bash
uv run ruff check --fix src/ tests/
uv run ruff format src/ tests/
```

- [ ] **Step 3: Verify CLI**

```bash
uv run lh --help
uv run lh knowledge --help
uv run lh scheduler --help
```

Expected: knowledge and scheduler commands visible.

- [ ] **Step 4: Commit fixes and tag**

```bash
git add -A
git commit -m "fix: lint and format cleanup for phase 3"
git tag -a v0.3.0 -m "Phase 3: Knowledge + QMD integration + scheduler"
```

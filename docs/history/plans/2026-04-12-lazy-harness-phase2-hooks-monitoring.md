# lazy-harness Phase 2: Hooks Engine + Monitoring — Implementation Plan

> **Archived.** This document was authored in `lazy-claudecode` before the rename and migration to `lazy-harness`. Preserved for historical context. References to files and paths may be stale.


> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add hook engine (resolve, execute, deploy hooks to agent config) and monitoring (session stats collection, SQLite storage, cost calculation, `lh status` dashboard) to lazy-harness.

**Architecture:** Hook engine resolves built-in + user hooks per event, executes them, and generates agent-native config (settings.json for Claude Code). Monitoring collects token stats from agent session JSONL files, stores in SQLite, and renders via Rich TUI dashboard. Both integrate into the existing CLI and deploy pipeline.

**Tech Stack:** Python 3.11+, click, rich, SQLite (stdlib), pytest

**Spec:** `docs/superpowers/specs/2026-04-12-lazy-harness-product-design.md`

---

## File Map

### New files

```
src/lazy_harness/
├── hooks/
│   ├── __init__.py
│   ├── engine.py              # Hook resolution & execution
│   ├── loader.py              # Discover built-in + user hooks
│   └── builtins/
│       ├── __init__.py
│       ├── context_inject.py  # SessionStart: git context + handoff
│       └── pre_compact.py     # PreCompact: transcript backup + summary
├── monitoring/
│   ├── __init__.py
│   ├── collector.py           # Parse session JSONL → stats
│   ├── db.py                  # SQLite metrics store
│   ├── pricing.py             # Model pricing (defaults + config overrides)
│   └── dashboard.py           # Rich TUI dashboard
├── cli/
│   ├── hooks_cmd.py           # `lh hooks list|run`
│   └── status_cmd.py          # `lh status [costs|sessions]`
tests/
├── unit/
│   ├── test_hook_engine.py
│   ├── test_hook_loader.py
│   ├── test_collector.py
│   ├── test_db.py
│   └── test_pricing.py
└── integration/
    ├── test_hooks_cmd.py
    └── test_status_cmd.py
```

### Modified files

```
src/lazy_harness/core/config.py       # Add HooksConfig to Config dataclass
src/lazy_harness/cli/main.py          # Register hooks + status commands
src/lazy_harness/deploy/engine.py     # Add deploy_hooks()
src/lazy_harness/cli/deploy_cmd.py    # Wire deploy hooks
```

---

## Task 1: Add hooks config to Config dataclass

**Files:**
- Modify: `src/lazy_harness/core/config.py`
- Modify: `tests/unit/test_config.py`

- [ ] **Step 1: Write failing test**

Add to `tests/unit/test_config.py`:

```python
def test_load_config_with_hooks(config_dir: Path) -> None:
    config_file = config_dir / "config.toml"
    config_file.write_text("""
[harness]
version = "1"

[hooks.session_start]
scripts = ["context-inject", "git-status"]

[hooks.session_stop]
scripts = ["session-export"]
""")
    from lazy_harness.core.config import load_config

    cfg = load_config(config_file)
    assert "session_start" in cfg.hooks
    assert cfg.hooks["session_start"].scripts == ["context-inject", "git-status"]
    assert cfg.hooks["session_stop"].scripts == ["session-export"]


def test_load_config_no_hooks_defaults_empty(config_dir: Path) -> None:
    config_file = config_dir / "config.toml"
    config_file.write_text("""
[harness]
version = "1"
""")
    from lazy_harness.core.config import load_config

    cfg = load_config(config_file)
    assert cfg.hooks == {}
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd ~/repos/lazy/lazy-harness
uv run pytest tests/unit/test_config.py::test_load_config_with_hooks -v
```

Expected: AttributeError — Config has no `hooks` attribute.

- [ ] **Step 3: Add hooks to Config**

In `src/lazy_harness/core/config.py`, add after `SchedulerConfig`:

```python
@dataclass
class HookEventConfig:
    scripts: list[str] = field(default_factory=list)
```

Add to `Config` dataclass:

```python
@dataclass
class Config:
    harness: HarnessConfig = field(default_factory=HarnessConfig)
    agent: AgentConfig = field(default_factory=AgentConfig)
    profiles: ProfilesConfig = field(default_factory=ProfilesConfig)
    knowledge: KnowledgeConfig = field(default_factory=KnowledgeConfig)
    monitoring: MonitoringConfig = field(default_factory=MonitoringConfig)
    scheduler: SchedulerConfig = field(default_factory=SchedulerConfig)
    hooks: dict[str, HookEventConfig] = field(default_factory=dict)
```

In `load_config()`, add after scheduler parsing:

```python
    hooks_raw = raw.get("hooks", {})
    for event_name, event_cfg in hooks_raw.items():
        if isinstance(event_cfg, dict):
            cfg.hooks[event_name] = HookEventConfig(
                scripts=event_cfg.get("scripts", []),
            )
```

In `_config_to_dict()`, add hooks serialization:

```python
    if cfg.hooks:
        hooks_dict: dict[str, Any] = {}
        for event_name, event_cfg in cfg.hooks.items():
            hooks_dict[event_name] = {"scripts": event_cfg.scripts}
        result["hooks"] = hooks_dict
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/unit/test_config.py -v
```

Expected: all tests PASS (including new ones).

- [ ] **Step 5: Commit**

```bash
git add src/lazy_harness/core/config.py tests/unit/test_config.py
git commit -m "feat: add hooks config to Config dataclass"
```

---

## Task 2: Hook loader (discover built-in + user hooks)

**Files:**
- Create: `src/lazy_harness/hooks/__init__.py`
- Create: `src/lazy_harness/hooks/loader.py`
- Create: `src/lazy_harness/hooks/builtins/__init__.py`
- Test: `tests/unit/test_hook_loader.py`

- [ ] **Step 1: Write failing tests**

`tests/unit/test_hook_loader.py`:

```python
"""Tests for hook discovery and loading."""

from __future__ import annotations

from pathlib import Path

import pytest

from lazy_harness.core.config import Config, HarnessConfig, HookEventConfig


def test_resolve_builtin_hook() -> None:
    from lazy_harness.hooks.loader import resolve_hook

    result = resolve_hook("context-inject")
    assert result is not None
    assert result.name == "context-inject"
    assert result.is_builtin is True


def test_resolve_user_hook(tmp_path: Path) -> None:
    from lazy_harness.hooks.loader import resolve_hook

    user_hooks_dir = tmp_path / "hooks"
    user_hooks_dir.mkdir()
    script = user_hooks_dir / "my-hook.py"
    script.write_text("#!/usr/bin/env python3\nprint('hello')\n")
    script.chmod(0o755)

    result = resolve_hook("my-hook", user_hooks_dir=user_hooks_dir)
    assert result is not None
    assert result.name == "my-hook"
    assert result.is_builtin is False


def test_resolve_unknown_hook() -> None:
    from lazy_harness.hooks.loader import resolve_hook

    result = resolve_hook("nonexistent-hook")
    assert result is None


def test_resolve_hooks_for_event() -> None:
    from lazy_harness.hooks.loader import resolve_hooks_for_event

    cfg = Config(
        harness=HarnessConfig(version="1"),
        hooks={"session_start": HookEventConfig(scripts=["context-inject"])},
    )
    hooks = resolve_hooks_for_event(cfg, "session_start")
    assert len(hooks) == 1
    assert hooks[0].name == "context-inject"


def test_resolve_hooks_for_unconfigured_event() -> None:
    from lazy_harness.hooks.loader import resolve_hooks_for_event

    cfg = Config(harness=HarnessConfig(version="1"))
    hooks = resolve_hooks_for_event(cfg, "session_start")
    assert hooks == []


def test_list_builtin_hooks() -> None:
    from lazy_harness.hooks.loader import list_builtin_hooks

    builtins = list_builtin_hooks()
    assert "context-inject" in builtins
    assert "pre-compact" in builtins
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/unit/test_hook_loader.py -v
```

- [ ] **Step 3: Implement hook loader**

`src/lazy_harness/hooks/__init__.py` — empty.
`src/lazy_harness/hooks/builtins/__init__.py` — empty.

`src/lazy_harness/hooks/loader.py`:

```python
"""Hook discovery — resolve built-in and user hooks by name."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from lazy_harness.core.config import Config
from lazy_harness.core.paths import config_dir


@dataclass
class HookInfo:
    name: str
    path: Path
    is_builtin: bool


# Registry of built-in hook names → module paths
_BUILTIN_HOOKS: dict[str, str] = {
    "context-inject": "lazy_harness.hooks.builtins.context_inject",
    "pre-compact": "lazy_harness.hooks.builtins.pre_compact",
}


def list_builtin_hooks() -> list[str]:
    """Return names of all built-in hooks."""
    return list(_BUILTIN_HOOKS.keys())


def _find_builtin(name: str) -> HookInfo | None:
    """Find a built-in hook by name."""
    module_path = _BUILTIN_HOOKS.get(name)
    if module_path is None:
        return None
    # Resolve module to file path
    parts = module_path.split(".")
    # Built-in hooks live in src/lazy_harness/hooks/builtins/<name>.py
    base = Path(__file__).parent / "builtins" / f"{parts[-1]}.py"
    return HookInfo(name=name, path=base, is_builtin=True)


def _find_user_hook(name: str, user_hooks_dir: Path | None = None) -> HookInfo | None:
    """Find a user hook by name in the user hooks directory."""
    hooks_dir = user_hooks_dir or config_dir() / "hooks"
    if not hooks_dir.is_dir():
        return None

    # Look for name.py or name (executable)
    for candidate in [hooks_dir / f"{name}.py", hooks_dir / name]:
        if candidate.is_file():
            return HookInfo(name=name, path=candidate, is_builtin=False)
    return None


def resolve_hook(name: str, user_hooks_dir: Path | None = None) -> HookInfo | None:
    """Resolve a hook by name. Built-ins take priority over user hooks."""
    return _find_builtin(name) or _find_user_hook(name, user_hooks_dir)


def resolve_hooks_for_event(
    cfg: Config, event: str, user_hooks_dir: Path | None = None
) -> list[HookInfo]:
    """Resolve all hooks configured for a given event."""
    event_cfg = cfg.hooks.get(event)
    if not event_cfg:
        return []

    hooks: list[HookInfo] = []
    for script_name in event_cfg.scripts:
        hook = resolve_hook(script_name, user_hooks_dir)
        if hook:
            hooks.append(hook)
    return hooks
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/unit/test_hook_loader.py -v
```

- [ ] **Step 5: Commit**

```bash
git add src/lazy_harness/hooks/ tests/unit/test_hook_loader.py
git commit -m "feat: hook loader (discover built-in + user hooks)"
```

---

## Task 3: Hook engine (execute hooks)

**Files:**
- Create: `src/lazy_harness/hooks/engine.py`
- Test: `tests/unit/test_hook_engine.py`

- [ ] **Step 1: Write failing tests**

`tests/unit/test_hook_engine.py`:

```python
"""Tests for hook execution engine."""

from __future__ import annotations

import json
from pathlib import Path

import pytest


def test_execute_hook_python_script(tmp_path: Path) -> None:
    from lazy_harness.hooks.engine import execute_hook
    from lazy_harness.hooks.loader import HookInfo

    script = tmp_path / "test_hook.py"
    script.write_text('import json, sys; print(json.dumps({"status": "ok"}))\n')

    hook = HookInfo(name="test", path=script, is_builtin=False)
    result = execute_hook(hook, event="session_start", payload={}, timeout=5)
    assert result.exit_code == 0
    assert result.hook_name == "test"


def test_execute_hook_with_payload(tmp_path: Path) -> None:
    from lazy_harness.hooks.engine import execute_hook
    from lazy_harness.hooks.loader import HookInfo

    script = tmp_path / "echo_hook.py"
    script.write_text("import sys, json; data = json.load(sys.stdin); print(data.get('cwd', ''))\n")

    hook = HookInfo(name="echo", path=script, is_builtin=False)
    result = execute_hook(hook, event="session_start", payload={"cwd": "/tmp/test"}, timeout=5)
    assert result.exit_code == 0
    assert "/tmp/test" in result.stdout


def test_execute_hook_timeout(tmp_path: Path) -> None:
    from lazy_harness.hooks.engine import execute_hook
    from lazy_harness.hooks.loader import HookInfo

    script = tmp_path / "slow_hook.py"
    script.write_text("import time; time.sleep(10)\n")

    hook = HookInfo(name="slow", path=script, is_builtin=False)
    result = execute_hook(hook, event="session_start", payload={}, timeout=1)
    assert result.exit_code != 0
    assert result.timed_out is True


def test_execute_hook_failure(tmp_path: Path) -> None:
    from lazy_harness.hooks.engine import execute_hook
    from lazy_harness.hooks.loader import HookInfo

    script = tmp_path / "fail_hook.py"
    script.write_text("import sys; sys.exit(1)\n")

    hook = HookInfo(name="fail", path=script, is_builtin=False)
    result = execute_hook(hook, event="session_start", payload={}, timeout=5)
    assert result.exit_code == 1


def test_run_hooks_for_event(tmp_path: Path) -> None:
    from lazy_harness.hooks.engine import HookResult, run_hooks_for_event
    from lazy_harness.hooks.loader import HookInfo

    script = tmp_path / "ok_hook.py"
    script.write_text("print('ok')\n")

    hooks = [HookInfo(name="ok", path=script, is_builtin=False)]
    results = run_hooks_for_event(hooks, event="session_start", payload={})
    assert len(results) == 1
    assert results[0].exit_code == 0
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/unit/test_hook_engine.py -v
```

- [ ] **Step 3: Implement hook engine**

`src/lazy_harness/hooks/engine.py`:

```python
"""Hook execution engine — run hooks and collect results."""

from __future__ import annotations

import json
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from lazy_harness.hooks.loader import HookInfo


@dataclass
class HookResult:
    hook_name: str
    event: str
    exit_code: int
    stdout: str
    stderr: str
    duration_ms: int
    timed_out: bool


def execute_hook(
    hook: HookInfo,
    event: str,
    payload: dict,
    timeout: int = 30,
) -> HookResult:
    """Execute a single hook script."""
    start = time.monotonic()

    cmd = [sys.executable, str(hook.path)]
    input_data = json.dumps(payload)

    try:
        result = subprocess.run(
            cmd,
            input=input_data,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        duration_ms = int((time.monotonic() - start) * 1000)
        return HookResult(
            hook_name=hook.name,
            event=event,
            exit_code=result.returncode,
            stdout=result.stdout,
            stderr=result.stderr,
            duration_ms=duration_ms,
            timed_out=False,
        )
    except subprocess.TimeoutExpired:
        duration_ms = int((time.monotonic() - start) * 1000)
        return HookResult(
            hook_name=hook.name,
            event=event,
            exit_code=-1,
            stdout="",
            stderr=f"Hook timed out after {timeout}s",
            duration_ms=duration_ms,
            timed_out=True,
        )
    except OSError as e:
        duration_ms = int((time.monotonic() - start) * 1000)
        return HookResult(
            hook_name=hook.name,
            event=event,
            exit_code=-1,
            stdout="",
            stderr=str(e),
            duration_ms=duration_ms,
            timed_out=False,
        )


def run_hooks_for_event(
    hooks: list[HookInfo],
    event: str,
    payload: dict,
    timeout: int = 30,
) -> list[HookResult]:
    """Execute all hooks for an event sequentially."""
    results: list[HookResult] = []
    for hook in hooks:
        result = execute_hook(hook, event, payload, timeout)
        results.append(result)
    return results
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/unit/test_hook_engine.py -v
```

- [ ] **Step 5: Commit**

```bash
git add src/lazy_harness/hooks/engine.py tests/unit/test_hook_engine.py
git commit -m "feat: hook execution engine"
```

---

## Task 4: Built-in context-inject hook

**Files:**
- Create: `src/lazy_harness/hooks/builtins/context_inject.py`
- Test: `tests/unit/test_builtin_context_inject.py`

- [ ] **Step 1: Write failing tests**

`tests/unit/test_builtin_context_inject.py`:

```python
"""Tests for built-in context-inject hook."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest


def test_context_inject_returns_json(tmp_path: Path) -> None:
    """Hook script should output valid JSON with hookSpecificOutput."""
    hook_path = Path(__file__).parent.parent.parent / "src" / "lazy_harness" / "hooks" / "builtins" / "context_inject.py"
    result = subprocess.run(
        [sys.executable, str(hook_path)],
        input="{}",
        capture_output=True,
        text=True,
        cwd=str(tmp_path),
        timeout=10,
    )
    assert result.returncode == 0
    output = json.loads(result.stdout)
    assert "hookSpecificOutput" in output
    hso = output["hookSpecificOutput"]
    assert hso["hookEventName"] == "SessionStart"
    assert "additionalContext" in hso


def test_context_inject_includes_git_info(tmp_path: Path) -> None:
    """When run in a git repo, should include branch info."""
    # Create a git repo
    subprocess.run(["git", "init"], cwd=str(tmp_path), capture_output=True)
    subprocess.run(["git", "commit", "--allow-empty", "-m", "init"], cwd=str(tmp_path), capture_output=True)

    hook_path = Path(__file__).parent.parent.parent / "src" / "lazy_harness" / "hooks" / "builtins" / "context_inject.py"
    result = subprocess.run(
        [sys.executable, str(hook_path)],
        input="{}",
        capture_output=True,
        text=True,
        cwd=str(tmp_path),
        timeout=10,
    )
    assert result.returncode == 0
    output = json.loads(result.stdout)
    ctx = output["hookSpecificOutput"]["additionalContext"]
    assert "Branch:" in ctx or "branch" in ctx.lower()
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/unit/test_builtin_context_inject.py -v
```

- [ ] **Step 3: Implement context-inject hook**

`src/lazy_harness/hooks/builtins/context_inject.py`:

```python
#!/usr/bin/env python3
"""SessionStart hook: inject project context.

Outputs JSON with hookSpecificOutput for Claude Code.
Collects: git status, last session info, handoff notes, episodic memory.
Always exits 0.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


def git_context() -> str:
    """Collect git branch, last commit, and working tree status."""
    try:
        subprocess.run(
            ["git", "rev-parse", "--is-inside-work-tree"],
            capture_output=True,
            check=True,
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        return ""

    parts: list[str] = []

    branch = _run_git("branch", "--show-current")
    parts.append(f"Branch: {branch or 'detached'}")

    last_commit = _run_git("log", "-1", "--format=%h %s")
    if last_commit:
        parts.append(f"Last commit: {last_commit}")

    status_output = _run_git("status", "--short")
    if status_output:
        lines = status_output.strip().splitlines()
        modified = sum(1 for l in lines if not l.startswith("?"))
        untracked = sum(1 for l in lines if l.startswith("?"))
        summary_parts: list[str] = []
        if modified:
            summary_parts.append(f"{modified} modified")
        if untracked:
            summary_parts.append(f"{untracked} untracked")
        if summary_parts:
            parts.append(f"Status: {', '.join(summary_parts)}")
    else:
        parts.append("Status: clean")

    return "\n".join(parts)


def handoff_context() -> str:
    """Read handoff notes and pre-compact summary from project memory."""
    claude_dir = Path(os.environ.get("CLAUDE_CONFIG_DIR", Path.home() / ".claude"))
    cwd = Path.cwd()
    encoded = "-" + str(cwd).replace("/", "-").lstrip("-")
    memory_dir = claude_dir / "projects" / encoded / "memory"

    parts: list[str] = []

    handoff = memory_dir / "handoff.md"
    if handoff.is_file():
        parts.append(handoff.read_text(encoding="utf-8").strip())

    pre_compact = memory_dir / "pre-compact-summary.md"
    if pre_compact.is_file():
        content = pre_compact.read_text(encoding="utf-8").strip()
        # Strip HTML comments
        lines = [l for l in content.splitlines() if not l.strip().startswith("<!--")]
        if lines:
            parts.append("Pre-compact context:\n" + "\n".join(lines))

    return "\n\n".join(parts)


def episodic_context() -> str:
    """Read recent decisions and failures from JSONL episodic memory."""
    claude_dir = Path(os.environ.get("CLAUDE_CONFIG_DIR", Path.home() / ".claude"))
    cwd = Path.cwd()
    encoded = "-" + str(cwd).replace("/", "-").lstrip("-")
    memory_dir = claude_dir / "projects" / encoded / "memory"

    parts: list[str] = []

    for filename, label in [("decisions.jsonl", "Recent decisions"), ("failures.jsonl", "Recent failures")]:
        filepath = memory_dir / filename
        if not filepath.is_file():
            continue
        try:
            lines = filepath.read_text().strip().splitlines()[-3:]
            items: list[str] = []
            for line in lines:
                data = json.loads(line)
                summary = data.get("summary", "?")
                prevention = data.get("prevention", "")
                if prevention:
                    items.append(f"- {summary} → {prevention}")
                else:
                    items.append(f"- {summary}")
            if items:
                parts.append(f"{label}:\n" + "\n".join(items))
        except (json.JSONDecodeError, OSError):
            continue

    return "\n".join(parts)


def _run_git(*args: str) -> str:
    """Run a git command and return stdout, or empty string on failure."""
    try:
        result = subprocess.run(
            ["git", *args],
            capture_output=True,
            text=True,
            timeout=5,
        )
        return result.stdout.strip()
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return ""


def main() -> None:
    sections: list[str] = []

    git_ctx = git_context()
    if git_ctx:
        sections.append(f"## Git\n{git_ctx}")

    handoff_ctx = handoff_context()
    if handoff_ctx:
        sections.append(f"## Handoff from last session\n{handoff_ctx}")

    episodic_ctx = episodic_context()
    if episodic_ctx:
        sections.append(f"## Recent history\n{episodic_ctx}")

    body = "\n\n".join(sections) if sections else "New project, no prior context."

    # Truncate if too long
    if len(body) > 3000:
        body = body[:2997] + "..."

    # Build banner
    branch_line = ""
    for line in (git_ctx or "").splitlines():
        if line.startswith("Branch:"):
            branch_line = line.replace("Branch: ", "on ")
            break
    banner = f"Session context loaded: {branch_line}" if branch_line else "Session context loaded"

    output = {
        "hookSpecificOutput": {
            "hookEventName": "SessionStart",
            "additionalContext": body,
            "systemMessage": banner,
        }
    }
    print(json.dumps(output))


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/unit/test_builtin_context_inject.py -v
```

- [ ] **Step 5: Commit**

```bash
git add src/lazy_harness/hooks/builtins/context_inject.py tests/unit/test_builtin_context_inject.py
git commit -m "feat: built-in context-inject hook (SessionStart)"
```

---

## Task 5: Built-in pre-compact hook

**Files:**
- Create: `src/lazy_harness/hooks/builtins/pre_compact.py`
- Test: `tests/unit/test_builtin_pre_compact.py`

- [ ] **Step 1: Write failing tests**

`tests/unit/test_builtin_pre_compact.py`:

```python
"""Tests for built-in pre-compact hook."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def test_pre_compact_returns_json(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import pytest

    hook_path = (
        Path(__file__).parent.parent.parent
        / "src"
        / "lazy_harness"
        / "hooks"
        / "builtins"
        / "pre_compact.py"
    )
    # Create a minimal transcript JSONL
    transcript = tmp_path / "session.jsonl"
    transcript.write_text(
        json.dumps({"role": "user", "content": "hello", "timestamp": "2026-04-12T10:00:00"}) + "\n"
        + json.dumps({"role": "assistant", "content": "hi", "timestamp": "2026-04-12T10:00:01"}) + "\n"
    )

    env = {
        "PATH": os.environ.get("PATH", ""),
        "HOME": str(tmp_path),
        "CLAUDE_CONFIG_DIR": str(tmp_path / ".claude"),
    }
    (tmp_path / ".claude").mkdir()

    result = subprocess.run(
        [sys.executable, str(hook_path)],
        input=json.dumps({"transcript_path": str(transcript)}),
        capture_output=True,
        text=True,
        cwd=str(tmp_path),
        timeout=10,
        env=env,
    )
    assert result.returncode == 0


def test_pre_compact_empty_input(tmp_path: Path) -> None:
    hook_path = (
        Path(__file__).parent.parent.parent
        / "src"
        / "lazy_harness"
        / "hooks"
        / "builtins"
        / "pre_compact.py"
    )
    result = subprocess.run(
        [sys.executable, str(hook_path)],
        input="{}",
        capture_output=True,
        text=True,
        cwd=str(tmp_path),
        timeout=10,
    )
    assert result.returncode == 0
```

Note: add `import os` at the top of the test file.

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/unit/test_builtin_pre_compact.py -v
```

- [ ] **Step 3: Implement pre-compact hook**

`src/lazy_harness/hooks/builtins/pre_compact.py`:

```python
#!/usr/bin/env python3
"""PreCompact hook: preserve context before compaction.

Reads transcript path from stdin JSON, backs up transcript,
extracts working context summary, writes to memory dir.
Always exits 0.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
from datetime import datetime
from pathlib import Path


def parse_transcript(path: Path) -> tuple[list[str], list[str]]:
    """Extract user messages and touched files from a transcript JSONL."""
    user_msgs: list[str] = []
    files_touched: set[str] = set()

    try:
        for line in path.read_text().splitlines():
            if not line.strip():
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue

            role = obj.get("role", "")
            content = obj.get("content", "")

            if role == "user" and isinstance(content, str) and len(content.strip()) > 15:
                user_msgs.append(content.strip()[:200])

            if role == "assistant" and isinstance(content, list):
                for block in content:
                    if not isinstance(block, dict) or block.get("type") != "tool_use":
                        continue
                    inp = block.get("input", {})
                    for key in ("file_path", "path"):
                        val = inp.get(key, "")
                        if isinstance(val, str) and "/" in val:
                            files_touched.add(val)
    except OSError:
        pass

    return user_msgs, sorted(files_touched)


def build_summary(user_msgs: list[str], files: list[str]) -> str:
    """Build a markdown summary from parsed transcript data."""
    parts: list[str] = []
    if user_msgs:
        parts.append("## Tasks in progress")
        for msg in user_msgs[-5:]:
            parts.append(f"- {msg}")
    if files:
        parts.append("\n## Files worked on")
        for f in files[-10:]:
            parts.append(f"- {f}")
    return "\n".join(parts)


def main() -> None:
    try:
        input_data = json.load(sys.stdin)
    except (json.JSONDecodeError, EOFError):
        input_data = {}

    transcript_path_str = ""
    for key in ("transcript_path", "transcriptPath", "input"):
        if key in input_data:
            transcript_path_str = input_data[key]
            break

    cwd = Path.cwd()
    claude_dir = Path(os.environ.get("CLAUDE_CONFIG_DIR", Path.home() / ".claude"))
    encoded = "-" + str(cwd).replace("/", "-").lstrip("-")
    memory_dir = claude_dir / "projects" / encoded / "memory"
    memory_dir.mkdir(parents=True, exist_ok=True)

    summary = ""

    if transcript_path_str:
        transcript_path = Path(transcript_path_str)
        if transcript_path.is_file():
            # Backup transcript
            backup_dir = claude_dir / "compact-backups"
            backup_dir.mkdir(parents=True, exist_ok=True)
            ts = datetime.now().strftime("%Y%m%d-%H%M%S")
            proj_name = cwd.name
            backup_file = backup_dir / f"{ts}-{proj_name}.jsonl"
            shutil.copy2(transcript_path, backup_file)

            # Parse and build summary
            user_msgs, files = parse_transcript(transcript_path)
            summary = build_summary(user_msgs, files)

    if summary:
        summary_file = memory_dir / "pre-compact-summary.md"
        ts = datetime.now().isoformat()
        summary_file.write_text(f"<!-- auto-generated by pre-compact hook at {ts} -->\n{summary}\n")

        # Output for context injection
        escaped = summary.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
        output = {
            "hookSpecificOutput": {
                "hookEventName": "PreCompact",
                "additionalContext": summary,
            }
        }
        print(json.dumps(output))


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/unit/test_builtin_pre_compact.py -v
```

- [ ] **Step 5: Commit**

```bash
git add src/lazy_harness/hooks/builtins/pre_compact.py tests/unit/test_builtin_pre_compact.py
git commit -m "feat: built-in pre-compact hook (PreCompact)"
```

---

## Task 6: `lh hooks list|run` CLI commands

**Files:**
- Create: `src/lazy_harness/cli/hooks_cmd.py`
- Modify: `src/lazy_harness/cli/main.py`
- Test: `tests/integration/test_hooks_cmd.py`

- [ ] **Step 1: Write failing tests**

`tests/integration/test_hooks_cmd.py`:

```python
"""Integration tests for lh hooks commands."""

from __future__ import annotations

from pathlib import Path

from click.testing import CliRunner

from lazy_harness.cli.main import cli
from lazy_harness.core.config import (
    Config,
    HarnessConfig,
    HookEventConfig,
    ProfilesConfig,
    save_config,
)


def _setup_config(home_dir: Path) -> Path:
    config_path = home_dir / ".config" / "lazy-harness" / "config.toml"
    cfg = Config(
        harness=HarnessConfig(version="1"),
        hooks={
            "session_start": HookEventConfig(scripts=["context-inject"]),
            "pre_compact": HookEventConfig(scripts=["pre-compact"]),
        },
    )
    save_config(cfg, config_path)
    return config_path


def test_hooks_list(home_dir: Path) -> None:
    _setup_config(home_dir)
    runner = CliRunner()
    result = runner.invoke(cli, ["hooks", "list"])
    assert result.exit_code == 0
    assert "session_start" in result.output
    assert "context-inject" in result.output


def test_hooks_list_no_config(home_dir: Path) -> None:
    runner = CliRunner()
    result = runner.invoke(cli, ["hooks", "list"])
    # Should show built-in hooks even without config
    assert "context-inject" in result.output or result.exit_code != 0
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/integration/test_hooks_cmd.py -v
```

- [ ] **Step 3: Implement hooks CLI**

`src/lazy_harness/cli/hooks_cmd.py`:

```python
"""lh hooks — hook management commands."""

from __future__ import annotations

import click
from rich.console import Console
from rich.table import Table

from lazy_harness.core.config import ConfigError, load_config
from lazy_harness.core.paths import config_file
from lazy_harness.hooks.loader import list_builtin_hooks, resolve_hooks_for_event


@click.group()
def hooks() -> None:
    """Manage hooks."""


@hooks.command("list")
def hooks_list() -> None:
    """List all configured and built-in hooks."""
    console = Console()

    # Show built-in hooks
    builtins = list_builtin_hooks()
    console.print("[bold]Built-in hooks:[/bold]")
    for name in builtins:
        console.print(f"  {name}")
    console.print()

    # Show configured hooks per event
    cf = config_file()
    if not cf.is_file():
        console.print("No config file. Run: lh init")
        return

    try:
        cfg = load_config(cf)
    except ConfigError as e:
        console.print(f"[red]Error: {e}[/red]")
        return

    if not cfg.hooks:
        console.print("No hooks configured in config.toml.")
        return

    console.print("[bold]Configured hooks:[/bold]")
    table = Table(show_header=True, pad_edge=False)
    table.add_column("Event")
    table.add_column("Scripts")
    table.add_column("Status")

    for event_name, event_cfg in cfg.hooks.items():
        resolved = resolve_hooks_for_event(cfg, event_name)
        resolved_names = {h.name for h in resolved}
        script_list: list[str] = []
        for s in event_cfg.scripts:
            if s in resolved_names:
                script_list.append(f"[green]✓[/green] {s}")
            else:
                script_list.append(f"[red]✗[/red] {s} (not found)")
        table.add_row(event_name, "\n".join(script_list), f"{len(resolved)}/{len(event_cfg.scripts)}")

    console.print(table)


@hooks.command("run")
@click.argument("event")
def hooks_run(event: str) -> None:
    """Run hooks for an event (for debugging)."""
    console = Console()

    cf = config_file()
    try:
        cfg = load_config(cf)
    except ConfigError as e:
        console.print(f"[red]Error: {e}[/red]")
        raise SystemExit(1)

    from lazy_harness.hooks.engine import run_hooks_for_event
    from lazy_harness.hooks.loader import resolve_hooks_for_event as resolve_hooks

    hooks_to_run = resolve_hooks(cfg, event)
    if not hooks_to_run:
        console.print(f"No hooks configured for event '{event}'.")
        return

    console.print(f"Running {len(hooks_to_run)} hook(s) for '{event}'...")
    results = run_hooks_for_event(hooks_to_run, event=event, payload={})

    for r in results:
        status = "[green]✓[/green]" if r.exit_code == 0 else "[red]✗[/red]"
        console.print(f"  {status} {r.hook_name} ({r.duration_ms}ms)")
        if r.stderr:
            console.print(f"    stderr: {r.stderr[:200]}")
```

Add to `src/lazy_harness/cli/main.py` in `register_commands()`:

```python
    from lazy_harness.cli.hooks_cmd import hooks
    cli.add_command(hooks, "hooks")
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/integration/test_hooks_cmd.py -v
```

- [ ] **Step 5: Commit**

```bash
git add src/lazy_harness/cli/hooks_cmd.py src/lazy_harness/cli/main.py tests/integration/test_hooks_cmd.py
git commit -m "feat: lh hooks list/run commands"
```

---

## Task 7: Deploy hooks to agent config

**Files:**
- Modify: `src/lazy_harness/deploy/engine.py`
- Modify: `src/lazy_harness/cli/deploy_cmd.py`
- Test: `tests/integration/test_deploy.py` (add test)

- [ ] **Step 1: Write failing test**

Add to `tests/integration/test_deploy.py`:

```python
def test_deploy_generates_hooks_in_settings(home_dir: Path) -> None:
    """Deploy should generate settings.json with hooks pointing to framework."""
    config_path = home_dir / ".config" / "lazy-harness" / "config.toml"
    profile_content_dir = home_dir / ".config" / "lazy-harness" / "profiles" / "personal"
    profile_content_dir.mkdir(parents=True)
    (profile_content_dir / "CLAUDE.md").write_text("# Profile\n")

    target_dir = home_dir / ".claude-personal"

    from lazy_harness.core.config import (
        Config,
        HarnessConfig,
        HookEventConfig,
        ProfileEntry,
        ProfilesConfig,
        save_config,
    )

    cfg = Config(
        harness=HarnessConfig(version="1"),
        profiles=ProfilesConfig(
            default="personal",
            items={"personal": ProfileEntry(config_dir=str(target_dir), roots=["~"])},
        ),
        hooks={
            "session_start": HookEventConfig(scripts=["context-inject"]),
        },
    )
    save_config(cfg, config_path)

    runner = CliRunner()
    result = runner.invoke(cli, ["deploy"])
    assert result.exit_code == 0

    settings_file = target_dir / "settings.json"
    assert settings_file.is_file()
    settings = json.loads(settings_file.read_text())
    assert "hooks" in settings
    assert "SessionStart" in settings["hooks"]
```

Add `import json` to the top of the test file if not already present.

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest tests/integration/test_deploy.py::test_deploy_generates_hooks_in_settings -v
```

- [ ] **Step 3: Implement deploy_hooks**

Add to `src/lazy_harness/deploy/engine.py`:

```python
import json
import sys

from lazy_harness.agents.registry import get_agent
from lazy_harness.hooks.loader import resolve_hooks_for_event


def deploy_hooks(cfg: Config) -> None:
    """Generate agent-native hook config for each profile."""
    agent = get_agent(cfg.agent.type)

    # Build hook command mapping: event → list of commands
    hook_commands: dict[str, list[str]] = {}
    for event_name in cfg.hooks:
        hooks = resolve_hooks_for_event(cfg, event_name)
        if hooks:
            commands: list[str] = []
            for hook in hooks:
                commands.append(f"{sys.executable} {hook.path}")
            hook_commands[event_name] = commands

    if not hook_commands:
        click.echo("  No hooks to deploy.")
        return

    # Generate agent-native config
    agent_hooks = agent.generate_hook_config(hook_commands)

    # Write to each profile's settings.json
    for name, entry in cfg.profiles.items.items():
        target_dir = expand_path(entry.config_dir)
        target_dir.mkdir(parents=True, exist_ok=True)
        settings_file = target_dir / "settings.json"

        # Merge with existing settings if present
        settings: dict = {}
        if settings_file.is_file():
            try:
                settings = json.loads(settings_file.read_text())
            except json.JSONDecodeError:
                pass

        settings["hooks"] = agent_hooks
        settings_file.write_text(json.dumps(settings, indent=2) + "\n")
        click.echo(f"  ✓ {name}/settings.json (hooks updated)")
```

Update `src/lazy_harness/cli/deploy_cmd.py` to call `deploy_hooks`:

```python
"""lh deploy — deploy profiles, hooks, skills."""

from __future__ import annotations

import click

from lazy_harness.core.config import ConfigError, load_config
from lazy_harness.core.paths import config_file
from lazy_harness.deploy.engine import deploy_claude_symlink, deploy_hooks, deploy_profiles


@click.command("deploy")
def deploy() -> None:
    """Deploy profiles, hooks, and skills."""
    cf = config_file()
    try:
        cfg = load_config(cf)
    except ConfigError as e:
        click.echo(f"Error: {e}", err=True)
        raise SystemExit(1)

    click.echo("=== lazy-harness deploy ===\n")

    click.echo("Deploying profiles:")
    deploy_profiles(cfg)
    click.echo()

    click.echo("Deploying hooks:")
    deploy_hooks(cfg)
    click.echo()

    click.echo("Setting up ~/.claude symlink:")
    deploy_claude_symlink(cfg)
    click.echo()

    click.echo("Done.")
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/integration/test_deploy.py -v
```

- [ ] **Step 5: Commit**

```bash
git add src/lazy_harness/deploy/engine.py src/lazy_harness/cli/deploy_cmd.py tests/integration/test_deploy.py
git commit -m "feat: deploy hooks to agent settings.json"
```

---

## Task 8: Monitoring — pricing module

**Files:**
- Create: `src/lazy_harness/monitoring/__init__.py`
- Create: `src/lazy_harness/monitoring/pricing.py`
- Test: `tests/unit/test_pricing.py`

- [ ] **Step 1: Write failing tests**

`tests/unit/test_pricing.py`:

```python
"""Tests for model pricing."""

from __future__ import annotations

from pathlib import Path


def test_default_pricing() -> None:
    from lazy_harness.monitoring.pricing import default_pricing

    pricing = default_pricing()
    assert "claude-opus-4-6" in pricing
    assert pricing["claude-opus-4-6"]["input"] == 15.0
    assert pricing["claude-opus-4-6"]["output"] == 75.0


def test_calculate_cost() -> None:
    from lazy_harness.monitoring.pricing import calculate_cost, default_pricing

    pricing = default_pricing()
    tokens = {"input": 1000, "output": 500, "cache_read": 2000, "cache_create": 100}
    cost = calculate_cost("claude-opus-4-6", tokens, pricing)
    # (1000*15 + 500*75 + 2000*1.5 + 100*18.75) / 1_000_000
    expected = (15000 + 37500 + 3000 + 1875) / 1_000_000
    assert abs(cost - expected) < 0.000001


def test_calculate_cost_unknown_model() -> None:
    from lazy_harness.monitoring.pricing import calculate_cost, default_pricing

    pricing = default_pricing()
    tokens = {"input": 1000, "output": 500, "cache_read": 0, "cache_create": 0}
    cost = calculate_cost("unknown-model", tokens, pricing)
    assert cost == 0.0


def test_load_pricing_with_config_overrides(config_dir: Path) -> None:
    from lazy_harness.monitoring.pricing import load_pricing

    pricing = load_pricing(overrides={"claude-opus-4-6": {"input": 20.0, "output": 100.0, "cache_read": 2.0, "cache_create": 25.0}})
    assert pricing["claude-opus-4-6"]["input"] == 20.0
    assert "claude-sonnet-4-6" in pricing  # defaults still present
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/unit/test_pricing.py -v
```

- [ ] **Step 3: Implement pricing module**

`src/lazy_harness/monitoring/__init__.py` — empty.

`src/lazy_harness/monitoring/pricing.py`:

```python
"""Model pricing �� defaults, config overrides, cost calculation."""

from __future__ import annotations

DEFAULT_PRICING: dict[str, dict[str, float]] = {
    "claude-opus-4-6": {
        "input": 15.0,
        "output": 75.0,
        "cache_read": 1.5,
        "cache_create": 18.75,
    },
    "claude-sonnet-4-6": {
        "input": 3.0,
        "output": 15.0,
        "cache_read": 0.3,
        "cache_create": 3.75,
    },
    "claude-haiku-4-5-20251001": {
        "input": 0.8,
        "output": 4.0,
        "cache_read": 0.08,
        "cache_create": 1.0,
    },
}


def default_pricing() -> dict[str, dict[str, float]]:
    """Return a copy of default pricing."""
    return {k: dict(v) for k, v in DEFAULT_PRICING.items()}


def load_pricing(
    overrides: dict[str, dict[str, float]] | None = None,
) -> dict[str, dict[str, float]]:
    """Load pricing with optional overrides merged on top of defaults."""
    pricing = default_pricing()
    if overrides:
        for model, rates in overrides.items():
            pricing[model] = dict(rates)
    return pricing


def calculate_cost(
    model: str,
    tokens: dict[str, int],
    pricing: dict[str, dict[str, float]],
) -> float:
    """Calculate cost in USD for token usage."""
    rates = pricing.get(model)
    if not rates:
        return 0.0
    cost = (
        tokens.get("input", 0) * rates.get("input", 0)
        + tokens.get("output", 0) * rates.get("output", 0)
        + tokens.get("cache_read", 0) * rates.get("cache_read", 0)
        + tokens.get("cache_create", 0) * rates.get("cache_create", 0)
    ) / 1_000_000
    return round(cost, 6)
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/unit/test_pricing.py -v
```

- [ ] **Step 5: Commit**

```bash
git add src/lazy_harness/monitoring/ tests/unit/test_pricing.py
git commit -m "feat: model pricing module with defaults and overrides"
```

---

## Task 9: Monitoring — session JSONL collector

**Files:**
- Create: `src/lazy_harness/monitoring/collector.py`
- Test: `tests/unit/test_collector.py`

- [ ] **Step 1: Write failing tests**

`tests/unit/test_collector.py`:

```python
"""Tests for session JSONL collector."""

from __future__ import annotations

import json
from pathlib import Path


def _write_session_jsonl(path: Path, messages: list[dict]) -> None:
    """Write a list of message dicts as JSONL."""
    with open(path, "w") as f:
        for msg in messages:
            f.write(json.dumps(msg) + "\n")


def test_parse_session_extracts_tokens(tmp_path: Path) -> None:
    from lazy_harness.monitoring.collector import parse_session

    session_file = tmp_path / "abc12345.jsonl"
    _write_session_jsonl(session_file, [
        {"type": "user", "content": "hello", "timestamp": "2026-04-12T10:00:00"},
        {
            "type": "assistant",
            "message": {
                "model": "claude-opus-4-6",
                "usage": {
                    "input_tokens": 100,
                    "output_tokens": 50,
                    "cache_read_input_tokens": 200,
                    "cache_creation_input_tokens": 10,
                },
            },
            "timestamp": "2026-04-12T10:00:01",
        },
    ])

    results = parse_session(session_file)
    assert len(results) == 1
    r = results[0]
    assert r["model"] == "claude-opus-4-6"
    assert r["input"] == 100
    assert r["output"] == 50
    assert r["cache_read"] == 200
    assert r["cache_create"] == 10
    assert r["session"] == "abc12345"
    assert r["date"] == "2026-04-12"


def test_parse_session_multiple_models(tmp_path: Path) -> None:
    from lazy_harness.monitoring.collector import parse_session

    session_file = tmp_path / "def67890.jsonl"
    _write_session_jsonl(session_file, [
        {"type": "user", "content": "hello", "timestamp": "2026-04-12T10:00:00"},
        {
            "type": "assistant",
            "message": {
                "model": "claude-opus-4-6",
                "usage": {"input_tokens": 100, "output_tokens": 50},
            },
        },
        {
            "type": "assistant",
            "message": {
                "model": "claude-sonnet-4-6",
                "usage": {"input_tokens": 200, "output_tokens": 100},
            },
        },
    ])

    results = parse_session(session_file)
    assert len(results) == 2
    models = {r["model"] for r in results}
    assert models == {"claude-opus-4-6", "claude-sonnet-4-6"}


def test_parse_session_empty_file(tmp_path: Path) -> None:
    from lazy_harness.monitoring.collector import parse_session

    session_file = tmp_path / "empty.jsonl"
    session_file.write_text("")
    results = parse_session(session_file)
    assert results == []


def test_extract_project_name() -> None:
    from lazy_harness.monitoring.collector import extract_project_name

    assert extract_project_name("-Users-foo-repos-my-project") == "my-project"
    assert extract_project_name("-Users-foo-repos-lazy-lazy-harness") == "lazy-harness"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/unit/test_collector.py -v
```

- [ ] **Step 3: Implement collector**

`src/lazy_harness/monitoring/collector.py`:

```python
"""Session JSONL collector — parse agent sessions into token stats."""

from __future__ import annotations

import json
import os
from collections import defaultdict
from pathlib import Path
from typing import Any


def extract_session_date(filepath: Path) -> str:
    """Extract date from the first timestamped entry in a JSONL file."""
    try:
        for line in filepath.read_text().splitlines():
            if not line.strip():
                continue
            try:
                obj = json.loads(line)
                ts = obj.get("timestamp", "")
                if ts and len(ts) >= 10:
                    return ts[:10]
            except json.JSONDecodeError:
                continue
    except OSError:
        pass
    return "unknown"


def extract_project_name(encoded_dir: str) -> str:
    """Convert encoded project dir name to human-readable name.

    Claude Code encodes paths: /Users/foo/repos/my-project → -Users-foo-repos-my-project
    We try to resolve against the filesystem, falling back to last path segment.
    """
    if not encoded_dir.startswith("-"):
        return encoded_dir
    raw = encoded_dir[1:]
    if not raw:
        return "(root)"
    parts = raw.split("-")

    def try_build(index: int, current_path: str) -> str | None:
        if index == len(parts):
            return current_path if os.path.exists(current_path) else None
        combined = parts[index]
        for j in range(index, len(parts)):
            if j > index:
                combined += "-" + parts[j]
            candidate = os.path.join(current_path, combined)
            result = try_build(j + 1, candidate)
            if result:
                return result
        return None

    resolved = try_build(0, "/")
    if resolved:
        return os.path.basename(resolved)
    return parts[-1] if parts else encoded_dir


def parse_session(filepath: Path) -> list[dict[str, Any]]:
    """Parse a session JSONL, return aggregated stats per model."""
    aggregated: dict[str, dict[str, int]] = defaultdict(
        lambda: {"input": 0, "output": 0, "cache_read": 0, "cache_create": 0}
    )

    try:
        for line in filepath.read_text().splitlines():
            if not line.strip():
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue

            if obj.get("type") != "assistant":
                continue

            msg = obj.get("message", {})
            if not isinstance(msg, dict):
                continue

            usage = msg.get("usage")
            model = msg.get("model", "unknown")
            if not usage:
                continue

            agg = aggregated[model]
            agg["input"] += usage.get("input_tokens", 0)
            agg["output"] += usage.get("output_tokens", 0)
            agg["cache_read"] += usage.get("cache_read_input_tokens", 0)
            agg["cache_create"] += usage.get("cache_creation_input_tokens", 0)
    except OSError:
        return []

    session_id = filepath.stem[:8]
    session_date = extract_session_date(filepath)

    results: list[dict[str, Any]] = []
    for model, tokens in aggregated.items():
        results.append({
            "session": session_id,
            "date": session_date,
            "model": model,
            "input": tokens["input"],
            "output": tokens["output"],
            "cache_read": tokens["cache_read"],
            "cache_create": tokens["cache_create"],
        })
    return results
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/unit/test_collector.py -v
```

- [ ] **Step 5: Commit**

```bash
git add src/lazy_harness/monitoring/collector.py tests/unit/test_collector.py
git commit -m "feat: session JSONL collector"
```

---

## Task 10: Monitoring — SQLite metrics store

**Files:**
- Create: `src/lazy_harness/monitoring/db.py`
- Test: `tests/unit/test_db.py`

- [ ] **Step 1: Write failing tests**

`tests/unit/test_db.py`:

```python
"""Tests for SQLite metrics store."""

from __future__ import annotations

from pathlib import Path


def test_create_db(tmp_path: Path) -> None:
    from lazy_harness.monitoring.db import MetricsDB

    db = MetricsDB(tmp_path / "metrics.db")
    assert (tmp_path / "metrics.db").is_file()
    db.close()


def test_insert_and_query_sessions(tmp_path: Path) -> None:
    from lazy_harness.monitoring.db import MetricsDB

    db = MetricsDB(tmp_path / "metrics.db")
    db.insert_stats([
        {
            "session": "abc12345",
            "date": "2026-04-12",
            "model": "claude-opus-4-6",
            "profile": "personal",
            "project": "my-project",
            "input": 1000,
            "output": 500,
            "cache_read": 200,
            "cache_create": 10,
            "cost": 0.05,
        },
    ])

    rows = db.query_stats(period="all")
    assert len(rows) == 1
    assert rows[0]["session"] == "abc12345"
    assert rows[0]["cost"] == 0.05
    db.close()


def test_query_by_period(tmp_path: Path) -> None:
    from lazy_harness.monitoring.db import MetricsDB

    db = MetricsDB(tmp_path / "metrics.db")
    db.insert_stats([
        {"session": "a", "date": "2026-04-10", "model": "m", "profile": "p", "project": "x", "input": 100, "output": 50, "cache_read": 0, "cache_create": 0, "cost": 0.01},
        {"session": "b", "date": "2026-04-12", "model": "m", "profile": "p", "project": "x", "input": 200, "output": 100, "cache_read": 0, "cache_create": 0, "cost": 0.02},
    ])

    rows = db.query_stats(since="2026-04-11")
    assert len(rows) == 1
    assert rows[0]["session"] == "b"
    db.close()


def test_aggregate_costs(tmp_path: Path) -> None:
    from lazy_harness.monitoring.db import MetricsDB

    db = MetricsDB(tmp_path / "metrics.db")
    db.insert_stats([
        {"session": "a", "date": "2026-04-12", "model": "claude-opus-4-6", "profile": "personal", "project": "x", "input": 100, "output": 50, "cache_read": 0, "cache_create": 0, "cost": 0.05},
        {"session": "b", "date": "2026-04-12", "model": "claude-opus-4-6", "profile": "personal", "project": "y", "input": 200, "output": 100, "cache_read": 0, "cache_create": 0, "cost": 0.10},
    ])

    totals = db.aggregate_costs(period="all")
    assert totals["total_cost"] == 0.15
    assert totals["total_input"] == 300
    db.close()


def test_no_duplicate_insert(tmp_path: Path) -> None:
    from lazy_harness.monitoring.db import MetricsDB

    db = MetricsDB(tmp_path / "metrics.db")
    entry = {"session": "abc", "date": "2026-04-12", "model": "m", "profile": "p", "project": "x", "input": 100, "output": 50, "cache_read": 0, "cache_create": 0, "cost": 0.01}
    db.insert_stats([entry])
    db.insert_stats([entry])  # duplicate
    rows = db.query_stats(period="all")
    assert len(rows) == 1
    db.close()
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/unit/test_db.py -v
```

- [ ] **Step 3: Implement SQLite metrics store**

`src/lazy_harness/monitoring/db.py`:

```python
"""SQLite metrics store for session stats."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any


class MetricsDB:
    """SQLite-backed metrics storage."""

    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(path))
        self._conn.row_factory = sqlite3.Row
        self._create_tables()

    def _create_tables(self) -> None:
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS session_stats (
                session TEXT NOT NULL,
                date TEXT NOT NULL,
                model TEXT NOT NULL,
                profile TEXT NOT NULL DEFAULT '',
                project TEXT NOT NULL DEFAULT '',
                input_tokens INTEGER NOT NULL DEFAULT 0,
                output_tokens INTEGER NOT NULL DEFAULT 0,
                cache_read INTEGER NOT NULL DEFAULT 0,
                cache_create INTEGER NOT NULL DEFAULT 0,
                cost REAL NOT NULL DEFAULT 0.0,
                UNIQUE(session, model)
            )
        """)
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_stats_date ON session_stats(date)"
        )
        self._conn.commit()

    def insert_stats(self, entries: list[dict[str, Any]]) -> int:
        """Insert stats entries. Duplicates (same session+model) are ignored."""
        inserted = 0
        for entry in entries:
            try:
                self._conn.execute(
                    """INSERT OR IGNORE INTO session_stats
                    (session, date, model, profile, project, input_tokens, output_tokens, cache_read, cache_create, cost)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        entry["session"],
                        entry["date"],
                        entry["model"],
                        entry.get("profile", ""),
                        entry.get("project", ""),
                        entry.get("input", 0),
                        entry.get("output", 0),
                        entry.get("cache_read", 0),
                        entry.get("cache_create", 0),
                        entry.get("cost", 0.0),
                    ),
                )
                inserted += self._conn.total_changes
            except sqlite3.IntegrityError:
                pass
        self._conn.commit()
        return inserted

    def query_stats(
        self,
        period: str = "all",
        since: str | None = None,
    ) -> list[dict[str, Any]]:
        """Query stats with optional date filtering."""
        if since:
            rows = self._conn.execute(
                "SELECT * FROM session_stats WHERE date >= ? ORDER BY date DESC",
                (since,),
            ).fetchall()
        elif period == "all":
            rows = self._conn.execute(
                "SELECT * FROM session_stats ORDER BY date DESC"
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT * FROM session_stats WHERE date LIKE ? ORDER BY date DESC",
                (f"{period}%",),
            ).fetchall()

        return [
            {
                "session": r["session"],
                "date": r["date"],
                "model": r["model"],
                "profile": r["profile"],
                "project": r["project"],
                "input": r["input_tokens"],
                "output": r["output_tokens"],
                "cache_read": r["cache_read"],
                "cache_create": r["cache_create"],
                "cost": r["cost"],
            }
            for r in rows
        ]

    def aggregate_costs(
        self,
        period: str = "all",
        since: str | None = None,
    ) -> dict[str, Any]:
        """Aggregate total costs and tokens."""
        if since:
            row = self._conn.execute(
                """SELECT
                    COALESCE(SUM(cost), 0) as total_cost,
                    COALESCE(SUM(input_tokens), 0) as total_input,
                    COALESCE(SUM(output_tokens), 0) as total_output,
                    COUNT(DISTINCT session) as session_count
                FROM session_stats WHERE date >= ?""",
                (since,),
            ).fetchone()
        elif period == "all":
            row = self._conn.execute(
                """SELECT
                    COALESCE(SUM(cost), 0) as total_cost,
                    COALESCE(SUM(input_tokens), 0) as total_input,
                    COALESCE(SUM(output_tokens), 0) as total_output,
                    COUNT(DISTINCT session) as session_count
                FROM session_stats"""
            ).fetchone()
        else:
            row = self._conn.execute(
                """SELECT
                    COALESCE(SUM(cost), 0) as total_cost,
                    COALESCE(SUM(input_tokens), 0) as total_input,
                    COALESCE(SUM(output_tokens), 0) as total_output,
                    COUNT(DISTINCT session) as session_count
                FROM session_stats WHERE date LIKE ?""",
                (f"{period}%",),
            ).fetchone()

        return {
            "total_cost": round(row["total_cost"], 2),
            "total_input": row["total_input"],
            "total_output": row["total_output"],
            "session_count": row["session_count"],
        }

    def close(self) -> None:
        self._conn.close()
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/unit/test_db.py -v
```

- [ ] **Step 5: Commit**

```bash
git add src/lazy_harness/monitoring/db.py tests/unit/test_db.py
git commit -m "feat: SQLite metrics store"
```

---

## Task 11: `lh status` dashboard

**Files:**
- Create: `src/lazy_harness/monitoring/dashboard.py`
- Create: `src/lazy_harness/cli/status_cmd.py`
- Modify: `src/lazy_harness/cli/main.py`
- Test: `tests/integration/test_status_cmd.py`

- [ ] **Step 1: Write failing tests**

`tests/integration/test_status_cmd.py`:

```python
"""Integration tests for lh status commands."""

from __future__ import annotations

from pathlib import Path

from click.testing import CliRunner

from lazy_harness.cli.main import cli
from lazy_harness.core.config import (
    Config,
    HarnessConfig,
    MonitoringConfig,
    ProfileEntry,
    ProfilesConfig,
    save_config,
)


def _setup_config(home_dir: Path) -> Path:
    config_path = home_dir / ".config" / "lazy-harness" / "config.toml"
    db_path = home_dir / ".local" / "share" / "lazy-harness" / "metrics.db"
    cfg = Config(
        harness=HarnessConfig(version="1"),
        profiles=ProfilesConfig(
            default="personal",
            items={"personal": ProfileEntry(config_dir=str(home_dir / ".claude-personal"), roots=["~"])},
        ),
        monitoring=MonitoringConfig(enabled=True, db=str(db_path)),
    )
    save_config(cfg, config_path)
    (home_dir / ".claude-personal").mkdir(parents=True, exist_ok=True)
    return config_path


def test_status_overview(home_dir: Path) -> None:
    _setup_config(home_dir)
    runner = CliRunner()
    result = runner.invoke(cli, ["status"])
    assert result.exit_code == 0
    assert "personal" in result.output.lower() or "session" in result.output.lower() or "no data" in result.output.lower()


def test_status_costs(home_dir: Path) -> None:
    _setup_config(home_dir)
    runner = CliRunner()
    result = runner.invoke(cli, ["status", "costs"])
    assert result.exit_code == 0


def test_status_no_monitoring(home_dir: Path) -> None:
    config_path = home_dir / ".config" / "lazy-harness" / "config.toml"
    cfg = Config(
        harness=HarnessConfig(version="1"),
        monitoring=MonitoringConfig(enabled=False),
    )
    save_config(cfg, config_path)
    runner = CliRunner()
    result = runner.invoke(cli, ["status"])
    assert "monitoring" in result.output.lower() or "disabled" in result.output.lower() or result.exit_code == 0
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/integration/test_status_cmd.py -v
```

- [ ] **Step 3: Implement dashboard and status CLI**

`src/lazy_harness/monitoring/dashboard.py`:

```python
"""Rich TUI dashboard for monitoring."""

from __future__ import annotations

from typing import Any

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from lazy_harness.monitoring.db import MetricsDB


def format_tokens(n: int) -> str:
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n / 1_000:.1f}K"
    return str(n)


def render_overview(db: MetricsDB, console: Console) -> None:
    """Render the overview dashboard panel."""
    totals = db.aggregate_costs(period="all")

    if totals["session_count"] == 0:
        console.print("No data yet. Run some sessions first.")
        return

    lines: list[str] = [
        f"Sessions: {totals['session_count']}",
        f"Tokens in: {format_tokens(totals['total_input'])}",
        f"Tokens out: {format_tokens(totals['total_output'])}",
        f"Total cost: ${totals['total_cost']}",
    ]
    panel = Panel("\n".join(lines), title="lh status", border_style="bold")
    console.print(panel)


def render_costs(db: MetricsDB, console: Console, period: str = "all", since: str | None = None) -> None:
    """Render cost breakdown table."""
    rows = db.query_stats(period=period, since=since)
    if not rows:
        console.print("No data for this period.")
        return

    # Aggregate by date
    by_date: dict[str, dict[str, Any]] = {}
    for r in rows:
        date = r["date"]
        if date not in by_date:
            by_date[date] = {"sessions": set(), "input": 0, "output": 0, "cost": 0.0}
        by_date[date]["sessions"].add(r["session"])
        by_date[date]["input"] += r["input"] + r["cache_read"] + r["cache_create"]
        by_date[date]["output"] += r["output"]
        by_date[date]["cost"] += r["cost"]

    table = Table(show_header=True, pad_edge=False)
    table.add_column("Date")
    table.add_column("Sessions", justify="right")
    table.add_column("Input", justify="right")
    table.add_column("Output", justify="right")
    table.add_column("Cost", justify="right")

    total_cost = 0.0
    for date in sorted(by_date, reverse=True):
        d = by_date[date]
        cost = round(d["cost"], 2)
        total_cost += cost
        table.add_row(
            date,
            str(len(d["sessions"])),
            format_tokens(d["input"]),
            format_tokens(d["output"]),
            f"${cost}",
        )

    table.add_section()
    table.add_row("Total", "", "", "", f"${round(total_cost, 2)}", style="bold")

    console.print(table)
```

`src/lazy_harness/cli/status_cmd.py`:

```python
"""lh status — monitoring dashboard."""

from __future__ import annotations

from datetime import datetime, timedelta

import click
from rich.console import Console

from lazy_harness.core.config import ConfigError, load_config
from lazy_harness.core.paths import config_file, data_dir, expand_path
from lazy_harness.monitoring.dashboard import render_costs, render_overview
from lazy_harness.monitoring.db import MetricsDB


def _get_db(cfg) -> MetricsDB:
    """Get or create MetricsDB from config."""
    if cfg.monitoring.db:
        db_path = expand_path(cfg.monitoring.db)
    else:
        db_path = data_dir() / "metrics.db"
    return MetricsDB(db_path)


@click.group(invoke_without_command=True)
@click.pass_context
def status(ctx: click.Context) -> None:
    """Monitoring dashboard."""
    if ctx.invoked_subcommand is not None:
        return

    console = Console()
    cf = config_file()
    try:
        cfg = load_config(cf)
    except ConfigError as e:
        console.print(f"[red]Error: {e}[/red]")
        raise SystemExit(1)

    if not cfg.monitoring.enabled:
        console.print("Monitoring is disabled. Enable in config.toml:")
        console.print("  [monitoring]")
        console.print("  enabled = true")
        return

    db = _get_db(cfg)
    try:
        render_overview(db, console)
    finally:
        db.close()


@status.command("costs")
@click.option("--period", default="7d", help="Period: 7d, 30d, month, all")
def status_costs(period: str) -> None:
    """Show cost breakdown."""
    console = Console()
    cf = config_file()
    try:
        cfg = load_config(cf)
    except ConfigError as e:
        console.print(f"[red]Error: {e}[/red]")
        raise SystemExit(1)

    if not cfg.monitoring.enabled:
        console.print("Monitoring is disabled.")
        return

    since = None
    query_period = "all"
    if period.endswith("d"):
        days = int(period[:-1])
        since = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    elif period == "month":
        query_period = datetime.now().strftime("%Y-%m")
    elif period != "all":
        query_period = period

    db = _get_db(cfg)
    try:
        render_costs(db, console, period=query_period, since=since)
    finally:
        db.close()
```

Add to `src/lazy_harness/cli/main.py` in `register_commands()`:

```python
    from lazy_harness.cli.status_cmd import status
    cli.add_command(status, "status")
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/integration/test_status_cmd.py -v
```

- [ ] **Step 5: Commit**

```bash
git add src/lazy_harness/monitoring/dashboard.py src/lazy_harness/cli/status_cmd.py src/lazy_harness/cli/main.py tests/integration/test_status_cmd.py
git commit -m "feat: lh status dashboard with costs view"
```

---

## Task 12: Full test suite + lint + validation

- [ ] **Step 1: Run all tests**

```bash
cd ~/repos/lazy/lazy-harness
uv run pytest -v
```

Expected: all tests PASS.

- [ ] **Step 2: Run linter**

```bash
uv run ruff check src/ tests/
uv run ruff format src/ tests/
```

Fix any issues.

- [ ] **Step 3: Verify CLI commands**

```bash
uv run lh --help
uv run lh hooks --help
uv run lh status --help
```

Expected: hooks and status commands visible.

- [ ] **Step 4: Commit fixes**

```bash
git add -A
git commit -m "fix: lint and format cleanup for phase 2"
```

- [ ] **Step 5: Tag**

```bash
git tag -a v0.2.0 -m "Phase 2: Hook engine + monitoring dashboard"
```

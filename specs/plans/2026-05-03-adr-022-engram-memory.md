# ADR-022 — Engram as Optional Episodic Memory Backend — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Strict TDD per repo non-negotiable #2.

**Goal:** Add an Engram CLI wrapper module + config sections + MCP deploy wiring so `lh deploy` ships an `engram` MCP server entry to each profile when (a) Engram is installed and (b) `[memory.engram].enabled = true`.

**Architecture:** Mirror the QMD precedent (ADR-016) one-to-one — new `memory/engram.py` module with `is_engram_available()` + `run_engram()` + `mcp_server_config()` + version pin constant. Extend `Config` with a new `[memory.engram]` section parsed by the same `load_config` flow. Extend `_collect_mcp_servers` in `deploy/engine.py` to include Engram when both gates are open. The MCP deploy machinery (ADR-024) carries the rest.

**Tech Stack:** Python 3.11, pytest, ruff, MkDocs Material. Runs in worktree `.worktrees/engram-memory` on branch `feat/engram-memory`. Pinned Engram version: 1.15.4 (per user decision).

**Out of scope (later work):** Wizard prompts (`enable_engram` flag in `WizardAnswers`) and `lh doctor` reporting both belong to Fase 3 — covered by a separate ADR/PR after Graphify (ADR-023). The cloud sync flag is exposed in config but no code branches on it in this PR.

---

## File Structure

| Path | Status | Responsibility |
|------|--------|----------------|
| `src/lazy_harness/memory/__init__.py` | create | Package marker |
| `src/lazy_harness/memory/engram.py` | create | CLI wrapper: probe, run, MCP entry, version check |
| `src/lazy_harness/core/config.py` | modify | Add `EngramConfig`, `MemoryConfig`, `Config.memory`, parser |
| `src/lazy_harness/deploy/engine.py` | modify | Extend `_collect_mcp_servers` to include Engram when gated open |
| `tests/unit/test_engram.py` | create | Wrapper tests (mirror `test_qmd.py`) |
| `tests/unit/test_config.py` | modify | Test `[memory.engram]` parse and defaults |
| `tests/unit/test_deploy_mcp.py` | modify | Test Engram inclusion + skip-when-disabled |
| `specs/adrs/022-engram-episodic-memory.md` | create | ADR document |
| `specs/adrs/README.md` | modify | Add ADR-022 to index |

---

## Task 1: Engram CLI wrapper module

**Files:**
- Create: `src/lazy_harness/memory/__init__.py`
- Create: `src/lazy_harness/memory/engram.py`
- Create: `tests/unit/test_engram.py`

- [ ] **Step 1.1: Create the package init**

```python
# src/lazy_harness/memory/__init__.py
"""Episodic memory backends — Engram and friends."""
```

- [ ] **Step 1.2: Write the first failing test (`is_engram_available` returns bool)**

Create `tests/unit/test_engram.py`:

```python
"""Tests for Engram CLI wrapper."""

from __future__ import annotations

from unittest.mock import patch


def test_engram_available_returns_bool() -> None:
    from lazy_harness.memory.engram import is_engram_available

    result = is_engram_available()
    assert isinstance(result, bool)
```

- [ ] **Step 1.3: Run, expect failure**

```bash
uv run pytest tests/unit/test_engram.py::test_engram_available_returns_bool -v
```

Expected: `ModuleNotFoundError: No module named 'lazy_harness.memory.engram'`

- [ ] **Step 1.4: Create the wrapper with the minimum to pass**

```python
# src/lazy_harness/memory/engram.py
"""Engram CLI wrapper — episodic memory for AI coding agents.

Pinned version: 1.15.4 (see ADR-022).
"""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass


PINNED_VERSION = "1.15.4"


@dataclass
class EngramResult:
    exit_code: int
    stdout: str
    stderr: str


def is_engram_available() -> bool:
    return shutil.which("engram") is not None
```

- [ ] **Step 1.5: Run, expect pass**

```bash
uv run pytest tests/unit/test_engram.py::test_engram_available_returns_bool -v
```

Expected: PASS.

- [ ] **Step 1.6: Add tests for `_build_command` and `run_engram`**

Append to `tests/unit/test_engram.py`:

```python
def test_engram_build_command_basic() -> None:
    from lazy_harness.memory.engram import _build_command

    cmd = _build_command("status")
    assert cmd == ["engram", "status"]


def test_engram_build_command_with_project() -> None:
    from lazy_harness.memory.engram import _build_command

    cmd = _build_command("search", project="lazy-harness")
    assert cmd == ["engram", "search", "--project", "lazy-harness"]


def test_engram_run_returns_result() -> None:
    from lazy_harness.memory.engram import EngramResult, run_engram

    with patch("subprocess.run") as mock_run:
        mock_run.return_value = type(
            "R", (), {"returncode": 0, "stdout": "OK", "stderr": ""}
        )()
        result = run_engram("status")
        assert isinstance(result, EngramResult)
        assert result.exit_code == 0
        assert result.stdout == "OK"


def test_engram_run_handles_missing_binary() -> None:
    from lazy_harness.memory.engram import run_engram

    with patch("subprocess.run", side_effect=FileNotFoundError):
        result = run_engram("status")
        assert result.exit_code == -1
        assert "engram not found" in result.stderr
```

- [ ] **Step 1.7: Run, expect failure on the new tests**

```bash
uv run pytest tests/unit/test_engram.py -v
```

Expected: 4 failures (`_build_command` and `run_engram` not defined).

- [ ] **Step 1.8: Implement `_build_command` and `run_engram`**

Append to `src/lazy_harness/memory/engram.py`:

```python
def _build_command(action: str, project: str | None = None) -> list[str]:
    cmd = ["engram", action]
    if project:
        cmd.extend(["--project", project])
    return cmd


def run_engram(
    action: str, project: str | None = None, timeout: int = 300
) -> EngramResult:
    cmd = _build_command(action, project=project)
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return EngramResult(
            exit_code=result.returncode, stdout=result.stdout, stderr=result.stderr
        )
    except subprocess.TimeoutExpired:
        return EngramResult(
            exit_code=-1, stdout="", stderr=f"engram timed out after {timeout}s"
        )
    except FileNotFoundError:
        return EngramResult(exit_code=-1, stdout="", stderr="engram not found in PATH")
```

- [ ] **Step 1.9: Run, expect pass**

```bash
uv run pytest tests/unit/test_engram.py -v
```

Expected: 5 tests pass.

- [ ] **Step 1.10: Add tests for `mcp_server_config` and `PINNED_VERSION`**

Append to `tests/unit/test_engram.py`:

```python
def test_engram_mcp_server_config_shape() -> None:
    from lazy_harness.memory.engram import mcp_server_config

    entry = mcp_server_config()
    assert entry["command"] == "engram"
    assert entry["args"] == ["mcp"]


def test_engram_pinned_version_constant() -> None:
    from lazy_harness.memory import engram

    assert engram.PINNED_VERSION == "1.15.4"
```

- [ ] **Step 1.11: Run, expect 1 fail (mcp_server_config missing)**

```bash
uv run pytest tests/unit/test_engram.py -v
```

Expected: 6 pass + 1 fail (`PINNED_VERSION` already passes from Step 1.4; `mcp_server_config` is missing).

- [ ] **Step 1.12: Implement `mcp_server_config`**

Append to `src/lazy_harness/memory/engram.py`:

```python
def mcp_server_config() -> dict:
    """Declarative MCP entry for Engram (consumed by deploy_mcp_servers)."""
    return {"command": "engram", "args": ["mcp"]}
```

- [ ] **Step 1.13: Run, expect all pass**

```bash
uv run pytest tests/unit/test_engram.py -v
```

Expected: 7 tests pass.

- [ ] **Step 1.14: Add `check_version` test**

Append to `tests/unit/test_engram.py`:

```python
def test_engram_check_version_matches_pin() -> None:
    from lazy_harness.memory.engram import check_version

    with patch("subprocess.run") as mock_run:
        mock_run.return_value = type(
            "R", (), {"returncode": 0, "stdout": "engram 1.15.4\n", "stderr": ""}
        )()
        matches, current = check_version()
        assert matches is True
        assert current == "1.15.4"


def test_engram_check_version_mismatch() -> None:
    from lazy_harness.memory.engram import check_version

    with patch("subprocess.run") as mock_run:
        mock_run.return_value = type(
            "R", (), {"returncode": 0, "stdout": "engram 1.16.0\n", "stderr": ""}
        )()
        matches, current = check_version()
        assert matches is False
        assert current == "1.16.0"


def test_engram_check_version_missing_binary() -> None:
    from lazy_harness.memory.engram import check_version

    with patch("subprocess.run", side_effect=FileNotFoundError):
        matches, current = check_version()
        assert matches is False
        assert current == ""
```

- [ ] **Step 1.15: Run, expect failure**

```bash
uv run pytest tests/unit/test_engram.py -v -k check_version
```

Expected: 3 failures (`check_version` undefined).

- [ ] **Step 1.16: Implement `check_version`**

Append to `src/lazy_harness/memory/engram.py`:

```python
def check_version() -> tuple[bool, str]:
    """Probe `engram --version` and compare against PINNED_VERSION.

    Returns `(matches, current_version)`. `current_version` is empty string
    if the binary is missing or the version line could not be parsed.
    """
    try:
        result = subprocess.run(
            ["engram", "--version"], capture_output=True, text=True, timeout=10
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False, ""

    if result.returncode != 0:
        return False, ""

    parts = result.stdout.strip().split()
    current = parts[-1] if parts else ""
    return current == PINNED_VERSION, current
```

- [ ] **Step 1.17: Run all engram tests, expect pass**

```bash
uv run pytest tests/unit/test_engram.py -v
```

Expected: 10 tests pass.

- [ ] **Step 1.18: Commit**

```bash
git add src/lazy_harness/memory/__init__.py src/lazy_harness/memory/engram.py tests/unit/test_engram.py
git commit -m "feat: add engram CLI wrapper module"
```

---

## Task 2: Config dataclasses for `[memory.engram]`

**Files:**
- Modify: `src/lazy_harness/core/config.py`
- Modify: `tests/unit/test_config.py`

- [ ] **Step 2.1: Read `tests/unit/test_config.py` to learn the test style**

```bash
head -80 tests/unit/test_config.py
```

Confirm the parser tests use `tomli_w.dumps` to write a test config and `load_config` to parse, asserting on `cfg.<section>.<field>`.

- [ ] **Step 2.2: Write the failing test for `Config.memory.engram` defaults**

Append to `tests/unit/test_config.py`:

```python
def test_config_memory_engram_defaults_when_missing() -> None:
    from lazy_harness.core.config import Config

    cfg = Config()
    assert cfg.memory.engram.enabled is False
    assert cfg.memory.engram.git_sync is True
    assert cfg.memory.engram.cloud is False
    assert cfg.memory.engram.version == "1.15.4"
```

- [ ] **Step 2.3: Run, expect failure**

```bash
uv run pytest tests/unit/test_config.py::test_config_memory_engram_defaults_when_missing -v
```

Expected: `AttributeError: 'Config' object has no attribute 'memory'`.

- [ ] **Step 2.4: Add `EngramConfig` and `MemoryConfig` dataclasses**

In `src/lazy_harness/core/config.py`, after the `MetricsConfig` dataclass (line ~143), insert:

```python
@dataclass
class EngramConfig:
    enabled: bool = False
    git_sync: bool = True
    cloud: bool = False
    version: str = "1.15.4"


@dataclass
class MemoryConfig:
    engram: EngramConfig = field(default_factory=EngramConfig)
```

- [ ] **Step 2.5: Add `memory` field to `Config`**

In the `Config` dataclass (around line 145–157), add (preserving existing fields, in alphabetical order with the others):

```python
    memory: MemoryConfig = field(default_factory=MemoryConfig)
```

- [ ] **Step 2.6: Run, expect pass on the defaults test**

```bash
uv run pytest tests/unit/test_config.py::test_config_memory_engram_defaults_when_missing -v
```

Expected: PASS.

- [ ] **Step 2.7: Add a test for parsing `[memory.engram]` from TOML**

Append to `tests/unit/test_config.py`:

```python
def test_config_memory_engram_parses_from_toml(tmp_path) -> None:
    import tomli_w

    from lazy_harness.core.config import load_config

    cfg_path = tmp_path / "config.toml"
    cfg_path.write_bytes(
        tomli_w.dumps(
            {
                "harness": {"version": "1"},
                "agent": {"type": "claude-code"},
                "profiles": {"default": "personal", "personal": {"config_dir": "~/.claude-personal"}},
                "memory": {"engram": {"enabled": True, "cloud": True, "version": "1.15.4"}},
            }
        ).encode()
    )

    cfg = load_config(cfg_path)
    assert cfg.memory.engram.enabled is True
    assert cfg.memory.engram.cloud is True
    assert cfg.memory.engram.git_sync is True  # default preserved
    assert cfg.memory.engram.version == "1.15.4"
```

- [ ] **Step 2.8: Run, expect failure**

```bash
uv run pytest tests/unit/test_config.py::test_config_memory_engram_parses_from_toml -v
```

Expected: failure — `load_config` does not yet read the `[memory]` section, so the result has defaults, not the parsed values.

- [ ] **Step 2.9: Read `load_config` to find the parsing section**

```bash
grep -n "def load_config\|knowledge\|monitoring" src/lazy_harness/core/config.py | head -20
```

Identify the spot where existing sections (e.g. `knowledge`, `monitoring`) are parsed and assigned. The new `_parse_memory` parser plugs into the same flow.

- [ ] **Step 2.10: Add the `_parse_memory` parser**

Add to `src/lazy_harness/core/config.py` (next to the other `_parse_*` helpers):

```python
def _parse_memory(raw: dict[str, Any]) -> MemoryConfig:
    if not raw:
        return MemoryConfig()
    engram_raw = raw.get("engram", {})
    if not isinstance(engram_raw, dict):
        raise ConfigError("[memory.engram] must be a table")
    engram = EngramConfig(
        enabled=bool(engram_raw.get("enabled", False)),
        git_sync=bool(engram_raw.get("git_sync", True)),
        cloud=bool(engram_raw.get("cloud", False)),
        version=str(engram_raw.get("version", "1.15.4")),
    )
    return MemoryConfig(engram=engram)
```

- [ ] **Step 2.11: Wire `_parse_memory` into `load_config`**

In `load_config`, where other top-level sections are read into the `Config` instance, add:

```python
    cfg.memory = _parse_memory(raw.get("memory", {}))
```

(Place it next to the existing `cfg.knowledge = ...` / `cfg.monitoring = ...` assignments — read the surrounding code first to match the exact style.)

- [ ] **Step 2.12: Run both new tests, expect pass**

```bash
uv run pytest tests/unit/test_config.py -v -k memory_engram
```

Expected: 2 tests pass.

- [ ] **Step 2.13: Run the full config test file to check no regressions**

```bash
uv run pytest tests/unit/test_config.py -v
```

Expected: all tests pass.

- [ ] **Step 2.14: Commit**

```bash
git add src/lazy_harness/core/config.py tests/unit/test_config.py
git commit -m "feat: add config sections for memory.engram"
```

---

## Task 3: Wire Engram into deploy MCP collector

**Files:**
- Modify: `src/lazy_harness/deploy/engine.py:_collect_mcp_servers`
- Modify: `tests/unit/test_deploy_mcp.py`

- [ ] **Step 3.1: Write the failing test for "engram included when enabled + available"**

Append to `tests/unit/test_deploy_mcp.py`:

```python
def test_collect_mcp_servers_includes_engram_when_enabled_and_available(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from lazy_harness.core.config import Config
    from lazy_harness.deploy import engine
    from lazy_harness.knowledge import qmd as qmd_mod
    from lazy_harness.memory import engram as engram_mod

    monkeypatch.setattr(qmd_mod, "is_qmd_available", lambda: False)
    monkeypatch.setattr(engram_mod, "is_engram_available", lambda: True)

    cfg = Config()
    cfg.memory.engram.enabled = True

    result = engine._collect_mcp_servers(cfg)
    assert "engram" in result
    assert result["engram"]["command"] == "engram"
```

- [ ] **Step 3.2: Run, expect failure**

```bash
uv run pytest tests/unit/test_deploy_mcp.py::test_collect_mcp_servers_includes_engram_when_enabled_and_available -v
```

Expected: failure — `_collect_mcp_servers` does not look at `memory.engram` yet.

- [ ] **Step 3.3: Update `_collect_mcp_servers`**

In `src/lazy_harness/deploy/engine.py`, modify `_collect_mcp_servers`:

```python
def _collect_mcp_servers(cfg: Config) -> dict[str, dict]:
    """Probe each known tool and return the MCP entries that should ship."""
    from lazy_harness.knowledge import qmd
    from lazy_harness.memory import engram

    servers: dict[str, dict] = {}
    if qmd.is_qmd_available():
        servers["qmd"] = qmd.mcp_server_config()
    if cfg.memory.engram.enabled and engram.is_engram_available():
        servers["engram"] = engram.mcp_server_config()
    return servers
```

- [ ] **Step 3.4: Run, expect pass**

```bash
uv run pytest tests/unit/test_deploy_mcp.py::test_collect_mcp_servers_includes_engram_when_enabled_and_available -v
```

Expected: PASS.

- [ ] **Step 3.5: Add tests for the two negative cases (disabled-but-available, enabled-but-missing)**

Append to `tests/unit/test_deploy_mcp.py`:

```python
def test_collect_mcp_servers_skips_engram_when_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from lazy_harness.core.config import Config
    from lazy_harness.deploy import engine
    from lazy_harness.knowledge import qmd as qmd_mod
    from lazy_harness.memory import engram as engram_mod

    monkeypatch.setattr(qmd_mod, "is_qmd_available", lambda: False)
    monkeypatch.setattr(engram_mod, "is_engram_available", lambda: True)

    cfg = Config()
    cfg.memory.engram.enabled = False

    result = engine._collect_mcp_servers(cfg)
    assert "engram" not in result


def test_collect_mcp_servers_skips_engram_when_binary_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from lazy_harness.core.config import Config
    from lazy_harness.deploy import engine
    from lazy_harness.knowledge import qmd as qmd_mod
    from lazy_harness.memory import engram as engram_mod

    monkeypatch.setattr(qmd_mod, "is_qmd_available", lambda: False)
    monkeypatch.setattr(engram_mod, "is_engram_available", lambda: False)

    cfg = Config()
    cfg.memory.engram.enabled = True

    result = engine._collect_mcp_servers(cfg)
    assert "engram" not in result
```

- [ ] **Step 3.6: Run all the new tests, expect pass**

```bash
uv run pytest tests/unit/test_deploy_mcp.py -v -k engram
```

Expected: 3 tests pass.

- [ ] **Step 3.7: Run the full deploy-mcp test file, expect no regressions**

```bash
uv run pytest tests/unit/test_deploy_mcp.py -v
```

Expected: all 8 tests pass (5 original + 3 new).

- [ ] **Step 3.8: Commit**

```bash
git add src/lazy_harness/deploy/engine.py tests/unit/test_deploy_mcp.py
git commit -m "feat: include engram in MCP deploy when enabled"
```

---

## Task 4: ADR-022 + index update

**Files:**
- Create: `specs/adrs/022-engram-episodic-memory.md`
- Modify: `specs/adrs/README.md`

- [ ] **Step 4.1: Write the ADR**

Create `specs/adrs/022-engram-episodic-memory.md`:

```markdown
# ADR-022: Engram as optional episodic memory backend

**Status:** accepted
**Date:** 2026-05-03

## Context

The harness covers semantic memory (the knowledge directory + optional QMD index, ADR-016) but does not address episodic memory: "what did the agent do in this project, when, and why". An on-machine audit of multi-repo projects flagged this as the most acute pain — most repos have no per-project agent diary, so every session re-explains decisions that the previous session already made.

Engram (https://github.com/Gentleman-Programming/engram) is a SQLite + FTS5 episodic-memory store with a built-in MCP server that the agent calls to save and recall what it did. It runs fully local by default, exposes an HTTP API on port 7437, and keeps memories scoped per project via a `--project` flag. Optional git sync ships compressed memory chunks under `.engram/chunks/` per repo, so a team's decision history travels with the code.

Engram is one of three tools converging on the harness's MCP deploy seam (ADR-024); the others are QMD (ADR-016, already wired) and Graphify (ADR-023, planned next). Each addresses a different memory layer; Engram covers the episodic layer specifically.

## Decision

**Add `src/lazy_harness/memory/engram.py` as a thin CLI wrapper, gated behind `shutil.which("engram")` and a config opt-in (`[memory.engram].enabled = true`). Wire it into the existing MCP deploy collector so `lh deploy` ships an `engram` entry to each profile's `settings.json` when both gates are open. Pin Engram to version `1.15.4` in config; `check_version()` exposes the comparison for `lh doctor` to use later.**

Concretely:

- `src/lazy_harness/memory/engram.py` — `is_engram_available()`, `_build_command(action, project=None)`, `run_engram(action, project=None, timeout=300)`, `mcp_server_config()` returning `{"command": "engram", "args": ["mcp"]}`, `check_version()` returning `(matches, current_version)`. Module-level `PINNED_VERSION = "1.15.4"` constant.
- `src/lazy_harness/core/config.py` — new `EngramConfig` dataclass (`enabled`, `git_sync`, `cloud`, `version` with `1.15.4` default), wrapped in a `MemoryConfig` table, exposed as `Config.memory`. Parsed by `_parse_memory` from the optional `[memory]` block in `config.toml`.
- `src/lazy_harness/deploy/engine.py` — `_collect_mcp_servers(cfg)` extends with `if cfg.memory.engram.enabled and engram.is_engram_available(): servers["engram"] = engram.mcp_server_config()`.
- The cloud sync flag is exposed (`cloud: bool = False`) but no code branches on it in this PR. Engram itself decides cloud behavior at the daemon level.

## Alternatives considered

- **Replace the existing `decisions.jsonl` / `failures.jsonl` files with Engram.** Rejected for now. The JSONL files are human-readable, version-controllable, and portable across machines without Engram installed. They are not redundant with Engram — Engram is the agent-facing real-time memory, the JSONLs are the post-session distilled record.
- **Make Engram a hard dependency.** Breaks the optionality contract from ADR-016. Users who do not install Engram would have a broken `lh deploy`. Same `shutil.which` gate keeps the framework installable without it.
- **Auto-install Engram during `lh init`.** Out of scope. Per the user-confirmed plan, the wizard prints the install command but does not run it. Detection-only, consistent with QMD.
- **Default the cloud sync to `true`.** Rejected. Engram cloud sync is opt-in by design. The harness reflects that with `cloud: bool = False` and a comment in the ADR; the user can flip it explicitly per project.

## Consequences

- A user who installs Engram (`brew install engram` or equivalent) and sets `[memory.engram].enabled = true` gets the `engram` MCP server wired into every profile on the next `lh deploy`. Removing Engram and re-running `lh deploy` removes the entry on the next merge — `_collect_mcp_servers` rebuilds the dict from scratch each call.
- Pinning the version in config (`version = "1.15.4"`) gives `lh doctor` (future ADR) a single source of truth for compatibility checks. `check_version()` returns the tuple it needs.
- The wizard step (`enable_engram`) and `lh doctor` reporting are intentionally deferred to the Fase 3 ADR. This PR ships the runtime mechanism only, mirroring how ADR-016 left wizard discovery to ADR-018.
- The `[memory]` config namespace is new. `MemoryConfig` is intentionally a thin wrapper today — it exists so future episodic backends slot in next to `engram` without breaking the namespace.
```

- [ ] **Step 4.2: Update the ADR index**

In `specs/adrs/README.md`, in the framework ADRs table, insert (above the ADR-024 row to keep numerical order):

```markdown
| [022](./022-engram-episodic-memory.md) | accepted | Engram as optional episodic memory backend | New `memory/engram.py` wrapper + `[memory.engram]` config + MCP deploy gating. Mirrors the ADR-016 QMD pattern. |
```

- [ ] **Step 4.3: Validate the docs build**

```bash
uv run --group docs mkdocs build --strict
```

Expected: clean build.

- [ ] **Step 4.4: Commit**

```bash
git add specs/adrs/022-engram-episodic-memory.md specs/adrs/README.md
git commit -m "docs: add ADR-022 (engram as episodic memory backend)"
```

---

## Task 5: Final pre-commit gate (`/tdd-check`) + commit the plan

- [ ] **Step 5.1: Run the full pytest suite**

```bash
uv run pytest
```

Expected: all tests pass (573 baseline + 13 new = 586).

- [ ] **Step 5.2: Run ruff**

```bash
uv run ruff check src tests
```

Expected: clean output.

- [ ] **Step 5.3: Run the strict mkdocs build**

```bash
uv run --group docs mkdocs build --strict
```

Expected: clean build.

- [ ] **Step 5.4: Commit the implementation plan**

```bash
git add specs/plans/2026-05-03-adr-022-engram-memory.md
git commit -m "chore: add ADR-022 implementation plan"
```

(If the plan was already committed earlier in the worktree, skip this step.)

- [ ] **Step 5.5: Revert any `uv.lock` churn before pushing**

```bash
git status
# If uv.lock is modified by uv version drift (known issue), revert it:
git checkout uv.lock
```

- [ ] **Step 5.6: Push and open the PR**

```bash
git push -u origin feat/engram-memory
gh pr create --title "feat: Engram as optional episodic memory backend (ADR-022)" --body "$(cat <<'EOF'
## Summary

- Add `src/lazy_harness/memory/engram.py` — thin CLI wrapper following the QMD pattern (ADR-016): `is_engram_available()`, `_build_command`, `run_engram`, `mcp_server_config()`, `check_version()`. Pinned to Engram 1.15.4.
- Add `[memory.engram]` config section (`enabled`, `git_sync`, `cloud`, `version`) with `MemoryConfig`/`EngramConfig` dataclasses and `_parse_memory` parser. Defaults to `enabled = false` so existing configs are unaffected.
- Extend `_collect_mcp_servers` so `lh deploy` ships an `engram` MCP entry when both gates are open (config opt-in + binary detected). Re-uses the ADR-024 deploy seam — no MCP plumbing changes.
- ADR-022 documents the decision; the implementation plan lives in `specs/plans/`.

## Test plan

- [x] `uv run pytest` — all tests pass (10 new in `test_engram.py`, 2 new in `test_config.py`, 3 new in `test_deploy_mcp.py`)
- [x] `uv run ruff check src tests` — clean
- [x] `uv run --group docs mkdocs build --strict` — clean
- [ ] Smoke: install Engram 1.15.4, set `[memory.engram].enabled = true`, run `lh deploy`, confirm `~/.claude-<profile>/settings.json` contains `mcpServers.engram` block
- [ ] Smoke: set `enabled = false`, re-run `lh deploy`, confirm `mcpServers.engram` is removed
EOF
)"
```

---

## Self-review notes

- Spec coverage: every section of the agreed Engram plan is mapped to a task. Wizard prompts and `lh doctor` reporting are explicitly deferred to a separate Fase 3 ADR.
- Placeholder scan: every code block is concrete; no "implement later", no "add error handling".
- Type consistency: `mcp_server_config() -> dict` matches the QMD signature (Task 1, ADR-024). `EngramConfig` field names (`enabled`, `git_sync`, `cloud`, `version`) match across Task 2 (dataclass), Task 2 (parser), Task 3 (caller), and the ADR document.
- The plan does not bump version numbers (release-please owns that).
- The plan does not edit `specs/archive/`.
- The plan does not duplicate work from ADR-024 — `deploy_mcp_servers` and `generate_mcp_config` are reused as-is.

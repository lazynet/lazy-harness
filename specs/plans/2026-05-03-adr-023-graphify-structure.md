# ADR-023 — Graphify as Optional Code-Structure Index — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Strict TDD per repo non-negotiable #2.

**Goal:** Add a Graphify CLI wrapper module + extend `[knowledge.structure]` config + MCP deploy wiring so `lh deploy` ships a `graphify` MCP server entry to each profile when (a) Graphify is installed and (b) `[knowledge.structure].enabled = true`.

**Architecture:** Mirror the QMD precedent (ADR-016) and the Engram precedent (ADR-022) one-to-one — new `knowledge/graphify.py` module with `is_graphify_available()` + `run_graphify()` + `mcp_server_config()` + `check_version()` + version pin constant. Extend `KnowledgeConfig` with a new `structure` sub-table parsed by the same `load_config` flow. Extend `_collect_mcp_servers` in `deploy/engine.py` to include Graphify when both gates are open. The MCP deploy machinery (ADR-024) carries the rest.

**Tech Stack:** Python 3.11, pytest, ruff, MkDocs Material. Runs in worktree `.worktrees/graphify-structure` on branch `feat/graphify-structure`. Pinned Graphify version: 0.6.9 (per user decision). MCP server invocation: `graphify mcp` (symmetric with QMD/Engram).

**Out of scope (later work):** Wizard prompts (`enable_graphify` flag in `WizardAnswers`), `lh doctor` reporting, the post-commit auto-rebuild git hook (`graphify hook install`) — all belong to Fase 3, covered by a separate ADR/PR. The `auto_rebuild_on_commit` config flag is exposed but no code branches on it in this PR.

---

## File Structure

| Path | Status | Responsibility |
|------|--------|----------------|
| `src/lazy_harness/knowledge/graphify.py` | create | CLI wrapper: probe, run, MCP entry, version check |
| `src/lazy_harness/core/config.py` | modify | Add `KnowledgeStructureConfig`, extend `KnowledgeConfig`, parse `[knowledge.structure]` |
| `src/lazy_harness/deploy/engine.py` | modify | Extend `_collect_mcp_servers` to include Graphify when gated open |
| `tests/unit/test_graphify.py` | create | Wrapper tests (mirror `test_qmd.py` / `test_engram.py`) |
| `tests/unit/test_config.py` | modify | Test `[knowledge.structure]` parse and defaults |
| `tests/unit/test_deploy_mcp.py` | modify | Test Graphify inclusion + skip-when-disabled |
| `specs/adrs/023-graphify-code-structure.md` | create | ADR document |
| `specs/adrs/README.md` | modify | Add ADR-023 to index |

---

## Task 1: Graphify CLI wrapper module

**Files:**
- Create: `src/lazy_harness/knowledge/graphify.py`
- Create: `tests/unit/test_graphify.py`

- [ ] **Step 1.1: Write the first failing test (`is_graphify_available` returns bool)**

Create `tests/unit/test_graphify.py`:

```python
"""Tests for Graphify CLI wrapper."""

from __future__ import annotations

from unittest.mock import patch


def test_graphify_available_returns_bool() -> None:
    from lazy_harness.knowledge.graphify import is_graphify_available

    result = is_graphify_available()
    assert isinstance(result, bool)
```

- [ ] **Step 1.2: Run, expect failure**

```bash
uv run pytest tests/unit/test_graphify.py::test_graphify_available_returns_bool -v
```

Expected: `ModuleNotFoundError: No module named 'lazy_harness.knowledge.graphify'`

- [ ] **Step 1.3: Create the wrapper with the minimum to pass**

Create `src/lazy_harness/knowledge/graphify.py`:

```python
"""Graphify CLI wrapper — code structure index for AI coding agents.

Pinned version: 0.6.9 (see ADR-023).
"""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass

PINNED_VERSION = "0.6.9"


@dataclass
class GraphifyResult:
    exit_code: int
    stdout: str
    stderr: str


def is_graphify_available() -> bool:
    return shutil.which("graphify") is not None
```

- [ ] **Step 1.4: Run, expect pass**

```bash
uv run pytest tests/unit/test_graphify.py::test_graphify_available_returns_bool -v
```

Expected: PASS.

- [ ] **Step 1.5: Add tests for `_build_command` and `run_graphify`**

Append to `tests/unit/test_graphify.py`:

```python
def test_graphify_build_command_basic() -> None:
    from lazy_harness.knowledge.graphify import _build_command

    cmd = _build_command("query")
    assert cmd == ["graphify", "query"]


def test_graphify_build_command_with_target() -> None:
    from lazy_harness.knowledge.graphify import _build_command

    cmd = _build_command("build", target=".")
    assert cmd == ["graphify", "build", "."]


def test_graphify_run_returns_result() -> None:
    from lazy_harness.knowledge.graphify import GraphifyResult, run_graphify

    with patch("subprocess.run") as mock_run:
        mock_run.return_value = type(
            "R", (), {"returncode": 0, "stdout": "OK", "stderr": ""}
        )()
        result = run_graphify("status")
        assert isinstance(result, GraphifyResult)
        assert result.exit_code == 0
        assert result.stdout == "OK"


def test_graphify_run_handles_missing_binary() -> None:
    from lazy_harness.knowledge.graphify import run_graphify

    with patch("subprocess.run", side_effect=FileNotFoundError):
        result = run_graphify("status")
        assert result.exit_code == -1
        assert "graphify not found" in result.stderr
```

- [ ] **Step 1.6: Run, expect failure on the new tests**

```bash
uv run pytest tests/unit/test_graphify.py -v
```

Expected: 4 failures.

- [ ] **Step 1.7: Implement `_build_command` and `run_graphify`**

Append to `src/lazy_harness/knowledge/graphify.py`:

```python
def _build_command(action: str, target: str | None = None) -> list[str]:
    cmd = ["graphify", action]
    if target:
        cmd.append(target)
    return cmd


def run_graphify(
    action: str, target: str | None = None, timeout: int = 600
) -> GraphifyResult:
    cmd = _build_command(action, target=target)
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return GraphifyResult(
            exit_code=result.returncode, stdout=result.stdout, stderr=result.stderr
        )
    except subprocess.TimeoutExpired:
        return GraphifyResult(
            exit_code=-1, stdout="", stderr=f"graphify timed out after {timeout}s"
        )
    except FileNotFoundError:
        return GraphifyResult(
            exit_code=-1, stdout="", stderr="graphify not found in PATH"
        )
```

- [ ] **Step 1.8: Run, expect pass**

```bash
uv run pytest tests/unit/test_graphify.py -v
```

Expected: 5 tests pass.

- [ ] **Step 1.9: Add tests for `mcp_server_config` and `PINNED_VERSION`**

Append to `tests/unit/test_graphify.py`:

```python
def test_graphify_mcp_server_config_shape() -> None:
    from lazy_harness.knowledge.graphify import mcp_server_config

    entry = mcp_server_config()
    assert entry["command"] == "graphify"
    assert entry["args"] == ["mcp"]


def test_graphify_pinned_version_constant() -> None:
    from lazy_harness.knowledge import graphify

    assert graphify.PINNED_VERSION == "0.6.9"
```

- [ ] **Step 1.10: Run, expect 1 fail (mcp_server_config missing)**

```bash
uv run pytest tests/unit/test_graphify.py -v
```

Expected: 6 pass + 1 fail (`mcp_server_config` undefined).

- [ ] **Step 1.11: Implement `mcp_server_config`**

Append to `src/lazy_harness/knowledge/graphify.py`:

```python
def mcp_server_config() -> dict:
    """Declarative MCP entry for Graphify (consumed by deploy_mcp_servers)."""
    return {"command": "graphify", "args": ["mcp"]}
```

- [ ] **Step 1.12: Run, expect all pass**

```bash
uv run pytest tests/unit/test_graphify.py -v
```

Expected: 7 tests pass.

- [ ] **Step 1.13: Add `check_version` tests**

Append to `tests/unit/test_graphify.py`:

```python
def test_graphify_check_version_matches_pin() -> None:
    from lazy_harness.knowledge.graphify import check_version

    with patch("subprocess.run") as mock_run:
        mock_run.return_value = type(
            "R", (), {"returncode": 0, "stdout": "graphify 0.6.9\n", "stderr": ""}
        )()
        matches, current = check_version()
        assert matches is True
        assert current == "0.6.9"


def test_graphify_check_version_mismatch() -> None:
    from lazy_harness.knowledge.graphify import check_version

    with patch("subprocess.run") as mock_run:
        mock_run.return_value = type(
            "R", (), {"returncode": 0, "stdout": "graphify 0.7.0\n", "stderr": ""}
        )()
        matches, current = check_version()
        assert matches is False
        assert current == "0.7.0"


def test_graphify_check_version_missing_binary() -> None:
    from lazy_harness.knowledge.graphify import check_version

    with patch("subprocess.run", side_effect=FileNotFoundError):
        matches, current = check_version()
        assert matches is False
        assert current == ""
```

- [ ] **Step 1.14: Run, expect failure**

```bash
uv run pytest tests/unit/test_graphify.py -v -k check_version
```

Expected: 3 failures.

- [ ] **Step 1.15: Implement `check_version`**

Append to `src/lazy_harness/knowledge/graphify.py`:

```python
def check_version() -> tuple[bool, str]:
    """Probe `graphify --version` and compare against PINNED_VERSION.

    Returns `(matches, current_version)`. `current_version` is empty string
    if the binary is missing or the version line could not be parsed.
    """
    try:
        result = subprocess.run(
            ["graphify", "--version"], capture_output=True, text=True, timeout=10
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False, ""

    if result.returncode != 0:
        return False, ""

    parts = result.stdout.strip().split()
    current = parts[-1] if parts else ""
    return current == PINNED_VERSION, current
```

- [ ] **Step 1.16: Run all graphify tests, expect pass**

```bash
uv run pytest tests/unit/test_graphify.py -v
```

Expected: 10 tests pass.

- [ ] **Step 1.17: Run ruff to catch any formatting issues now (avoid trailing fix-up commit)**

```bash
uv run ruff check src/lazy_harness/knowledge/graphify.py tests/unit/test_graphify.py --fix
uv run ruff check src/lazy_harness/knowledge/graphify.py tests/unit/test_graphify.py
```

Expected: clean output after the auto-fix.

- [ ] **Step 1.18: Commit**

```bash
git add src/lazy_harness/knowledge/graphify.py tests/unit/test_graphify.py
git commit -m "feat: add graphify CLI wrapper module"
```

---

## Task 2: Config sub-table for `[knowledge.structure]`

**Files:**
- Modify: `src/lazy_harness/core/config.py`
- Modify: `tests/unit/test_config.py`

- [ ] **Step 2.1: Write the failing test for defaults**

Append to `tests/unit/test_config.py`:

```python
def test_config_knowledge_structure_defaults_when_missing() -> None:
    from lazy_harness.core.config import Config

    cfg = Config()
    assert cfg.knowledge.structure.engine == "graphify"
    assert cfg.knowledge.structure.enabled is False
    assert cfg.knowledge.structure.auto_rebuild_on_commit is False
    assert cfg.knowledge.structure.version == "0.6.9"
```

- [ ] **Step 2.2: Run, expect failure**

```bash
uv run pytest tests/unit/test_config.py::test_config_knowledge_structure_defaults_when_missing -v
```

Expected: `AttributeError: 'KnowledgeConfig' object has no attribute 'structure'`

- [ ] **Step 2.3: Add `KnowledgeStructureConfig` dataclass**

In `src/lazy_harness/core/config.py`, after the existing `KnowledgeSearchConfig` dataclass (search around line 56), insert:

```python
@dataclass
class KnowledgeStructureConfig:
    engine: str = "graphify"
    enabled: bool = False
    auto_rebuild_on_commit: bool = False
    version: str = "0.6.9"
```

- [ ] **Step 2.4: Add `structure` field to `KnowledgeConfig`**

In the existing `KnowledgeConfig` dataclass (around line 60), add the `structure` field next to `search`:

```python
@dataclass
class KnowledgeConfig:
    path: str = ""
    sessions: KnowledgeSessionsConfig = field(default_factory=KnowledgeSessionsConfig)
    learnings: KnowledgeLearningsConfig = field(default_factory=KnowledgeLearningsConfig)
    search: KnowledgeSearchConfig = field(default_factory=KnowledgeSearchConfig)
    structure: KnowledgeStructureConfig = field(default_factory=KnowledgeStructureConfig)
```

- [ ] **Step 2.5: Run defaults test, expect pass**

```bash
uv run pytest tests/unit/test_config.py::test_config_knowledge_structure_defaults_when_missing -v
```

Expected: PASS.

- [ ] **Step 2.6: Add the parse-from-TOML test**

Append to `tests/unit/test_config.py`:

```python
def test_config_knowledge_structure_parses_from_toml(config_dir: Path) -> None:
    config_file = config_dir / "config.toml"
    config_file.write_text("""
[harness]
version = "1"

[knowledge.structure]
enabled = true
auto_rebuild_on_commit = true
version = "0.6.9"
""")
    from lazy_harness.core.config import load_config

    cfg = load_config(config_file)
    assert cfg.knowledge.structure.enabled is True
    assert cfg.knowledge.structure.auto_rebuild_on_commit is True
    assert cfg.knowledge.structure.engine == "graphify"
    assert cfg.knowledge.structure.version == "0.6.9"
```

- [ ] **Step 2.7: Run, expect failure**

```bash
uv run pytest tests/unit/test_config.py::test_config_knowledge_structure_parses_from_toml -v
```

Expected: failure — `load_config` does not yet read the `[knowledge.structure]` section.

- [ ] **Step 2.8: Wire the parser**

In `src/lazy_harness/core/config.py`, find the existing `cfg.knowledge = KnowledgeConfig(...)` block (around line 278) and extend it to read `[knowledge.structure]`:

```python
    knowledge_raw = raw.get("knowledge", {})
    cfg.knowledge = KnowledgeConfig(
        path=knowledge_raw.get("path", ""),
        sessions=KnowledgeSessionsConfig(**knowledge_raw.get("sessions", {})),
        learnings=KnowledgeLearningsConfig(**knowledge_raw.get("learnings", {})),
        search=KnowledgeSearchConfig(**knowledge_raw.get("search", {})),
        structure=KnowledgeStructureConfig(**knowledge_raw.get("structure", {})),
    )
```

- [ ] **Step 2.9: Run both new tests, expect pass**

```bash
uv run pytest tests/unit/test_config.py -v -k knowledge_structure
```

Expected: 2 tests pass.

- [ ] **Step 2.10: Run the full config test file, no regressions**

```bash
uv run pytest tests/unit/test_config.py -v
```

Expected: all tests pass.

- [ ] **Step 2.11: Run ruff for the touched files**

```bash
uv run ruff check src/lazy_harness/core/config.py tests/unit/test_config.py --fix
uv run ruff check src/lazy_harness/core/config.py tests/unit/test_config.py
```

Expected: clean.

- [ ] **Step 2.12: Commit**

```bash
git add src/lazy_harness/core/config.py tests/unit/test_config.py
git commit -m "feat: add config sub-table for knowledge.structure"
```

---

## Task 3: Wire Graphify into deploy MCP collector

**Files:**
- Modify: `src/lazy_harness/deploy/engine.py:_collect_mcp_servers`
- Modify: `tests/unit/test_deploy_mcp.py`

- [ ] **Step 3.1: Write the failing test for "graphify included when enabled + available"**

Append to `tests/unit/test_deploy_mcp.py`:

```python
def test_collect_mcp_servers_includes_graphify_when_enabled_and_available(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from lazy_harness.core.config import Config
    from lazy_harness.deploy import engine
    from lazy_harness.knowledge import graphify as graphify_mod
    from lazy_harness.knowledge import qmd as qmd_mod

    monkeypatch.setattr(qmd_mod, "is_qmd_available", lambda: False)
    monkeypatch.setattr(graphify_mod, "is_graphify_available", lambda: True)

    cfg = Config()
    cfg.knowledge.structure.enabled = True

    result = engine._collect_mcp_servers(cfg)
    assert "graphify" in result
    assert result["graphify"]["command"] == "graphify"
```

- [ ] **Step 3.2: Run, expect failure**

```bash
uv run pytest tests/unit/test_deploy_mcp.py::test_collect_mcp_servers_includes_graphify_when_enabled_and_available -v
```

Expected: failure — `_collect_mcp_servers` does not look at `knowledge.structure` yet.

- [ ] **Step 3.3: Update `_collect_mcp_servers`**

In `src/lazy_harness/deploy/engine.py`, modify `_collect_mcp_servers`:

```python
def _collect_mcp_servers(cfg: Config) -> dict[str, dict]:
    """Probe each known tool and return the MCP entries that should ship."""
    from lazy_harness.knowledge import graphify, qmd
    from lazy_harness.memory import engram

    servers: dict[str, dict] = {}
    if qmd.is_qmd_available():
        servers["qmd"] = qmd.mcp_server_config()
    if cfg.memory.engram.enabled and engram.is_engram_available():
        servers["engram"] = engram.mcp_server_config()
    if cfg.knowledge.structure.enabled and graphify.is_graphify_available():
        servers["graphify"] = graphify.mcp_server_config()
    return servers
```

- [ ] **Step 3.4: Run, expect pass**

```bash
uv run pytest tests/unit/test_deploy_mcp.py::test_collect_mcp_servers_includes_graphify_when_enabled_and_available -v
```

Expected: PASS.

- [ ] **Step 3.5: Add tests for the two negative cases**

Append to `tests/unit/test_deploy_mcp.py`:

```python
def test_collect_mcp_servers_skips_graphify_when_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from lazy_harness.core.config import Config
    from lazy_harness.deploy import engine
    from lazy_harness.knowledge import graphify as graphify_mod
    from lazy_harness.knowledge import qmd as qmd_mod

    monkeypatch.setattr(qmd_mod, "is_qmd_available", lambda: False)
    monkeypatch.setattr(graphify_mod, "is_graphify_available", lambda: True)

    cfg = Config()
    cfg.knowledge.structure.enabled = False

    result = engine._collect_mcp_servers(cfg)
    assert "graphify" not in result


def test_collect_mcp_servers_skips_graphify_when_binary_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from lazy_harness.core.config import Config
    from lazy_harness.deploy import engine
    from lazy_harness.knowledge import graphify as graphify_mod
    from lazy_harness.knowledge import qmd as qmd_mod

    monkeypatch.setattr(qmd_mod, "is_qmd_available", lambda: False)
    monkeypatch.setattr(graphify_mod, "is_graphify_available", lambda: False)

    cfg = Config()
    cfg.knowledge.structure.enabled = True

    result = engine._collect_mcp_servers(cfg)
    assert "graphify" not in result
```

- [ ] **Step 3.6: Run all the new tests, expect pass**

```bash
uv run pytest tests/unit/test_deploy_mcp.py -v -k graphify
```

Expected: 3 tests pass.

- [ ] **Step 3.7: Run the full deploy-mcp test file, no regressions**

```bash
uv run pytest tests/unit/test_deploy_mcp.py -v
```

Expected: all 11 tests pass (8 from earlier + 3 new).

- [ ] **Step 3.8: Run ruff**

```bash
uv run ruff check src/lazy_harness/deploy/engine.py tests/unit/test_deploy_mcp.py --fix
uv run ruff check src/lazy_harness/deploy/engine.py tests/unit/test_deploy_mcp.py
```

Expected: clean.

- [ ] **Step 3.9: Commit**

```bash
git add src/lazy_harness/deploy/engine.py tests/unit/test_deploy_mcp.py
git commit -m "feat: include graphify in MCP deploy when enabled"
```

---

## Task 4: ADR-023 + index update

**Files:**
- Create: `specs/adrs/023-graphify-code-structure.md`
- Modify: `specs/adrs/README.md`

- [ ] **Step 4.1: Write the ADR**

Create `specs/adrs/023-graphify-code-structure.md`:

```markdown
# ADR-023: Graphify as optional code-structure index

**Status:** accepted
**Date:** 2026-05-03

## Context

The harness covers semantic memory (QMD, ADR-016) and episodic memory (Engram, ADR-022) but does not capture the third memory layer flagged in the literature review: code-structure or procedural memory. For multi-repo solutions where a single product spans tens of repositories, the agent has no compact way to ask "where does function X live, what calls it, and which file is the central node of this subsystem".

Graphify (https://github.com/safishamsi/graphify) is a tree-sitter based knowledge-graph builder for code, supporting 25 languages. It runs the AST extraction locally (no API cost), produces queryable JSON + interactive HTML + a markdown report, and exposes an MCP server for natural-language graph queries from the agent. Multi-repo workflows are first-class via `graphify merge-graphs` and the convention of committing the `graphify-out/` directory per repo so teammates reuse the index without re-building.

Graphify is the third tool converging on the harness's MCP deploy seam (ADR-024); together with QMD (ADR-016, semantic) and Engram (ADR-022, episodic), it covers the structural layer.

## Decision

**Add `src/lazy_harness/knowledge/graphify.py` as a thin CLI wrapper, gated behind `shutil.which("graphify")` and a config opt-in (`[knowledge.structure].enabled = true`). Wire it into the existing MCP deploy collector so `lh deploy` ships a `graphify` entry to each profile's `settings.json` when both gates are open. Pin Graphify to version `0.6.9` in config; `check_version()` exposes the comparison for `lh doctor` to use later.**

Concretely:

- `src/lazy_harness/knowledge/graphify.py` — `is_graphify_available()`, `_build_command(action, target=None)`, `run_graphify(action, target=None, timeout=600)`, `mcp_server_config()` returning `{"command": "graphify", "args": ["mcp"]}`, `check_version()` returning `(matches, current_version)`. Module-level `PINNED_VERSION = "0.6.9"` constant. Default timeout is 600s because graph builds on large repos can take minutes.
- `src/lazy_harness/core/config.py` — new `KnowledgeStructureConfig` dataclass (`engine` defaulting to `"graphify"`, `enabled`, `auto_rebuild_on_commit`, `version` with `0.6.9` default), added as a `structure` field on `KnowledgeConfig`. Parsed inline by `load_config` next to the existing `search` sub-table.
- `src/lazy_harness/deploy/engine.py` — `_collect_mcp_servers(cfg)` extends with `if cfg.knowledge.structure.enabled and graphify.is_graphify_available(): servers["graphify"] = graphify.mcp_server_config()`.
- The `auto_rebuild_on_commit` flag is exposed but no code branches on it in this PR. Graphify's own `graphify hook install` writes a git `post-commit` hook directly into `.git/hooks/`; wiring that from `lh deploy` is deferred to the Fase 3 ADR.
- The `engine` field on `KnowledgeStructureConfig` exists so a future structural backend (e.g. a ctags-based or Sourcegraph-style alternative) can plug into the same seam without breaking the namespace.

## Alternatives considered

- **Build the graph inside the harness with our own tree-sitter wrapper.** Reinvents an actively maintained tool that already supports 25 languages. Rejected on maintenance grounds.
- **Make Graphify a hard dependency.** Breaks the optionality contract from ADR-016. Same `shutil.which` gate keeps the framework installable without it.
- **Auto-install Graphify or auto-install the post-commit hook on `lh init`.** Out of scope. Per the user-confirmed plan, the wizard prints the install command but does not run it. The hook install is a separate opt-in (`auto_rebuild_on_commit = true` plus a future `lh deploy` step).
- **Place Graphify under `memory/` next to Engram.** Rejected. Graphify indexes code structure, not agent activity. It belongs next to QMD under `knowledge/` because both answer "what do we know about this codebase / domain", just at different layers.
- **Invoke MCP via `python -m graphify.serve` instead of `graphify mcp`.** The Python module form requires the right Python on PATH; the CLI form is symmetric with QMD and Engram and matches the conventional MCP pattern. If a future Graphify release breaks `graphify mcp`, the canonical command can be exposed as a config override in a follow-up ADR.

## Consequences

- A user who installs Graphify (`pip install graphify` or equivalent) and sets `[knowledge.structure].enabled = true` gets the `graphify` MCP server wired into every profile on the next `lh deploy`. Removing Graphify and re-running `lh deploy` removes the entry on the next merge — `_collect_mcp_servers` rebuilds the dict from scratch each call.
- Pinning the version in config (`version = "0.6.9"`) gives `lh doctor` (future ADR) a single source of truth for compatibility checks. `check_version()` returns the tuple it needs.
- For multi-repo solutions, the convention is to commit `graphify-out/` per repo and use `graphify merge-graphs *.json` to query across repos. The harness does not orchestrate the merge — that lives at the repo level.
- The post-commit auto-rebuild hook (Graphify's `graphify hook install`) is intentionally not wired from `lh deploy` in this PR. Doing so is a Fase 3 concern that needs its own design — `lh deploy` writing to `.git/hooks/` of arbitrary repos is a different blast radius from writing to `~/.claude-<profile>/settings.json`.
- The `[knowledge.structure]` namespace mirrors `[knowledge.search]`. Both are sub-tables of `[knowledge]` because both answer "what do we know about this codebase". Episodic memory stays under `[memory]` because it is a different concept (what the agent did, not what we know).
```

- [ ] **Step 4.2: Update the ADR index**

In `specs/adrs/README.md`, in the framework ADRs table, insert (above the ADR-024 row to keep numerical order):

```markdown
| [023](./023-graphify-code-structure.md) | accepted | Graphify as optional code-structure index | New `knowledge/graphify.py` wrapper + `[knowledge.structure]` config + MCP deploy gating. Mirrors ADR-016 / ADR-022. |
```

- [ ] **Step 4.3: Validate the docs build**

```bash
uv run --group docs mkdocs build --strict
```

Expected: clean build.

- [ ] **Step 4.4: Commit**

```bash
git add specs/adrs/023-graphify-code-structure.md specs/adrs/README.md
git commit -m "docs: add ADR-023 (graphify as code-structure index)"
```

---

## Task 5: Final pre-commit gate (`/tdd-check`) + plan + PR

- [ ] **Step 5.1: Run the full pytest suite**

```bash
uv run pytest
```

Expected: all tests pass (591 baseline + 13 new = 604).

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
git add specs/plans/2026-05-03-adr-023-graphify-structure.md
git commit -m "chore: add ADR-023 implementation plan"
```

- [ ] **Step 5.5: Revert any `uv.lock` churn before pushing**

```bash
git status
# If uv.lock is modified by uv version drift (known issue), revert it:
git checkout uv.lock
```

- [ ] **Step 5.6: Switch gh auth to lazynet, push, open PR**

```bash
gh auth switch -u lazynet
git push -u origin feat/graphify-structure
gh pr create --title "feat: Graphify as optional code-structure index (ADR-023)" --body "$(cat <<'EOF'
## Summary

- Add `src/lazy_harness/knowledge/graphify.py` — thin CLI wrapper following the QMD/Engram pattern: `is_graphify_available()`, `_build_command`, `run_graphify`, `mcp_server_config()`, `check_version()`. Pinned to Graphify 0.6.9.
- Add `[knowledge.structure]` config sub-table (`engine`, `enabled`, `auto_rebuild_on_commit`, `version`) on `KnowledgeConfig`. Defaults to `enabled = false` so existing configs are unaffected.
- Extend `_collect_mcp_servers` so `lh deploy` ships a `graphify` MCP entry when both gates are open (config opt-in + binary detected). Re-uses the ADR-024 deploy seam — no MCP plumbing changes.
- ADR-023 documents the decision; the implementation plan lives in `specs/plans/`.

## Test plan

- [x] `uv run pytest` — all tests pass (10 new in `test_graphify.py`, 2 new in `test_config.py`, 3 new in `test_deploy_mcp.py`)
- [x] `uv run ruff check src tests` — clean
- [x] `uv run --group docs mkdocs build --strict` — clean
- [ ] Smoke: install Graphify 0.6.9, set `[knowledge.structure].enabled = true`, run `lh deploy`, confirm `~/.claude-<profile>/settings.json` contains `mcpServers.graphify` block alongside `qmd` (and `engram` if enabled)
- [ ] Smoke: set `enabled = false`, re-run `lh deploy`, confirm `mcpServers.graphify` is removed
EOF
)"
gh auth switch -u mvago-flx
```

---

## Self-review notes

- Spec coverage: every section of the agreed Graphify plan is mapped to a task. Wizard prompts, `lh doctor`, and the post-commit hook install are explicitly deferred to a separate Fase 3 ADR.
- Placeholder scan: every code block is concrete; no "implement later", no "add error handling".
- Type consistency: `mcp_server_config() -> dict` matches the QMD/Engram signatures (Task 1, ADR-024). `KnowledgeStructureConfig` field names (`engine`, `enabled`, `auto_rebuild_on_commit`, `version`) match across Task 2 (dataclass), Task 2 (parser), Task 3 (caller), and the ADR document.
- The plan uses real `Config()` instances in deploy tests (lesson from ADR-022 where the old `type("Cfg", (), {})()` stub broke when `_collect_mcp_servers` started reading config).
- The plan does not bump version numbers (release-please owns that).
- The plan does not edit `specs/archive/`.
- The plan does not duplicate work from ADR-024 — `deploy_mcp_servers` and `generate_mcp_config` are reused as-is.

# ADR-024 — MCP Server Orchestration via `lh deploy` — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Strict TDD per repo non-negotiable #2.

**Goal:** Add an MCP server deploy mechanism to `lh deploy` that writes a `mcpServers` block into each profile's `settings.json`, wired for QMD as the first concrete server. Engram and Graphify slot in later via the same mechanism (ADR-022 / ADR-023).

**Architecture:** Extend the `AgentAdapter` Protocol with `generate_mcp_config(servers) -> dict`. Each tool wrapper exposes a `mcp_server_config()` that returns its declarative MCP entry. `deploy/engine.py` collects entries from detected tools (`shutil.which` gated), asks the adapter to format them, and merges into `settings.json` next to the existing `hooks` block.

**Tech Stack:** Python 3.11, pytest, ruff, MkDocs Material. Runs in worktree `.worktrees/mcp-deploy` on branch `feat/mcp-deploy`.

**Out of scope (later ADRs):** Engram wrapper module (ADR-022), Graphify wrapper module (ADR-023), wizard prompts for opt-in (Fase 3 of the wider plan), `lh doctor` reporting (Fase 3).

---

## File Structure

| Path | Status | Responsibility |
|------|--------|----------------|
| `src/lazy_harness/agents/base.py` | modify | Add `generate_mcp_config` to Protocol |
| `src/lazy_harness/agents/claude_code.py` | modify | Implement `generate_mcp_config` for Claude Code's `settings.json` shape |
| `src/lazy_harness/knowledge/qmd.py` | modify | Add `mcp_server_config()` returning the QMD MCP entry |
| `src/lazy_harness/deploy/engine.py` | modify | Add `deploy_mcp_servers(cfg)` that collects + writes |
| `src/lazy_harness/cli/deploy_cmd.py` | modify | Call `deploy_mcp_servers` from `lh deploy` |
| `tests/unit/test_agent_claude.py` | modify | Add tests for `generate_mcp_config` |
| `tests/unit/test_qmd.py` | modify | Add test for `mcp_server_config()` |
| `tests/unit/test_deploy_mcp.py` | create | Test the orchestration flow |
| `specs/adrs/024-mcp-server-orchestration.md` | create | ADR document |
| `specs/adrs/README.md` | modify | Add ADR-024 to index |

---

## Task 1: Extend `AgentAdapter` Protocol with `generate_mcp_config`

**Files:**
- Modify: `src/lazy_harness/agents/base.py:26-28`
- Test: `tests/unit/test_agent_claude.py` (added cases)

- [ ] **Step 1.1: Write the failing test for the Protocol shape**

Add to `tests/unit/test_agent_claude.py`:

```python
def test_claude_adapter_generate_mcp_config_returns_dict() -> None:
    from lazy_harness.agents.claude_code import ClaudeCodeAdapter

    adapter = ClaudeCodeAdapter()
    servers = {
        "qmd": {"command": "qmd", "args": ["mcp"]},
    }
    result = adapter.generate_mcp_config(servers)
    assert isinstance(result, dict)
    assert "mcpServers" in result
    assert "qmd" in result["mcpServers"]
    assert result["mcpServers"]["qmd"]["command"] == "qmd"
    assert result["mcpServers"]["qmd"]["args"] == ["mcp"]
```

- [ ] **Step 1.2: Run the test, expect failure**

```bash
uv run pytest tests/unit/test_agent_claude.py::test_claude_adapter_generate_mcp_config_returns_dict -v
```

Expected: `AttributeError: 'ClaudeCodeAdapter' object has no attribute 'generate_mcp_config'`

- [ ] **Step 1.3: Add the method to the Protocol**

In `src/lazy_harness/agents/base.py`, after `generate_hook_config` (line 28), add:

```python
    def generate_mcp_config(self, servers: dict[str, dict]) -> dict:
        """Generate agent-native MCP server config block.

        `servers` is a mapping of server name -> declarative entry
        (`{"command": str, "args": list[str], "env": dict[str, str] | None}`).
        Returns a dict ready to merge into the agent's settings file.
        """
        ...
```

- [ ] **Step 1.4: Implement in `ClaudeCodeAdapter`**

Append to `src/lazy_harness/agents/claude_code.py`:

```python
    def generate_mcp_config(self, servers: dict[str, dict]) -> dict:
        normalized: dict[str, dict] = {}
        for name, entry in servers.items():
            normalized[name] = {
                "command": entry["command"],
                "args": list(entry.get("args", [])),
            }
            if entry.get("env"):
                normalized[name]["env"] = dict(entry["env"])
        return {"mcpServers": normalized}
```

- [ ] **Step 1.5: Run the test, expect pass**

```bash
uv run pytest tests/unit/test_agent_claude.py::test_claude_adapter_generate_mcp_config_returns_dict -v
```

Expected: PASS.

- [ ] **Step 1.6: Add a test for empty servers dict**

```python
def test_claude_adapter_generate_mcp_config_empty() -> None:
    from lazy_harness.agents.claude_code import ClaudeCodeAdapter

    result = ClaudeCodeAdapter().generate_mcp_config({})
    assert result == {"mcpServers": {}}
```

- [ ] **Step 1.7: Add a test for env passthrough**

```python
def test_claude_adapter_generate_mcp_config_passes_env() -> None:
    from lazy_harness.agents.claude_code import ClaudeCodeAdapter

    servers = {
        "engram": {
            "command": "engram",
            "args": ["mcp"],
            "env": {"ENGRAM_PORT": "7437"},
        },
    }
    result = ClaudeCodeAdapter().generate_mcp_config(servers)
    assert result["mcpServers"]["engram"]["env"] == {"ENGRAM_PORT": "7437"}
```

- [ ] **Step 1.8: Run all the new tests, expect pass**

```bash
uv run pytest tests/unit/test_agent_claude.py -v -k generate_mcp_config
```

Expected: 3 tests pass.

- [ ] **Step 1.9: Commit**

```bash
git add src/lazy_harness/agents/base.py src/lazy_harness/agents/claude_code.py tests/unit/test_agent_claude.py
git commit -m "feat: add generate_mcp_config to agent adapter protocol"
```

---

## Task 2: Add `mcp_server_config()` to QMD wrapper

**Files:**
- Modify: `src/lazy_harness/knowledge/qmd.py`
- Test: `tests/unit/test_qmd.py`

- [ ] **Step 2.1: Write the failing test**

Append to `tests/unit/test_qmd.py`:

```python
def test_qmd_mcp_server_config_shape() -> None:
    from lazy_harness.knowledge.qmd import mcp_server_config

    entry = mcp_server_config()
    assert entry["command"] == "qmd"
    assert entry["args"] == ["mcp"]
```

- [ ] **Step 2.2: Run the test, expect failure**

```bash
uv run pytest tests/unit/test_qmd.py::test_qmd_mcp_server_config_shape -v
```

Expected: `ImportError: cannot import name 'mcp_server_config' from 'lazy_harness.knowledge.qmd'`

- [ ] **Step 2.3: Implement**

Append to `src/lazy_harness/knowledge/qmd.py`:

```python
def mcp_server_config() -> dict:
    """Declarative MCP entry for QMD (consumed by deploy_mcp_servers)."""
    return {"command": "qmd", "args": ["mcp"]}
```

- [ ] **Step 2.4: Run the test, expect pass**

```bash
uv run pytest tests/unit/test_qmd.py::test_qmd_mcp_server_config_shape -v
```

Expected: PASS.

- [ ] **Step 2.5: Commit**

```bash
git add src/lazy_harness/knowledge/qmd.py tests/unit/test_qmd.py
git commit -m "feat: expose mcp_server_config for QMD"
```

---

## Task 3: Implement `deploy_mcp_servers` in `deploy/engine.py`

**Files:**
- Modify: `src/lazy_harness/deploy/engine.py`
- Create: `tests/unit/test_deploy_mcp.py`

- [ ] **Step 3.1: Create the test file with the first failing test (skip-when-no-tools case)**

Create `tests/unit/test_deploy_mcp.py`:

```python
"""Tests for deploy_mcp_servers — MCP block writer in deploy/engine.py."""

from __future__ import annotations

import json
from pathlib import Path

import pytest


def _make_cfg(profile_dir: Path, agent_type: str = "claude-code"):
    from lazy_harness.core.config import Config

    cfg = Config()
    cfg.agent.type = agent_type
    cfg.profiles.items = {
        "default": type(
            "Profile",
            (),
            {"config_dir": str(profile_dir)},
        )()
    }
    return cfg


def test_deploy_mcp_servers_writes_settings_when_qmd_available(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from lazy_harness.deploy import engine

    profile_dir = tmp_path / ".claude-test"
    profile_dir.mkdir()

    monkeypatch.setattr(engine, "_collect_mcp_servers", lambda cfg: {
        "qmd": {"command": "qmd", "args": ["mcp"]},
    })

    cfg = _make_cfg(profile_dir)
    engine.deploy_mcp_servers(cfg)

    settings = json.loads((profile_dir / "settings.json").read_text())
    assert "mcpServers" in settings
    assert settings["mcpServers"]["qmd"]["command"] == "qmd"
```

- [ ] **Step 3.2: Run the test, expect failure**

```bash
uv run pytest tests/unit/test_deploy_mcp.py -v
```

Expected: `AttributeError: module 'lazy_harness.deploy.engine' has no attribute 'deploy_mcp_servers'` (or similar import error).

- [ ] **Step 3.3: Implement `_collect_mcp_servers` and `deploy_mcp_servers`**

Append to `src/lazy_harness/deploy/engine.py`:

```python
def _collect_mcp_servers(cfg: Config) -> dict[str, dict]:
    """Probe each known tool and return the MCP entries that should ship."""
    from lazy_harness.knowledge import qmd

    servers: dict[str, dict] = {}
    if qmd.is_qmd_available():
        servers["qmd"] = qmd.mcp_server_config()
    return servers


def deploy_mcp_servers(cfg: Config) -> None:
    """Write detected MCP server entries into each profile's settings.json."""
    from lazy_harness.agents.registry import get_agent

    servers = _collect_mcp_servers(cfg)
    if not servers:
        click.echo("  No MCP servers detected — nothing to deploy.")
        return

    agent = get_agent(cfg.agent.type)
    mcp_block = agent.generate_mcp_config(servers)

    for name, entry in cfg.profiles.items.items():
        target_dir = expand_path(entry.config_dir)
        target_dir.mkdir(parents=True, exist_ok=True)
        settings_file = target_dir / "settings.json"

        settings: dict = {}
        if settings_file.is_file():
            try:
                settings = json.loads(settings_file.read_text())
            except json.JSONDecodeError:
                pass

        settings.update(mcp_block)
        settings_file.write_text(json.dumps(settings, indent=2) + "\n")
        click.echo(f"  ✓ {name}/settings.json (MCP servers updated: {', '.join(servers)})")
```

- [ ] **Step 3.4: Run the test, expect pass**

```bash
uv run pytest tests/unit/test_deploy_mcp.py -v
```

Expected: PASS.

- [ ] **Step 3.5: Add the test for "preserves existing hooks block"**

Append to `tests/unit/test_deploy_mcp.py`:

```python
def test_deploy_mcp_servers_preserves_existing_hooks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from lazy_harness.deploy import engine

    profile_dir = tmp_path / ".claude-test"
    profile_dir.mkdir()
    (profile_dir / "settings.json").write_text(
        json.dumps({"hooks": {"SessionStart": [{"matcher": "", "hooks": []}]}})
    )

    monkeypatch.setattr(engine, "_collect_mcp_servers", lambda cfg: {
        "qmd": {"command": "qmd", "args": ["mcp"]},
    })

    engine.deploy_mcp_servers(_make_cfg(profile_dir))

    settings = json.loads((profile_dir / "settings.json").read_text())
    assert "hooks" in settings
    assert "mcpServers" in settings
```

- [ ] **Step 3.6: Run the test, expect pass**

```bash
uv run pytest tests/unit/test_deploy_mcp.py -v
```

Expected: 2 tests pass.

- [ ] **Step 3.7: Add the test for "no-op when no tools detected"**

Append to `tests/unit/test_deploy_mcp.py`:

```python
def test_deploy_mcp_servers_noop_when_no_tools(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from lazy_harness.deploy import engine

    profile_dir = tmp_path / ".claude-test"
    profile_dir.mkdir()
    monkeypatch.setattr(engine, "_collect_mcp_servers", lambda cfg: {})

    engine.deploy_mcp_servers(_make_cfg(profile_dir))

    assert not (profile_dir / "settings.json").is_file()
```

- [ ] **Step 3.8: Run the test, expect pass**

```bash
uv run pytest tests/unit/test_deploy_mcp.py -v
```

Expected: 3 tests pass.

- [ ] **Step 3.9: Add the test for "_collect_mcp_servers picks QMD via shutil.which"**

Append to `tests/unit/test_deploy_mcp.py`:

```python
def test_collect_mcp_servers_includes_qmd_when_available(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from lazy_harness.deploy import engine
    from lazy_harness.knowledge import qmd as qmd_mod

    monkeypatch.setattr(qmd_mod, "is_qmd_available", lambda: True)
    cfg = type("Cfg", (), {})()
    result = engine._collect_mcp_servers(cfg)
    assert "qmd" in result


def test_collect_mcp_servers_skips_qmd_when_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from lazy_harness.deploy import engine
    from lazy_harness.knowledge import qmd as qmd_mod

    monkeypatch.setattr(qmd_mod, "is_qmd_available", lambda: False)
    cfg = type("Cfg", (), {})()
    result = engine._collect_mcp_servers(cfg)
    assert "qmd" not in result
```

- [ ] **Step 3.10: Run all deploy_mcp tests, expect pass**

```bash
uv run pytest tests/unit/test_deploy_mcp.py -v
```

Expected: 5 tests pass.

- [ ] **Step 3.11: Commit**

```bash
git add src/lazy_harness/deploy/engine.py tests/unit/test_deploy_mcp.py
git commit -m "feat: add deploy_mcp_servers orchestration"
```

---

## Task 4: Wire `deploy_mcp_servers` into `lh deploy` CLI

**Files:**
- Modify: `src/lazy_harness/cli/deploy_cmd.py`
- Test: `tests/unit/cli/` (find existing or create)

- [ ] **Step 4.1: Inspect the existing deploy command to understand the call sequence**

```bash
cat src/lazy_harness/cli/deploy_cmd.py
```

Identify the function that runs `deploy_profiles` and `deploy_hooks`. The MCP step plugs in next to those, after hooks (so hooks block exists before MCP merge).

- [ ] **Step 4.2: Find or create the deploy CLI test file**

```bash
ls tests/unit/cli/ 2>/dev/null
```

Use the existing test file for `deploy_cmd.py` if present (likely `tests/unit/cli/test_deploy_cmd.py`). If absent, create one with the same import pattern as `tests/unit/test_agent_claude.py` (imports inside the test functions).

- [ ] **Step 4.3: Write the failing test**

In the deploy CLI test file:

```python
def test_lh_deploy_invokes_deploy_mcp_servers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from lazy_harness.cli import deploy_cmd
    from lazy_harness.deploy import engine

    called = {"mcp": False}
    monkeypatch.setattr(engine, "deploy_profiles", lambda cfg: None)
    monkeypatch.setattr(engine, "deploy_hooks", lambda cfg: None)
    monkeypatch.setattr(engine, "deploy_claude_symlink", lambda cfg: None)

    def fake_mcp(cfg):
        called["mcp"] = True

    monkeypatch.setattr(engine, "deploy_mcp_servers", fake_mcp)

    # Invoke the CLI handler with a stub config — adapt to the actual entry-point.
    deploy_cmd.run_deploy(cfg=None)

    assert called["mcp"] is True
```

(If the existing CLI handler signature differs, mirror what the file already exposes — read `deploy_cmd.py` and adapt the assertion target accordingly.)

- [ ] **Step 4.4: Run the test, expect failure**

```bash
uv run pytest tests/unit/cli/test_deploy_cmd.py -v -k mcp
```

Expected: failure because the CLI handler does not call `deploy_mcp_servers` yet.

- [ ] **Step 4.5: Wire the call**

Add the invocation inside the deploy command handler, after the existing `deploy_hooks(cfg)` call:

```python
deploy_mcp_servers(cfg)
```

Add the import at the top of `deploy_cmd.py`:

```python
from lazy_harness.deploy.engine import (
    deploy_claude_symlink,
    deploy_hooks,
    deploy_mcp_servers,
    deploy_profiles,
)
```

(Adjust to whatever import style the file already uses — keep the file consistent.)

- [ ] **Step 4.6: Run the test, expect pass**

```bash
uv run pytest tests/unit/cli/test_deploy_cmd.py -v -k mcp
```

Expected: PASS.

- [ ] **Step 4.7: Run the full deploy test suite, expect no regressions**

```bash
uv run pytest tests/unit/cli/ tests/unit/test_deploy_mcp.py -v
```

Expected: all tests pass.

- [ ] **Step 4.8: Commit**

```bash
git add src/lazy_harness/cli/deploy_cmd.py tests/unit/cli/test_deploy_cmd.py
git commit -m "feat: wire deploy_mcp_servers into lh deploy"
```

---

## Task 5: ADR-024 document

**Files:**
- Create: `specs/adrs/024-mcp-server-orchestration.md`
- Modify: `specs/adrs/README.md`

- [ ] **Step 5.1: Write the ADR**

Create `specs/adrs/024-mcp-server-orchestration.md` with the standard ADR template used by ADR-016. Sections:

```markdown
# ADR-024: MCP server orchestration via `lh deploy`

**Status:** accepted
**Date:** 2026-05-03

## Context

The harness already detects optional knowledge tools (QMD) and gates them behind `shutil.which` (ADR-016). What it did not do until now was **deploy** those tools to the agent — the user still had to hand-edit `~/.claude/settings.json` to declare an `mcpServers` block.

With three tools converging on the MCP standard (QMD, Engram per ADR-022, Graphify per ADR-023), the per-tool wiring needs a single seam in the deploy pipeline that knows about agent-specific config formats.

## Decision

Extend the `AgentAdapter` Protocol with `generate_mcp_config(servers) -> dict`. Each tool wrapper exposes a `mcp_server_config()` returning a declarative entry. `deploy_mcp_servers(cfg)` in `deploy/engine.py`:

1. Probes each known tool via its `is_<tool>_available()` predicate.
2. Collects MCP entries from those that responded yes.
3. Asks the agent adapter to format the block.
4. Merges into each profile's `settings.json` next to the existing `hooks` block.

This is invoked from `lh deploy` after `deploy_hooks`, so a single command keeps the agent surface fully in sync with the harness config.

## Alternatives considered

- **Hand-edited `mcpServers` in profile templates.** Reproducible but breaks when a tool is uninstalled — the entry stays and the agent fails to start the missing server.
- **A dedicated `lh mcp` subcommand.** Splits the surface unnecessarily; users would have to remember to run it after every install. Folding it into `lh deploy` keeps one command as the source of truth.
- **Generate per-agent config files outside `settings.json`.** Some agents support standalone `mcp.json`, but Claude Code reads `mcpServers` from `settings.json`. One file is simpler.

## Consequences

- New tools that want to ship as MCP servers expose `mcp_server_config()` and a `is_<tool>_available()` probe — same shape as the QMD precedent.
- Adapters for new agents (Codex, Gemini CLI, Copilot) implement `generate_mcp_config` to translate the canonical dict into their native format. The Protocol is the contract.
- `lh deploy` is now responsible for both hooks and MCP. The two share the `settings.json` merge logic, which keeps idempotency invariant: re-running deploy converges on the same state.
- The harness still does not write any MCP entry for tools that are not installed. Removing a tool and re-running `lh deploy` removes its entry on the next merge.
```

- [ ] **Step 5.2: Add ADR-024 to the index**

Edit `specs/adrs/README.md` and append the entry following the existing index style.

- [ ] **Step 5.3: Validate the docs build**

```bash
uv run --group docs mkdocs build --strict
```

Expected: clean build, no warnings.

- [ ] **Step 5.4: Commit**

```bash
git add specs/adrs/024-mcp-server-orchestration.md specs/adrs/README.md
git commit -m "docs: add ADR-024 (MCP server orchestration)"
```

---

## Task 6: Final pre-commit gate (`/tdd-check`)

- [ ] **Step 6.1: Run the full pytest suite**

```bash
uv run pytest
```

Expected: all tests green.

- [ ] **Step 6.2: Run ruff**

```bash
uv run ruff check src tests
```

Expected: clean output.

- [ ] **Step 6.3: Run the strict mkdocs build**

```bash
uv run --group docs mkdocs build --strict
```

Expected: clean build.

- [ ] **Step 6.4: If any of the three fail, fix and amend the relevant prior commit (or add a follow-up commit)**

Do **not** use `--no-verify`. Do **not** skip a check.

---

## Self-review notes

- Spec coverage: every section of the agreed ADR-024 plan is mapped to a task. Engram and Graphify are explicitly out of scope (ADR-022 / ADR-023 will follow).
- Placeholder scan: every code block is concrete; no "implement later", no "add error handling".
- Type consistency: `generate_mcp_config(servers: dict[str, dict]) -> dict` is the same signature in Task 1 (Protocol), Task 1 (adapter), Task 3 (caller). `mcp_server_config()` returns the same shape in Task 2 (definition) and Task 3 (caller).
- The plan does not bump version numbers (release-please owns that).
- The plan does not edit `specs/archive/`.

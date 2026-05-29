# ADR-031: Agent adapter completeness — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development`
> (recommended) or `superpowers:executing-plans` to implement this plan task-by-task.
> Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close seven Claude-specific leaks that bypass the `AgentAdapter` Protocol, making
the ADR-004 promise true: adding a second agent adapter requires one new file and one registry
entry, with zero changes elsewhere.

**Architecture:** Four new methods on `AgentAdapter` Protocol (`global_config_link`,
`mcp_config_file`, `session_dirs`, `system_doc_name`). `ClaudeCodeAdapter` implements them
returning the values that were previously hardcoded. All seven leak sites are updated to call
through the adapter. `sync_claude.py` is renamed `sync_agent_md.py` with the filename
resolved dynamically. A `NullAdapter` stub is registered in tests to prove the Protocol
contract at the boundary.

**Tech Stack:** Python 3.11+, `uv`, pytest, ruff, mkdocs Material.

**Spec / ADR:** [`specs/adrs/031-agent-adapter-completeness.md`](../adrs/031-agent-adapter-completeness.md)

---

## File structure

**Modify:**
- `src/lazy_harness/agents/base.py` — add 4 Protocol methods
- `src/lazy_harness/agents/claude_code.py` — implement 4 new methods
- `src/lazy_harness/agents/registry.py` — register `NullAdapter` under `"null"` for tests
- `src/lazy_harness/deploy/engine.py` — call `global_config_link`, `mcp_config_file` through adapter; fix L3 env-var reads
- `src/lazy_harness/deploy/defaults.py` — gate `sync-claude` default on `system_doc_name`
- `src/lazy_harness/cli/doctor_cmd.py` — resolve config dir through adapter
- `src/lazy_harness/cli/knowledge_cmd.py` — resolve config dir + subdirs through adapter
- `src/lazy_harness/hooks/builtins/compound_loop.py` — resolve config dir + subdirs through adapter

**Rename:**
- `src/lazy_harness/core/sync_claude.py` → `src/lazy_harness/core/sync_agent_md.py`
- Update call sites: `cli/profile_cmd.py`, `hooks/builtins/post_tool_use_sync_claude.py`, `deploy/defaults.py`

**Create:**
- `tests/unit/test_agent_protocol.py` — Protocol conformance test against every registered adapter

**Modify (tests):**
- `tests/unit/test_agent_claude.py` — extend with 4 new method assertions
- `tests/integration/test_deploy.py` — verify `deploy_claude_symlink` calls `global_config_link()`
- `tests/integration/test_profile_cmd.py` — verify `sync-agent-md` uses `system_doc_name()`

---

## Task 1 — Protocol conformance test (fails until Task 3)

**Files:** Create `tests/unit/test_agent_protocol.py`

- [ ] **Step 1: Write the failing test**

```python
"""Protocol conformance — every registered adapter must implement all methods."""
from __future__ import annotations

import pytest

REGISTERED_AGENT_TYPES = ["claude-code"]  # extend when new adapters ship


@pytest.mark.parametrize("agent_type", REGISTERED_AGENT_TYPES)
def test_adapter_satisfies_full_protocol(agent_type: str) -> None:
    from lazy_harness.agents.base import AgentAdapter
    from lazy_harness.agents.registry import get_agent

    adapter = get_agent(agent_type)
    assert isinstance(adapter, AgentAdapter), (
        f"{agent_type!r} adapter does not satisfy AgentAdapter Protocol"
    )


def test_null_adapter_satisfies_protocol() -> None:
    """NullAdapter returns None / empty-string sentinels — proves optional methods work."""
    from lazy_harness.agents.base import AgentAdapter
    from lazy_harness.agents.registry import get_agent

    adapter = get_agent("null")
    assert isinstance(adapter, AgentAdapter)
    assert adapter.global_config_link() is None
    assert adapter.mcp_config_file() == ""
    assert adapter.system_doc_name() == ""
    assert adapter.session_dirs() == {"sessions": "", "logs": "", "queue": ""}
```

- [ ] **Step 2: Run to confirm failure**

```bash
uv run pytest tests/unit/test_agent_protocol.py -v
```

Expected: `AttributeError: 'AgentAdapter' has no attribute 'global_config_link'`
(or similar — Protocol methods don't exist yet).

---

## Task 2 — Extend `AgentAdapter` Protocol

**Files:** Modify `src/lazy_harness/agents/base.py`

- [ ] **Step 1: Add the four new methods to the Protocol**

After `generate_mcp_config`, add:

```python
def global_config_link(self) -> Path | None:
    """Canonical global symlink for this agent (e.g. ~/.claude).

    Return None if the agent does not use a global symlink convention.
    """
    ...

def mcp_config_file(self) -> str:
    """Filename inside the config dir holding MCP server config.

    Return empty string if MCP config is merged into the main settings file.
    """
    ...

def session_dirs(self) -> dict[str, str]:
    """Subdirectory names for agent-managed session artefacts.

    Keys: 'sessions', 'logs', 'queue'. Empty string means not available.
    """
    ...

def system_doc_name(self) -> str:
    """Primary system-instruction document filename (e.g. 'CLAUDE.md').

    Return empty string for agents that use a different injection mechanism.
    """
    ...
```

- [ ] **Step 2: Run conformance test — still fails** (ClaudeCodeAdapter not updated yet)

```bash
uv run pytest tests/unit/test_agent_protocol.py::test_adapter_satisfies_full_protocol -v
```

---

## Task 3 — Implement new methods on `ClaudeCodeAdapter` + add `NullAdapter`

**Files:** Modify `src/lazy_harness/agents/claude_code.py`,
modify `src/lazy_harness/agents/registry.py`

- [ ] **Step 1: Write the tests first**

Extend `tests/unit/test_agent_claude.py` — add after the existing `test_claude_adapter_generate_mcp_config_passes_env` test:

```python
def test_claude_adapter_global_config_link() -> None:
    from lazy_harness.agents.claude_code import ClaudeCodeAdapter

    result = ClaudeCodeAdapter().global_config_link()
    assert result == Path.home() / ".claude"


def test_claude_adapter_mcp_config_file() -> None:
    from lazy_harness.agents.claude_code import ClaudeCodeAdapter

    assert ClaudeCodeAdapter().mcp_config_file() == ".claude.json"


def test_claude_adapter_session_dirs() -> None:
    from lazy_harness.agents.claude_code import ClaudeCodeAdapter

    dirs = ClaudeCodeAdapter().session_dirs()
    assert dirs["sessions"] == "projects"
    assert dirs["logs"] == "logs"
    assert dirs["queue"] == "queue"


def test_claude_adapter_system_doc_name() -> None:
    from lazy_harness.agents.claude_code import ClaudeCodeAdapter

    assert ClaudeCodeAdapter().system_doc_name() == "CLAUDE.md"
```

- [ ] **Step 2: Run new tests to confirm failure**

```bash
uv run pytest tests/unit/test_agent_claude.py::test_claude_adapter_global_config_link -v
```

- [ ] **Step 3: Implement the four methods on `ClaudeCodeAdapter`**

Add after `generate_mcp_config`:

```python
def global_config_link(self) -> Path | None:
    return Path.home() / ".claude"

def mcp_config_file(self) -> str:
    return ".claude.json"

def session_dirs(self) -> dict[str, str]:
    return {"sessions": "projects", "logs": "logs", "queue": "queue"}

def system_doc_name(self) -> str:
    return "CLAUDE.md"
```

- [ ] **Step 4: Add `NullAdapter` to `registry.py`**

```python
class NullAdapter:
    """Sentinel adapter for testing — returns None/empty for all optional methods."""

    @property
    def name(self) -> str:
        return "null"

    def config_dir(self, profile_config_dir: str) -> Path:
        from lazy_harness.core.paths import expand_path
        return expand_path(profile_config_dir)

    def env_var(self) -> str:
        return ""

    def resolve_binary(self) -> Path | None:
        return None

    def supported_hooks(self) -> list[str]:
        return []

    def generate_hook_config(self, hooks: dict) -> dict:
        return {}

    def generate_mcp_config(self, servers: dict) -> dict:
        return {}

    def global_config_link(self) -> Path | None:
        return None

    def mcp_config_file(self) -> str:
        return ""

    def session_dirs(self) -> dict[str, str]:
        return {"sessions": "", "logs": "", "queue": ""}

    def system_doc_name(self) -> str:
        return ""


_AGENTS: dict[str, type] = {
    "claude-code": ClaudeCodeAdapter,
    "null": NullAdapter,
}
```

- [ ] **Step 5: Run all agent tests — all pass**

```bash
uv run pytest tests/unit/test_agent_claude.py tests/unit/test_agent_protocol.py -v
```

---

## Task 4 — Update leak sites L1–L4 (deploy engine + doctor + knowledge + compound_loop)

**Files:** `deploy/engine.py`, `cli/doctor_cmd.py`, `cli/knowledge_cmd.py`,
`hooks/builtins/compound_loop.py`

- [ ] **Step 1: Write integration tests that assert the adapter path is used**

In `tests/integration/test_deploy.py`, add:

```python
def test_deploy_symlink_uses_adapter_global_config_link(tmp_path, monkeypatch) -> None:
    """deploy_claude_symlink must call agent.global_config_link(), not hardcode ~/.claude."""
    from unittest.mock import MagicMock, patch
    from lazy_harness.deploy.engine import deploy_claude_symlink

    mock_agent = MagicMock()
    mock_agent.global_config_link.return_value = tmp_path / ".myagent"

    with patch("lazy_harness.deploy.engine.get_agent", return_value=mock_agent):
        cfg = _make_cfg(tmp_path, default_profile="personal")
        deploy_claude_symlink(cfg)

    mock_agent.global_config_link.assert_called_once()


def test_deploy_mcp_uses_adapter_mcp_config_file(tmp_path) -> None:
    """deploy_mcp_servers must use agent.mcp_config_file() for the output filename."""
    from unittest.mock import MagicMock, patch
    from lazy_harness.deploy.engine import deploy_mcp_servers

    mock_agent = MagicMock()
    mock_agent.mcp_config_file.return_value = ".myagent.json"

    cfg = _make_cfg(tmp_path, default_profile="personal")
    cfg.profiles.items["personal"] = ProfileEntry(config_dir=str(tmp_path / "profile"))

    with patch("lazy_harness.deploy.engine.get_agent", return_value=mock_agent):
        deploy_mcp_servers(cfg, {"test-server": {"command": "ts", "args": []}})

    assert (tmp_path / "profile" / ".myagent.json").exists()
```

- [ ] **Step 2: Run new tests to confirm failure**

```bash
uv run pytest tests/integration/test_deploy.py::test_deploy_symlink_uses_adapter_global_config_link -v
```

- [ ] **Step 3: Update `deploy/engine.py`**

`deploy_claude_symlink` → resolve link target via `agent.global_config_link()`:

```python
def deploy_claude_symlink(cfg: Config) -> None:
    """Create the agent's global config symlink to the default profile's config dir."""
    from lazy_harness.agents.registry import get_agent

    agent = get_agent(cfg.agent.type)
    link_target = agent.global_config_link()
    if link_target is None:
        return

    default_name = cfg.profiles.default
    entry = cfg.profiles.items.get(default_name)
    if not entry:
        click.echo(f"  · Default profile '{default_name}' not found in config.")
        return

    target = expand_path(entry.config_dir)
    status = ensure_symlink(target, link_target)
    if status == "exists":
        click.echo(f"  · {link_target} → {entry.config_dir} (already linked)")
    else:
        click.echo(f"  ✓ {link_target} → {entry.config_dir}")
```

`deploy_mcp_servers` → resolve filename via `agent.mcp_config_file()`:

```python
# Replace the hardcoded ".claude.json" line:
mcp_file_name = agent.mcp_config_file()
if not mcp_file_name:
    return   # agent does not use a separate MCP config file
mcp_config_file = target_dir / mcp_file_name
```

- [ ] **Step 4: Update L3 — direct env-var reads**

`cli/doctor_cmd.py:42` — replace:
```python
# Before:
base = Path(os.environ.get("CLAUDE_CONFIG_DIR", Path.home() / ".claude"))
# After:
from lazy_harness.agents.registry import get_agent
agent = get_agent(cfg.agent.type)
env_val = os.environ.get(agent.env_var())
base = Path(env_val) if env_val else agent.config_dir(
    cfg.profiles.items.get(cfg.profiles.default, ProfileEntry()).config_dir
    or str(Path.home() / ".claude")
)
```

`cli/knowledge_cmd.py:200-205` — replace the three hardcoded subdir lines:
```python
# Before:
claude_dir = Path(os.environ.get("CLAUDE_CONFIG_DIR", Path.home() / ".claude"))
sessions_dir = claude_dir / "projects" / encoded
queue_dir = claude_dir / "queue"
log_dir = claude_dir / "logs"
# After:
from lazy_harness.agents.registry import get_agent
agent = get_agent(cfg.agent.type)
env_val = os.environ.get(agent.env_var())
agent_dir = Path(env_val) if env_val else expand_path(
    cfg.profiles.items.get(cfg.profiles.default, ProfileEntry()).config_dir
)
subdirs = agent.session_dirs()
sessions_dir = agent_dir / subdirs["sessions"] / encoded
queue_dir = agent_dir / subdirs["queue"]
log_dir = agent_dir / subdirs["logs"]
```

`hooks/builtins/compound_loop.py:65-87` — same pattern, replace `CLAUDE_CONFIG_DIR`
reads and `logs/`, `queue/`, `projects/` strings with `agent.env_var()`,
`agent.session_dirs()`. The agent instance is resolved from the config loaded
at hook startup.

- [ ] **Step 5: Run integration tests — all pass**

```bash
uv run pytest tests/integration/test_deploy.py tests/integration/test_knowledge_cmd.py -v
```

---

## Task 5 — Rename `sync_claude.py` → `sync_agent_md.py`

**Files:** `core/sync_claude.py` → `core/sync_agent_md.py`, plus call sites:
`cli/profile_cmd.py`, `hooks/builtins/post_tool_use_sync_claude.py`

- [ ] **Step 1: Write the test**

In `tests/integration/test_profile_cmd.py`, add:

```python
def test_sync_agent_md_uses_system_doc_name(tmp_path) -> None:
    """sync_profiles must write <system_doc_name>, not a hardcoded 'CLAUDE.md'."""
    from lazy_harness.core.sync_agent_md import sync_profiles
    from lazy_harness.agents.claude_code import ClaudeCodeAdapter

    profiles_dir = tmp_path / "profiles"
    profile = profiles_dir / "personal"
    profile.mkdir(parents=True)
    common_dir = profiles_dir / "_common"
    common_dir.mkdir()
    (common_dir / "CLAUDE.common.md").write_text("## common\n")
    (profile / "CLAUDE.head.md").write_text("## head\n")
    (profile / "CLAUDE.tail.md").write_text("## tail\n")

    adapter = ClaudeCodeAdapter()
    sync_profiles(profiles_dir, adapter)

    out = profile / adapter.system_doc_name()  # "CLAUDE.md"
    assert out.is_file()
    assert "## head" in out.read_text()
    assert "## common" in out.read_text()
    assert "## tail" in out.read_text()
```

- [ ] **Step 2: Run to confirm failure** (module doesn't exist yet)

```bash
uv run pytest tests/integration/test_profile_cmd.py::test_sync_agent_md_uses_system_doc_name -v
```

- [ ] **Step 3: Rename the file and update the public API signature**

`sync_profiles(profiles_dir: Path, adapter: AgentAdapter) -> list[Path]`

The adapter parameter replaces the implicit `"CLAUDE.md"` hardcode. Inside
`sync_profiles`, replace:
```python
# Before:
head = entry / "CLAUDE.head.md"
tail = entry / "CLAUDE.tail.md"
out  = entry / "CLAUDE.md"
common_path = profiles_dir / "_common" / "CLAUDE.common.md"
# After:
doc_name = adapter.system_doc_name()
if not doc_name:
    continue  # agent does not use a system doc; skip this profile
head = entry / f"{doc_name.removesuffix('.md')}.head.md"
tail = entry / f"{doc_name.removesuffix('.md')}.tail.md"
out  = entry / doc_name
common_path = profiles_dir / "_common" / f"{doc_name.removesuffix('.md')}.common.md"
```

- [ ] **Step 4: Update call sites**

`cli/profile_cmd.py` — update import `sync_claude` → `sync_agent_md`; pass `agent`
instance as second arg.

`hooks/builtins/post_tool_use_sync_claude.py` — update import. Filename of the hook
script stays as-is (it is already deployed by name in `settings.json`; renaming it
requires a migration). Only the internal import changes.

- [ ] **Step 5: Run profile tests**

```bash
uv run pytest tests/integration/test_profile_cmd.py -v
```

---

## Task 6 — Gate `sync-claude` default hook on `system_doc_name`

**Files:** `src/lazy_harness/deploy/defaults.py`

- [ ] **Step 1: Write the test**

In `tests/unit/test_deploy_defaults.py`, add:

```python
def test_sync_claude_hook_excluded_for_null_agent() -> None:
    from lazy_harness.agents.registry import get_agent
    from lazy_harness.deploy.defaults import merge_with_defaults

    agent = get_agent("null")  # system_doc_name() == ""
    merged = merge_with_defaults({}, agent)
    all_scripts = [s for scripts in merged.values() for s in scripts]
    assert "post-tool-use-sync-claude" not in all_scripts


def test_sync_claude_hook_included_for_claude_agent() -> None:
    from lazy_harness.agents.registry import get_agent
    from lazy_harness.deploy.defaults import merge_with_defaults

    agent = get_agent("claude-code")
    merged = merge_with_defaults({}, agent)
    all_scripts = [s for scripts in merged.values() for s in scripts]
    assert "post-tool-use-sync-claude" in all_scripts
```

- [ ] **Step 2: Run tests to confirm failure**

```bash
uv run pytest tests/unit/test_deploy_defaults.py::test_sync_claude_hook_excluded_for_null_agent -v
```

- [ ] **Step 3: Update `merge_with_defaults` signature and logic**

`merge_with_defaults(user_hooks, agent)` — accept the `AgentAdapter` instance:

```python
def merge_with_defaults(
    user_hooks: dict[str, HookEventConfig],
    agent: AgentAdapter,
) -> dict[str, list[str]]:
    base = {k: list(v) for k, v in DEFAULT_HOOKS.items()}
    # Gate system-doc hook on agent support
    if not agent.system_doc_name():
        base.get("post_tool_use", []).remove("post-tool-use-sync-claude")  # if present
    # User overrides win per-event
    for event, cfg in user_hooks.items():
        if cfg.scripts:
            base[event] = list(cfg.scripts)
    return base
```

Update the single caller in `deploy/engine.py:deploy_hooks`:
```python
effective = merge_with_defaults(cfg.hooks, agent)
```

- [ ] **Step 4: Run unit tests**

```bash
uv run pytest tests/unit/test_deploy_defaults.py -v
```

---

## Task 7 — Full suite verification

- [ ] **Step 1: Run the complete test suite**

```bash
uv run pytest
```

- [ ] **Step 2: Run ruff**

```bash
uv run ruff check src tests
```

- [ ] **Step 3: Build docs**

```bash
uv run --group docs mkdocs build --strict
```

- [ ] **Step 4: Register `NullAdapter` removal from production registry**

The `NullAdapter` is registered under `"null"` in `registry.py`. Confirm it is
never reachable from user-facing config validation (a `ConfigError` if
`cfg.agent.type == "null"` is acceptable). Alternatively, move `NullAdapter` to
`tests/conftest.py` and patch the registry only during tests — the cleaner option
if you prefer production code to not carry a test-only class.

- [ ] **Step 5: Update ADR-031 status to `accepted` once all checks pass**

```
**Status:** accepted
```

---

## Quick reference — the seven leaks and their resolution

| # | Leak | Location | Fix |
|---|------|----------|-----|
| L1 | `~/.claude` hardcoded | `deploy/engine.py:deploy_claude_symlink` | `agent.global_config_link()` (Task 4) |
| L2 | `.claude.json` hardcoded | `deploy/engine.py:deploy_mcp_servers` | `agent.mcp_config_file()` (Task 4) |
| L3 | `CLAUDE_CONFIG_DIR` direct reads | `doctor_cmd`, `knowledge_cmd`, `compound_loop` | `agent.env_var()` + `agent.config_dir()` (Task 4) |
| L4 | `logs/queue/projects` subdirs | same three files | `agent.session_dirs()` (Task 4) |
| L5 | `CLAUDE.md` filename | `sync_claude.py` + callers | `agent.system_doc_name()` (Task 5) |
| L6 | `sync-claude` unconditional default | `deploy/defaults.py` | gate on `system_doc_name()` (Task 6) |
| L7 | Comment "Claude Code hooks block" | `deploy/engine.py:41` | cosmetic rename (any task) |

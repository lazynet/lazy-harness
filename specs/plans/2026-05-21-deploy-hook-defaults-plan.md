# `lh deploy` default hooks merge — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `lh deploy` apply a framework-provided default hook set on every profile, with per-event override from `config.toml` and a backup-on-unknown safeguard when settings.json had hand-edited hook entries.

**Architecture:** Pure `merge_with_defaults` function in a new `deploy/defaults.py` that combines `DEFAULT_HOOKS` (Python literal) with `cfg.hooks` overrides per-event. `deploy/engine.py` consumes the merged map instead of iterating `cfg.hooks` directly. Hook block in `settings.json` becomes framework-owned; manual entries are backed up and warned before being replaced.

**Tech Stack:** Python 3.11+, `uv`, pytest, ruff, mkdocs Material. Existing test scaffolding in `tests/unit/deploy/`.

**Spec:** [`specs/designs/2026-05-21-deploy-hook-defaults-design.md`](../designs/2026-05-21-deploy-hook-defaults-design.md)

---

## File Structure

- **Create:** `src/lazy_harness/deploy/defaults.py` — `DEFAULT_HOOKS` literal + `merge_with_defaults` pure function.
- **Create:** `tests/unit/test_deploy_defaults.py` — pure-logic tests (1–5).
- **Modify:** `src/lazy_harness/hooks/loader.py` — extract `resolve_script_names`; `resolve_hooks_for_event` becomes a one-liner wrapper.
- **Modify:** `src/lazy_harness/deploy/engine.py` — call `merge_with_defaults`, add unknown-entry backup.
- **Modify:** `tests/unit/test_deploy_engine.py` — engine integration tests (6–11).
- **Create:** `specs/adrs/031-default-hooks-merge.md` — ADR.
- **Modify:** `docs/how/hooks.md` — new "Default hooks" section.
- **Modify:** `templates/config.toml.default` — comment block pointing to defaults.
- **Modify:** `specs/backlog.md` — move item to Done.

---

## Task 1: Contract test — DEFAULT_HOOKS only references registered builtins

**Files:**
- Create: `tests/unit/test_deploy_defaults.py`
- Create: `src/lazy_harness/deploy/defaults.py`

- [ ] **Step 1: Write the failing test**

```python
"""Tests for the deploy.defaults module — default hook set + merge logic."""

from __future__ import annotations

from lazy_harness.core.config import HookEventConfig
from lazy_harness.deploy.defaults import DEFAULT_HOOKS, merge_with_defaults
from lazy_harness.hooks.loader import list_builtin_hooks


def test_default_hooks_only_references_registered_builtins() -> None:
    builtins = set(list_builtin_hooks())
    for event, scripts in DEFAULT_HOOKS.items():
        for script in scripts:
            assert script in builtins, (
                f"DEFAULT_HOOKS[{event!r}] references {script!r}, "
                "which is not in lazy_harness.hooks.loader._BUILTIN_HOOKS"
            )
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest tests/unit/test_deploy_defaults.py::test_default_hooks_only_references_registered_builtins -v
```

Expected: `ModuleNotFoundError: No module named 'lazy_harness.deploy.defaults'` or ImportError.

- [ ] **Step 3: Write minimal implementation**

Create `src/lazy_harness/deploy/defaults.py`:

```python
"""Framework-provided default hook set.

The implicit hook configuration every profile starts with. User overrides
in config.toml replace per-event values; events not declared in user config
fall through to the defaults below.
"""

from __future__ import annotations

from lazy_harness.core.config import HookEventConfig

DEFAULT_HOOKS: dict[str, list[str]] = {
    "session_start": ["context-inject"],
    "session_stop": ["session-export", "compound-loop", "engram-persist"],
    "session_end": ["session-end"],
    "pre_compact": ["pre-compact"],
    "post_compact": ["post-compact"],
    "pre_tool_use": ["pre-tool-use-security", "pre-tool-use-memory-size"],
    "post_tool_use": ["post-tool-use-format", "post-tool-use-sync-claude"],
}


def merge_with_defaults(user_hooks: dict[str, HookEventConfig]) -> dict[str, list[str]]:
    """Produce the effective hook event → script-names mapping.

    For each event in DEFAULT_HOOKS: if user_hooks declares it (even with an
    empty list), use user_hooks[event].scripts. Otherwise use the default.
    For each event in user_hooks but NOT in DEFAULT_HOOKS, include verbatim.
    """
    effective: dict[str, list[str]] = {}
    for event, default_scripts in DEFAULT_HOOKS.items():
        if event in user_hooks:
            effective[event] = list(user_hooks[event].scripts)
        else:
            effective[event] = list(default_scripts)
    for event, hooks_cfg in user_hooks.items():
        if event not in DEFAULT_HOOKS:
            effective[event] = list(hooks_cfg.scripts)
    return effective
```

- [ ] **Step 4: Run test to verify it passes**

```bash
uv run pytest tests/unit/test_deploy_defaults.py::test_default_hooks_only_references_registered_builtins -v
```

Expected: PASS.

- [ ] **Step 5: Do NOT commit yet** — bundle commits per logical group at the end of Task 5.

---

## Task 2: merge empty user returns defaults verbatim

**Files:**
- Modify: `tests/unit/test_deploy_defaults.py`

- [ ] **Step 1: Append the failing test**

```python
def test_merge_empty_user_returns_defaults_verbatim() -> None:
    result = merge_with_defaults({})

    assert result == {k: list(v) for k, v in DEFAULT_HOOKS.items()}
    # Verify the returned lists are not aliased to DEFAULT_HOOKS internals
    result["session_start"].append("mutated")
    assert "mutated" not in DEFAULT_HOOKS["session_start"]
```

- [ ] **Step 2: Run test to verify it passes** (impl from Task 1 already covers this)

```bash
uv run pytest tests/unit/test_deploy_defaults.py::test_merge_empty_user_returns_defaults_verbatim -v
```

Expected: PASS.

---

## Task 3: merge user overrides one event

**Files:**
- Modify: `tests/unit/test_deploy_defaults.py`

- [ ] **Step 1: Append the failing test**

```python
def test_merge_user_overrides_one_event() -> None:
    user = {"session_stop": HookEventConfig(scripts=["my-hook"])}

    result = merge_with_defaults(user)

    assert result["session_stop"] == ["my-hook"]
    assert result["session_start"] == ["context-inject"]
    assert result["pre_tool_use"] == ["pre-tool-use-security", "pre-tool-use-memory-size"]
```

- [ ] **Step 2: Run test to verify it passes**

```bash
uv run pytest tests/unit/test_deploy_defaults.py::test_merge_user_overrides_one_event -v
```

Expected: PASS.

---

## Task 4: merge user empty list is explicit opt-out

**Files:**
- Modify: `tests/unit/test_deploy_defaults.py`

- [ ] **Step 1: Append the failing test**

```python
def test_merge_user_empty_list_is_explicit_opt_out() -> None:
    user = {"session_stop": HookEventConfig(scripts=[])}

    result = merge_with_defaults(user)

    # opt-out is preserved as empty list (engine drops it before writing)
    assert result["session_stop"] == []
    assert result["session_start"] == ["context-inject"]
```

- [ ] **Step 2: Run test to verify it passes**

```bash
uv run pytest tests/unit/test_deploy_defaults.py::test_merge_user_empty_list_is_explicit_opt_out -v
```

Expected: PASS.

---

## Task 5: merge preserves user custom event

**Files:**
- Modify: `tests/unit/test_deploy_defaults.py`

- [ ] **Step 1: Append the failing test**

```python
def test_merge_preserves_user_custom_event() -> None:
    user = {"notification": HookEventConfig(scripts=["my-notify"])}

    result = merge_with_defaults(user)

    assert result["notification"] == ["my-notify"]
    assert result["session_start"] == ["context-inject"]
```

- [ ] **Step 2: Run test to verify it passes**

```bash
uv run pytest tests/unit/test_deploy_defaults.py::test_merge_preserves_user_custom_event -v
```

Expected: PASS.

- [ ] **Step 3: Commit defaults module + tests 1-5**

```bash
git add src/lazy_harness/deploy/defaults.py tests/unit/test_deploy_defaults.py
git commit -m "feat: add DEFAULT_HOOKS and merge_with_defaults"
```

---

## Task 6: Refactor loader — extract resolve_script_names

**Files:**
- Modify: `src/lazy_harness/hooks/loader.py`
- Modify: `tests/unit/test_hook_loader.py` (if exists; otherwise add to existing tests file)

- [ ] **Step 1: Check existing loader tests**

```bash
ls tests/unit/
grep -n "resolve_hooks_for_event\|resolve_script_names" tests/ -r
```

Identify the existing test file and confirm test shape.

- [ ] **Step 2: Write the failing test for new function**

Add to the appropriate test file (likely `tests/unit/test_hook_loader.py`):

```python
from lazy_harness.hooks.loader import resolve_script_names


def test_resolve_script_names_returns_hookinfo_list(tmp_path: Path) -> None:
    # context-inject is a built-in
    result = resolve_script_names(["context-inject"])

    assert len(result) == 1
    assert result[0].name == "context-inject"
    assert result[0].is_builtin is True


def test_resolve_script_names_skips_unresolvable(tmp_path: Path) -> None:
    result = resolve_script_names(["context-inject", "no-such-hook-xyz"])

    # Only the resolvable one is returned (matches resolve_hooks_for_event behavior)
    assert [h.name for h in result] == ["context-inject"]
```

- [ ] **Step 3: Run tests to verify they fail**

```bash
uv run pytest tests/unit/test_hook_loader.py::test_resolve_script_names_returns_hookinfo_list -v
```

Expected: `ImportError: cannot import name 'resolve_script_names'`.

- [ ] **Step 4: Refactor loader.py**

Find this in `src/lazy_harness/hooks/loader.py`:

```python
def resolve_hooks_for_event(
    cfg: Config, event: str, user_hooks_dir: Path | None = None
) -> list[HookInfo]:
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

Replace with:

```python
def resolve_script_names(
    names: list[str], user_hooks_dir: Path | None = None
) -> list[HookInfo]:
    """Resolve a list of hook names to HookInfo records, skipping unresolvable."""
    hooks: list[HookInfo] = []
    for script_name in names:
        hook = resolve_hook(script_name, user_hooks_dir)
        if hook:
            hooks.append(hook)
    return hooks


def resolve_hooks_for_event(
    cfg: Config, event: str, user_hooks_dir: Path | None = None
) -> list[HookInfo]:
    event_cfg = cfg.hooks.get(event)
    if not event_cfg:
        return []
    return resolve_script_names(event_cfg.scripts, user_hooks_dir)
```

- [ ] **Step 5: Run new + existing loader tests**

```bash
uv run pytest tests/unit/ -v
```

Expected: all pass (new tests + pre-existing).

- [ ] **Step 6: Run full suite to ensure no regression**

```bash
uv run pytest -q
```

Expected: all green.

- [ ] **Step 7: Commit refactor**

```bash
git add src/lazy_harness/hooks/loader.py tests/unit/test_hook_loader.py
git commit -m "refactor: extract resolve_script_names from resolve_hooks_for_event"
```

---

## Task 7: Test 6 — deploy fresh profile writes all defaults

**Files:**
- Modify: `tests/unit/test_deploy_engine.py`
- (will modify `src/lazy_harness/deploy/engine.py` in next task)

- [ ] **Step 1: Inspect existing engine tests for fixture patterns**

```bash
grep -n "def test_\|deploy_hooks\|tmp_path" tests/unit/test_deploy_engine.py | head -30
```

Identify how a `Config` + temp profile fixture is built today, and reuse the helper.

- [ ] **Step 2: Append the failing test**

```python
def test_deploy_hooks_fresh_profile_writes_all_defaults(tmp_path: Path) -> None:
    profile_dir = tmp_path / "profile"
    cfg = _make_cfg_with_profile(tmp_path, profile_dir, hooks={})  # use existing helper or inline

    deploy_hooks(cfg)

    settings = json.loads((profile_dir / "settings.json").read_text())
    cc_hooks = settings["hooks"]
    # Every default event must appear in the Claude Code event glossary names
    for cc_event in ("SessionStart", "Stop", "SessionEnd", "PreCompact",
                     "PostCompact", "PreToolUse", "PostToolUse"):
        assert cc_event in cc_hooks, f"missing {cc_event} in deployed hooks"
```

If `_make_cfg_with_profile` doesn't exist as a helper, inline-construct using the same shape the other engine tests use.

- [ ] **Step 3: Run test to verify it fails**

```bash
uv run pytest tests/unit/test_deploy_engine.py::test_deploy_hooks_fresh_profile_writes_all_defaults -v
```

Expected: FAIL — current `deploy_hooks` writes nothing (or limited entries) when `cfg.hooks == {}`.

- [ ] **Step 4: Modify deploy_hooks to use merge_with_defaults**

In `src/lazy_harness/deploy/engine.py`, find:

```python
def deploy_hooks(cfg: Config) -> None:
    """Generate agent-native hook config for each profile."""
    from lazy_harness.agents.base import HookEntry
    from lazy_harness.agents.registry import get_agent
    from lazy_harness.hooks.loader import resolve_hooks_for_event

    agent = get_agent(cfg.agent.type)

    hook_entries: dict[str, list[str | HookEntry]] = {}
    for event_name in cfg.hooks:
        hooks = resolve_hooks_for_event(cfg, event_name)
        if hooks:
            entries: list[str | HookEntry] = []
            for hook in hooks:
                command = f"{sys.executable} {hook.path}"
                if hook.matcher is not None:
                    entries.append(HookEntry(command=command, matcher=hook.matcher))
                else:
                    entries.append(command)
            hook_entries[event_name] = entries

    if not hook_entries:
        click.echo("  No hooks to deploy.")
        return

    agent_hooks = agent.generate_hook_config(hook_entries)
```

Replace with:

```python
def deploy_hooks(cfg: Config) -> None:
    """Generate agent-native hook config for each profile."""
    from lazy_harness.agents.base import HookEntry
    from lazy_harness.agents.registry import get_agent
    from lazy_harness.deploy.defaults import merge_with_defaults
    from lazy_harness.hooks.loader import resolve_script_names

    agent = get_agent(cfg.agent.type)

    effective = merge_with_defaults(cfg.hooks)
    hook_entries: dict[str, list[str | HookEntry]] = {}
    for event_name, script_names in effective.items():
        if not script_names:
            continue
        hooks = resolve_script_names(script_names)
        if hooks:
            entries: list[str | HookEntry] = []
            for hook in hooks:
                command = f"{sys.executable} {hook.path}"
                if hook.matcher is not None:
                    entries.append(HookEntry(command=command, matcher=hook.matcher))
                else:
                    entries.append(command)
            hook_entries[event_name] = entries

    if not hook_entries:
        click.echo("  No hooks to deploy.")
        return

    agent_hooks = agent.generate_hook_config(hook_entries)
```

- [ ] **Step 5: Run test to verify it passes**

```bash
uv run pytest tests/unit/test_deploy_engine.py::test_deploy_hooks_fresh_profile_writes_all_defaults -v
```

Expected: PASS.

- [ ] **Step 6: Run full suite to catch regressions**

```bash
uv run pytest -q
```

Expected: all green (some existing tests may break if they relied on `cfg.hooks == {}` producing zero hooks — those need updating).

---

## Task 8: Test 7 — idempotent on clean managed state

**Files:**
- Modify: `tests/unit/test_deploy_engine.py`

- [ ] **Step 1: Append the failing test**

```python
def test_deploy_hooks_idempotent_on_clean_managed_state(tmp_path: Path) -> None:
    profile_dir = tmp_path / "profile"
    cfg = _make_cfg_with_profile(tmp_path, profile_dir, hooks={})

    deploy_hooks(cfg)
    first = (profile_dir / "settings.json").read_text()

    deploy_hooks(cfg)
    second = (profile_dir / "settings.json").read_text()

    assert first == second
    assert not (profile_dir / "settings.json.bak").exists()
```

- [ ] **Step 2: Run test to verify it passes** (current engine should already be idempotent for the framework-managed case)

```bash
uv run pytest tests/unit/test_deploy_engine.py::test_deploy_hooks_idempotent_on_clean_managed_state -v
```

Expected: PASS.

---

## Task 9: Test 8 — backup + warn on unknown manual entries

**Files:**
- Modify: `tests/unit/test_deploy_engine.py`
- Modify: `src/lazy_harness/deploy/engine.py`

- [ ] **Step 1: Append the failing test**

```python
def test_deploy_hooks_backs_up_and_removes_unknown_entries(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    profile_dir = tmp_path / "profile"
    profile_dir.mkdir(parents=True)
    # Seed settings.json with a manual hook entry the framework does not know about
    pre = {
        "hooks": {
            "Stop": [
                {
                    "matcher": "",
                    "hooks": [{"type": "command", "command": "/usr/local/bin/my-manual-hook"}],
                }
            ]
        }
    }
    (profile_dir / "settings.json").write_text(json.dumps(pre, indent=2) + "\n")

    cfg = _make_cfg_with_profile(tmp_path, profile_dir, hooks={})

    deploy_hooks(cfg)

    backup = profile_dir / "settings.json.bak"
    assert backup.is_file(), "expected backup of pre-existing settings.json"
    assert "my-manual-hook" in backup.read_text()

    new = json.loads((profile_dir / "settings.json").read_text())
    # The manual command must no longer be present anywhere in the new hook block
    serialized = json.dumps(new["hooks"])
    assert "my-manual-hook" not in serialized

    out = capsys.readouterr().out
    assert "unknown" in out.lower() or "hand" in out.lower() or "manual" in out.lower()
    assert "my-manual-hook" in out  # the removed command surfaced to the user
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest tests/unit/test_deploy_engine.py::test_deploy_hooks_backs_up_and_removes_unknown_entries -v
```

Expected: FAIL (no backup file is created today).

- [ ] **Step 3: Implement backup-on-unknown in engine.py**

In `src/lazy_harness/deploy/engine.py`, in `deploy_hooks`, find the block:

```python
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

        settings["hooks"] = agent_hooks
        settings_file.write_text(json.dumps(settings, indent=2) + "\n")
        click.echo(f"  ✓ {name}/settings.json (hooks updated)")
```

Replace with:

```python
    for name, entry in cfg.profiles.items.items():
        target_dir = expand_path(entry.config_dir)
        target_dir.mkdir(parents=True, exist_ok=True)
        settings_file = target_dir / "settings.json"

        settings: dict = {}
        existing_raw = ""
        if settings_file.is_file():
            existing_raw = settings_file.read_text()
            try:
                settings = json.loads(existing_raw)
            except json.JSONDecodeError:
                settings = {}

        existing_hooks = settings.get("hooks", {}) if isinstance(settings, dict) else {}
        unknowns = _unknown_hook_commands(existing_hooks, agent_hooks)
        if unknowns:
            backup = settings_file.with_suffix(".json.bak")
            backup.write_text(existing_raw)
            click.echo(
                f"  ⚠  {name}/settings.json had {len(unknowns)} unknown hook "
                f"entries; backup saved to {backup.name}."
            )
            for cmd in unknowns:
                click.echo(f"      removed: {cmd[:80]}")

        settings["hooks"] = agent_hooks
        settings_file.write_text(json.dumps(settings, indent=2) + "\n")
        click.echo(f"  ✓ {name}/settings.json (hooks updated)")
```

And add the helper at module level (above `deploy_hooks`):

```python
def _hook_commands(hook_block: dict) -> set[str]:
    """Collect every command string from a Claude Code hooks block."""
    commands: set[str] = set()
    if not isinstance(hook_block, dict):
        return commands
    for entries in hook_block.values():
        if not isinstance(entries, list):
            continue
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            for h in entry.get("hooks", []):
                if isinstance(h, dict):
                    cmd = h.get("command")
                    if isinstance(cmd, str):
                        commands.add(cmd)
    return commands


def _unknown_hook_commands(existing: dict, new: dict) -> list[str]:
    """Commands present in `existing` but absent from `new`, sorted for stable output."""
    return sorted(_hook_commands(existing) - _hook_commands(new))
```

- [ ] **Step 4: Run test to verify it passes**

```bash
uv run pytest tests/unit/test_deploy_engine.py::test_deploy_hooks_backs_up_and_removes_unknown_entries -v
```

Expected: PASS.

- [ ] **Step 5: Run full suite**

```bash
uv run pytest -q
```

Expected: all green.

---

## Task 10: Test 9 — empty existing hooks block

**Files:**
- Modify: `tests/unit/test_deploy_engine.py`

- [ ] **Step 1: Append the failing test**

```python
def test_deploy_hooks_empty_existing_hooks_block(tmp_path: Path) -> None:
    profile_dir = tmp_path / "profile"
    profile_dir.mkdir(parents=True)
    (profile_dir / "settings.json").write_text(json.dumps({"hooks": {}}, indent=2) + "\n")

    cfg = _make_cfg_with_profile(tmp_path, profile_dir, hooks={})

    deploy_hooks(cfg)

    settings = json.loads((profile_dir / "settings.json").read_text())
    assert "SessionStart" in settings["hooks"]
    assert not (profile_dir / "settings.json.bak").exists()
```

- [ ] **Step 2: Run test to verify it passes**

```bash
uv run pytest tests/unit/test_deploy_engine.py::test_deploy_hooks_empty_existing_hooks_block -v
```

Expected: PASS (no unknowns means no backup).

---

## Task 11: Test 10 — per-event opt-out

**Files:**
- Modify: `tests/unit/test_deploy_engine.py`

- [ ] **Step 1: Append the failing test**

```python
def test_deploy_hooks_honors_per_event_opt_out(tmp_path: Path) -> None:
    profile_dir = tmp_path / "profile"
    cfg = _make_cfg_with_profile(
        tmp_path, profile_dir, hooks={"pre_compact": HookEventConfig(scripts=[])}
    )

    deploy_hooks(cfg)

    settings = json.loads((profile_dir / "settings.json").read_text())
    assert "PreCompact" not in settings["hooks"]
    # Other defaults still present
    assert "SessionStart" in settings["hooks"]
    assert "Stop" in settings["hooks"]
```

- [ ] **Step 2: Run test to verify it passes**

```bash
uv run pytest tests/unit/test_deploy_engine.py::test_deploy_hooks_honors_per_event_opt_out -v
```

Expected: PASS.

---

## Task 12: Test 11 — regression for the 2026-04-17 incident

**Files:**
- Modify: `tests/unit/test_deploy_engine.py`

- [ ] **Step 1: Append the failing test**

```python
def test_deploy_hooks_regression_2026_04_17(tmp_path: Path) -> None:
    """Partial user config (only pre_tool_use + post_tool_use declared) must
    not strip the SessionStart / Stop / SessionEnd / PreCompact / PostCompact
    defaults. Captures the real incident from 2026-04-17."""
    profile_dir = tmp_path / "profile"
    cfg = _make_cfg_with_profile(
        tmp_path,
        profile_dir,
        hooks={
            "pre_tool_use": HookEventConfig(scripts=["pre-tool-use-security"]),
            "post_tool_use": HookEventConfig(scripts=["post-tool-use-format"]),
        },
    )

    deploy_hooks(cfg)

    cc_hooks = json.loads((profile_dir / "settings.json").read_text())["hooks"]
    # Defaults survive
    assert "SessionStart" in cc_hooks
    assert "Stop" in cc_hooks
    assert "SessionEnd" in cc_hooks
    assert "PreCompact" in cc_hooks
    assert "PostCompact" in cc_hooks
    # User overrides honored
    pre_tool_commands = json.dumps(cc_hooks["PreToolUse"])
    assert "pre-tool-use-security" in pre_tool_commands
    assert "pre-tool-use-memory-size" not in pre_tool_commands  # overridden out
```

- [ ] **Step 2: Run test to verify it passes**

```bash
uv run pytest tests/unit/test_deploy_engine.py::test_deploy_hooks_regression_2026_04_17 -v
```

Expected: PASS.

- [ ] **Step 3: Commit engine integration tests + impl**

```bash
git add tests/unit/test_deploy_engine.py src/lazy_harness/deploy/engine.py
git commit -m "feat: merge DEFAULT_HOOKS with cfg.hooks per event in lh deploy"
```

---

## Task 13: ADR-031

**Files:**
- Create: `specs/adrs/031-default-hooks-merge.md`

- [ ] **Step 1: Write the ADR**

Path: `specs/adrs/031-default-hooks-merge.md`. Content:

```markdown
# ADR-031: Default hooks merge layer in `lh deploy`

**Status:** accepted
**Date:** 2026-05-21
**Supersedes:** —
**Superseded by:** —
**Related:** ADR-006 (hooks as subprocess), ADR-009 (profile symlink deploy)

## Context

Through ADR-006 + ADR-009 the framework deploys hooks by translating
`[hooks.<event>]` blocks from `config.toml` into per-profile
`settings.json` entries. The implementation in `deploy/engine.py:79` is
`settings["hooks"] = agent_hooks`, where `agent_hooks` is generated only
from events the user explicitly declared in `config.toml`.

Two operational failures follow from this:

1. A user who adds a partial `[hooks.*]` block to their `config.toml`
   (e.g. just `pre_tool_use` for the security cluster) silently loses
   every previously-deployed hook for the events they did not declare.
   This was the real incident on 2026-04-17: pasting two `[hooks.*]`
   sections wiped `SessionStart` (context-inject), `Stop` (session-export
   + compound-loop), and `PreCompact` (pre-compact) from a profile that
   had been working for months.
2. `lh init` ships `templates/config.toml.default` with zero
   `[hooks.*]` blocks, so a fresh install deploys a profile with no
   hooks at all. The README advertises "session-start context injection,
   pre-compact summaries, session export and compound-loop enforcement"
   as out-of-the-box behavior, but none of that fires until the user
   copies hook declarations from the docs by hand.

The framework conflated "user override" with "complete set". They are
not the same thing.

## Decision

The framework owns a Python-literal `DEFAULT_HOOKS` map in
`src/lazy_harness/deploy/defaults.py`. `lh deploy` computes the
effective per-event script list as

    effective[event] =
        user_hooks[event].scripts if event in user_hooks
        else DEFAULT_HOOKS[event]

User declarations override per-event (`scripts = []` is an explicit
opt-out for that event). Events present in `user_hooks` but absent from
`DEFAULT_HOOKS` (custom events) pass through verbatim. The `settings.json`
`hooks` block is wholly framework-owned: on every deploy, the engine
diffs the existing block against the new effective block and, when it
finds command strings that no longer appear, writes
`settings.json.bak` and logs a warning naming the removed commands. No
chain of backups is kept — the user is expected to version-control
`~/.config/lazy-harness/` if they want a longer history.

## Alternatives considered

- **Keep `cfg.hooks` as the complete set, document harder.** Rejected.
  The README and the docs site already document the built-ins as
  out-of-the-box; aligning behavior with documentation is cheaper than
  rewriting both. The 2026-04-17 incident also shows that "remember to
  declare every hook you want" is a tripwire, not a feature.
- **Preserve unknown entries in `settings.json`.** Rejected. Breaks the
  idempotency contract — the output of `lh deploy` would depend on
  whatever happened to be in `settings.json` previously, including drift
  from prior framework versions. The backup + warning gives users the
  data they need without compromising idempotency.
- **Per-script override granularity (`scripts_disabled = [...]`).**
  Rejected. The smallest stable override unit is one event. Per-script
  disables would force the framework to version the default *set* so a
  rename or replacement could be expressed; one event keeps the API
  surface flat. Users who want fine control re-list the event with the
  subset they want.
- **TOML-embedded default set in the package.** Rejected. Adds parsing
  cost on every deploy, requires a new resource-loading step, and gains
  nothing over a Python literal for a list this small. A future
  `lh config show-defaults` command can print the dict in TOML form
  without changing the source-of-truth representation.

## Consequences

- Fresh installs deploy the built-in hooks automatically. The README's
  out-of-the-box promise is now true.
- The 2026-04-17 failure mode is gone: a partial `[hooks.*]` config can
  no longer strip undeclared events.
- Users who want to suppress a built-in must opt-out per-event with
  `scripts = []` or override the event explicitly. There is no
  per-script disable.
- When a future release adds a new entry to `DEFAULT_HOOKS[event]`,
  users who did not declare that event get it automatically on the next
  `lh deploy`. Users who did declare the event keep their list
  unchanged.
- Hand-edits to the `hooks` block in `settings.json` no longer survive a
  deploy. They surface as a one-line warning per command with a backup
  for forensic recovery, but the canonical path is to declare the hook
  through `config.toml` or `~/.config/lazy-harness/hooks/`.

## Implementation

Tracked in `specs/plans/2026-05-21-deploy-hook-defaults-plan.md` and
delivered in the same PR as this ADR.
```

- [ ] **Step 2: No standalone commit yet** — ADR ships with the rest in the final commit batch.

---

## Task 14: Docs — new "Default hooks" section in `docs/how/hooks.md`

**Files:**
- Modify: `docs/how/hooks.md`
- Modify: `templates/config.toml.default`

- [ ] **Step 1: Add Default hooks section to hooks.md**

In `docs/how/hooks.md`, immediately after the existing "Event glossary" table (before "The built-ins" header), insert:

```markdown
## Default hooks

`lh deploy` ships with an opinionated default set ([ADR-031](https://github.com/lazynet/lazy-harness/blob/main/specs/adrs/031-default-hooks-merge.md)): a fresh profile gets the framework's built-in hooks wired into `settings.json` automatically. You do **not** need to declare them in `config.toml` for them to fire.

| Event | Default built-ins |
|---|---|
| `session_start` | `context-inject` |
| `session_stop` | `session-export`, `compound-loop`, `engram-persist` |
| `session_end` | `session-end` |
| `pre_compact` | `pre-compact` |
| `post_compact` | `post-compact` |
| `pre_tool_use` | `pre-tool-use-security`, `pre-tool-use-memory-size` |
| `post_tool_use` | `post-tool-use-format`, `post-tool-use-sync-claude` |

**Overriding.** Declaring `[hooks.<event>]` with `scripts = [...]` in `config.toml` replaces the default for that event. The smallest override unit is one event — there is no per-script disable. To opt out of a single event entirely, declare it with `scripts = []`.

**Backups when manual entries are removed.** `settings.json["hooks"]` is wholly framework-owned. If `lh deploy` finds a hook command in the existing block that does not appear in the effective set (typically a hand-edit), it writes `settings.json.bak` next to `settings.json` and prints a one-line warning listing the removed command. No chain of backups is kept; version-control your `~/.config/lazy-harness/` if you want a longer history.

The literal default set lives in `src/lazy_harness/deploy/defaults.py`.
```

- [ ] **Step 2: Add a comment block to templates/config.toml.default**

Insert at the top of `templates/config.toml.default`, after the existing top comments:

```toml
# Hook configuration is OPTIONAL. lh deploy applies a framework-provided
# default set (context-inject on SessionStart, compound-loop on Stop, the
# PreToolUse security cluster, etc.). To override a single event, declare
# [hooks.<event>] with scripts = [...]. To opt out of an event entirely,
# declare it with scripts = []. See docs/how/hooks.md#default-hooks for the
# full default list and ADR-031 for the rationale.
```

- [ ] **Step 3: Run mkdocs strict to catch link/anchor breakage**

```bash
uv run --group docs mkdocs build --strict
```

Expected: no warnings, build succeeds.

---

## Task 15: Backlog update

**Files:**
- Modify: `specs/backlog.md`

- [ ] **Step 1: Move the item from MEDIA to Done**

In `specs/backlog.md`, find the `## Open — Prioridad MEDIA` block titled `### \`lh deploy\` — merge hook defaults instead of total overwrite`.

Cut it from there and add a new bullet at the bottom of `## Done`:

```markdown
- [x] **`lh deploy` default hooks merge** — DEFAULT_HOOKS literal in `deploy/defaults.py` + `merge_with_defaults` pure function; per-event override via config.toml (scripts = [] opts out); framework-owned settings.json[hooks] with backup + warning when manual entries are clobbered (ADR-031, 11 tests TDD). Closes the 2026-04-17 partial-config drift and makes built-ins out-of-the-box.
```

Leave the rest of MEDIA untouched. Note: the section header `## Open — Prioridad MEDIA` stays — there are other items below this one.

---

## Task 16: Pre-commit gate

**Files:** none (verification only)

- [ ] **Step 1: pytest**

```bash
uv run pytest -q
```

Expected: 780+ passing, zero failing.

- [ ] **Step 2: ruff**

```bash
uv run ruff check src tests
```

Expected: `All checks passed!`.

- [ ] **Step 3: mkdocs strict**

```bash
uv run --group docs mkdocs build --strict
```

Expected: build succeeds, no warnings about broken anchors.

---

## Task 17: Final commit and PR

**Files:** all staged changes from Tasks 13–15.

- [ ] **Step 1: Stage and commit remaining changes**

```bash
git add specs/adrs/031-default-hooks-merge.md \
        docs/how/hooks.md \
        templates/config.toml.default \
        specs/backlog.md
git commit -m "docs: ADR-031 and how-page section for default hooks"
```

- [ ] **Step 2: Push branch**

Switch to the `lazynet` gh account first, then push.

```bash
gh auth switch -u lazynet
git push -u origin feat/deploy-hook-defaults
```

- [ ] **Step 3: Open PR**

```bash
gh pr create --title "feat: default hooks merge layer in lh deploy" --body "$(cat <<'EOF'
## Summary

Implements [specs/designs/2026-05-21-deploy-hook-defaults-design.md](https://github.com/lazynet/lazy-harness/blob/main/specs/designs/2026-05-21-deploy-hook-defaults-design.md) and closes the Open Prioridad MEDIA item in \`specs/backlog.md\` (\`lh deploy\` — merge hook defaults instead of total overwrite).

Two failure modes fixed:

1. **Drift on partial config.** Adding \`[hooks.pre_tool_use]\` to a config.toml that did not previously declare hooks no longer wipes \`SessionStart\`, \`Stop\`, \`PreCompact\`, etc. from the deployed settings.json. Each event is now overridden independently.
2. **No batteries-included default.** A fresh \`lh init\` now deploys the framework's built-in hooks (context-inject, compound-loop, security cluster, etc.) automatically. The README's out-of-the-box promise is now backed by the deploy behavior.

## What changed

- \`src/lazy_harness/deploy/defaults.py\` (new) — \`DEFAULT_HOOKS\` literal + \`merge_with_defaults\` pure function.
- \`src/lazy_harness/hooks/loader.py\` — \`resolve_script_names\` extracted; \`resolve_hooks_for_event\` becomes a wrapper.
- \`src/lazy_harness/deploy/engine.py\` — calls \`merge_with_defaults\`, writes \`settings.json.bak\` + warning when pre-existing hand-edited commands are clobbered.
- \`specs/adrs/031-default-hooks-merge.md\` (new) — ADR.
- \`docs/how/hooks.md\` — new "Default hooks" section after the event glossary.
- \`templates/config.toml.default\` — comment block pointing users at the defaults + override semantics.
- \`specs/backlog.md\` — item moved to Done.

## Test plan

- [x] \`uv run pytest\` — all green (11 new tests).
- [x] \`uv run ruff check src tests\` — clean.
- [x] \`uv run --group docs mkdocs build --strict\` — clean.
- [x] Regression test for the 2026-04-17 incident is the last test in test_engine.py.
EOF
)"
```

- [ ] **Step 4: Switch gh back to mvago-flx**

```bash
gh auth switch -u mvago-flx
```

---

## Task 18: Merge and cleanup

**Files:** none (operational).

- [ ] **Step 1: Verify PR is mergeable**

```bash
gh auth switch -u lazynet
gh pr view <PR-number> --json state,mergeable,mergeStateStatus
```

Expected: \`mergeable: MERGEABLE\`, \`mergeStateStatus: CLEAN\`.

- [ ] **Step 2: Squash merge via admin API**

```bash
gh pr merge <PR-number> --squash --admin
```

- [ ] **Step 3: Sync local main**

```bash
git -C /Users/lazynet/repos/lazy/lazy-harness fetch origin
git -C /Users/lazynet/repos/lazy/lazy-harness pull --ff-only origin main
```

- [ ] **Step 4: Cleanup worktree (squash-merge bypass)**

```bash
git -C /Users/lazynet/repos/lazy/lazy-harness worktree remove --force .worktrees/deploy-hook-defaults
git -C /Users/lazynet/repos/lazy/lazy-harness branch -D feat/deploy-hook-defaults
```

- [ ] **Step 5: Switch gh back**

```bash
gh auth switch -u mvago-flx
```

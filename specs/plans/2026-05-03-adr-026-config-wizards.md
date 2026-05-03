# ADR-026 — `lh config <feature> --init` Wizards (Fase 3b) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Strict TDD per repo non-negotiable #2.

**Goal:** Implement the `lh config <feature> --init` wizards per ADR-018 for the `memory` and `knowledge` features. Each wizard interactively probes detection, confirms opt-in, previews the TOML block it will write, and merges into the active profile's `config.toml`. Closes the ADR-018 implementation cycle (flips status from `accepted-deferred` to `accepted`).

**Architecture:** New `lh config` Click command group (`cli/config_cmd.py`) with two subcommands: `knowledge` and `memory`. Each subcommand takes a `--init` flag and delegates to a wizard function in a separate package (`wizards/`). Wizard functions receive the config path + an injected prompt/confirm/echo trio, so they're testable without mocking Click's runtime. A shared `wizards/_toml_merge.py` deep-merges new blocks into existing `config.toml` atomically.

**Tech Stack:** Python 3.11, pytest, ruff, MkDocs Material, `click.prompt` / `click.confirm`, `tomllib` + `tomli_w`. Runs in worktree `.worktrees/config-wizards` on branch `feat/config-wizards`.

**Out of scope:** `lh config <feature> --show` and `lh config <feature> --reset` (per ADR-018, "implementation details of the future slice"). Upgrade notice (ADR-018 #3) — separate ADR if/when wanted. The wizard does NOT auto-install missing tools; it prints the install command and lets the user proceed or abort.

---

## File Structure

| Path | Status | Responsibility |
|------|--------|----------------|
| `src/lazy_harness/wizards/__init__.py` | create | Package marker |
| `src/lazy_harness/wizards/_toml_merge.py` | create | Atomic deep-merge helper |
| `src/lazy_harness/wizards/memory.py` | create | Engram wizard (pure logic, IO injected) |
| `src/lazy_harness/wizards/knowledge.py` | create | Graphify wizard (pure logic, IO injected) |
| `src/lazy_harness/cli/config_cmd.py` | create | Click `lh config` group + `knowledge`/`memory` subcommands |
| `src/lazy_harness/cli/main.py` | modify | Register `lh config` group |
| `tests/unit/wizards/__init__.py` | create | Test package marker |
| `tests/unit/wizards/test_toml_merge.py` | create | Tests for the merge helper |
| `tests/unit/wizards/test_memory.py` | create | Tests for Engram wizard |
| `tests/unit/wizards/test_knowledge.py` | create | Tests for Graphify wizard |
| `tests/unit/cli/test_config_cmd.py` | create | CLI integration tests for `lh config` group |
| `specs/adrs/026-config-wizards.md` | create | ADR for the wizard implementation |
| `specs/adrs/018-config-discoverability.md` | modify | Flip status `accepted-deferred` → `accepted` + implementation note |
| `specs/adrs/README.md` | modify | Update 018 status, add 026 row |

---

## Wizard IO injection pattern

Each wizard function takes its IO callables as keyword args with sensible defaults. This makes them testable without monkeypatching Click globally.

```python
def wizard_memory(
    config_path: Path,
    *,
    prompt_confirm: Callable[[str, bool], bool] = click.confirm,
    echo: Callable[[str], None] = click.echo,
) -> bool:
    ...
```

Tests pass stub `prompt_confirm` (returns predetermined sequence) and capturing `echo`. The CLI subcommand passes the real Click functions.

---

## Task 1: TOML deep-merge helper

**Files:**
- Create: `src/lazy_harness/wizards/__init__.py`
- Create: `src/lazy_harness/wizards/_toml_merge.py`
- Create: `tests/unit/wizards/__init__.py`
- Create: `tests/unit/wizards/test_toml_merge.py`

- [ ] **Step 1.1: Create the empty package markers**

```python
# src/lazy_harness/wizards/__init__.py
"""Interactive wizards for `lh config <feature> --init`."""
```

```python
# tests/unit/wizards/__init__.py
```

- [ ] **Step 1.2: Write the first failing test (merge into empty file)**

Create `tests/unit/wizards/test_toml_merge.py`:

```python
"""Tests for the wizards._toml_merge helper."""

from __future__ import annotations

from pathlib import Path


def test_merge_into_missing_file_creates_it(tmp_path: Path) -> None:
    from lazy_harness.wizards._toml_merge import merge_into_config

    cfg_path = tmp_path / "config.toml"
    merge_into_config(cfg_path, {"memory": {"engram": {"enabled": True}}})

    content = cfg_path.read_text()
    assert "[memory.engram]" in content
    assert "enabled = true" in content
```

- [ ] **Step 1.3: Run, expect failure**

```bash
uv run pytest tests/unit/wizards/test_toml_merge.py -v
```

Expected: `ModuleNotFoundError: No module named 'lazy_harness.wizards._toml_merge'`

- [ ] **Step 1.4: Implement the helper**

Create `src/lazy_harness/wizards/_toml_merge.py`:

```python
"""Atomic deep-merge of a TOML block into an existing config.toml."""

from __future__ import annotations

import os
import tempfile
import tomllib
from pathlib import Path
from typing import Any

import tomli_w


def _deep_merge(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    """Recursively merge `overlay` into a copy of `base`. Overlay wins on leaves."""
    result = dict(base)
    for key, value in overlay.items():
        if (
            key in result
            and isinstance(result[key], dict)
            and isinstance(value, dict)
        ):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def merge_into_config(config_path: Path, new_block: dict[str, Any]) -> None:
    """Read `config_path` (TOML), deep-merge `new_block` into it, write atomically."""
    if config_path.is_file():
        existing = tomllib.loads(config_path.read_text())
    else:
        existing = {}

    merged = _deep_merge(existing, new_block)
    serialized = tomli_w.dumps(merged)

    config_path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=config_path.parent, prefix=config_path.name + ".")
    try:
        os.write(fd, serialized.encode())
        os.close(fd)
        os.replace(tmp, config_path)
    except Exception:
        os.unlink(tmp)
        raise
```

- [ ] **Step 1.5: Run, expect pass**

```bash
uv run pytest tests/unit/wizards/test_toml_merge.py -v
```

Expected: PASS.

- [ ] **Step 1.6: Add tests for merge into existing file (preserves other sections)**

Append to `tests/unit/wizards/test_toml_merge.py`:

```python
def test_merge_preserves_existing_sections(tmp_path: Path) -> None:
    from lazy_harness.wizards._toml_merge import merge_into_config

    cfg_path = tmp_path / "config.toml"
    cfg_path.write_text(
        '[harness]\nversion = "1"\n\n[agent]\ntype = "claude-code"\n'
    )

    merge_into_config(cfg_path, {"memory": {"engram": {"enabled": True}}})

    import tomllib
    parsed = tomllib.loads(cfg_path.read_text())
    assert parsed["harness"]["version"] == "1"
    assert parsed["agent"]["type"] == "claude-code"
    assert parsed["memory"]["engram"]["enabled"] is True


def test_merge_overlays_existing_keys(tmp_path: Path) -> None:
    from lazy_harness.wizards._toml_merge import merge_into_config

    cfg_path = tmp_path / "config.toml"
    cfg_path.write_text(
        '[memory.engram]\nenabled = false\ngit_sync = true\n'
    )

    merge_into_config(cfg_path, {"memory": {"engram": {"enabled": True}}})

    import tomllib
    parsed = tomllib.loads(cfg_path.read_text())
    assert parsed["memory"]["engram"]["enabled"] is True
    assert parsed["memory"]["engram"]["git_sync"] is True  # preserved
```

- [ ] **Step 1.7: Run, expect pass**

```bash
uv run pytest tests/unit/wizards/test_toml_merge.py -v
```

Expected: 3 tests pass.

- [ ] **Step 1.8: Ruff + commit**

```bash
uv run ruff check src/lazy_harness/wizards/ tests/unit/wizards/test_toml_merge.py --fix
uv run ruff check src/lazy_harness/wizards/ tests/unit/wizards/test_toml_merge.py
git add src/lazy_harness/wizards/__init__.py src/lazy_harness/wizards/_toml_merge.py tests/unit/wizards/__init__.py tests/unit/wizards/test_toml_merge.py
git commit -m "feat: add atomic toml deep-merge helper for wizards"
```

---

## Task 2: Memory wizard (Engram)

**Files:**
- Create: `src/lazy_harness/wizards/memory.py`
- Create: `tests/unit/wizards/test_memory.py`

- [ ] **Step 2.1: Write the failing test for the happy path (Engram installed, user accepts all defaults)**

Create `tests/unit/wizards/test_memory.py`:

```python
"""Tests for the lh config memory --init wizard."""

from __future__ import annotations

from pathlib import Path

import pytest


def _scripted_confirm(answers: list[bool]):
    """Returns a click.confirm-compatible callable that pops answers in order."""
    iterator = iter(answers)

    def _confirm(prompt: str, default: bool = False) -> bool:
        try:
            return next(iterator)
        except StopIteration:
            return default

    return _confirm


def test_memory_wizard_writes_block_when_engram_installed_and_user_confirms(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from lazy_harness.memory import engram as engram_mod
    from lazy_harness.wizards.memory import wizard_memory

    monkeypatch.setattr(engram_mod, "is_engram_available", lambda: True)
    cfg_path = tmp_path / "config.toml"
    output: list[str] = []

    # Confirms in order: enable=true, git_sync=true, cloud=false, write=true
    confirm = _scripted_confirm([True, True, False, True])

    wrote = wizard_memory(
        cfg_path,
        prompt_confirm=confirm,
        echo=output.append,
    )

    assert wrote is True
    assert cfg_path.is_file()
    content = cfg_path.read_text()
    assert "[memory.engram]" in content
    assert "enabled = true" in content
    assert "git_sync = true" in content
    assert "cloud = false" in content
```

- [ ] **Step 2.2: Run, expect failure**

```bash
uv run pytest tests/unit/wizards/test_memory.py -v
```

Expected: `ModuleNotFoundError`.

- [ ] **Step 2.3: Implement the wizard**

Create `src/lazy_harness/wizards/memory.py`:

```python
"""Interactive wizard for [memory.engram] (lh config memory --init)."""

from __future__ import annotations

from pathlib import Path
from typing import Callable

import click
import tomli_w

from lazy_harness.memory import engram
from lazy_harness.wizards._toml_merge import merge_into_config


def wizard_memory(
    config_path: Path,
    *,
    prompt_confirm: Callable[[str, bool], bool] = click.confirm,
    echo: Callable[[str], None] = click.echo,
) -> bool:
    """Run the [memory.engram] wizard. Returns True if config was written."""
    echo("Engram — episodic memory backend (per-project agent diary).")
    echo("")

    installed = engram.is_engram_available()
    if not installed:
        echo("⚠ Engram is not installed.")
        echo("  Install with your package manager (e.g. `brew install engram`).")
        echo(f"  Pinned version: {engram.PINNED_VERSION}")
        echo("")
        if not prompt_confirm(
            "Continue setup anyway (settings activate when Engram is installed)?",
            False,
        ):
            echo("Cancelled.")
            return False
        echo("")

    enabled = prompt_confirm("Enable Engram MCP server in profiles?", True)
    git_sync = (
        prompt_confirm(
            "Use git sync for memory chunks (.engram/chunks/ committed per repo)?",
            True,
        )
        if enabled
        else False
    )
    cloud = (
        prompt_confirm(
            "Enable Engram cloud sync (opt-in, breaks local-first guarantee)?",
            False,
        )
        if enabled
        else False
    )

    new_block = {
        "memory": {
            "engram": {
                "enabled": enabled,
                "git_sync": git_sync,
                "cloud": cloud,
                "version": engram.PINNED_VERSION,
            }
        }
    }

    echo("")
    echo(f"Will write to {config_path}:")
    echo("")
    echo(tomli_w.dumps(new_block))

    if not prompt_confirm("Write this block to your config?", True):
        echo("Cancelled.")
        return False

    merge_into_config(config_path, new_block)
    echo(f"✓ Updated {config_path}")
    return True
```

- [ ] **Step 2.4: Run, expect pass**

```bash
uv run pytest tests/unit/wizards/test_memory.py -v
```

Expected: PASS.

- [ ] **Step 2.5: Add tests for the cancellation paths**

Append to `tests/unit/wizards/test_memory.py`:

```python
def test_memory_wizard_cancels_when_user_declines_final_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from lazy_harness.memory import engram as engram_mod
    from lazy_harness.wizards.memory import wizard_memory

    monkeypatch.setattr(engram_mod, "is_engram_available", lambda: True)
    cfg_path = tmp_path / "config.toml"

    # enable=true, git_sync=true, cloud=false, write=false
    confirm = _scripted_confirm([True, True, False, False])

    wrote = wizard_memory(cfg_path, prompt_confirm=confirm, echo=lambda _m: None)

    assert wrote is False
    assert not cfg_path.is_file()


def test_memory_wizard_cancels_when_user_aborts_at_install_warning(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from lazy_harness.memory import engram as engram_mod
    from lazy_harness.wizards.memory import wizard_memory

    monkeypatch.setattr(engram_mod, "is_engram_available", lambda: False)
    cfg_path = tmp_path / "config.toml"

    # First (and only) prompt: "continue anyway?" → false
    confirm = _scripted_confirm([False])

    wrote = wizard_memory(cfg_path, prompt_confirm=confirm, echo=lambda _m: None)

    assert wrote is False
    assert not cfg_path.is_file()


def test_memory_wizard_when_engram_missing_prints_install_hint(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from lazy_harness.memory import engram as engram_mod
    from lazy_harness.wizards.memory import wizard_memory

    monkeypatch.setattr(engram_mod, "is_engram_available", lambda: False)
    cfg_path = tmp_path / "config.toml"
    output: list[str] = []
    confirm = _scripted_confirm([False])

    wizard_memory(cfg_path, prompt_confirm=confirm, echo=output.append)

    joined = "\n".join(output)
    assert "Engram is not installed" in joined
    assert "brew install engram" in joined
    assert "1.15.4" in joined  # pinned version surfaced
```

- [ ] **Step 2.6: Run all memory wizard tests, expect pass**

```bash
uv run pytest tests/unit/wizards/test_memory.py -v
```

Expected: 4 tests pass.

- [ ] **Step 2.7: Ruff + commit**

```bash
uv run ruff check src/lazy_harness/wizards/memory.py tests/unit/wizards/test_memory.py --fix
uv run ruff check src/lazy_harness/wizards/memory.py tests/unit/wizards/test_memory.py
git add src/lazy_harness/wizards/memory.py tests/unit/wizards/test_memory.py
git commit -m "feat: add lh config memory wizard for engram"
```

---

## Task 3: Knowledge wizard (Graphify)

**Files:**
- Create: `src/lazy_harness/wizards/knowledge.py`
- Create: `tests/unit/wizards/test_knowledge.py`

- [ ] **Step 3.1: Write the failing test for happy path**

Create `tests/unit/wizards/test_knowledge.py`:

```python
"""Tests for the lh config knowledge --init wizard."""

from __future__ import annotations

from pathlib import Path

import pytest


def _scripted_confirm(answers: list[bool]):
    iterator = iter(answers)

    def _confirm(prompt: str, default: bool = False) -> bool:
        try:
            return next(iterator)
        except StopIteration:
            return default

    return _confirm


def test_knowledge_wizard_writes_structure_block_when_graphify_installed_and_user_confirms(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from lazy_harness.knowledge import graphify as graphify_mod
    from lazy_harness.wizards.knowledge import wizard_knowledge

    monkeypatch.setattr(graphify_mod, "is_graphify_available", lambda: True)
    cfg_path = tmp_path / "config.toml"
    output: list[str] = []

    # Confirms: enable_structure=true, auto_rebuild=false, write=true
    confirm = _scripted_confirm([True, False, True])

    wrote = wizard_knowledge(
        cfg_path,
        prompt_confirm=confirm,
        echo=output.append,
    )

    assert wrote is True
    content = cfg_path.read_text()
    assert "[knowledge.structure]" in content
    assert "enabled = true" in content
    assert "auto_rebuild_on_commit = false" in content
```

- [ ] **Step 3.2: Run, expect failure**

```bash
uv run pytest tests/unit/wizards/test_knowledge.py -v
```

Expected: `ModuleNotFoundError`.

- [ ] **Step 3.3: Implement the wizard**

Create `src/lazy_harness/wizards/knowledge.py`:

```python
"""Interactive wizard for [knowledge.structure] (lh config knowledge --init)."""

from __future__ import annotations

from pathlib import Path
from typing import Callable

import click
import tomli_w

from lazy_harness.knowledge import graphify
from lazy_harness.wizards._toml_merge import merge_into_config


def wizard_knowledge(
    config_path: Path,
    *,
    prompt_confirm: Callable[[str, bool], bool] = click.confirm,
    echo: Callable[[str], None] = click.echo,
) -> bool:
    """Run the [knowledge.structure] wizard for Graphify. Returns True if written."""
    echo("Graphify — code structure index (tree-sitter knowledge graph).")
    echo("")

    installed = graphify.is_graphify_available()
    if not installed:
        echo("⚠ Graphify is not installed.")
        echo("  Install with `pip install graphify` or your preferred package manager.")
        echo(f"  Pinned version: {graphify.PINNED_VERSION}")
        echo("")
        if not prompt_confirm(
            "Continue setup anyway (settings activate when Graphify is installed)?",
            False,
        ):
            echo("Cancelled.")
            return False
        echo("")

    enabled = prompt_confirm(
        "Enable Graphify MCP server in profiles?", True
    )
    auto_rebuild = (
        prompt_confirm(
            "Auto-rebuild graph on each git commit (post-commit hook)?",
            False,
        )
        if enabled
        else False
    )

    new_block = {
        "knowledge": {
            "structure": {
                "engine": "graphify",
                "enabled": enabled,
                "auto_rebuild_on_commit": auto_rebuild,
                "version": graphify.PINNED_VERSION,
            }
        }
    }

    echo("")
    echo(f"Will write to {config_path}:")
    echo("")
    echo(tomli_w.dumps(new_block))

    if not prompt_confirm("Write this block to your config?", True):
        echo("Cancelled.")
        return False

    merge_into_config(config_path, new_block)
    echo(f"✓ Updated {config_path}")
    return True
```

- [ ] **Step 3.4: Run, expect pass**

```bash
uv run pytest tests/unit/wizards/test_knowledge.py -v
```

Expected: PASS.

- [ ] **Step 3.5: Add the cancellation/install-missing tests**

Append to `tests/unit/wizards/test_knowledge.py`:

```python
def test_knowledge_wizard_cancels_when_user_declines_final_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from lazy_harness.knowledge import graphify as graphify_mod
    from lazy_harness.wizards.knowledge import wizard_knowledge

    monkeypatch.setattr(graphify_mod, "is_graphify_available", lambda: True)
    cfg_path = tmp_path / "config.toml"

    confirm = _scripted_confirm([True, False, False])  # enable, auto_rebuild, write

    wrote = wizard_knowledge(cfg_path, prompt_confirm=confirm, echo=lambda _m: None)

    assert wrote is False
    assert not cfg_path.is_file()


def test_knowledge_wizard_when_graphify_missing_prints_install_hint(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from lazy_harness.knowledge import graphify as graphify_mod
    from lazy_harness.wizards.knowledge import wizard_knowledge

    monkeypatch.setattr(graphify_mod, "is_graphify_available", lambda: False)
    cfg_path = tmp_path / "config.toml"
    output: list[str] = []
    confirm = _scripted_confirm([False])  # decline at install warning

    wizard_knowledge(cfg_path, prompt_confirm=confirm, echo=output.append)

    joined = "\n".join(output)
    assert "Graphify is not installed" in joined
    assert "pip install graphify" in joined
    assert "0.6.9" in joined
```

- [ ] **Step 3.6: Run all knowledge wizard tests, expect pass**

```bash
uv run pytest tests/unit/wizards/test_knowledge.py -v
```

Expected: 3 tests pass.

- [ ] **Step 3.7: Ruff + commit**

```bash
uv run ruff check src/lazy_harness/wizards/knowledge.py tests/unit/wizards/test_knowledge.py --fix
uv run ruff check src/lazy_harness/wizards/knowledge.py tests/unit/wizards/test_knowledge.py
git add src/lazy_harness/wizards/knowledge.py tests/unit/wizards/test_knowledge.py
git commit -m "feat: add lh config knowledge wizard for graphify"
```

---

## Task 4: `lh config` Click command group

**Files:**
- Create: `src/lazy_harness/cli/config_cmd.py`
- Create: `tests/unit/cli/test_config_cmd.py`
- Modify: `src/lazy_harness/cli/main.py`

- [ ] **Step 4.1: Write failing tests for the CLI surface**

Create `tests/unit/cli/test_config_cmd.py`:

```python
"""Tests for the lh config CLI command group."""

from __future__ import annotations

from pathlib import Path

import pytest
from click.testing import CliRunner


def test_config_memory_init_invokes_wizard(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from lazy_harness.cli import config_cmd

    cfg_path = tmp_path / "config.toml"
    monkeypatch.setattr(config_cmd, "config_file", lambda: cfg_path)

    called: dict[str, Path] = {}

    def fake_wizard(path, **kwargs):
        called["path"] = path
        return True

    monkeypatch.setattr(config_cmd, "wizard_memory", fake_wizard)

    runner = CliRunner()
    result = runner.invoke(config_cmd.config, ["memory", "--init"])

    assert result.exit_code == 0
    assert called["path"] == cfg_path


def test_config_knowledge_init_invokes_wizard(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from lazy_harness.cli import config_cmd

    cfg_path = tmp_path / "config.toml"
    monkeypatch.setattr(config_cmd, "config_file", lambda: cfg_path)

    called: dict[str, Path] = {}

    def fake_wizard(path, **kwargs):
        called["path"] = path
        return True

    monkeypatch.setattr(config_cmd, "wizard_knowledge", fake_wizard)

    runner = CliRunner()
    result = runner.invoke(config_cmd.config, ["knowledge", "--init"])

    assert result.exit_code == 0
    assert called["path"] == cfg_path


def test_config_memory_without_init_prints_usage(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from lazy_harness.cli import config_cmd

    monkeypatch.setattr(config_cmd, "config_file", lambda: tmp_path / "config.toml")

    runner = CliRunner()
    result = runner.invoke(config_cmd.config, ["memory"])

    assert result.exit_code == 0
    assert "--init" in result.output
```

- [ ] **Step 4.2: Run, expect failure**

```bash
uv run pytest tests/unit/cli/test_config_cmd.py -v
```

Expected: `ModuleNotFoundError`.

- [ ] **Step 4.3: Implement the CLI group**

Create `src/lazy_harness/cli/config_cmd.py`:

```python
"""lh config — interactive wizards for optional features (per ADR-018, ADR-026)."""

from __future__ import annotations

import click

from lazy_harness.core.paths import config_file
from lazy_harness.wizards.knowledge import wizard_knowledge
from lazy_harness.wizards.memory import wizard_memory


@click.group("config")
def config() -> None:
    """Configure optional features interactively."""


@config.command("memory")
@click.option("--init", is_flag=True, help="Run the interactive [memory] wizard.")
def memory_cmd(init: bool) -> None:
    """Configure episodic memory backends ([memory] section)."""
    if not init:
        click.echo("Usage: lh config memory --init")
        return
    wizard_memory(config_file())


@config.command("knowledge")
@click.option("--init", is_flag=True, help="Run the interactive [knowledge] wizard.")
def knowledge_cmd(init: bool) -> None:
    """Configure knowledge backends ([knowledge] section)."""
    if not init:
        click.echo("Usage: lh config knowledge --init")
        return
    wizard_knowledge(config_file())
```

- [ ] **Step 4.4: Register the group in main**

In `src/lazy_harness/cli/main.py`, append next to the other `cli.add_command` calls (e.g. after `metrics`):

```python
    from lazy_harness.cli.config_cmd import config

    cli.add_command(config, "config")
```

- [ ] **Step 4.5: Run all CLI tests, expect pass**

```bash
uv run pytest tests/unit/cli/test_config_cmd.py -v
```

Expected: 3 tests pass.

- [ ] **Step 4.6: Run the full CLI suite for regressions**

```bash
uv run pytest tests/unit/cli/ -v
```

Expected: all CLI tests pass.

- [ ] **Step 4.7: Ruff + commit**

```bash
uv run ruff check src/lazy_harness/cli/config_cmd.py src/lazy_harness/cli/main.py tests/unit/cli/test_config_cmd.py --fix
uv run ruff check src/lazy_harness/cli/config_cmd.py src/lazy_harness/cli/main.py tests/unit/cli/test_config_cmd.py
git add src/lazy_harness/cli/config_cmd.py src/lazy_harness/cli/main.py tests/unit/cli/test_config_cmd.py
git commit -m "feat: add lh config command group for interactive wizards"
```

---

## Task 5: ADR-026 + flip ADR-018 + index update

**Files:**
- Create: `specs/adrs/026-config-wizards.md`
- Modify: `specs/adrs/018-config-discoverability.md`
- Modify: `specs/adrs/README.md`

- [ ] **Step 5.1: Write ADR-026**

Create `specs/adrs/026-config-wizards.md`:

```markdown
# ADR-026: `lh config <feature> --init` wizards (Fase 3b)

**Status:** accepted
**Date:** 2026-05-03

## Context

ADR-018 specified two surfaces: `lh doctor` for discoverability (implemented in ADR-025) and `lh config <feature> --init` for interactive opt-in (deferred). With the triple stack (QMD/Engram/Graphify) wired through ADR-024 and surfaced via ADR-025, the remaining piece is the wizard surface that lets a user enable a feature without hand-editing TOML.

## Decision

**Add a `lh config` Click command group with two subcommands today: `memory` and `knowledge`. Each subcommand takes a `--init` flag and delegates to a wizard function in a separate `wizards/` package. Wizards inject their IO callables (`prompt_confirm`, `echo`) so they are testable without monkeypatching Click globally.**

The wizards always:
1. Probe whether the underlying tool is installed (`is_<tool>_available`); if not, print the install hint with the pinned version and ask for confirmation to continue setup anyway.
2. Walk the user through the relevant options with `click.confirm` defaults that match the safest path (cloud sync defaults to `false`, auto-rebuild defaults to `false`).
3. Print the proposed TOML block before writing.
4. Ask for explicit confirmation before merging into `config.toml`.
5. Use the shared `wizards/_toml_merge.py` helper to do an atomic deep-merge that preserves all other sections.

ADR-018 is flipped from `accepted-deferred` to `accepted` in the same PR.

## Alternatives considered

- **`click.prompt` chain without IO injection.** Rejected. Tests would have to monkeypatch `click.confirm` globally, which is fragile and leaks across tests. Injecting the callables makes wizard tests deterministic.
- **One wizard per tool (`lh config engram --init`, `lh config graphify --init`).** ADR-018's example output named features by section (`knowledge_backend`, `metrics_sink`), so per-section is the documented pattern. Per-tool would explode the surface as the tool count grows.
- **Auto-install missing tools.** Out of scope. Per the user-confirmed plan, the wizard prints the install command but does not run it. The user retains control of when network/package-manager calls happen.
- **Skip the TOML preview.** Rejected. ADR-018 requires "they always preview the TOML they are about to add and ask for confirmation". Surprise-free is the whole point of the discoverability split.

## Consequences

- New optional features that need an interactive wizard ship as `lh config <feature> --init` plus a function in `wizards/<feature>.py`. The contract is uniform; adding a new wizard is a checklist, not a design exercise.
- The `wizards/` package is intentionally separate from `cli/`. Wizards are pure functions of `(config_path, prompt_confirm, echo)`; the CLI subcommand is a thin adapter that injects the real Click callables. This keeps tests fast and predictable.
- The TOML merge helper is atomic (`tempfile + os.replace`), matching the precedent set by other `config.toml` writes in the repo (ADR-016 mentioned this as the pattern for the knowledge directory tree).
- ADR-018 flips to `accepted`. The doctor + wizards combination is the full implementation of the discoverability decision. Future extension points add a doctor row plus a wizard subcommand and they are done.
- `--show` and `--reset` remain out of scope until a concrete need surfaces. The wizard is enough for the current opt-in flow; inspection is covered by reading the file or running `lh doctor`.
```

- [ ] **Step 5.2: Flip ADR-018 status**

In `specs/adrs/018-config-discoverability.md`, change the header from:

```markdown
**Status:** accepted-deferred
**Date:** 2026-04-14
**Implementation:** deferred — the decision is locked, but the `lh config <feature>` command group and the "Features" section of `lh doctor` are intentionally not yet scheduled. See the "Consequences" section below. This ADR is not incomplete; its implementation is waiting for a concrete second extension point to drive the wizard UX.
```

to:

```markdown
**Status:** accepted
**Date:** 2026-04-14
**Implementation:** accepted in 2026-05 via ADR-025 (`lh doctor` Features section) and ADR-026 (`lh config <feature> --init` wizards). The triple stack (QMD/Engram/Graphify) drove the concrete UX.
```

- [ ] **Step 5.3: Update the index**

In `specs/adrs/README.md`:
- Change the ADR-018 row's status column from `accepted-deferred` to `accepted`.
- Append a new row for ADR-026 after the ADR-025 row:

```markdown
| [026](./026-config-wizards.md) | accepted | `lh config <feature> --init` wizards (Fase 3b) | New `lh config` Click group + `wizards/` package with TOML deep-merge. Closes ADR-018 implementation. |
```

- [ ] **Step 5.4: Validate docs build**

```bash
uv run --group docs mkdocs build --strict
```

Expected: clean.

- [ ] **Step 5.5: Commit**

```bash
git add specs/adrs/026-config-wizards.md specs/adrs/018-config-discoverability.md specs/adrs/README.md
git commit -m "docs: add ADR-026 (config wizards) and flip ADR-018 to accepted"
```

---

## Task 6: Final pre-commit gate (`/tdd-check`) + plan + PR

- [ ] **Step 6.1: Full pytest**

```bash
uv run pytest
```

Expected: all tests pass (618 baseline + 13 new = 631).

- [ ] **Step 6.2: Ruff**

```bash
uv run ruff check src tests
```

Expected: clean.

- [ ] **Step 6.3: Mkdocs strict**

```bash
uv run --group docs mkdocs build --strict
```

Expected: clean.

- [ ] **Step 6.4: Commit the implementation plan**

```bash
git add specs/plans/2026-05-03-adr-026-config-wizards.md
git commit -m "chore: add ADR-026 implementation plan"
```

- [ ] **Step 6.5: Revert any uv.lock churn**

```bash
git status
# If uv.lock is modified: git checkout uv.lock
```

- [ ] **Step 6.6: Switch gh auth to lazynet, push, open PR**

```bash
gh auth switch -u lazynet
git push -u origin feat/config-wizards
gh pr create --title "feat: lh config wizards for memory + knowledge (ADR-026, closes ADR-018)" --body "$(cat <<'EOF'
## Summary

- Add `src/lazy_harness/wizards/` package with `_toml_merge.py` (atomic deep-merge) plus `memory.py` and `knowledge.py` wizards. Each wizard injects its IO callables for testability.
- Add `lh config` Click command group (`cli/config_cmd.py`) with `memory --init` and `knowledge --init` subcommands. Each subcommand probes the relevant tool, walks the user through opt-in, previews the TOML block, and merges into `config.toml` only after explicit confirmation.
- ADR-026 documents the wizard implementation. ADR-018 flips from `accepted-deferred` to `accepted` — the discoverability split (doctor + wizards) is now fully implemented.

## Test plan

- [x] `uv run pytest` — all tests pass (3 new in `test_toml_merge.py`, 4 new in `test_memory.py`, 3 new in `test_knowledge.py`, 3 new in `test_config_cmd.py`)
- [x] `uv run ruff check src tests` — clean
- [x] `uv run --group docs mkdocs build --strict` — clean
- [ ] Smoke: run `lh config memory --init` interactively, accept defaults → verify `[memory.engram]` block appears in `~/.config/lazy-harness/config.toml`
- [ ] Smoke: run `lh config knowledge --init` interactively → verify `[knowledge.structure]` block written without clobbering existing sections
- [ ] Smoke: run wizard, decline at the final prompt → verify config file is NOT modified
EOF
)"
gh auth switch -u mvago-flx
```

---

## Self-review notes

- Spec coverage: every requirement in ADR-018 for the wizard surface is mapped to a task. `--show` and `--reset` are explicitly out of scope per ADR-018 itself.
- Placeholder scan: every code block is concrete; no "implement later", no "add error handling".
- Type consistency: `wizard_memory(config_path, *, prompt_confirm, echo) -> bool` and `wizard_knowledge(config_path, *, prompt_confirm, echo) -> bool` share the same signature shape. `merge_into_config(path, new_block) -> None` matches across the helper definition and both wizard callers.
- The plan does not bump version numbers (release-please owns that).
- The plan does not edit `specs/archive/`.
- The ADR-018 status flip happens in this PR because both halves of its implementation now exist; this is what `accepted-deferred` was waiting on.
- Wizards are pure functions of injected IO callables — Click is the adapter, not the test target. Tests use scripted confirm responses.

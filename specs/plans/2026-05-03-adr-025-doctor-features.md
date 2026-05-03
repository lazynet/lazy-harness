# ADR-025 — `lh doctor` Features Section for Triple Stack — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Strict TDD per repo non-negotiable #2.

**Goal:** Implement the "Features" section of `lh doctor` per ADR-018, listing the three optional tools (qmd, engram, graphify) with detected version, pinned version, install/enable hints, and a state icon. This is Fase 3a — the discoverability surface. The wizard surface (`lh config <feature> --init`, Fase 3b) ships in a separate PR.

**Architecture:** New top-level helper module `src/lazy_harness/features.py` with a `FeatureStatus` dataclass and a `collect_feature_statuses(cfg)` function that probes each of the three tools and returns a normalized status list. `cli/doctor_cmd.py` calls the helper and renders a "Features" section. The existing standalone QMD line (`doctor_cmd.py:65-69`) is replaced by the unified Features section to avoid duplication.

**Tech Stack:** Python 3.11, pytest, ruff, MkDocs Material, `rich.console.Console`. Runs in worktree `.worktrees/doctor-features` on branch `feat/doctor-features`.

**Out of scope (separate PR — Fase 3b):** `lh config knowledge --init` and `lh config memory --init` wizards, the upgrade notice (ADR-018 #3). When both are done, ADR-018 flips from `accepted-deferred` to `accepted`. This PR keeps ADR-018 deferred and adds ADR-025 documenting the doctor implementation specifically.

---

## File Structure

| Path | Status | Responsibility |
|------|--------|----------------|
| `src/lazy_harness/features.py` | create | `FeatureStatus` dataclass + `collect_feature_statuses(cfg)` |
| `src/lazy_harness/cli/doctor_cmd.py` | modify | Render Features section; remove duplicated QMD line |
| `tests/unit/test_features.py` | create | Unit tests for the helper (pure function, fully mocked) |
| `tests/unit/cli/test_doctor_cmd.py` | modify | Assert Features section is rendered |
| `specs/adrs/025-doctor-features-section.md` | create | ADR documenting the implementation |
| `specs/adrs/README.md` | modify | Add ADR-025 to index |

---

## State semantics

For each of the three tools the helper returns one of these states:

| State | Meaning | Icon |
|-------|---------|------|
| `active` | Installed AND (enabled in config OR auto-on like QMD) | ✓ green |
| `dormant` | Installed but disabled in config (not applicable to QMD which is auto-on) | · yellow |
| `missing` | Not installed | · grey |
| `broken` | Enabled in config but binary not in PATH (configuration error) | ✗ red |

QMD has no opt-in flag — it's `active` when installed, `missing` otherwise.
Engram and Graphify have explicit `enabled` flags; both gates must agree.

---

## Task 1: `FeatureStatus` dataclass + helper module

**Files:**
- Create: `src/lazy_harness/features.py`
- Create: `tests/unit/test_features.py`

- [ ] **Step 1.1: Write the failing test for `FeatureStatus` dataclass shape**

Create `tests/unit/test_features.py`:

```python
"""Tests for the features helper used by lh doctor."""

from __future__ import annotations

from unittest.mock import patch


def test_feature_status_dataclass_shape() -> None:
    from lazy_harness.features import FeatureStatus

    s = FeatureStatus(
        name="qmd",
        section="knowledge.search",
        state="active",
        installed_version="2.1.0",
        pinned_version="",
        install_hint="",
        enable_hint="",
    )
    assert s.name == "qmd"
    assert s.state == "active"
```

- [ ] **Step 1.2: Run, expect failure**

```bash
uv run pytest tests/unit/test_features.py::test_feature_status_dataclass_shape -v
```

Expected: `ModuleNotFoundError: No module named 'lazy_harness.features'`

- [ ] **Step 1.3: Create the module with the dataclass**

```python
# src/lazy_harness/features.py
"""Feature status helper for lh doctor (per ADR-018, ADR-025)."""

from __future__ import annotations

from dataclasses import dataclass

from lazy_harness.core.config import Config


@dataclass
class FeatureStatus:
    name: str
    section: str
    state: str  # one of: active, dormant, missing, broken
    installed_version: str
    pinned_version: str
    install_hint: str
    enable_hint: str
```

- [ ] **Step 1.4: Run, expect pass**

```bash
uv run pytest tests/unit/test_features.py::test_feature_status_dataclass_shape -v
```

Expected: PASS.

- [ ] **Step 1.5: Add tests for QMD status — installed and missing**

Append to `tests/unit/test_features.py`:

```python
def test_qmd_status_active_when_installed(monkeypatch) -> None:
    from lazy_harness.core.config import Config
    from lazy_harness.features import collect_feature_statuses
    from lazy_harness.knowledge import qmd as qmd_mod

    monkeypatch.setattr(qmd_mod, "is_qmd_available", lambda: True)
    monkeypatch.setattr(
        "lazy_harness.features._probe_version",
        lambda binary: "2.1.0",
    )

    statuses = collect_feature_statuses(Config())
    qmd = next(s for s in statuses if s.name == "qmd")
    assert qmd.state == "active"
    assert qmd.installed_version == "2.1.0"


def test_qmd_status_missing_when_not_installed(monkeypatch) -> None:
    from lazy_harness.core.config import Config
    from lazy_harness.features import collect_feature_statuses
    from lazy_harness.knowledge import qmd as qmd_mod

    monkeypatch.setattr(qmd_mod, "is_qmd_available", lambda: False)

    statuses = collect_feature_statuses(Config())
    qmd = next(s for s in statuses if s.name == "qmd")
    assert qmd.state == "missing"
    assert qmd.installed_version == ""
    assert "qmd" in qmd.install_hint.lower()
```

- [ ] **Step 1.6: Run, expect failure**

```bash
uv run pytest tests/unit/test_features.py -v -k qmd
```

Expected: 2 failures (`collect_feature_statuses` not defined).

- [ ] **Step 1.7: Implement `collect_feature_statuses` and `_probe_version` for QMD only**

Append to `src/lazy_harness/features.py`:

```python
def _probe_version(binary: str) -> str:
    """Run `<binary> --version` and return the last token of stdout, or "" on failure."""
    import subprocess

    try:
        result = subprocess.run(
            [binary, "--version"], capture_output=True, text=True, timeout=10
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return ""
    if result.returncode != 0:
        return ""
    parts = result.stdout.strip().split()
    return parts[-1] if parts else ""


def _qmd_status() -> FeatureStatus:
    from lazy_harness.knowledge import qmd

    if qmd.is_qmd_available():
        return FeatureStatus(
            name="qmd",
            section="knowledge.search",
            state="active",
            installed_version=_probe_version("qmd"),
            pinned_version="",
            install_hint="",
            enable_hint="",
        )
    return FeatureStatus(
        name="qmd",
        section="knowledge.search",
        state="missing",
        installed_version="",
        pinned_version="",
        install_hint="Install QMD to enable semantic search across the knowledge dir.",
        enable_hint="",
    )


def collect_feature_statuses(cfg: Config) -> list[FeatureStatus]:
    """Collect status for every optional tool the harness knows about."""
    return [_qmd_status()]
```

- [ ] **Step 1.8: Run, expect pass**

```bash
uv run pytest tests/unit/test_features.py -v -k qmd
```

Expected: 2 tests pass.

- [ ] **Step 1.9: Add tests for Engram — 4 states (active, dormant, missing, broken)**

Append to `tests/unit/test_features.py`:

```python
def test_engram_status_active(monkeypatch) -> None:
    from lazy_harness.core.config import Config
    from lazy_harness.features import collect_feature_statuses
    from lazy_harness.knowledge import qmd as qmd_mod
    from lazy_harness.memory import engram as engram_mod

    monkeypatch.setattr(qmd_mod, "is_qmd_available", lambda: False)
    monkeypatch.setattr(engram_mod, "is_engram_available", lambda: True)
    monkeypatch.setattr(
        "lazy_harness.features._probe_version",
        lambda binary: "1.15.4",
    )

    cfg = Config()
    cfg.memory.engram.enabled = True

    statuses = collect_feature_statuses(cfg)
    engram = next(s for s in statuses if s.name == "engram")
    assert engram.state == "active"
    assert engram.installed_version == "1.15.4"
    assert engram.pinned_version == "1.15.4"


def test_engram_status_dormant_when_installed_but_disabled(monkeypatch) -> None:
    from lazy_harness.core.config import Config
    from lazy_harness.features import collect_feature_statuses
    from lazy_harness.knowledge import qmd as qmd_mod
    from lazy_harness.memory import engram as engram_mod

    monkeypatch.setattr(qmd_mod, "is_qmd_available", lambda: False)
    monkeypatch.setattr(engram_mod, "is_engram_available", lambda: True)
    monkeypatch.setattr(
        "lazy_harness.features._probe_version", lambda binary: "1.15.4"
    )

    cfg = Config()
    cfg.memory.engram.enabled = False

    statuses = collect_feature_statuses(cfg)
    engram = next(s for s in statuses if s.name == "engram")
    assert engram.state == "dormant"
    assert "[memory.engram].enabled" in engram.enable_hint


def test_engram_status_missing(monkeypatch) -> None:
    from lazy_harness.core.config import Config
    from lazy_harness.features import collect_feature_statuses
    from lazy_harness.knowledge import qmd as qmd_mod
    from lazy_harness.memory import engram as engram_mod

    monkeypatch.setattr(qmd_mod, "is_qmd_available", lambda: False)
    monkeypatch.setattr(engram_mod, "is_engram_available", lambda: False)

    cfg = Config()
    cfg.memory.engram.enabled = False

    statuses = collect_feature_statuses(cfg)
    engram = next(s for s in statuses if s.name == "engram")
    assert engram.state == "missing"
    assert "engram" in engram.install_hint.lower()


def test_engram_status_broken_when_enabled_but_missing(monkeypatch) -> None:
    from lazy_harness.core.config import Config
    from lazy_harness.features import collect_feature_statuses
    from lazy_harness.knowledge import qmd as qmd_mod
    from lazy_harness.memory import engram as engram_mod

    monkeypatch.setattr(qmd_mod, "is_qmd_available", lambda: False)
    monkeypatch.setattr(engram_mod, "is_engram_available", lambda: False)

    cfg = Config()
    cfg.memory.engram.enabled = True

    statuses = collect_feature_statuses(cfg)
    engram = next(s for s in statuses if s.name == "engram")
    assert engram.state == "broken"
```

- [ ] **Step 1.10: Run, expect failure**

```bash
uv run pytest tests/unit/test_features.py -v -k engram
```

Expected: 4 failures.

- [ ] **Step 1.11: Implement `_engram_status` and add it to the collector**

Append to `src/lazy_harness/features.py`:

```python
def _engram_status(cfg: Config) -> FeatureStatus:
    from lazy_harness.memory import engram

    enabled = cfg.memory.engram.enabled
    installed = engram.is_engram_available()
    pinned = engram.PINNED_VERSION
    detected = _probe_version("engram") if installed else ""

    if enabled and installed:
        state = "active"
    elif installed and not enabled:
        state = "dormant"
    elif enabled and not installed:
        state = "broken"
    else:
        state = "missing"

    install_hint = (
        f"Install Engram (pin {pinned}) and set [memory.engram].enabled = true."
        if state in ("missing", "broken")
        else ""
    )
    enable_hint = (
        "Set [memory.engram].enabled = true to activate."
        if state == "dormant"
        else ""
    )

    return FeatureStatus(
        name="engram",
        section="memory.engram",
        state=state,
        installed_version=detected,
        pinned_version=pinned,
        install_hint=install_hint,
        enable_hint=enable_hint,
    )
```

Update `collect_feature_statuses`:

```python
def collect_feature_statuses(cfg: Config) -> list[FeatureStatus]:
    return [_qmd_status(), _engram_status(cfg)]
```

- [ ] **Step 1.12: Run, expect pass**

```bash
uv run pytest tests/unit/test_features.py -v -k engram
```

Expected: 4 tests pass.

- [ ] **Step 1.13: Add Graphify tests (mirror Engram) and implementation**

Append the four equivalent Graphify tests (active / dormant / missing / broken) to `tests/unit/test_features.py`:

```python
def test_graphify_status_active(monkeypatch) -> None:
    from lazy_harness.core.config import Config
    from lazy_harness.features import collect_feature_statuses
    from lazy_harness.knowledge import graphify as graphify_mod
    from lazy_harness.knowledge import qmd as qmd_mod

    monkeypatch.setattr(qmd_mod, "is_qmd_available", lambda: False)
    monkeypatch.setattr(graphify_mod, "is_graphify_available", lambda: True)
    monkeypatch.setattr(
        "lazy_harness.features._probe_version", lambda binary: "0.6.9"
    )

    cfg = Config()
    cfg.knowledge.structure.enabled = True

    statuses = collect_feature_statuses(cfg)
    graphify = next(s for s in statuses if s.name == "graphify")
    assert graphify.state == "active"
    assert graphify.installed_version == "0.6.9"
    assert graphify.pinned_version == "0.6.9"


def test_graphify_status_dormant_when_installed_but_disabled(monkeypatch) -> None:
    from lazy_harness.core.config import Config
    from lazy_harness.features import collect_feature_statuses
    from lazy_harness.knowledge import graphify as graphify_mod
    from lazy_harness.knowledge import qmd as qmd_mod

    monkeypatch.setattr(qmd_mod, "is_qmd_available", lambda: False)
    monkeypatch.setattr(graphify_mod, "is_graphify_available", lambda: True)
    monkeypatch.setattr(
        "lazy_harness.features._probe_version", lambda binary: "0.6.9"
    )

    cfg = Config()
    cfg.knowledge.structure.enabled = False

    statuses = collect_feature_statuses(cfg)
    graphify = next(s for s in statuses if s.name == "graphify")
    assert graphify.state == "dormant"
    assert "[knowledge.structure].enabled" in graphify.enable_hint


def test_graphify_status_missing(monkeypatch) -> None:
    from lazy_harness.core.config import Config
    from lazy_harness.features import collect_feature_statuses
    from lazy_harness.knowledge import graphify as graphify_mod
    from lazy_harness.knowledge import qmd as qmd_mod

    monkeypatch.setattr(qmd_mod, "is_qmd_available", lambda: False)
    monkeypatch.setattr(graphify_mod, "is_graphify_available", lambda: False)

    cfg = Config()
    cfg.knowledge.structure.enabled = False

    statuses = collect_feature_statuses(cfg)
    graphify = next(s for s in statuses if s.name == "graphify")
    assert graphify.state == "missing"
    assert "graphify" in graphify.install_hint.lower()


def test_graphify_status_broken_when_enabled_but_missing(monkeypatch) -> None:
    from lazy_harness.core.config import Config
    from lazy_harness.features import collect_feature_statuses
    from lazy_harness.knowledge import graphify as graphify_mod
    from lazy_harness.knowledge import qmd as qmd_mod

    monkeypatch.setattr(qmd_mod, "is_qmd_available", lambda: False)
    monkeypatch.setattr(graphify_mod, "is_graphify_available", lambda: False)

    cfg = Config()
    cfg.knowledge.structure.enabled = True

    statuses = collect_feature_statuses(cfg)
    graphify = next(s for s in statuses if s.name == "graphify")
    assert graphify.state == "broken"
```

Run, expect 4 failures, then implement `_graphify_status` (mirror `_engram_status` — same shape, different attribute names):

```python
def _graphify_status(cfg: Config) -> FeatureStatus:
    from lazy_harness.knowledge import graphify

    enabled = cfg.knowledge.structure.enabled
    installed = graphify.is_graphify_available()
    pinned = graphify.PINNED_VERSION
    detected = _probe_version("graphify") if installed else ""

    if enabled and installed:
        state = "active"
    elif installed and not enabled:
        state = "dormant"
    elif enabled and not installed:
        state = "broken"
    else:
        state = "missing"

    install_hint = (
        f"Install Graphify (pin {pinned}) and set [knowledge.structure].enabled = true."
        if state in ("missing", "broken")
        else ""
    )
    enable_hint = (
        "Set [knowledge.structure].enabled = true to activate."
        if state == "dormant"
        else ""
    )

    return FeatureStatus(
        name="graphify",
        section="knowledge.structure",
        state=state,
        installed_version=detected,
        pinned_version=pinned,
        install_hint=install_hint,
        enable_hint=enable_hint,
    )
```

Update `collect_feature_statuses`:

```python
def collect_feature_statuses(cfg: Config) -> list[FeatureStatus]:
    return [_qmd_status(), _engram_status(cfg), _graphify_status(cfg)]
```

- [ ] **Step 1.14: Run all features tests**

```bash
uv run pytest tests/unit/test_features.py -v
```

Expected: 11 tests pass (1 dataclass + 2 qmd + 4 engram + 4 graphify).

- [ ] **Step 1.15: Run ruff**

```bash
uv run ruff check src/lazy_harness/features.py tests/unit/test_features.py --fix
uv run ruff check src/lazy_harness/features.py tests/unit/test_features.py
```

Expected: clean.

- [ ] **Step 1.16: Commit**

```bash
git add src/lazy_harness/features.py tests/unit/test_features.py
git commit -m "feat: add features helper for doctor discoverability"
```

---

## Task 2: Render Features section in `lh doctor`

**Files:**
- Modify: `src/lazy_harness/cli/doctor_cmd.py`
- Modify: `tests/unit/cli/test_doctor_cmd.py`

- [ ] **Step 2.1: Read existing doctor tests to understand the test style**

```bash
cat tests/unit/cli/test_doctor_cmd.py
```

Identify the pattern (likely uses `CliRunner` from `click.testing`). Mirror it for the new assertions.

- [ ] **Step 2.2: Write the failing test for the Features section**

Append to `tests/unit/cli/test_doctor_cmd.py`:

```python
def test_doctor_renders_features_section(tmp_path, monkeypatch) -> None:
    from click.testing import CliRunner

    from lazy_harness.cli import doctor_cmd
    from lazy_harness.knowledge import graphify as graphify_mod
    from lazy_harness.knowledge import qmd as qmd_mod
    from lazy_harness.memory import engram as engram_mod

    # Stub config_file to point to a minimal valid config
    cfg_path = tmp_path / "config.toml"
    cfg_path.write_text(
        """
[harness]
version = "1"

[agent]
type = "claude-code"

[profiles]
default = "personal"

[profiles.personal]
config_dir = "~/.claude-personal"
"""
    )
    monkeypatch.setattr(doctor_cmd, "config_file", lambda: cfg_path)

    monkeypatch.setattr(qmd_mod, "is_qmd_available", lambda: False)
    monkeypatch.setattr(engram_mod, "is_engram_available", lambda: False)
    monkeypatch.setattr(graphify_mod, "is_graphify_available", lambda: False)

    runner = CliRunner()
    result = runner.invoke(doctor_cmd.doctor)

    assert "Features" in result.output
    assert "qmd" in result.output
    assert "engram" in result.output
    assert "graphify" in result.output
```

- [ ] **Step 2.3: Run, expect failure**

```bash
uv run pytest tests/unit/cli/test_doctor_cmd.py::test_doctor_renders_features_section -v
```

Expected: failure — Features section not rendered.

- [ ] **Step 2.4: Replace the standalone QMD line with the Features section**

In `src/lazy_harness/cli/doctor_cmd.py`, locate the existing QMD block:

```python
    if cfg.knowledge.search.engine == "qmd":
        if shutil.which("qmd"):
            console.print("[green]✓[/green] QMD: found in PATH")
        else:
            console.print("[yellow]·[/yellow] QMD: not found in PATH (optional)")
```

Replace it with:

```python
    from lazy_harness.features import collect_feature_statuses

    console.print("\n[bold]Features[/bold]")
    statuses = collect_feature_statuses(cfg)
    icons = {
        "active": "[green]✓[/green]",
        "dormant": "[yellow]·[/yellow]",
        "missing": "[grey50]·[/grey50]",
        "broken": "[red]✗[/red]",
    }
    for s in statuses:
        icon = icons.get(s.state, "?")
        version_part = ""
        if s.installed_version:
            version_part = f" v{s.installed_version}"
            if s.pinned_version and s.installed_version != s.pinned_version:
                version_part += f" [yellow](pin {s.pinned_version})[/yellow]"
        line = f"  {icon} {s.name:<10} ({s.section}){version_part}"
        console.print(line)
        hint = s.install_hint or s.enable_hint
        if hint:
            console.print(f"      [grey50]{hint}[/grey50]")
        if s.state == "broken":
            ok = False
```

- [ ] **Step 2.5: Run, expect pass**

```bash
uv run pytest tests/unit/cli/test_doctor_cmd.py::test_doctor_renders_features_section -v
```

Expected: PASS.

- [ ] **Step 2.6: Run all existing doctor tests, no regressions**

```bash
uv run pytest tests/unit/cli/test_doctor_cmd.py -v
```

Expected: all tests pass.

- [ ] **Step 2.7: Verify the unused `import shutil` is gone (if it became dead after replacing the QMD line)**

```bash
uv run ruff check src/lazy_harness/cli/doctor_cmd.py --fix
uv run ruff check src/lazy_harness/cli/doctor_cmd.py
```

Expected: clean.

- [ ] **Step 2.8: Commit**

```bash
git add src/lazy_harness/cli/doctor_cmd.py tests/unit/cli/test_doctor_cmd.py
git commit -m "feat: render features section in lh doctor"
```

---

## Task 3: ADR-025 + index update

**Files:**
- Create: `specs/adrs/025-doctor-features-section.md`
- Modify: `specs/adrs/README.md`

- [ ] **Step 3.1: Write ADR-025**

Create `specs/adrs/025-doctor-features-section.md`:

```markdown
# ADR-025: `lh doctor` Features section — implementation for the triple stack

**Status:** accepted
**Date:** 2026-05-03

## Context

ADR-018 locked the discoverability approach in April 2026 but left implementation deferred until a concrete extension point needed it. With QMD (ADR-016), Engram (ADR-022), and Graphify (ADR-023) now wired through the MCP deploy seam (ADR-024), the harness has three optional tools the user can opt into. Each one needs a way for the user to ask "is this installed, is it active, what version do I have, and what is the canonical pin".

Before this ADR, `lh doctor` carried a single hard-coded QMD line that did not generalize. Engram and Graphify shipped without any `lh doctor` representation — the only way to know whether the deploy step had picked them up was to read `~/.claude-<profile>/settings.json` by hand.

## Decision

**Add a `Features` section to `lh doctor`, populated by a new `lazy_harness.features` helper module. The helper exposes a `FeatureStatus` dataclass and a `collect_feature_statuses(cfg)` function that probes the three tools (qmd, engram, graphify) and returns a normalized status list. `doctor_cmd.py` renders the list with state icons, version comparison against the pin, and actionable install/enable hints.**

State semantics:

| State | Meaning | Doctor icon | Sets ok=False |
|-------|---------|-------------|---------------|
| `active` | Installed AND enabled (or auto-on like QMD) | `✓` green | no |
| `dormant` | Installed but disabled in config | `·` yellow | no |
| `missing` | Not installed | `·` grey | no |
| `broken` | Enabled in config but binary not in PATH | `✗` red | yes |

QMD has no opt-in flag (per ADR-016) — it is `active` when installed, `missing` otherwise. Engram and Graphify use both gates.

The helper lives at `src/lazy_harness/features.py` (top-level, not under `cli/`) because the `lh config <feature> --init` wizards (Fase 3b, deferred) will reuse it for the same probing logic.

## Alternatives considered

- **Inline the per-tool probing in `doctor_cmd.py`.** Rejected. Three tools today, more in the future. The helper is one extraction that pays back at the second tool.
- **Read the version from a constant rather than probing the binary.** Rejected. The harness pins a version; the user might have a different one installed. The doctor's job is to surface that mismatch.
- **Treat `broken` as an info-level row, not an error.** Rejected. `enabled = true` plus `binary not in PATH` is a configuration error — the user explicitly asked for the tool but the next `lh deploy` will produce a settings file with an MCP entry that fails to start. That deserves `ok = False`.
- **Expose the helper under `cli/`.** Rejected. The helper has no CLI dependencies; placing it at `src/lazy_harness/features.py` keeps the import graph clean and makes it reusable from non-CLI contexts (the future `lh config` wizards, possibly the upgrade-notice machinery).

## Consequences

- New optional tools need three things to surface in the doctor: a `is_<tool>_available()` probe, a `PINNED_VERSION` constant, and a status function added to `collect_feature_statuses`. The contract is uniform across qmd, engram, graphify and any future addition.
- ADR-018 stays `accepted-deferred` for now. It flips to `accepted` when the `lh config <feature> --init` wizards (Fase 3b) ship in a follow-up PR. The doctor side is now done.
- Version drift surfaces at doctor time without needing a separate `lh version-check` command. Pin mismatches are visible inline next to each tool.
- The standalone QMD line that lived in `doctor_cmd.py` is removed — the Features section subsumes it. There is no behaviour difference for QMD users; the message just moves into the new section.
- The `broken` state guarantees that a misconfigured profile (e.g. user enabled engram in config but uninstalled the binary) fails `lh doctor` instead of silently producing a broken `settings.json` on the next `lh deploy`. This is the same defensive posture as the existing "profile dir missing" check.
```

- [ ] **Step 3.2: Add ADR-025 to the index**

In `specs/adrs/README.md`, in the framework ADRs table, append (above the ADR-018 row to keep numerical-ish order, or at the end since the table is mostly numerical):

Append after the ADR-024 row:

```markdown
| [025](./025-doctor-features-section.md) | accepted | `lh doctor` Features section for triple stack | New `lazy_harness.features` helper + Features section in `lh doctor` listing qmd/engram/graphify with state, version, and pin. First half of ADR-018 implementation. |
```

- [ ] **Step 3.3: Validate docs build**

```bash
uv run --group docs mkdocs build --strict
```

Expected: clean.

- [ ] **Step 3.4: Commit**

```bash
git add specs/adrs/025-doctor-features-section.md specs/adrs/README.md
git commit -m "docs: add ADR-025 (doctor features section)"
```

---

## Task 4: Final pre-commit gate (`/tdd-check`) + plan + PR

- [ ] **Step 4.1: Full pytest**

```bash
uv run pytest
```

Expected: all tests pass (606 baseline + 12 new = 618).

- [ ] **Step 4.2: Ruff**

```bash
uv run ruff check src tests
```

Expected: clean.

- [ ] **Step 4.3: Mkdocs strict**

```bash
uv run --group docs mkdocs build --strict
```

Expected: clean.

- [ ] **Step 4.4: Commit the implementation plan**

```bash
git add specs/plans/2026-05-03-adr-025-doctor-features.md
git commit -m "chore: add ADR-025 implementation plan"
```

- [ ] **Step 4.5: Revert any `uv.lock` churn**

```bash
git status
# If uv.lock is modified, revert: git checkout uv.lock
```

- [ ] **Step 4.6: Switch gh auth to lazynet, push, open PR**

```bash
gh auth switch -u lazynet
git push -u origin feat/doctor-features
gh pr create --title "feat: lh doctor Features section for triple stack (ADR-025)" --body "$(cat <<'EOF'
## Summary

- Add `src/lazy_harness/features.py` — `FeatureStatus` dataclass + `collect_feature_statuses(cfg)` that probes qmd/engram/graphify and returns normalized status (state, detected version, pin, install/enable hints).
- Add `Features` section to `lh doctor` rendering each tool with a state icon (`active` / `dormant` / `missing` / `broken`), version comparison against the pin, and actionable hints.
- Replace the standalone QMD line in `doctor_cmd.py` with the unified Features section.
- ADR-025 documents the implementation. ADR-018 stays `accepted-deferred` until the `lh config <feature> --init` wizards ship (Fase 3b).

## Test plan

- [x] `uv run pytest` — all tests pass (11 new in `test_features.py`, 1 new in `test_doctor_cmd.py`)
- [x] `uv run ruff check src tests` — clean
- [x] `uv run --group docs mkdocs build --strict` — clean
- [ ] Smoke: run `lh doctor` with QMD installed, Engram + Graphify not installed → confirm Features section shows qmd active, engram/graphify missing
- [ ] Smoke: install Engram, set `[memory.engram].enabled = true`, run `lh doctor` → engram shows active with version
- [ ] Smoke: set `[memory.engram].enabled = true` while Engram is uninstalled → engram shows broken (✗) and `lh doctor` exits non-zero
EOF
)"
gh auth switch -u mvago-flx
```

---

## Self-review notes

- Spec coverage: ADR-018 calls for both a doctor Features section and `lh config <feature> --init` wizards. This PR ships only the doctor half; the wizards are explicitly Fase 3b in a follow-up.
- Placeholder scan: every code block is concrete; no "implement later", no "add error handling".
- Type consistency: `collect_feature_statuses(cfg) -> list[FeatureStatus]` signature is the same in Task 1 (definition) and Task 2 (caller). `FeatureStatus` field names (`name`, `section`, `state`, `installed_version`, `pinned_version`, `install_hint`, `enable_hint`) match across the dataclass, the per-tool helpers, and the doctor renderer.
- The plan does not bump version numbers (release-please owns that).
- The plan does not edit `specs/archive/`.
- The plan does not flip ADR-018 from `accepted-deferred` to `accepted` — that flip happens after Fase 3b ships.
- Doctor regression tests preserve the existing flow; the new Features section is additive plus replaces the duplicated QMD line.

# Config persistence Implementation Plan (wave 1)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `save_config` non-destructive — preserve every key, section and comment it does not own — and wire the three `[context_inject]` keys the loader silently ignores.

**Architecture:** Replace `tomli_w` writing with `tomlkit`, which round-trips comments, key order and formatting. `save_config` becomes read-modify-write: load the existing document, apply only what `_config_to_dict` models, prune profiles that were deliberately removed, write atomically via same-directory temp plus `os.replace`. Reading stays on stdlib `tomllib`.

**Tech Stack:** Python 3.11+, `tomlkit`, `pytest`, `ruff`.

**Spec:** [`specs/designs/2026-08-17-capability-registry-design.md`](../designs/2026-08-17-capability-registry-design.md) section D5.

**Branch:** `fix/config-round-trip` — PR title `fix: preserve unmodelled sections and comments when writing config`. Releases as **0.39.1**.

## Global Constraints

- Python `>=3.11`. `tomllib` is stdlib and stays the reader.
- Strict TDD: no production code without a failing test that exercises it first. No exceptions, including for bug fixes.
- Every new test must be **observed failing** before the implementation lands. A test that passes both with and without the fix covers nothing.
- `pytest.raises(match=...)` anchors on literal config keys or enum names, never on a substring that could also appear in a `tmp_path`. `tmp_path` contains the test's own name.
- Conventional commits, no AI-attribution trailers, no `--no-verify`.
- `/tdd-check` (pytest + ruff + `mkdocs build --strict`) before every commit.
- Never run `uv` from a worktree. `uv add tomlkit` runs in the root checkout; the worktree picks it up from the shared `uv.lock`.

## Deviation from the spec, recorded

The spec's D5 chose read-modify-write over completing `_config_to_dict`. Planning surfaced two facts that refine it:

1. **`lh profile remove` (`cli/profile_cmd.py:325-340`) calls `save_config` and needs deletion to take effect.** A pure deep merge resurrects the removed profile, because a merge cannot express absence. So the merge needs one targeted prune.
2. **Comments are lost too, and the repo already routes around it twice** — `wizards/_toml_merge.py` exists so wizards do not corrupt config, and `cli/knowledge_cmd.py:367` `_write_repo_list` rewrites a single line by hand with the comment *"a full `save_config` round-trip is the wrong tool: it drops every comment and any key this version does not model."* The live config carries 7 comment lines of operational rationale.

Hence `tomlkit` rather than `tomli_w` for writing. If the dependency is rejected, the fallback is Tasks 1–5 unchanged with `tomli_w`, accepting comment loss and keeping both workarounds — that closes the 51-key bug but leaves the comment bug and the two workarounds in place.

## File Structure

| File | Responsibility |
|---|---|
| `pyproject.toml` | add `tomlkit>=0.13` to `[project].dependencies` |
| `src/lazy_harness/core/config.py` | `save_config` becomes read-modify-write over a `tomlkit` document; `_config_to_dict` completed; `[context_inject]` parse gap closed |
| `src/lazy_harness/selftest/checks/config_check.py` | new check: every key present before a round trip is present after |
| `tests/unit/test_config.py` | round-trip, key-loss, comment-preservation, double-round-trip, deletion, context_inject parse |
| `tests/unit/selftest/test_checks_config.py` | the new selftest check |

---

### Task 1: Prove the key loss

Establishes the failing baseline. This test must stay in the suite permanently — it is the regression net for every future config section.

**Files:**
- Test: `tests/unit/test_config.py`

**Interfaces:**
- Consumes: `load_config`, `save_config` from `lazy_harness.core.config`
- Produces: `_FULL_CONFIG` module-level fixture string, reused by Tasks 2, 3, 5 and 6

- [ ] **Step 1: Write the failing test**

Add to `tests/unit/test_config.py`:

```python
_FULL_CONFIG = """\
[harness]
version = "1"

[agent]
type = "claude-code"

[profiles]
default = "lazy"

[profiles.lazy]
config_dir = "~/.claude-lazy"
roots = ["~/repos/lazy"]
lazynorth_doc = "LazyNorth.md"

[profiles.flex]
config_dir = "~/.claude-flex"
roots = ["~/repos/flex"]
lazynorth_doc = "FlexNorth.md"

[knowledge]
root = "~/repos/lazy/lazy-knowledge"

[knowledge.sessions]
enabled = true

[knowledge.learnings]
enabled = true

[knowledge.search]
engine = "qmd"

[knowledge.structure]
engine = "graphify"
enabled = true
version = "0.9.38"
repos = ["~/repos/lazy/lazy-harness"]

[memory.engram]
enabled = true
git_sync = true
cloud = false
version = "1.15.4"
binary = "/usr/local/bin/engram"

[monitoring]
enabled = true
db = "~/.local/share/lazy-harness/metrics.db"

[scheduler]
backend = "auto"

[scheduler.jobs.qmd-sync]
schedule = "0 */6 * * *"
command = "qmd sync"

[scheduler.jobs.metrics-ingest]
schedule = "*/30 * * * *"
command = "lh metrics ingest"

[hooks.session_start]
scripts = ["context-inject"]

[hooks.pre_tool_use]
scripts = ["pre-tool-use-security"]
allow_patterns = ["rm -rf ./build"]

[compound_loop]
enabled = true
model = "claude-haiku-4-5-20251001"
min_messages = 4
slim_handoff_enabled = true

[lazynorth]
enabled = true
path = "~/LazyMind/LazyNorth.md"
universal_doc = "LazyNorth.md"

[context_inject]
enabled = true
max_body_chars = 12000
qmd_suggest_enabled = false
qmd_suggest_top_k = 7
graphify_surface_enabled = false

[loops]
inject_goal_prompt = true
"""


def _flat_keys(data: dict, prefix: str = "") -> set[str]:
    """Every dotted key path in a parsed TOML document, tables included."""
    out: set[str] = set()
    for key, value in data.items():
        path = f"{prefix}{key}"
        out.add(path)
        if isinstance(value, dict):
            out |= _flat_keys(value, path + ".")
    return out


def test_save_config_preserves_every_key_it_did_not_change(tmp_path: Path) -> None:
    """save_config must not drop sections the serializer does not model.

    Measured against the live config before this fix: 51 keys were lost per
    write, including all six declared scheduler jobs.
    """
    import tomllib

    from lazy_harness.core.config import load_config, save_config

    cfg_path = tmp_path / "config.toml"
    cfg_path.write_text(_FULL_CONFIG)
    before = _flat_keys(tomllib.loads(cfg_path.read_text()))

    save_config(load_config(cfg_path), cfg_path)

    after = _flat_keys(tomllib.loads(cfg_path.read_text()))
    lost = sorted(before - after)
    assert not lost, f"save_config dropped {len(lost)} keys: {lost}"
```

- [ ] **Step 2: Run it and confirm it fails, and read what it reports**

Run: `uv run pytest tests/unit/test_config.py::test_save_config_preserves_every_key_it_did_not_change -v`

Expected: FAIL. The assertion message enumerates the dropped keys — `compound_loop`, `memory`, `lazynorth`, `knowledge.structure`, `scheduler.jobs`, `hooks.pre_tool_use.allow_patterns`, `profiles.lazy.lazynorth_doc`, and the three `context_inject.qmd_*` / `graphify_surface_enabled` entries.

Record that list in the PR description. It is the evidence the fix is needed.

- [ ] **Step 3: Commit the failing test alone**

Committing the red test separately makes the before/after visible in history.

```bash
git add tests/unit/test_config.py
git commit -m "test: pin the config keys save_config currently destroys"
```

---

### Task 2: Prove the comment loss

**Files:**
- Test: `tests/unit/test_config.py`

**Interfaces:**
- Consumes: `_FULL_CONFIG` from Task 1

- [ ] **Step 1: Write the failing test**

```python
def test_save_config_preserves_comments(tmp_path: Path) -> None:
    """Config is hand-edited and version-controlled; comments carry rationale.

    The live config has seven comment lines explaining why the engram MCP is
    off and why the graphify sweep exists. `cli/knowledge_cmd.py:_write_repo_list`
    hand-edits a single line specifically to avoid losing them.
    """
    from lazy_harness.core.config import load_config, save_config

    cfg_path = tmp_path / "config.toml"
    cfg_path.write_text(
        "# top-of-file rationale\n"
        + _FULL_CONFIG
        + '\n# why this sweep exists\n[scheduler.jobs.graphify-update]\n'
        + 'schedule = "0 3 * * *"\ncommand = "lh knowledge graph update"\n'
    )

    save_config(load_config(cfg_path), cfg_path)

    text = cfg_path.read_text()
    assert "# top-of-file rationale" in text
    assert "# why this sweep exists" in text
```

- [ ] **Step 2: Run it and confirm it fails**

Run: `uv run pytest tests/unit/test_config.py::test_save_config_preserves_comments -v`
Expected: FAIL — `tomli_w` emits no comments.

- [ ] **Step 3: Commit**

```bash
git add tests/unit/test_config.py
git commit -m "test: pin the comments save_config currently destroys"
```

---

### Task 3: Prove the double-round-trip gap

A deserializer that supplies a default the serializer omits drops it on the **second** rewrite, not the first. One round trip cannot see it. The repo's config gate requires this test explicitly.

**Files:**
- Test: `tests/unit/test_config.py`

- [ ] **Step 1: Write the failing test**

```python
def test_save_load_save_load_is_stable(tmp_path: Path) -> None:
    """save → load → save → load must reach the same Config as one cycle.

    A field the loader defaults and the writer omits survives the first
    rewrite and vanishes on the second.
    """
    import tomllib

    from lazy_harness.core.config import load_config, save_config

    cfg_path = tmp_path / "config.toml"
    cfg_path.write_text(_FULL_CONFIG)

    save_config(load_config(cfg_path), cfg_path)
    once = tomllib.loads(cfg_path.read_text())

    save_config(load_config(cfg_path), cfg_path)
    twice = tomllib.loads(cfg_path.read_text())

    assert once == twice
```

- [ ] **Step 2: Run it and confirm it fails**

Run: `uv run pytest tests/unit/test_config.py::test_save_load_save_load_is_stable -v`
Expected: FAIL.

- [ ] **Step 3: Commit**

```bash
git add tests/unit/test_config.py
git commit -m "test: pin double-round-trip stability for config"
```

---

### Task 4: Add tomlkit

**Files:**
- Modify: `pyproject.toml`

- [ ] **Step 1: Add the dependency from the ROOT CHECKOUT, not the worktree**

Config generators embed the invoking interpreter's path, and worktree `uv` runs have degraded `uv.lock` before.

```bash
cd ~/repos/lazy/lazy-harness
uv add 'tomlkit>=0.13'
```

- [ ] **Step 2: Verify it resolved and the suite still passes**

```bash
uv run python -c "import tomlkit; print(tomlkit.__version__)"
uv run pytest -q
```
Expected: a version string, then 1338 passed plus the 3 new failures from Tasks 1–3.

- [ ] **Step 3: Commit**

```bash
git add pyproject.toml uv.lock
git commit -m "chore: add tomlkit for style-preserving config writes"
```

---

### Task 5: Make `save_config` read-modify-write

**Files:**
- Modify: `src/lazy_harness/core/config.py` — `save_config`, and complete `_config_to_dict`
- Test: `tests/unit/test_config.py` (Tasks 1–3 turn green)

**Interfaces:**
- Consumes: `_config_to_dict(cfg) -> dict[str, Any]`
- Produces: `save_config(cfg: Config, path: Path) -> None` — signature unchanged, so no caller changes

- [ ] **Step 1: Complete `_config_to_dict`**

Deletion within a modelled section must take effect, so the serializer emits everything the loader reads. The merge in Step 2 is the safety net for what it still misses, not a substitute for this.

Add to the `result` dict in `_config_to_dict`, after the existing `knowledge` block:

```python
    result["knowledge"]["structure"] = {
        "engine": cfg.knowledge.structure.engine,
        "enabled": cfg.knowledge.structure.enabled,
        "version": cfg.knowledge.structure.version,
        "repos": cfg.knowledge.structure.repos,
    }
    result["knowledge"]["classify_rules"] = [
        {"pattern": r.pattern, "profile": r.profile, "session_type": r.session_type}
        for r in cfg.knowledge.classify_rules
    ]
    result["memory"] = {
        "engram": {
            "enabled": cfg.memory.engram.enabled,
            "git_sync": cfg.memory.engram.git_sync,
            "cloud": cfg.memory.engram.cloud,
            "version": cfg.memory.engram.version,
            "binary": cfg.memory.engram.binary,
        }
    }
    result["compound_loop"] = {
        "enabled": cfg.compound_loop.enabled,
        "model": cfg.compound_loop.model,
        "min_messages": cfg.compound_loop.min_messages,
        "min_user_chars": cfg.compound_loop.min_user_chars,
        "debounce_seconds": cfg.compound_loop.debounce_seconds,
        "timeout_seconds": cfg.compound_loop.timeout_seconds,
        "reprocess_min_growth_seconds": cfg.compound_loop.reprocess_min_growth_seconds,
        "grading_enabled": cfg.compound_loop.grading_enabled,
        "slim_handoff_enabled": cfg.compound_loop.slim_handoff_enabled,
        "backend": cfg.compound_loop.backend,
        "backend_options": cfg.compound_loop.backend_options,
    }
    if cfg.compound_loop.lazymind_dir is not None:
        result["compound_loop"]["lazymind_dir"] = cfg.compound_loop.lazymind_dir
    result["lazynorth"] = {
        "enabled": cfg.lazynorth.enabled,
        "path": cfg.lazynorth.path,
        "universal_doc": cfg.lazynorth.universal_doc,
    }
    result["scheduler"]["jobs"] = {
        j.name: {"schedule": j.schedule, "command": j.command}
        for j in cfg.scheduler.jobs
    }
    result["context_inject"]["qmd_suggest_enabled"] = cfg.context_inject.qmd_suggest_enabled
    result["context_inject"]["qmd_suggest_top_k"] = cfg.context_inject.qmd_suggest_top_k
    result["context_inject"]["graphify_surface_enabled"] = (
        cfg.context_inject.graphify_surface_enabled
    )
```

And in the `profiles_dict` loop, carry the third field:

```python
        profiles_dict[name] = {
            "config_dir": entry.config_dir,
            "roots": entry.roots,
            "lazynorth_doc": entry.lazynorth_doc,
        }
```

- [ ] **Step 2: Rewrite `save_config`**

Replace the existing `save_config` and add the two helpers above it:

```python
def _apply(doc: Any, overlay: dict[str, Any]) -> None:
    """Recursively apply `overlay` onto a tomlkit document, in place.

    In-place assignment is what preserves comments, key order and formatting:
    tomlkit keeps the trivia attached to each key it does not rewrite.
    Keys absent from `overlay` are left untouched, which is what carries
    sections this version does not model.
    """
    for key, value in overlay.items():
        if isinstance(value, dict) and isinstance(doc.get(key), dict):
            _apply(doc[key], value)
        else:
            doc[key] = value


def _prune_removed_profiles(doc: Any, cfg: Config) -> None:
    """Drop profile tables the Config no longer carries.

    `lh profile remove` expresses deletion by absence, and applying an overlay
    can only add or overwrite. Without this, a removed profile comes back.
    """
    profiles = doc.get("profiles")
    if not isinstance(profiles, dict):
        return
    for name in [k for k in profiles if k != "default"]:
        if name not in cfg.profiles.items:
            del profiles[name]


def save_config(cfg: Config, path: Path) -> None:
    """Write config, preserving comments and every key this version does not model.

    Read-modify-write rather than serialize-from-scratch: the previous
    implementation emitted 10 of the 14 sections `load_config` reads and
    destroyed 51 keys per write against a real config.
    """
    import os
    import tempfile

    import tomlkit

    if path.is_file():
        doc = tomlkit.parse(path.read_text(encoding="utf-8"))
    else:
        doc = tomlkit.document()

    _apply(doc, _config_to_dict(cfg))
    _prune_removed_profiles(doc, cfg)

    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=path.name + ".")
    try:
        os.write(fd, tomlkit.dumps(doc).encode())
        os.close(fd)
        os.replace(tmp, path)
    except Exception:
        os.unlink(tmp)
        raise
```

Same-directory temp plus `os.replace` matches the atomic-write pattern already used in `knowledge/session_export.py:141` and `knowledge/compound_loop.py:813`, chosen so a syncing filesystem observes one rename rather than a partial write.

- [ ] **Step 3: Run the three tests from Tasks 1–3**

Run: `uv run pytest tests/unit/test_config.py -k "preserves_every_key or preserves_comments or save_load_save_load" -v`
Expected: 3 PASSED.

- [ ] **Step 4: Run the whole suite — existing round-trip tests must still pass**

Run: `uv run pytest -q`
Expected: all pass. Pay attention to `test_save_config`, `test_external_hooks_survive_a_full_save_load_cycle` and `test_context_inject_repo_map_survives_round_trip`, which exercised the old writer.

- [ ] **Step 5: Prove the fix is load-bearing**

Temporarily revert `save_config` to `path.write_bytes(tomli_w.dumps(_config_to_dict(cfg)).encode())`, run the three tests, confirm all three fail, then restore. A guard whose removal breaks nothing was never guarding anything.

- [ ] **Step 6: Commit**

```bash
git add src/lazy_harness/core/config.py
git commit -m "fix: preserve unmodelled sections and comments when writing config"
```

---

### Task 6: Prove profile deletion still works

Guards the one place where merge semantics and deletion semantics disagree.

**Files:**
- Test: `tests/unit/test_config.py`

- [ ] **Step 1: Write the test**

```python
def test_removing_a_profile_survives_a_save(tmp_path: Path) -> None:
    """`lh profile remove` expresses deletion by absence; the merge must honour it."""
    import tomllib

    from lazy_harness.core.config import load_config, save_config

    cfg_path = tmp_path / "config.toml"
    cfg_path.write_text(_FULL_CONFIG)

    cfg = load_config(cfg_path)
    del cfg.profiles.items["flex"]
    save_config(cfg, cfg_path)

    raw = tomllib.loads(cfg_path.read_text())
    assert "flex" not in raw["profiles"]
    assert "lazy" in raw["profiles"]
    assert raw["profiles"]["lazy"]["lazynorth_doc"] == "LazyNorth.md"
```

- [ ] **Step 2: Run it**

Run: `uv run pytest tests/unit/test_config.py::test_removing_a_profile_survives_a_save -v`
Expected: PASS.

- [ ] **Step 3: Confirm it is load-bearing**

Comment out the `_prune_removed_profiles(doc, cfg)` call, re-run, confirm FAIL, restore.

- [ ] **Step 4: Commit**

```bash
git add tests/unit/test_config.py
git commit -m "test: profile removal survives the read-modify-write save"
```

---

### Task 7: Close the `[context_inject]` parse gap

Three fields are declared on the dataclass and read by `hooks/builtins/context_inject.py` at lines 779, 787 and 790, and `load_config` never populates them from the file. They are pinned to their defaults with no way to change them.

**Files:**
- Modify: `src/lazy_harness/core/config.py` — the `ci_raw` block in `load_config`
- Test: `tests/unit/test_config.py`

- [ ] **Step 1: Write the failing test**

```python
def test_context_inject_qmd_and_graphify_switches_are_read(tmp_path: Path) -> None:
    """These three are consumed by context_inject.py:779,787,790 and were never parsed."""
    from lazy_harness.core.config import load_config

    cfg_path = tmp_path / "config.toml"
    cfg_path.write_text(
        '[harness]\nversion = "1"\n\n'
        "[context_inject]\n"
        "qmd_suggest_enabled = false\n"
        "qmd_suggest_top_k = 7\n"
        "graphify_surface_enabled = false\n"
    )

    ci = load_config(cfg_path).context_inject
    assert ci.qmd_suggest_enabled is False
    assert ci.qmd_suggest_top_k == 7
    assert ci.graphify_surface_enabled is False
```

- [ ] **Step 2: Run it and confirm it fails**

Run: `uv run pytest tests/unit/test_config.py::test_context_inject_qmd_and_graphify_switches_are_read -v`
Expected: FAIL — `assert True is False`.

- [ ] **Step 3: Add the three keys to the parse block**

In `load_config`, inside `cfg.context_inject = ContextInjectConfig(...)`, add:

```python
            qmd_suggest_enabled=ci_raw.get(
                "qmd_suggest_enabled", ContextInjectConfig.qmd_suggest_enabled
            ),
            qmd_suggest_top_k=ci_raw.get(
                "qmd_suggest_top_k", ContextInjectConfig.qmd_suggest_top_k
            ),
            graphify_surface_enabled=ci_raw.get(
                "graphify_surface_enabled", ContextInjectConfig.graphify_surface_enabled
            ),
```

- [ ] **Step 4: Run it**

Run: `uv run pytest tests/unit/test_config.py::test_context_inject_qmd_and_graphify_switches_are_read -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/lazy_harness/core/config.py tests/unit/test_config.py
git commit -m "fix: read the three [context_inject] switches the loader ignored"
```

---

### Task 8: Selftest check — every key survives a round trip

The permanent net. This check would have caught all 51 keys and all three ignored switches, and it will catch section 15 when someone adds it.

**Files:**
- Modify: `src/lazy_harness/selftest/checks/config_check.py`
- Test: `tests/unit/selftest/test_checks_config.py`
- Modify: `src/lazy_harness/cli/selftest_cmd.py` (register the check, if it is not already registered via `config_check`)

**Interfaces:**
- Consumes: `CheckResult`, `CheckStatus` from `lazy_harness.selftest.result`
- Produces: `check_config_round_trip(*, config_path: Path) -> list[CheckResult]`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/selftest/test_checks_config.py`:

```python
from __future__ import annotations

from pathlib import Path

from lazy_harness.selftest.result import CheckStatus


def test_round_trip_check_warns_when_there_is_no_config(tmp_path: Path) -> None:
    """CheckStatus has no SKIPPED member; absence warns rather than failing."""
    from lazy_harness.selftest.checks.config_check import check_config_round_trip

    results = check_config_round_trip(config_path=tmp_path / "absent.toml")
    assert [r.status for r in results] == [CheckStatus.WARNING]


def test_round_trip_check_passes_on_a_full_config(tmp_path: Path) -> None:
    from lazy_harness.selftest.checks.config_check import check_config_round_trip

    cfg_path = tmp_path / "config.toml"
    cfg_path.write_text(
        '[harness]\nversion = "1"\n\n'
        "[compound_loop]\nenabled = true\n\n"
        '[scheduler.jobs.qmd-sync]\nschedule = "0 */6 * * *"\ncommand = "qmd sync"\n'
    )

    results = check_config_round_trip(config_path=cfg_path)
    assert [r.status for r in results] == [CheckStatus.PASSED]


def test_round_trip_check_names_the_lost_keys(tmp_path: Path, monkeypatch) -> None:
    """A writer that drops a section must fail the check and name what it dropped."""
    from lazy_harness.core import config as config_mod
    from lazy_harness.selftest.checks.config_check import check_config_round_trip

    cfg_path = tmp_path / "config.toml"
    cfg_path.write_text(
        '[harness]\nversion = "1"\n\n[compound_loop]\nenabled = true\n'
    )

    def lossy(cfg):  # noqa: ANN001, ANN202
        return {"harness": {"version": cfg.harness.version}}

    monkeypatch.setattr(config_mod, "_config_to_dict", lossy)

    results = check_config_round_trip(config_path=cfg_path)
    assert results[0].status == CheckStatus.FAILED
    assert "compound_loop" in results[0].message
```

- [ ] **Step 2: Run and confirm both fail**

Run: `uv run pytest tests/unit/selftest/test_checks_config.py -v`
Expected: all three FAIL with `ImportError` / `cannot import name 'check_config_round_trip'`.

- [ ] **Step 3: Implement the check**

Append to `src/lazy_harness/selftest/checks/config_check.py`:

```python
def check_config_round_trip(*, config_path: Path) -> list[CheckResult]:
    """Verify that writing the config back preserves every key it started with.

    A writer that silently drops a section is invisible until the day a
    command rewrites the file. This is the net for that.
    """
    import shutil
    import tempfile
    import tomllib

    from lazy_harness.core.config import ConfigError, load_config, save_config

    group = "config"
    if not config_path.is_file():
        # CheckStatus has exactly three members — PASSED, FAILED, WARNING.
        # There is no SKIPPED; a missing config is the neighbouring checks'
        # problem to report, so this one warns rather than failing the run.
        return [
            CheckResult(
                group=group,
                name="round-trip",
                status=CheckStatus.WARNING,
                message=f"no config at {config_path}",
            )
        ]

    def flat(data: dict, prefix: str = "") -> set[str]:
        out: set[str] = set()
        for key, value in data.items():
            path = f"{prefix}{key}"
            out.add(path)
            if isinstance(value, dict):
                out |= flat(value, path + ".")
        return out

    try:
        before = flat(tomllib.loads(config_path.read_text(encoding="utf-8")))
        with tempfile.TemporaryDirectory() as td:
            probe = Path(td) / "config.toml"
            shutil.copyfile(config_path, probe)
            save_config(load_config(probe), probe)
            after = flat(tomllib.loads(probe.read_text(encoding="utf-8")))
    except (ConfigError, OSError, tomllib.TOMLDecodeError) as e:
        return [
            CheckResult(
                group=group,
                name="round-trip",
                status=CheckStatus.FAILED,
                message=f"round-trip probe failed: {e}",
            )
        ]

    lost = sorted(before - after)
    if lost:
        shown = ", ".join(lost[:8]) + (f" (+{len(lost) - 8} more)" if len(lost) > 8 else "")
        return [
            CheckResult(
                group=group,
                name="round-trip",
                status=CheckStatus.FAILED,
                message=f"save_config would drop {len(lost)} keys: {shown}",
            )
        ]
    return [
        CheckResult(
            group=group,
            name="round-trip",
            status=CheckStatus.PASSED,
            message=f"{len(before)} keys survive a write",
        )
    ]
```

The probe runs against a **copy in a temp dir**. It must never write to the user's real config — a health check that mutates what it checks is not a health check.

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/unit/selftest/test_checks_config.py -v`
Expected: 3 PASSED.

- [ ] **Step 5: Register the check in the selftest runner**

A check that is implemented but not registered passes every test and never runs. In `src/lazy_harness/cli/selftest_cmd.py`, extend the import on line 10 and add one lambda to the checks list, immediately after the existing `check_config` entry on line 29:

```python
from lazy_harness.selftest.checks.config_check import check_config, check_config_round_trip
```

```python
            lambda: check_config(config_path=cfg_path),
            lambda: check_config_round_trip(config_path=cfg_path),
```

- [ ] **Step 6: Verify it runs end-to-end against the real config**

Run: `uv run lh selftest 2>&1 | grep -A1 round-trip`
Expected: a `config / round-trip` row reporting PASSED with a key count. If it reports FAILED, the fix is incomplete — read the named keys and extend `_config_to_dict`.

- [ ] **Step 7: Commit**

```bash
git add src/lazy_harness/selftest/checks/config_check.py \
        src/lazy_harness/cli/selftest_cmd.py \
        tests/unit/selftest/test_checks_config.py
git commit -m "feat: selftest check that config survives a write round trip"
```

---

### Task 9: Retire the workarounds

Two helpers exist only because `save_config` was destructive. Leaving them keeps two ways to write config, which is how they drift.

**Files:**
- Modify: `src/lazy_harness/cli/knowledge_cmd.py:367` `_write_repo_list`
- Leave: `src/lazy_harness/wizards/_toml_merge.py`

**Interfaces:**
- Consumes: `save_config` from Task 5

- [ ] **Step 1: Check what `_write_repo_list` is tested by**

Run: `uv run pytest -k repo_list -v --collect-only`

Note the test names. They pin the current behaviour and must still pass after the change.

- [ ] **Step 2: Replace the hand-rolled line rewrite**

`_write_repo_list` becomes:

```python
def _write_repo_list(cfg_path: Path, repos: list[str]) -> None:
    """Persist the graphify repo list.

    Was a hand-rolled single-line rewrite because `save_config` destroyed
    comments and unmodelled keys. It no longer does.
    """
    from lazy_harness.core.config import load_config, save_config

    cfg = load_config(cfg_path)
    cfg.knowledge.structure.repos = list(repos)
    save_config(cfg, cfg_path)
```

- [ ] **Step 3: Run the repo-list tests plus the full suite**

Run: `uv run pytest -k repo_list -v && uv run pytest -q`
Expected: all pass.

- [ ] **Step 4: Verify against a real config with comments**

```bash
cp ~/.config/lazy-harness/config.toml /tmp/probe.toml
uv run python -c "
from pathlib import Path
from lazy_harness.cli.knowledge_cmd import _write_repo_list
_write_repo_list(Path('/tmp/probe.toml'), ['~/repos/lazy/lazy-harness'])
"
diff ~/.config/lazy-harness/config.toml /tmp/probe.toml
```
Expected: only the `repos` line differs. Every comment intact.

`wizards/_toml_merge.py` stays. The wizards merge a *partial* block without loading a full `Config`, which is a different operation from persisting one — that helper is not a workaround, it is its own thing.

- [ ] **Step 5: Commit**

```bash
git add src/lazy_harness/cli/knowledge_cmd.py
git commit -m "refactor: use save_config for the graphify repo list"
```

---

### Task 10: Full gate and PR

- [ ] **Step 1: Run `/tdd-check`**

```bash
uv run pytest && uv run ruff check src tests && uv run --group docs mkdocs build --strict
```
All three must pass with pristine output.

- [ ] **Step 2: Run the acceptance gate against the real config**

This is the check that matters more than the suite — a fixture proves the logic, this proves the outcome.

```bash
cp ~/.config/lazy-harness/config.toml /tmp/cfg-before.toml
cp /tmp/cfg-before.toml /tmp/cfg-after.toml
uv run python -c "
from pathlib import Path
from lazy_harness.core.config import load_config, save_config
p = Path('/tmp/cfg-after.toml')
save_config(load_config(p), p)
"
diff /tmp/cfg-before.toml /tmp/cfg-after.toml
```
Expected: no removed lines, all 7 comments present. Formatting differences on rewritten values are acceptable; a missing key or comment is not.

- [ ] **Step 3: Push and open the PR**

```bash
gh auth switch --user lazynet
git push -u origin fix/config-round-trip
gh pr create --title "fix: preserve unmodelled sections and comments when writing config" \
  --body "$(cat <<'EOF'
`save_config` emitted 10 of the 14 sections `load_config` reads. Measured
against the live config: **51 keys lost per write**, including all six
declared `[scheduler.jobs.*]`, the whole of `[compound_loop]`,
`[memory.engram]` and `[lazynorth]`, and `hooks.pre_tool_use.allow_patterns`.
Comments were lost too — the live config carries seven lines of operational
rationale.

Fix: read-modify-write over a `tomlkit` document, plus a completed
`_config_to_dict` so deletion inside a modelled section still takes effect.
`lh profile remove` is covered by an explicit prune and its own test.

Also closes an independent gap: `qmd_suggest_enabled`, `qmd_suggest_top_k`
and `graphify_surface_enabled` are read by `context_inject.py:779,787,790`
and were never parsed from the file, pinning them to their defaults.

New `lh selftest` check asserts every key survives a write. It fails on the
pre-fix writer naming the dropped keys.

Retires the `_write_repo_list` hand-rolled line rewrite, which existed only
to route around the destructive writer.
EOF
)"
gh auth switch --user mvago-flx
```

- [ ] **Step 4: After merge, follow the deploy procedure**

See [`2026-08-17-refactor-release-train.md`](2026-08-17-refactor-release-train.md), Deploy procedure. The wave-1 grep string for step 4 is `_prune_removed_profiles`.

---

## Self-review

**Spec coverage.** D5's three required tests are Tasks 1 (no key loss), 3 (double round trip) and the existing round-trip tests that stay green in Task 5 Step 4. The `[context_inject]` gap is Task 7. The selftest net that D4 anticipated is Task 8. Task 2 (comments) and Task 6 (deletion) are additions the spec did not anticipate; both are recorded in "Deviation from the spec".

**Placeholders.** None. Every code step carries the code.

**Type consistency.** `_apply(doc, overlay) -> None`, `_prune_removed_profiles(doc, cfg) -> None`, `save_config(cfg, path) -> None`, `check_config_round_trip(*, config_path) -> list[CheckResult]`. `save_config`'s signature is unchanged, so `cli/profile_cmd.py:103,340` need no edit.

**Open risk.** `tomlkit` re-serialises values it rewrites, so formatting inside a modified table may change even where the value did not. The Task 10 Step 2 diff is where that is inspected. If the churn is unacceptable, narrow `_apply` to assign only leaves whose value actually differs from the parsed document.

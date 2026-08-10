# Knowledge Store Extraction Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move agent-generated sessions and learnings out of the Obsidian vault into a dedicated multi-writer git repository, with a self-describing marker file as the single declaration of the store's structure.

**Architecture:** The harness owns the contract. A `knowledge.toml` marker at the repository root declares subdirectory names; every consumer resolves only the *root* (env var, own config, or default) and reads structure from the marker. Producers never touch git — a scheduler job commits and pushes on its own cycle.

**Tech Stack:** Python 3.11+, `uv`, `pytest`, `ruff`, `click`, `tomllib` (read) / `tomli-w` (write), `fcntl.flock`, MkDocs Material.

**Design spec:** [`2026-08-10-knowledge-store-extraction-design.md`](2026-08-10-knowledge-store-extraction-design.md)

## Global Constraints

- **Worktree for every code change.** `.worktrees/<short-name>` on `<type>/<short-name>`, never directly on `main`. See `specs/workflow/worktrees.md`.
- **Strict TDD, no exceptions.** No production code without a failing test that exercises it first.
- **Conventional commits, no AI trailers.** `type: short description`. No `Co-Authored-By`. No `--no-verify`.
- **Pre-commit gate is all three:** `uv run pytest`, `uv run ruff check src tests`, `uv run --group docs mkdocs build --strict`.
- **Never hand-bump versions.** release-please owns `pyproject.toml` and `src/lazy_harness/__init__.py`.
- **Public repository.** No personal names, no absolute `/Users/...` paths, no PII in code, tests, docs, or commit messages.
- **Marker filename is `knowledge.toml`; marker schema `version = 1`.**
- **Subdirectory names are lowercase: `sessions`, `learnings`.** The pre-migration `Learnings` capitalisation is a bug being fixed, not a value to preserve.
- **Module is `knowledge/marker.py`, not `contract.py`.** `core/paths.py:89` already exports `contract_path()`, which means "abbreviate a path with `~`". A second, unrelated "contract" would be a naming collision.
- **Tests mirror source one-to-one** under `tests/unit/test_<module>.py`.

---

## Phase map

This plan covers **Phase 1 only** — the `lazy-harness` code. The surrounding phases are coordinated from the driving session and are listed here so an implementer knows what they can and cannot assume.

| Phase | Owner | Content |
|---|---|---|
| 0 | driving session | Create `lazy-knowledge`, write the marker, `cp -a` the data |
| **1** | **this plan** | **harness: marker, config, directory, naming, push, CLI, docs** |
| 2 | `lazy-ai-tools` plan | `KnowledgeConfig`, `relative_to` fix |
| 3 | `lazy-hermes` plan + driving session | Marge's soul, `index.yml`, `LazyMind/CLAUDE.md` |
| 4 | driving session | Verification |
| 5 | driving session | Delete from the vault |

**Phase 0 is already complete when you start.** You can assume `~/repos/lazy/lazy-knowledge/knowledge.toml` exists on disk. Do not create, move, or delete any data files — this plan is code only.

## File structure

| File | Responsibility |
|---|---|
| `src/lazy_harness/knowledge/marker.py` | **new** — read, write, validate `knowledge.toml`; resolve the root |
| `src/lazy_harness/knowledge/git_push.py` | **new** — one commit/rebase/push cycle under `flock` |
| `src/lazy_harness/core/config.py` | `KnowledgeConfig.root`; drop the `subdir` fields |
| `src/lazy_harness/knowledge/directory.py` | Resolve paths from the marker |
| `src/lazy_harness/knowledge/compound_loop.py:872-879` | Host-suffixed learning filenames |
| `src/lazy_harness/knowledge/compound_loop_worker.py:55-66` | `_resolve_learnings_dir` via marker |
| `src/lazy_harness/monitoring/views/_helpers.py:47` | Same resolution |
| `src/lazy_harness/migrate/` | `config.toml` shape migration |
| `src/lazy_harness/cli/knowledge_cmd.py` | `init`, `path`, `push` subcommands |
| `docs/reference/cli.md`, `docs/architecture/memory-compound.md` | Non-negotiable #6 |

---

### Task 1: Marker read/write/validate

**Files:**
- Create: `src/lazy_harness/knowledge/marker.py`
- Test: `tests/unit/test_knowledge_marker.py`

**Interfaces:**
- Consumes: `lazy_harness.core.paths.expand_path`
- Produces:
  - `MARKER_FILENAME: str = "knowledge.toml"`
  - `MARKER_VERSION: int = 1`
  - `class MarkerError(Exception)`
  - `@dataclass(frozen=True) class KnowledgeMarker: sessions: str; learnings: str`
  - `read_marker(root: Path) -> KnowledgeMarker`
  - `write_marker(root: Path) -> Path`
  - `resolve_root(configured: str | None = None) -> Path`
  - `DEFAULT_ROOT: str = "~/repos/lazy/lazy-knowledge"`

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_knowledge_marker.py`:

```python
"""Tests for the knowledge store marker file."""

from __future__ import annotations

from pathlib import Path

import pytest


def _write(root: Path, body: str) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / "knowledge.toml").write_text(body, encoding="utf-8")


def test_read_marker_returns_declared_subdirs(tmp_path: Path) -> None:
    from lazy_harness.knowledge.marker import read_marker

    _write(
        tmp_path,
        '[knowledge]\nversion = 1\nsessions = "sessions"\nlearnings = "learnings"\n',
    )
    marker = read_marker(tmp_path)
    assert marker.sessions == "sessions"
    assert marker.learnings == "learnings"


def test_read_marker_missing_file_raises(tmp_path: Path) -> None:
    from lazy_harness.knowledge.marker import MarkerError, read_marker

    with pytest.raises(MarkerError, match="no knowledge.toml"):
        read_marker(tmp_path)


def test_read_marker_unknown_version_raises(tmp_path: Path) -> None:
    from lazy_harness.knowledge.marker import MarkerError, read_marker

    _write(
        tmp_path,
        '[knowledge]\nversion = 99\nsessions = "s"\nlearnings = "l"\n',
    )
    with pytest.raises(MarkerError, match="version 99"):
        read_marker(tmp_path)


def test_read_marker_missing_field_raises_not_empty_string(tmp_path: Path) -> None:
    from lazy_harness.knowledge.marker import MarkerError, read_marker

    _write(tmp_path, '[knowledge]\nversion = 1\nsessions = "sessions"\n')
    with pytest.raises(MarkerError, match="learnings"):
        read_marker(tmp_path)


def test_read_marker_rejects_absolute_subdir(tmp_path: Path) -> None:
    from lazy_harness.knowledge.marker import MarkerError, read_marker

    _write(
        tmp_path,
        '[knowledge]\nversion = 1\nsessions = "/etc"\nlearnings = "learnings"\n',
    )
    with pytest.raises(MarkerError, match="must be relative"):
        read_marker(tmp_path)


def test_read_marker_rejects_escaping_subdir(tmp_path: Path) -> None:
    from lazy_harness.knowledge.marker import MarkerError, read_marker

    _write(
        tmp_path,
        '[knowledge]\nversion = 1\nsessions = "../out"\nlearnings = "learnings"\n',
    )
    with pytest.raises(MarkerError, match="must be relative"):
        read_marker(tmp_path)


def test_write_marker_roundtrips(tmp_path: Path) -> None:
    from lazy_harness.knowledge.marker import read_marker, write_marker

    path = write_marker(tmp_path)
    assert path == tmp_path / "knowledge.toml"
    marker = read_marker(tmp_path)
    assert marker.sessions == "sessions"
    assert marker.learnings == "learnings"


def test_resolve_root_prefers_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from lazy_harness.knowledge.marker import resolve_root

    monkeypatch.setenv("LAZY_KNOWLEDGE_ROOT", str(tmp_path))
    assert resolve_root("~/somewhere/else") == tmp_path.resolve()


def test_resolve_root_falls_back_to_configured(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from lazy_harness.knowledge.marker import resolve_root

    monkeypatch.delenv("LAZY_KNOWLEDGE_ROOT", raising=False)
    assert resolve_root(str(tmp_path)) == tmp_path.resolve()


def test_resolve_root_default_when_nothing_set(monkeypatch: pytest.MonkeyPatch) -> None:
    from lazy_harness.knowledge.marker import DEFAULT_ROOT, resolve_root
    from lazy_harness.core.paths import expand_path

    monkeypatch.delenv("LAZY_KNOWLEDGE_ROOT", raising=False)
    assert resolve_root(None) == expand_path(DEFAULT_ROOT)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_knowledge_marker.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'lazy_harness.knowledge.marker'`

- [ ] **Step 3: Write the implementation**

Create `src/lazy_harness/knowledge/marker.py`:

```python
"""The knowledge store's self-describing marker file.

The store declares its own structure in `knowledge.toml` at its root. Consumers
resolve only the root — from the environment, their own config, or the default —
and read subdirectory names from here. That split keeps the environmental part
(where the store lives, which differs per machine) separate from the global part
(how it is laid out, which must not).
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass
from pathlib import Path

from lazy_harness.core.paths import expand_path

MARKER_FILENAME = "knowledge.toml"
MARKER_VERSION = 1
DEFAULT_ROOT = "~/repos/lazy/lazy-knowledge"
ENV_VAR = "LAZY_KNOWLEDGE_ROOT"


class MarkerError(Exception):
    """The marker is absent, unreadable, or declares something unusable."""


@dataclass(frozen=True)
class KnowledgeMarker:
    sessions: str
    learnings: str


def _require_relative(name: str, value: str) -> str:
    candidate = Path(value)
    if candidate.is_absolute() or ".." in candidate.parts:
        raise MarkerError(f"{MARKER_FILENAME}: [knowledge].{name} must be relative to the root")
    return value


def read_marker(root: Path) -> KnowledgeMarker:
    """Read and validate the marker at `root`.

    Every failure is loud. A missing field must never read as "" — that would
    silently land files at the repository root.
    """
    path = root / MARKER_FILENAME
    if not path.is_file():
        raise MarkerError(f"no {MARKER_FILENAME} at {root}")

    try:
        with open(path, "rb") as f:
            raw = tomllib.load(f)
    except (OSError, tomllib.TOMLDecodeError) as e:
        raise MarkerError(f"{path}: unreadable ({e})") from e

    block = raw.get("knowledge", {})
    version = block.get("version")
    if version != MARKER_VERSION:
        raise MarkerError(
            f"{path}: version {version} is not supported (this build expects {MARKER_VERSION})"
        )

    values = {}
    for name in ("sessions", "learnings"):
        value = block.get(name)
        if not isinstance(value, str) or not value:
            raise MarkerError(f"{path}: [knowledge].{name} is missing or empty")
        values[name] = _require_relative(name, value)

    return KnowledgeMarker(sessions=values["sessions"], learnings=values["learnings"])


def write_marker(root: Path) -> Path:
    """Write a fresh version-1 marker at `root` and return its path."""
    root.mkdir(parents=True, exist_ok=True)
    path = root / MARKER_FILENAME
    path.write_text(
        "[knowledge]\n"
        f"version   = {MARKER_VERSION}\n"
        'sessions  = "sessions"\n'
        'learnings = "learnings"\n',
        encoding="utf-8",
    )
    return path


def resolve_root(configured: str | None = None) -> Path:
    """Resolve the store root: env var, then configured value, then default."""
    return expand_path(os.environ.get(ENV_VAR) or configured or DEFAULT_ROOT)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_knowledge_marker.py -v`
Expected: PASS, 10 tests

- [ ] **Step 5: Lint**

Run: `uv run ruff check src tests`
Expected: `All checks passed!`

- [ ] **Step 6: Commit**

```bash
git add src/lazy_harness/knowledge/marker.py tests/unit/test_knowledge_marker.py
git commit -m "feat: add knowledge store marker with strict validation"
```

---

### Task 2: `KnowledgeConfig.root` and config migration

**Files:**
- Modify: `src/lazy_harness/core/config.py` (`KnowledgeConfig`, `CompoundLoopConfig`, the parser near line 360, the serializer near line 465)
- Test: `tests/unit/test_config.py`

**Interfaces:**
- Consumes: nothing from Task 1 — the config layer only carries the root string.
- Produces:
  - `KnowledgeConfig.root: str` replaces `KnowledgeConfig.path`
  - `KnowledgeSessionsConfig` / `KnowledgeLearningsConfig` keep `enabled`, lose `subdir`
  - `CompoundLoopConfig.learnings_subdir` removed; `lazymind_dir` untouched

Reading `[knowledge].path` from an old config must raise a `ConfigError` naming the new key. A silent fallback would leave writes going to the vault while everything reports success.

- [ ] **Step 1: Write the failing tests**

Add to `tests/unit/test_config.py`:

```python
def test_knowledge_root_replaces_path(tmp_path: Path) -> None:
    from lazy_harness.core.config import load_config

    cfg_file = tmp_path / "config.toml"
    cfg_file.write_text(
        '[knowledge]\nroot = "~/repos/lazy/lazy-knowledge"\n', encoding="utf-8"
    )
    cfg = load_config(cfg_file)
    assert cfg.knowledge.root == "~/repos/lazy/lazy-knowledge"


def test_legacy_knowledge_path_raises_naming_new_key(tmp_path: Path) -> None:
    from lazy_harness.core.config import ConfigError, load_config

    cfg_file = tmp_path / "config.toml"
    cfg_file.write_text('[knowledge]\npath = "~/vault/Meta"\n', encoding="utf-8")
    with pytest.raises(ConfigError, match="root"):
        load_config(cfg_file)


def test_legacy_learnings_subdir_raises(tmp_path: Path) -> None:
    from lazy_harness.core.config import ConfigError, load_config

    cfg_file = tmp_path / "config.toml"
    cfg_file.write_text(
        '[knowledge]\nroot = "~/k"\n\n[compound_loop]\nlearnings_subdir = "Learnings"\n',
        encoding="utf-8",
    )
    with pytest.raises(ConfigError, match="learnings_subdir"):
        load_config(cfg_file)


def test_compound_loop_lazymind_dir_survives(tmp_path: Path) -> None:
    from lazy_harness.core.config import load_config

    cfg_file = tmp_path / "config.toml"
    cfg_file.write_text(
        '[knowledge]\nroot = "~/k"\n\n[compound_loop]\nlazymind_dir = "~/vault"\n',
        encoding="utf-8",
    )
    cfg = load_config(cfg_file)
    assert cfg.compound_loop.lazymind_dir == "~/vault"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_config.py -k "knowledge_root or legacy or lazymind_dir_survives" -v`
Expected: FAIL — `AttributeError: 'KnowledgeConfig' object has no attribute 'root'`

- [ ] **Step 3: Update the dataclasses**

In `src/lazy_harness/core/config.py`, change `KnowledgeConfig`'s `path: str = ""` to `root: str = ""`, delete `subdir` from `KnowledgeSessionsConfig` and `KnowledgeLearningsConfig`, and delete `learnings_subdir` from `CompoundLoopConfig` (line 151). Leave `lazymind_dir` (line 154) exactly as it is.

- [ ] **Step 4: Update the parser**

Replace the `cfg.knowledge = KnowledgeConfig(...)` block near line 360:

```python
    if "path" in knowledge_raw:
        raise ConfigError(
            "[knowledge].path was replaced by [knowledge].root, which points at the "
            "knowledge store repository rather than a vault subdirectory. "
            "Run `lh migrate config` to update."
        )
    for legacy in ("sessions", "learnings"):
        if "subdir" in (knowledge_raw.get(legacy) or {}):
            raise ConfigError(
                f"[knowledge.{legacy}].subdir was removed; knowledge.toml in the store "
                "declares the layout now. Run `lh migrate config`."
            )

    cfg.knowledge = KnowledgeConfig(
        root=knowledge_raw.get("root", ""),
        sessions=KnowledgeSessionsConfig(**knowledge_raw.get("sessions", {})),
        learnings=KnowledgeLearningsConfig(**knowledge_raw.get("learnings", {})),
        search=KnowledgeSearchConfig(**knowledge_raw.get("search", {})),
        structure=_parse_structure(knowledge_raw.get("structure", {})),
    )
```

And in the `[compound_loop]` parse near line 411, replace the `learnings_subdir=` argument with a guard before the constructor:

```python
    if "learnings_subdir" in cl_raw:
        raise ConfigError(
            "[compound_loop].learnings_subdir was removed; knowledge.toml in the store "
            "declares the layout now. Run `lh migrate config`."
        )
```

- [ ] **Step 5: Update the serializer**

Near line 465, change `"path": cfg.knowledge.path` to `"root": cfg.knowledge.root`, and drop both `"subdir"` entries from the `sessions` and `learnings` sub-dicts.

- [ ] **Step 6: Run the full suite**

Run: `uv run pytest`
Expected: the four new tests pass. Other tests referencing `knowledge.path` or `learnings_subdir` will fail — fix each to the new shape. Do not add compatibility shims.

- [ ] **Step 7: Lint and commit**

```bash
uv run ruff check src tests
git add src/lazy_harness/core/config.py tests/unit/test_config.py
git commit -m "feat!: replace knowledge.path with knowledge.root"
```

---

### Task 3: Resolve directories from the marker

**Files:**
- Modify: `src/lazy_harness/knowledge/directory.py`
- Test: `tests/unit/test_knowledge_dir.py`

**Interfaces:**
- Consumes: `read_marker`, `resolve_root`, `write_marker`, `KnowledgeMarker` from Task 1; `KnowledgeConfig.root` from Task 2
- Produces:
  - `ensure_knowledge_dir(root: str | Path) -> Path` — creates the store *and* its marker if absent
  - `sessions_dir(root: Path) -> Path`
  - `learnings_dir(root: Path) -> Path`
  - `session_export_path(root, date_str, session_id) -> Path` — **signature change**, the `subdir` parameter is gone
  - `list_sessions(root: Path) -> list[Path]` — **signature change**, `subdir` gone

- [ ] **Step 1: Write the failing tests**

Replace the body of `tests/unit/test_knowledge_dir.py`:

```python
"""Tests for knowledge directory management."""

from __future__ import annotations

from pathlib import Path


def test_ensure_knowledge_dir_creates_marker_and_subdirs(tmp_path: Path) -> None:
    from lazy_harness.knowledge.directory import ensure_knowledge_dir

    root = ensure_knowledge_dir(tmp_path / "store")
    assert (root / "knowledge.toml").is_file()
    assert (root / "sessions").is_dir()
    assert (root / "learnings").is_dir()


def test_ensure_knowledge_dir_is_idempotent(tmp_path: Path) -> None:
    from lazy_harness.knowledge.directory import ensure_knowledge_dir

    first = ensure_knowledge_dir(tmp_path / "store")
    (first / "knowledge.toml").write_text(
        '[knowledge]\nversion = 1\nsessions = "s"\nlearnings = "l"\n', encoding="utf-8"
    )
    second = ensure_knowledge_dir(tmp_path / "store")
    assert second == first
    assert (second / "s").is_dir()


def test_subdir_names_come_from_the_marker(tmp_path: Path) -> None:
    from lazy_harness.knowledge.directory import learnings_dir, sessions_dir

    root = tmp_path / "store"
    root.mkdir()
    (root / "knowledge.toml").write_text(
        '[knowledge]\nversion = 1\nsessions = "logs"\nlearnings = "lessons"\n',
        encoding="utf-8",
    )
    assert sessions_dir(root).name == "logs"
    assert learnings_dir(root).name == "lessons"


def test_session_export_path_buckets_by_year_month(tmp_path: Path) -> None:
    from lazy_harness.knowledge.directory import ensure_knowledge_dir, session_export_path

    root = ensure_knowledge_dir(tmp_path / "store")
    path = session_export_path(root, "2026-08-10", "abcdef1234567890")
    assert path == root / "sessions" / "2026-08" / "2026-08-10-abcdef12.md"
    assert path.parent.is_dir()


def test_list_sessions_newest_first(tmp_path: Path) -> None:
    from lazy_harness.knowledge.directory import ensure_knowledge_dir, list_sessions

    root = ensure_knowledge_dir(tmp_path / "store")
    bucket = root / "sessions" / "2026-08"
    bucket.mkdir(parents=True)
    (bucket / "2026-08-01-aaaaaaaa.md").write_text("a", encoding="utf-8")
    (bucket / "2026-08-09-bbbbbbbb.md").write_text("b", encoding="utf-8")
    names = [p.name for p in list_sessions(root)]
    assert names == ["2026-08-09-bbbbbbbb.md", "2026-08-01-aaaaaaaa.md"]


def test_list_sessions_empty_when_absent(tmp_path: Path) -> None:
    from lazy_harness.knowledge.directory import ensure_knowledge_dir, list_sessions

    root = ensure_knowledge_dir(tmp_path / "store")
    (root / "sessions").rmdir()
    assert list_sessions(root) == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_knowledge_dir.py -v`
Expected: FAIL — `ImportError: cannot import name 'sessions_dir'`

- [ ] **Step 3: Write the implementation**

Replace `src/lazy_harness/knowledge/directory.py`:

```python
"""Knowledge store layout — resolve paths from the store's own marker."""

from __future__ import annotations

from pathlib import Path

from lazy_harness.core.paths import expand_path
from lazy_harness.knowledge.marker import MARKER_FILENAME, read_marker, write_marker


def ensure_knowledge_dir(root: str | Path) -> Path:
    """Create the store, its marker, and the declared subdirectories."""
    kdir = expand_path(root)
    kdir.mkdir(parents=True, exist_ok=True)
    if not (kdir / MARKER_FILENAME).is_file():
        write_marker(kdir)
    marker = read_marker(kdir)
    (kdir / marker.sessions).mkdir(exist_ok=True)
    (kdir / marker.learnings).mkdir(exist_ok=True)
    return kdir


def sessions_dir(root: Path) -> Path:
    return root / read_marker(root).sessions


def learnings_dir(root: Path) -> Path:
    return root / read_marker(root).learnings


def session_export_path(root: Path, date_str: str, session_id: str) -> Path:
    export_dir = sessions_dir(root) / date_str[:7]
    export_dir.mkdir(parents=True, exist_ok=True)
    return export_dir / f"{date_str}-{session_id[:8]}.md"


def list_sessions(root: Path) -> list[Path]:
    target = sessions_dir(root)
    if not target.is_dir():
        return []
    return sorted(target.rglob("*.md"), reverse=True)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_knowledge_dir.py -v`
Expected: PASS, 6 tests

- [ ] **Step 5: Fix the callers**

Run: `uv run pytest` — `session_export.py`, `knowledge_cmd.py`, and `test_builtin_session_export.py` call the old signatures. Update each call site to drop the `subdir` argument and pass the store root.

- [ ] **Step 6: Lint and commit**

```bash
uv run ruff check src tests
git add src/lazy_harness/knowledge/directory.py tests/unit/test_knowledge_dir.py
git commit -m "feat: resolve knowledge subdirectories from the store marker"
```

---

### Task 4: Host-suffixed learning filenames

**Files:**
- Modify: `src/lazy_harness/knowledge/compound_loop.py:872-879`
- Test: `tests/unit/test_compound_loop.py`

**Interfaces:**
- Consumes: nothing from earlier tasks
- Produces: `origin_host() -> str` in `compound_loop.py`

Two machines writing the same day on similar topics produce identical `YYYY-MM-DD-<slug>.md` paths with different content — an add/add conflict on rebase. The host suffix makes the key unique by construction. The existing `if filepath.exists(): continue` dedup keeps working unchanged, because the host is constant within a machine.

- [ ] **Step 1: Write the failing tests**

Add to `tests/unit/test_compound_loop.py`:

```python
def test_origin_host_is_slugified_first_label(monkeypatch: pytest.MonkeyPatch) -> None:
    from lazy_harness.knowledge import compound_loop

    monkeypatch.setattr(compound_loop.platform, "node", lambda: "Some-Laptop.local")
    assert compound_loop.origin_host() == "some-laptop"


def test_origin_host_strips_unsafe_characters(monkeypatch: pytest.MonkeyPatch) -> None:
    from lazy_harness.knowledge import compound_loop

    monkeypatch.setattr(compound_loop.platform, "node", lambda: "box_01!.lan")
    assert compound_loop.origin_host() == "box-01"


def test_origin_host_raises_when_unresolvable(monkeypatch: pytest.MonkeyPatch) -> None:
    from lazy_harness.knowledge import compound_loop

    monkeypatch.setattr(compound_loop.platform, "node", lambda: "!!!")
    with pytest.raises(ValueError, match="host"):
        compound_loop.origin_host()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_compound_loop.py -k origin_host -v`
Expected: FAIL — `AttributeError: module ... has no attribute 'origin_host'`

- [ ] **Step 3: Implement `origin_host`**

Add `import platform` and `import re` to the imports of `compound_loop.py`, then:

```python
def origin_host() -> str:
    """Slugified first label of the machine's hostname.

    Used to make learning filenames unique per writer. An empty result is a hard
    error: an unsuffixed name is precisely the cross-machine collision this
    prevents.
    """
    label = platform.node().split(".")[0]
    slug = re.sub(r"[^a-z0-9]+", "-", label.lower()).strip("-")
    if not slug:
        raise ValueError(f"cannot derive an origin host slug from {platform.node()!r}")
    return slug
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_compound_loop.py -k origin_host -v`
Expected: PASS, 3 tests

- [ ] **Step 5: Write the failing test for the filename**

```python
def test_learning_filename_carries_origin_host(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from lazy_harness.knowledge import compound_loop

    monkeypatch.setattr(compound_loop, "origin_host", lambda: "some-laptop")
    learnings = tmp_path / "learnings"
    compound_loop.write_learnings(
        {"learnings": [{"title": "Use flock for locks", "tags": [], "scope": "universal"}]},
        learnings,
        "2026-08-10T12:00:00",
        "lazy-harness",
        tmp_path / "memory",
    )
    written = list((learnings / "2026-08").glob("*.md"))
    assert len(written) == 1
    assert written[0].name == "2026-08-10-use-flock-for-locks-some-laptop.md"
```

Adjust the call to match the real signature of the function containing line 872 — read it first and pass exactly what it takes.

- [ ] **Step 6: Run it, then change line 878**

Run: `uv run pytest tests/unit/test_compound_loop.py -k origin_host_filename -v` → FAIL.

Change line 878 from:

```python
        filepath = learnings_subdir / f"{date_str}-{_slugify(title)}.md"
```

to:

```python
        filepath = learnings_subdir / f"{date_str}-{_slugify(title)}-{origin_host()}.md"
```

- [ ] **Step 7: Run the full suite, lint, commit**

```bash
uv run pytest
uv run ruff check src tests
git add src/lazy_harness/knowledge/compound_loop.py tests/unit/test_compound_loop.py
git commit -m "feat: suffix learning filenames with the origin host"
```

---

### Task 5: Point the worker and the monitoring helper at the marker

**Files:**
- Modify: `src/lazy_harness/knowledge/compound_loop_worker.py:55-66`
- Modify: `src/lazy_harness/monitoring/views/_helpers.py:47`
- Test: `tests/unit/test_compound_loop_worker.py`

**Interfaces:**
- Consumes: `learnings_dir` from Task 3, `resolve_root` from Task 1, `KnowledgeConfig.root` from Task 2
- Produces: nothing new

The `LCT_LEARNINGS_DIR` back-compat branch at line 60 predates this design and points into the vault. It is removed — `LAZY_KNOWLEDGE_ROOT` is the supported override now.

- [ ] **Step 1: Write the failing tests**

Add to `tests/unit/test_compound_loop_worker.py`:

```python
def test_resolve_learnings_dir_uses_marker(tmp_path: Path, monkeypatch) -> None:
    from lazy_harness.core.config import Config
    from lazy_harness.knowledge.compound_loop_worker import _resolve_learnings_dir

    monkeypatch.delenv("LAZY_KNOWLEDGE_ROOT", raising=False)
    store = tmp_path / "store"
    store.mkdir()
    (store / "knowledge.toml").write_text(
        '[knowledge]\nversion = 1\nsessions = "sessions"\nlearnings = "lessons"\n',
        encoding="utf-8",
    )
    cfg = Config()
    cfg.knowledge.root = str(store)
    assert _resolve_learnings_dir(cfg) == store / "lessons"


def test_resolve_learnings_dir_ignores_removed_lct_env(tmp_path: Path, monkeypatch) -> None:
    from lazy_harness.core.config import Config
    from lazy_harness.knowledge.compound_loop_worker import _resolve_learnings_dir

    monkeypatch.delenv("LAZY_KNOWLEDGE_ROOT", raising=False)
    monkeypatch.setenv("LCT_LEARNINGS_DIR", str(tmp_path / "old-vault"))
    store = tmp_path / "store"
    store.mkdir()
    (store / "knowledge.toml").write_text(
        '[knowledge]\nversion = 1\nsessions = "sessions"\nlearnings = "learnings"\n',
        encoding="utf-8",
    )
    cfg = Config()
    cfg.knowledge.root = str(store)
    assert _resolve_learnings_dir(cfg) == store / "learnings"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_compound_loop_worker.py -k resolve_learnings -v`
Expected: FAIL — the second test returns the `LCT_LEARNINGS_DIR` path.

- [ ] **Step 3: Rewrite `_resolve_learnings_dir`**

Replace lines 55-66 of `compound_loop_worker.py`:

```python
def _resolve_learnings_dir(cfg: Config) -> Path:
    """Resolve where learnings land, from the store marker."""
    root = resolve_root(cfg.knowledge.root or None)
    return learnings_dir(root)
```

Add the imports, and drop the now-unused `os` import if nothing else in the module uses it.

- [ ] **Step 4: Apply the same change to the monitoring helper**

`monitoring/views/_helpers.py:47` currently builds `knowledge_path / cfg.compound_loop.learnings_subdir`. Replace it with `learnings_dir(resolve_root(cfg.knowledge.root or None))`.

- [ ] **Step 5: Run, lint, commit**

```bash
uv run pytest
uv run ruff check src tests
git add src/lazy_harness/knowledge/compound_loop_worker.py src/lazy_harness/monitoring/views/_helpers.py tests/unit/test_compound_loop_worker.py
git commit -m "feat: resolve learnings dir from the store marker"
```

---

### Task 6: The push cycle

**Files:**
- Create: `src/lazy_harness/knowledge/git_push.py`
- Test: `tests/unit/test_knowledge_push.py`

**Interfaces:**
- Consumes: `read_marker` from Task 1
- Produces:
  - `@dataclass(frozen=True) class PushResult: status: str; detail: str` where `status` is one of `"locked"`, `"clean"`, `"pushed"`, `"committed"`, `"conflict"`, `"invalid"`
  - `push_once(root: Path, host: str) -> PushResult`

`push_once` never raises for an expected failure — it returns a `PushResult` the CLI turns into an exit code. A rebase conflict aborts and stops; it is never auto-resolved.

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_knowledge_push.py`:

```python
"""Tests for the knowledge store push cycle."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest


def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True)


@pytest.fixture
def store(tmp_path: Path) -> Path:
    root = tmp_path / "store"
    root.mkdir()
    (root / "knowledge.toml").write_text(
        '[knowledge]\nversion = 1\nsessions = "sessions"\nlearnings = "learnings"\n',
        encoding="utf-8",
    )
    _git(root, "init", "-q", "-b", "main")
    _git(root, "config", "user.email", "test@example.invalid")
    _git(root, "config", "user.name", "test")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "init")
    return root


def test_clean_store_is_a_noop(store: Path) -> None:
    from lazy_harness.knowledge.git_push import push_once

    result = push_once(store, host="test-host")
    assert result.status == "clean"


def test_new_files_are_committed(store: Path) -> None:
    from lazy_harness.knowledge.git_push import push_once

    (store / "learnings").mkdir()
    (store / "learnings" / "a.md").write_text("x", encoding="utf-8")
    result = push_once(store, host="test-host")
    assert result.status in {"committed", "pushed"}
    log = subprocess.run(
        ["git", "-C", str(store), "log", "-1", "--format=%s"],
        capture_output=True, text=True, check=True,
    ).stdout
    assert "test-host" in log


def test_invalid_marker_stops_before_touching_git(store: Path) -> None:
    from lazy_harness.knowledge.git_push import push_once

    (store / "knowledge.toml").write_text(
        '[knowledge]\nversion = 99\nsessions = "s"\nlearnings = "l"\n', encoding="utf-8"
    )
    (store / "dirty.md").write_text("x", encoding="utf-8")
    result = push_once(store, host="test-host")
    assert result.status == "invalid"
    status = subprocess.run(
        ["git", "-C", str(store), "status", "--porcelain"],
        capture_output=True, text=True, check=True,
    ).stdout
    assert "dirty.md" in status


def test_held_lock_is_a_silent_noop(store: Path) -> None:
    import fcntl
    import os

    from lazy_harness.knowledge.git_push import push_once

    lock = store / ".push.lock"
    fd = os.open(str(lock), os.O_CREAT | os.O_WRONLY, 0o600)
    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    try:
        (store / "learnings.md").write_text("x", encoding="utf-8")
        assert push_once(store, host="test-host").status == "locked"
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


def test_no_remote_leaves_commits_local(store: Path) -> None:
    from lazy_harness.knowledge.git_push import push_once

    (store / "a.md").write_text("x", encoding="utf-8")
    result = push_once(store, host="test-host")
    assert result.status == "committed"
    count = subprocess.run(
        ["git", "-C", str(store), "rev-list", "--count", "HEAD"],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    assert count == "2"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_knowledge_push.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'lazy_harness.knowledge.git_push'`

- [ ] **Step 3: Write the implementation**

Create `src/lazy_harness/knowledge/git_push.py`:

```python
"""One commit/rebase/push cycle for the knowledge store.

Producers never call this — the Stop hook and the compound-loop worker only
write files. Keeping git on a scheduler cycle means a broken transport (no
network, dead remote, bad credentials) cannot stall a session or lose a write:
the files are on disk and the next cycle picks them up.
"""

from __future__ import annotations

import fcntl
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

from lazy_harness.knowledge.marker import MarkerError, read_marker

LOCK_FILENAME = ".push.lock"


@dataclass(frozen=True)
class PushResult:
    status: str
    detail: str = ""


def _git(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(root), *args], capture_output=True, text=True
    )


def _has_remote(root: Path) -> bool:
    return bool(_git(root, "remote").stdout.strip())


def _summarise(root: Path, marker_sessions: str, marker_learnings: str) -> str:
    out = _git(root, "status", "--porcelain").stdout.splitlines()
    sessions = sum(1 for line in out if f" {marker_sessions}/" in f" {line[3:]}")
    learnings = sum(1 for line in out if f" {marker_learnings}/" in f" {line[3:]}")
    return f"{sessions} sessions, {learnings} learnings"


def push_once(root: Path, host: str) -> PushResult:
    """Run one cycle. Expected failures are returned, not raised."""
    try:
        marker = read_marker(root)
    except MarkerError as e:
        return PushResult("invalid", str(e))

    lock_fd = os.open(str(root / LOCK_FILENAME), os.O_CREAT | os.O_WRONLY, 0o600)
    try:
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return PushResult("locked", "another cycle is running")

        dirty = bool(_git(root, "status", "--porcelain").stdout.strip())
        ahead = _git(root, "log", "--branches", "--not", "--remotes", "--oneline").stdout.strip()
        if not dirty and not ahead:
            return PushResult("clean")

        if dirty:
            summary = _summarise(root, marker.sessions, marker.learnings)
            _git(root, "add", "-A")
            commit = _git(root, "commit", "-m", f"knowledge: {summary} ({host})")
            if commit.returncode != 0:
                return PushResult("invalid", commit.stderr.strip())

        if not _has_remote(root):
            return PushResult("committed", "no remote configured")

        rebase = _git(root, "pull", "--rebase")
        if rebase.returncode != 0:
            _git(root, "rebase", "--abort")
            return PushResult("conflict", rebase.stderr.strip())

        pushed = _git(root, "push")
        if pushed.returncode != 0:
            return PushResult("committed", pushed.stderr.strip())

        return PushResult("pushed")
    finally:
        fcntl.flock(lock_fd, fcntl.LOCK_UN)
        os.close(lock_fd)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_knowledge_push.py -v`
Expected: PASS, 5 tests

- [ ] **Step 5: Lint and commit**

```bash
uv run ruff check src tests
git add src/lazy_harness/knowledge/git_push.py tests/unit/test_knowledge_push.py
git commit -m "feat: add knowledge store push cycle"
```

---

### Task 7: `lh knowledge init`, `path`, `push`

**Files:**
- Modify: `src/lazy_harness/cli/knowledge_cmd.py`
- Test: `tests/unit/cli/test_knowledge_cmd.py`

**Interfaces:**
- Consumes: `ensure_knowledge_dir`, `sessions_dir`, `learnings_dir` (Task 3); `resolve_root`, `MarkerError` (Task 1); `push_once`, `PushResult` (Task 6); `origin_host` (Task 4)
- Produces: three `click` subcommands on the existing `knowledge` group

Exit codes: `path` and `push` exit 1 on `invalid` or `conflict`, 0 on `clean`, `locked`, `committed`, `pushed`. A held lock is a normal skip, not an error.

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/cli/test_knowledge_cmd.py` (or add to it if it exists):

```python
"""Tests for lh knowledge init/path/push."""

from __future__ import annotations

from pathlib import Path

from click.testing import CliRunner


def test_init_creates_store_and_marker(tmp_path: Path) -> None:
    from lazy_harness.cli.knowledge_cmd import knowledge

    result = CliRunner().invoke(knowledge, ["init", "--root", str(tmp_path / "store")])
    assert result.exit_code == 0
    assert (tmp_path / "store" / "knowledge.toml").is_file()
    assert (tmp_path / "store" / "sessions").is_dir()
    assert (tmp_path / "store" / "learnings").is_dir()


def test_path_prints_absolute_learnings_dir(tmp_path: Path, monkeypatch) -> None:
    from lazy_harness.cli.knowledge_cmd import knowledge

    store = tmp_path / "store"
    CliRunner().invoke(knowledge, ["init", "--root", str(store)])
    monkeypatch.setenv("LAZY_KNOWLEDGE_ROOT", str(store))
    result = CliRunner().invoke(knowledge, ["path", "--kind", "learnings"])
    assert result.exit_code == 0
    assert result.output.strip() == str(store.resolve() / "learnings")


def test_path_on_missing_marker_exits_nonzero(tmp_path: Path, monkeypatch) -> None:
    from lazy_harness.cli.knowledge_cmd import knowledge

    monkeypatch.setenv("LAZY_KNOWLEDGE_ROOT", str(tmp_path / "nope"))
    result = CliRunner().invoke(knowledge, ["path", "--kind", "learnings"])
    assert result.exit_code == 1
    assert "knowledge.toml" in result.output


def test_push_reports_clean(tmp_path: Path, monkeypatch) -> None:
    import subprocess

    from lazy_harness.cli.knowledge_cmd import knowledge

    store = tmp_path / "store"
    CliRunner().invoke(knowledge, ["init", "--root", str(store)])
    for args in (
        ["init", "-q", "-b", "main"],
        ["config", "user.email", "test@example.invalid"],
        ["config", "user.name", "test"],
        ["add", "-A"],
        ["commit", "-qm", "init"],
    ):
        subprocess.run(["git", "-C", str(store), *args], check=True, capture_output=True)

    monkeypatch.setenv("LAZY_KNOWLEDGE_ROOT", str(store))
    result = CliRunner().invoke(knowledge, ["push"])
    assert result.exit_code == 0
    assert "clean" in result.output.lower()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/cli/test_knowledge_cmd.py -v`
Expected: FAIL — `Error: No such command 'init'`

- [ ] **Step 3: Add the subcommands**

Append to `src/lazy_harness/cli/knowledge_cmd.py`:

```python
@knowledge.command("init")
@click.option("--root", default=None, help="Store root (defaults to configured/env/default)")
def knowledge_init(root: str | None) -> None:
    """Create the knowledge store, its marker, and its subdirectories."""
    from lazy_harness.knowledge.directory import ensure_knowledge_dir
    from lazy_harness.knowledge.marker import resolve_root

    target = resolve_root(root) if root else resolve_root(_configured_root())
    created = ensure_knowledge_dir(target)
    console.print(f"[green]Knowledge store ready:[/green] {contract_path(created)}")


@knowledge.command("path")
@click.option(
    "--kind",
    type=click.Choice(["root", "sessions", "learnings"]),
    default="root",
    help="Which path to print",
)
def knowledge_path(kind: str) -> None:
    """Print an absolute path inside the knowledge store."""
    from lazy_harness.knowledge.directory import learnings_dir, sessions_dir
    from lazy_harness.knowledge.marker import MarkerError, resolve_root

    root = resolve_root(_configured_root())
    try:
        if kind == "root":
            target = root
        elif kind == "sessions":
            target = sessions_dir(root)
        else:
            target = learnings_dir(root)
    except MarkerError as e:
        console.print(f"[red]{e}[/red]")
        sys.exit(1)
    click.echo(str(target))


@knowledge.command("push")
def knowledge_push() -> None:
    """Commit, rebase, and push the knowledge store."""
    from lazy_harness.knowledge.compound_loop import origin_host
    from lazy_harness.knowledge.git_push import push_once
    from lazy_harness.knowledge.marker import resolve_root

    root = resolve_root(_configured_root())
    result = push_once(root, host=origin_host())
    log_append(default_log_dir() / "knowledge-push.log", f"{result.status}: {result.detail}")
    console.print(f"{result.status}: {result.detail}" if result.detail else result.status)
    if result.status in {"invalid", "conflict"}:
        sys.exit(1)
```

Add the `_configured_root()` helper near the top of the module:

```python
def _configured_root() -> str | None:
    """Read [knowledge].root from config, tolerating an absent config file."""
    cf = config_file()
    if not cf.is_file():
        return None
    try:
        return load_config(cf).knowledge.root or None
    except ConfigError:
        return None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/cli/test_knowledge_cmd.py -v`
Expected: PASS, 4 tests

- [ ] **Step 5: Full gate and commit**

```bash
uv run pytest
uv run ruff check src tests
uv run --group docs mkdocs build --strict
git add src/lazy_harness/cli/knowledge_cmd.py tests/unit/cli/test_knowledge_cmd.py
git commit -m "feat: add lh knowledge init, path and push"
```

---

### Task 8: Config migration

**Files:**
- Modify: `src/lazy_harness/migrate/` (follow the existing migration pattern in that package)
- Test: `tests/unit/migrate/`

**Interfaces:**
- Consumes: `KnowledgeConfig.root` (Task 2)
- Produces: a migration that rewrites the old `[knowledge]` shape into the new one

Read the existing migrations in `src/lazy_harness/migrate/` first and follow their registration pattern exactly. Do not invent a new mechanism.

- [ ] **Step 1: Write the failing test**

```python
def test_migrate_knowledge_path_to_root(tmp_path: Path) -> None:
    from lazy_harness.migrate.config_shape import migrate_knowledge_block

    cfg = tmp_path / "config.toml"
    cfg.write_text(
        '[knowledge]\n'
        'path = "~/vault/Meta"\n\n'
        '[knowledge.sessions]\nenabled = true\nsubdir = "sessions"\n\n'
        '[knowledge.learnings]\nenabled = true\nsubdir = "Learnings"\n\n'
        '[compound_loop]\nlearnings_subdir = "Learnings"\nlazymind_dir = "~/vault"\n',
        encoding="utf-8",
    )
    migrate_knowledge_block(cfg, new_root="~/repos/lazy/lazy-knowledge")
    text = cfg.read_text(encoding="utf-8")
    assert 'root = "~/repos/lazy/lazy-knowledge"' in text
    assert "path =" not in text
    assert "subdir" not in text
    assert "learnings_subdir" not in text
    assert 'lazymind_dir = "~/vault"' in text
```

- [ ] **Step 2: Run it, implement, run again**

Run: `uv run pytest tests/unit/migrate/ -k knowledge -v` → FAIL, then implement, then PASS.

The migration must preserve `lazymind_dir` — it points at the vault on purpose, because `resolve_prj_md()` reads `1-Projects/` from there.

- [ ] **Step 3: Full gate and commit**

```bash
uv run pytest && uv run ruff check src tests
git add src/lazy_harness/migrate tests/unit/migrate
git commit -m "feat: migrate knowledge config to the root shape"
```

---

### Task 9: Documentation

**Files:**
- Modify: `docs/reference/cli.md` — the three new subcommands
- Modify: `docs/architecture/memory-compound.md` — the store is no longer in the vault
- Modify: `specs/backlog.md:15` — drop the `Meta/Learnings/` reference

Non-negotiable #6: the CLI reference must match implemented commands and the memory architecture docs must match compound-loop artifacts.

- [ ] **Step 1: Read the current pages**

Read all three before editing so the new text matches their voice and structure.

- [ ] **Step 2: Document the subcommands**

In `docs/reference/cli.md`, document `lh knowledge init`, `lh knowledge path --kind`, and `lh knowledge push` alongside the existing `status`, `sync`, `embed`, `context-gen`. Keep it generic: no personal paths, no machine names.

- [ ] **Step 3: Update the architecture page**

In `docs/architecture/memory-compound.md`, replace any description of learnings living in a vault subdirectory with the store model: a separate repository, a `knowledge.toml` marker, and a scheduler-driven push. State that producers never touch git.

- [ ] **Step 4: Verify the build and commit**

```bash
uv run --group docs mkdocs build --strict
git add docs specs/backlog.md
git commit -m "docs: describe the knowledge store and its CLI"
```

---

### Task 10: Final gate

- [ ] **Step 1: Run the full pre-commit suite**

```bash
uv run pytest
uv run ruff check src tests
uv run --group docs mkdocs build --strict
```

All three must pass with pristine output.

- [ ] **Step 2: Confirm no stale references remain**

```bash
grep -rn "learnings_subdir\|knowledge\.path\|LCT_LEARNINGS_DIR" src tests docs specs \
  --exclude-dir=archive
```

Expected: no matches outside `specs/archive/`.

- [ ] **Step 3: Confirm no PII entered the tree**

```bash
git diff main --unified=0 | grep -nE "^\+.*(/Users/|Martin)" || echo "clean"
```

Expected: `clean`.

- [ ] **Step 4: Push and open the PR**

```bash
git push -u origin feat/knowledge-store
gh pr create --title "feat: extract the knowledge store from the vault" --body "..."
```

Report back to the driving session with the PR number. **Do not merge** — phases 2 through 5 are sequenced from there.

---

## Self-review notes

Checked against the design spec:

- Marker, validation, root resolution → Task 1
- Config shape and the case fix → Tasks 2, 8
- Directory resolution → Task 3
- Host suffix / add-add collision → Task 4
- Worker and monitoring call sites → Task 5
- Push cycle, lock, conflict-abort, failure modes → Task 6
- CLI surface → Task 7
- Non-negotiable #6 docs coherence → Task 9

Deliberately **not** in this plan, because they belong to other phases: creating the repository and copying data (phase 0), `lazy-ai-tools` (phase 2), Marge and `index.yml` (phase 3), verification (phase 4), vault deletion (phase 5).

Naming is consistent across tasks: `read_marker`/`write_marker`/`resolve_root`/`KnowledgeMarker`/`MarkerError` (Task 1) are used with those exact names in Tasks 3, 5, 6, 7; `sessions_dir`/`learnings_dir` (Task 3) in Tasks 5 and 7; `push_once`/`PushResult` (Task 6) in Task 7; `origin_host` (Task 4) in Tasks 6 and 7.

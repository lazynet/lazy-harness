# lazy-harness Phase 1: Framework Bootstrap — Implementation Plan

> **Archived.** This document was authored in `lazy-claudecode` before the rename and migration to `lazy-harness`. Preserved for historical context. References to files and paths may be stale.


> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Create the `lazy-harness` Python package with core config, profile management, and basic CLI (`lh init`, `lh profile`, `lh doctor`, `lh deploy`) — enough to replace the current `lcc-admin` workflow.

**Architecture:** Python package in `src/lazy_harness/` with CLI entrypoint via `click`. TOML config at `~/.config/lazy-harness/config.toml`. Profile management with cross-platform path resolution. Agent adapter protocol with Claude Code as first implementation.

**Tech Stack:** Python 3.11+, click (CLI), tomli-w (TOML writing), rich (TUI output), pytest (testing), uv (package management)

**Spec:** `docs/superpowers/specs/2026-04-12-lazy-harness-product-design.md`

**Repo:** New repo `lazy-harness` at `~/repos/lazy/lazy-harness`

---

## File Map

### Package structure

```
lazy-harness/
├── pyproject.toml
├── src/lazy_harness/
│   ├── __init__.py              # version string
│   ├── core/
│   │   ├── __init__.py
│   │   ├── config.py            # TOML config loading, validation, defaults
│   │   ├── paths.py             # Cross-platform XDG-aware path resolution
│   │   └── profiles.py          # Profile CRUD operations
│   ├── agents/
│   │   ├── __init__.py
│   │   ├── base.py              # AgentAdapter protocol
│   │   ├── claude_code.py       # Claude Code adapter
│   │   └── registry.py          # Agent discovery from config
│   ├── cli/
│   │   ├── __init__.py
│   │   ├── main.py              # Top-level click group: `lh`
│   │   ├── init_cmd.py          # `lh init` wizard
│   │   ├── profile_cmd.py       # `lh profile list|add|remove`
│   │   ├── doctor_cmd.py        # `lh doctor`
│   │   └── deploy_cmd.py        # `lh deploy`
│   └── deploy/
│       ├── __init__.py
│       ├── symlinks.py          # Symlink creation (cross-platform)
│       └── engine.py            # Deploy orchestration
├── templates/
│   └── config.toml.default      # Default config template
├── tests/
│   ├── conftest.py              # Shared fixtures (tmp_path, mock config)
│   ├── unit/
│   │   ├── test_config.py
│   │   ├── test_paths.py
│   │   ├── test_profiles.py
│   │   └── test_agent_claude.py
│   └── integration/
│       ├── test_init.py
│       ├── test_deploy.py
│       └── test_doctor.py
└── docs/
    └── architecture/
        └── adrs/
            ├── 001-hybrid-architecture.md
            ├── 002-python-uv-distribution.md
            ├── 003-toml-config-format.md
            ├── 004-agent-adapter-pattern.md
            └── 007-parallel-bootstrap-migration.md
```

---

## Task 1: Repo scaffold and pyproject.toml

**Files:**
- Create: `~/repos/lazy/lazy-harness/pyproject.toml`
- Create: `~/repos/lazy/lazy-harness/src/lazy_harness/__init__.py`
- Create: `~/repos/lazy/lazy-harness/.gitignore`

- [ ] **Step 1: Create repo directory and initialize git**

```bash
mkdir -p ~/repos/lazy/lazy-harness
cd ~/repos/lazy/lazy-harness
git init
```

- [ ] **Step 2: Create .gitignore**

```gitignore
__pycache__/
*.pyc
*.egg-info/
dist/
build/
.venv/
.pytest_cache/
.ruff_cache/
```

- [ ] **Step 3: Create pyproject.toml**

```toml
[project]
name = "lazy-harness"
version = "0.1.0"
description = "A cross-platform harnessing framework for AI coding agents"
readme = "README.md"
requires-python = ">=3.11"
license = "MIT"
dependencies = [
    "click>=8.1",
    "rich>=13.0",
    "tomli-w>=1.0",
]

[project.scripts]
lh = "lazy_harness.cli.main:cli"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/lazy_harness"]

[tool.pytest.ini_options]
testpaths = ["tests"]
pythonpath = ["src"]

[tool.ruff]
target-version = "py311"
line-length = 100

[tool.ruff.lint]
select = ["E", "F", "I", "UP"]

[dependency-groups]
dev = [
    "pytest>=8.0",
    "ruff>=0.4",
]
```

- [ ] **Step 4: Create __init__.py**

```python
"""lazy-harness — A cross-platform harnessing framework for AI coding agents."""

__version__ = "0.1.0"
```

- [ ] **Step 5: Verify uv can resolve the project**

```bash
cd ~/repos/lazy/lazy-harness
uv sync
```

Expected: dependencies install, `.venv/` created.

- [ ] **Step 6: Commit**

```bash
git add .
git commit -m "feat: initial repo scaffold with pyproject.toml"
```

---

## Task 2: Cross-platform path resolution

**Files:**
- Create: `src/lazy_harness/core/__init__.py`
- Create: `src/lazy_harness/core/paths.py`
- Test: `tests/unit/test_paths.py`
- Create: `tests/__init__.py`
- Create: `tests/unit/__init__.py`
- Create: `tests/conftest.py`

- [ ] **Step 1: Create test infrastructure**

`tests/__init__.py` — empty file.
`tests/unit/__init__.py` — empty file.
`tests/conftest.py`:

```python
"""Shared test fixtures for lazy-harness."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Generator

import pytest


@pytest.fixture
def config_dir(tmp_path: Path) -> Path:
    """Temporary config directory mimicking ~/.config/lazy-harness/."""
    d = tmp_path / "config" / "lazy-harness"
    d.mkdir(parents=True)
    return d


@pytest.fixture
def data_dir(tmp_path: Path) -> Path:
    """Temporary data directory mimicking ~/.local/share/lazy-harness/."""
    d = tmp_path / "data" / "lazy-harness"
    d.mkdir(parents=True)
    return d


@pytest.fixture
def home_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Temporary home directory. Patches HOME and relevant env vars."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))  # Windows
    # Clear XDG vars so defaults resolve to tmp home
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    monkeypatch.delenv("XDG_DATA_HOME", raising=False)
    monkeypatch.delenv("XDG_CACHE_HOME", raising=False)
    monkeypatch.delenv("LH_CONFIG_DIR", raising=False)
    return home
```

- [ ] **Step 2: Write failing tests for paths**

`tests/unit/test_paths.py`:

```python
"""Tests for cross-platform path resolution."""

from __future__ import annotations

import platform
from pathlib import Path

import pytest


def test_config_dir_default_unix(home_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("platform.system", lambda: "Linux")
    from lazy_harness.core.paths import config_dir
    assert config_dir() == home_dir / ".config" / "lazy-harness"


def test_config_dir_xdg_override(home_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    custom = home_dir / "custom-config"
    monkeypatch.setenv("XDG_CONFIG_HOME", str(custom))
    from importlib import reload
    import lazy_harness.core.paths as paths_mod
    reload(paths_mod)
    assert paths_mod.config_dir() == custom / "lazy-harness"


def test_config_dir_env_override(home_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    custom = home_dir / "explicit"
    monkeypatch.setenv("LH_CONFIG_DIR", str(custom))
    from importlib import reload
    import lazy_harness.core.paths as paths_mod
    reload(paths_mod)
    assert paths_mod.config_dir() == custom


def test_data_dir_default_unix(home_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("platform.system", lambda: "Linux")
    from lazy_harness.core.paths import data_dir
    assert data_dir() == home_dir / ".local" / "share" / "lazy-harness"


def test_cache_dir_default_unix(home_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("platform.system", lambda: "Linux")
    from lazy_harness.core.paths import cache_dir
    assert cache_dir() == home_dir / ".cache" / "lazy-harness"


def test_config_file_path(home_dir: Path) -> None:
    from lazy_harness.core.paths import config_file
    result = config_file()
    assert result.name == "config.toml"
    assert "lazy-harness" in str(result)


def test_expand_user_path() -> None:
    from lazy_harness.core.paths import expand_path
    result = expand_path("~/projects")
    assert "~" not in str(result)
    assert result.is_absolute()


def test_contract_path(home_dir: Path) -> None:
    from lazy_harness.core.paths import contract_path
    full = home_dir / "projects" / "foo"
    result = contract_path(full)
    assert result.startswith("~")
    assert "foo" in result
```

- [ ] **Step 3: Run tests to verify they fail**

```bash
cd ~/repos/lazy/lazy-harness
uv run pytest tests/unit/test_paths.py -v
```

Expected: ModuleNotFoundError — `lazy_harness.core.paths` does not exist.

- [ ] **Step 4: Implement paths module**

`src/lazy_harness/core/__init__.py` — empty file.

`src/lazy_harness/core/paths.py`:

```python
"""Cross-platform path resolution for lazy-harness.

Resolution order for each directory:
1. Explicit env var (LH_CONFIG_DIR, LH_DATA_DIR, LH_CACHE_DIR)
2. XDG env vars (XDG_CONFIG_HOME, etc.) — Linux/macOS
3. Platform defaults:
   - macOS/Linux: ~/.config, ~/.local/share, ~/.cache
   - Windows: %APPDATA%, %LOCALAPPDATA%
"""

from __future__ import annotations

import os
import platform
from pathlib import Path

APP_NAME = "lazy-harness"


def _home() -> Path:
    return Path(os.environ.get("USERPROFILE", os.environ.get("HOME", Path.home())))


def config_dir() -> Path:
    """Return the config directory for lazy-harness."""
    explicit = os.environ.get("LH_CONFIG_DIR")
    if explicit:
        return Path(explicit)

    xdg = os.environ.get("XDG_CONFIG_HOME")
    if xdg:
        return Path(xdg) / APP_NAME

    if platform.system() == "Windows":
        appdata = os.environ.get("APPDATA", _home() / "AppData" / "Roaming")
        return Path(appdata) / APP_NAME

    return _home() / ".config" / APP_NAME


def data_dir() -> Path:
    """Return the data directory for lazy-harness."""
    explicit = os.environ.get("LH_DATA_DIR")
    if explicit:
        return Path(explicit)

    xdg = os.environ.get("XDG_DATA_HOME")
    if xdg:
        return Path(xdg) / APP_NAME

    if platform.system() == "Windows":
        local = os.environ.get("LOCALAPPDATA", _home() / "AppData" / "Local")
        return Path(local) / APP_NAME

    return _home() / ".local" / "share" / APP_NAME


def cache_dir() -> Path:
    """Return the cache directory for lazy-harness."""
    explicit = os.environ.get("LH_CACHE_DIR")
    if explicit:
        return Path(explicit)

    xdg = os.environ.get("XDG_CACHE_HOME")
    if xdg:
        return Path(xdg) / APP_NAME

    if platform.system() == "Windows":
        local = os.environ.get("LOCALAPPDATA", _home() / "AppData" / "Local")
        return Path(local) / APP_NAME / "cache"

    return _home() / ".cache" / APP_NAME


def config_file() -> Path:
    """Return the path to config.toml."""
    return config_dir() / "config.toml"


def expand_path(path: str | Path) -> Path:
    """Expand ~ and resolve to absolute path."""
    return Path(os.path.expanduser(str(path))).resolve()


def contract_path(path: Path | str) -> str:
    """Contract absolute path replacing home dir with ~."""
    s = str(path)
    home = str(_home())
    if s.startswith(home):
        return "~" + s[len(home):]
    return s
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
cd ~/repos/lazy/lazy-harness
uv run pytest tests/unit/test_paths.py -v
```

Expected: all tests PASS.

- [ ] **Step 6: Commit**

```bash
git add src/lazy_harness/core/ tests/
git commit -m "feat: cross-platform path resolution module"
```

---

## Task 3: TOML config loading and validation

**Files:**
- Create: `src/lazy_harness/core/config.py`
- Create: `templates/config.toml.default`
- Test: `tests/unit/test_config.py`

- [ ] **Step 1: Create default config template**

`templates/config.toml.default`:

```toml
# lazy-harness configuration
# Docs: https://github.com/lazynet/lazy-harness

[harness]
version = "1"

[agent]
type = "claude-code"

[profiles]
default = "personal"

[profiles.personal]
config_dir = "~/.claude-personal"
roots = ["~"]

[knowledge]
path = ""

[knowledge.sessions]
enabled = false
subdir = "sessions"

[knowledge.learnings]
enabled = false
subdir = "learnings"

[knowledge.search]
engine = "qmd"

[monitoring]
enabled = false

[scheduler]
backend = "auto"
```

- [ ] **Step 2: Write failing tests for config**

`tests/unit/test_config.py`:

```python
"""Tests for TOML config loading and validation."""

from __future__ import annotations

from pathlib import Path

import pytest


def test_load_config_from_file(config_dir: Path) -> None:
    config_file = config_dir / "config.toml"
    config_file.write_text("""
[harness]
version = "1"

[agent]
type = "claude-code"

[profiles]
default = "personal"

[profiles.personal]
config_dir = "~/.claude-personal"
roots = ["~"]
""")
    from lazy_harness.core.config import load_config
    cfg = load_config(config_file)
    assert cfg.harness.version == "1"
    assert cfg.agent.type == "claude-code"
    assert cfg.profiles.default == "personal"
    assert "personal" in cfg.profiles.items
    assert cfg.profiles.items["personal"].config_dir == "~/.claude-personal"


def test_load_config_missing_file(tmp_path: Path) -> None:
    from lazy_harness.core.config import load_config, ConfigError
    with pytest.raises(ConfigError, match="not found"):
        load_config(tmp_path / "nonexistent.toml")


def test_load_config_invalid_toml(config_dir: Path) -> None:
    config_file = config_dir / "config.toml"
    config_file.write_text("this is not [valid toml")
    from lazy_harness.core.config import load_config, ConfigError
    with pytest.raises(ConfigError, match="parse"):
        load_config(config_file)


def test_load_config_missing_version(config_dir: Path) -> None:
    config_file = config_dir / "config.toml"
    config_file.write_text("""
[agent]
type = "claude-code"
""")
    from lazy_harness.core.config import load_config, ConfigError
    with pytest.raises(ConfigError, match="version"):
        load_config(config_file)


def test_load_config_defaults(config_dir: Path) -> None:
    config_file = config_dir / "config.toml"
    config_file.write_text("""
[harness]
version = "1"
""")
    from lazy_harness.core.config import load_config
    cfg = load_config(config_file)
    assert cfg.agent.type == "claude-code"
    assert cfg.monitoring.enabled is False
    assert cfg.scheduler.backend == "auto"


def test_config_get_profile(config_dir: Path) -> None:
    config_file = config_dir / "config.toml"
    config_file.write_text("""
[harness]
version = "1"

[profiles]
default = "work"

[profiles.work]
config_dir = "~/.claude-work"
roots = ["~/work"]

[profiles.personal]
config_dir = "~/.claude-personal"
roots = ["~"]
""")
    from lazy_harness.core.config import load_config
    cfg = load_config(config_file)
    assert cfg.profiles.default == "work"
    assert len(cfg.profiles.items) == 2
    assert cfg.profiles.items["work"].roots == ["~/work"]


def test_save_config(config_dir: Path) -> None:
    config_file = config_dir / "config.toml"
    config_file.write_text("""
[harness]
version = "1"
""")
    from lazy_harness.core.config import load_config, save_config
    cfg = load_config(config_file)
    cfg.agent.type = "ollama"
    save_config(cfg, config_file)

    cfg2 = load_config(config_file)
    assert cfg2.agent.type == "ollama"
```

- [ ] **Step 3: Run tests to verify they fail**

```bash
uv run pytest tests/unit/test_config.py -v
```

Expected: ModuleNotFoundError — `lazy_harness.core.config` does not exist.

- [ ] **Step 4: Implement config module**

`src/lazy_harness/core/config.py`:

```python
"""TOML config loading, validation, and persistence.

Config lives at ~/.config/lazy-harness/config.toml (or LH_CONFIG_DIR override).
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import tomli_w


class ConfigError(Exception):
    """Raised when config is invalid or missing."""


@dataclass
class ProfileEntry:
    config_dir: str = ""
    roots: list[str] = field(default_factory=list)


@dataclass
class ProfilesConfig:
    default: str = "personal"
    items: dict[str, ProfileEntry] = field(default_factory=dict)


@dataclass
class AgentConfig:
    type: str = "claude-code"


@dataclass
class HarnessConfig:
    version: str = "1"


@dataclass
class KnowledgeSessionsConfig:
    enabled: bool = False
    subdir: str = "sessions"


@dataclass
class KnowledgeLearningsConfig:
    enabled: bool = False
    subdir: str = "learnings"


@dataclass
class KnowledgeSearchConfig:
    engine: str = "qmd"


@dataclass
class KnowledgeConfig:
    path: str = ""
    sessions: KnowledgeSessionsConfig = field(default_factory=KnowledgeSessionsConfig)
    learnings: KnowledgeLearningsConfig = field(default_factory=KnowledgeLearningsConfig)
    search: KnowledgeSearchConfig = field(default_factory=KnowledgeSearchConfig)


@dataclass
class MonitoringConfig:
    enabled: bool = False
    db: str = ""
    pricing: dict[str, dict[str, float]] = field(default_factory=dict)


@dataclass
class SchedulerConfig:
    backend: str = "auto"


@dataclass
class Config:
    harness: HarnessConfig = field(default_factory=HarnessConfig)
    agent: AgentConfig = field(default_factory=AgentConfig)
    profiles: ProfilesConfig = field(default_factory=ProfilesConfig)
    knowledge: KnowledgeConfig = field(default_factory=KnowledgeConfig)
    monitoring: MonitoringConfig = field(default_factory=MonitoringConfig)
    scheduler: SchedulerConfig = field(default_factory=SchedulerConfig)


def _parse_profiles(raw: dict[str, Any]) -> ProfilesConfig:
    """Parse [profiles] section, separating 'default' key from profile entries."""
    default = raw.get("default", "personal")
    items: dict[str, ProfileEntry] = {}
    for key, value in raw.items():
        if key == "default":
            continue
        if isinstance(value, dict):
            items[key] = ProfileEntry(
                config_dir=value.get("config_dir", ""),
                roots=value.get("roots", []),
            )
    return ProfilesConfig(default=default, items=items)


def load_config(path: Path) -> Config:
    """Load and validate config from a TOML file."""
    if not path.is_file():
        raise ConfigError(f"Config file not found: {path}")

    try:
        raw = tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as e:
        raise ConfigError(f"Failed to parse {path}: {e}") from e

    harness_raw = raw.get("harness", {})
    if not harness_raw.get("version"):
        raise ConfigError(f"Missing [harness].version in {path}")

    cfg = Config()
    cfg.harness = HarnessConfig(version=harness_raw["version"])

    agent_raw = raw.get("agent", {})
    cfg.agent = AgentConfig(type=agent_raw.get("type", "claude-code"))

    profiles_raw = raw.get("profiles", {})
    cfg.profiles = _parse_profiles(profiles_raw)

    knowledge_raw = raw.get("knowledge", {})
    cfg.knowledge = KnowledgeConfig(
        path=knowledge_raw.get("path", ""),
        sessions=KnowledgeSessionsConfig(**knowledge_raw.get("sessions", {})),
        learnings=KnowledgeLearningsConfig(**knowledge_raw.get("learnings", {})),
        search=KnowledgeSearchConfig(**knowledge_raw.get("search", {})),
    )

    monitoring_raw = raw.get("monitoring", {})
    cfg.monitoring = MonitoringConfig(
        enabled=monitoring_raw.get("enabled", False),
        db=monitoring_raw.get("db", ""),
        pricing=monitoring_raw.get("pricing", {}),
    )

    scheduler_raw = raw.get("scheduler", {})
    cfg.scheduler = SchedulerConfig(backend=scheduler_raw.get("backend", "auto"))

    return cfg


def _config_to_dict(cfg: Config) -> dict[str, Any]:
    """Serialize Config to a dict suitable for TOML output."""
    profiles_dict: dict[str, Any] = {"default": cfg.profiles.default}
    for name, entry in cfg.profiles.items.items():
        profiles_dict[name] = {
            "config_dir": entry.config_dir,
            "roots": entry.roots,
        }

    result: dict[str, Any] = {
        "harness": {"version": cfg.harness.version},
        "agent": {"type": cfg.agent.type},
        "profiles": profiles_dict,
        "knowledge": {
            "path": cfg.knowledge.path,
            "sessions": {
                "enabled": cfg.knowledge.sessions.enabled,
                "subdir": cfg.knowledge.sessions.subdir,
            },
            "learnings": {
                "enabled": cfg.knowledge.learnings.enabled,
                "subdir": cfg.knowledge.learnings.subdir,
            },
            "search": {"engine": cfg.knowledge.search.engine},
        },
        "monitoring": {
            "enabled": cfg.monitoring.enabled,
        },
        "scheduler": {"backend": cfg.scheduler.backend},
    }

    if cfg.monitoring.db:
        result["monitoring"]["db"] = cfg.monitoring.db
    if cfg.monitoring.pricing:
        result["monitoring"]["pricing"] = cfg.monitoring.pricing

    return result


def save_config(cfg: Config, path: Path) -> None:
    """Save config to a TOML file."""
    data = _config_to_dict(cfg)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(tomli_w.dumps(data).encode())
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
uv run pytest tests/unit/test_config.py -v
```

Expected: all tests PASS.

- [ ] **Step 6: Commit**

```bash
git add src/lazy_harness/core/config.py templates/ tests/unit/test_config.py
git commit -m "feat: TOML config loading, validation, and persistence"
```

---

## Task 4: Profile management

**Files:**
- Create: `src/lazy_harness/core/profiles.py`
- Test: `tests/unit/test_profiles.py`

- [ ] **Step 1: Write failing tests for profiles**

`tests/unit/test_profiles.py`:

```python
"""Tests for profile management."""

from __future__ import annotations

from pathlib import Path

import pytest

from lazy_harness.core.config import Config, ProfileEntry, ProfilesConfig, HarnessConfig


def _make_config(tmp_path: Path, profiles: dict[str, ProfileEntry] | None = None) -> tuple[Config, Path]:
    """Helper to create a Config with profiles pointing to tmp dirs."""
    items = profiles or {
        "personal": ProfileEntry(
            config_dir=str(tmp_path / ".claude-personal"),
            roots=["~"],
        ),
    }
    cfg = Config(
        harness=HarnessConfig(version="1"),
        profiles=ProfilesConfig(default="personal", items=items),
    )
    return cfg, tmp_path


def test_list_profiles(tmp_path: Path) -> None:
    from lazy_harness.core.profiles import list_profiles
    cfg, _ = _make_config(tmp_path)
    result = list_profiles(cfg)
    assert len(result) == 1
    assert result[0].name == "personal"
    assert result[0].is_default is True


def test_list_profiles_multiple(tmp_path: Path) -> None:
    from lazy_harness.core.profiles import list_profiles
    cfg, _ = _make_config(tmp_path, {
        "personal": ProfileEntry(config_dir=str(tmp_path / ".claude-personal"), roots=["~"]),
        "work": ProfileEntry(config_dir=str(tmp_path / ".claude-work"), roots=["~/work"]),
    })
    cfg.profiles.default = "personal"
    result = list_profiles(cfg)
    assert len(result) == 2
    names = {p.name for p in result}
    assert names == {"personal", "work"}


def test_add_profile(tmp_path: Path) -> None:
    from lazy_harness.core.profiles import add_profile
    cfg, _ = _make_config(tmp_path)
    add_profile(cfg, "work", str(tmp_path / ".claude-work"), ["~/work"])
    assert "work" in cfg.profiles.items
    assert cfg.profiles.items["work"].config_dir == str(tmp_path / ".claude-work")


def test_add_profile_duplicate(tmp_path: Path) -> None:
    from lazy_harness.core.profiles import add_profile, ProfileError
    cfg, _ = _make_config(tmp_path)
    with pytest.raises(ProfileError, match="already exists"):
        add_profile(cfg, "personal", str(tmp_path / ".claude-personal"), ["~"])


def test_remove_profile(tmp_path: Path) -> None:
    from lazy_harness.core.profiles import remove_profile
    cfg, _ = _make_config(tmp_path, {
        "personal": ProfileEntry(config_dir=str(tmp_path / ".claude-personal"), roots=["~"]),
        "work": ProfileEntry(config_dir=str(tmp_path / ".claude-work"), roots=["~/work"]),
    })
    remove_profile(cfg, "work")
    assert "work" not in cfg.profiles.items


def test_remove_default_profile_fails(tmp_path: Path) -> None:
    from lazy_harness.core.profiles import remove_profile, ProfileError
    cfg, _ = _make_config(tmp_path)
    with pytest.raises(ProfileError, match="default"):
        remove_profile(cfg, "personal")


def test_remove_nonexistent_profile(tmp_path: Path) -> None:
    from lazy_harness.core.profiles import remove_profile, ProfileError
    cfg, _ = _make_config(tmp_path)
    with pytest.raises(ProfileError, match="not found"):
        remove_profile(cfg, "ghost")


def test_resolve_profile_by_cwd(tmp_path: Path) -> None:
    from lazy_harness.core.profiles import resolve_profile
    work_root = tmp_path / "work" / "project"
    work_root.mkdir(parents=True)
    cfg, _ = _make_config(tmp_path, {
        "personal": ProfileEntry(config_dir=str(tmp_path / ".claude-personal"), roots=[str(tmp_path)]),
        "work": ProfileEntry(config_dir=str(tmp_path / ".claude-work"), roots=[str(tmp_path / "work")]),
    })
    result = resolve_profile(cfg, cwd=work_root)
    assert result == "work"


def test_resolve_profile_falls_back_to_default(tmp_path: Path) -> None:
    from lazy_harness.core.profiles import resolve_profile
    cfg, _ = _make_config(tmp_path)
    result = resolve_profile(cfg, cwd=Path("/some/random/path"))
    assert result == "personal"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/unit/test_profiles.py -v
```

Expected: ModuleNotFoundError.

- [ ] **Step 3: Implement profiles module**

`src/lazy_harness/core/profiles.py`:

```python
"""Profile management — list, add, remove, resolve."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from lazy_harness.core.config import Config, ProfileEntry
from lazy_harness.core.paths import expand_path


class ProfileError(Exception):
    """Raised for profile operation failures."""


@dataclass
class ProfileInfo:
    name: str
    config_dir: Path
    roots: list[str]
    is_default: bool
    exists: bool


def list_profiles(cfg: Config) -> list[ProfileInfo]:
    """Return info about all configured profiles."""
    result: list[ProfileInfo] = []
    for name, entry in cfg.profiles.items.items():
        config_path = expand_path(entry.config_dir)
        result.append(ProfileInfo(
            name=name,
            config_dir=config_path,
            roots=entry.roots,
            is_default=(name == cfg.profiles.default),
            exists=config_path.is_dir(),
        ))
    return result


def add_profile(cfg: Config, name: str, config_dir: str, roots: list[str]) -> None:
    """Add a new profile to config."""
    if name in cfg.profiles.items:
        raise ProfileError(f"Profile '{name}' already exists")
    cfg.profiles.items[name] = ProfileEntry(config_dir=config_dir, roots=roots)


def remove_profile(cfg: Config, name: str) -> None:
    """Remove a profile from config."""
    if name not in cfg.profiles.items:
        raise ProfileError(f"Profile '{name}' not found")
    if name == cfg.profiles.default:
        raise ProfileError(f"Cannot remove default profile '{name}'. Change default first.")
    del cfg.profiles.items[name]


def resolve_profile(cfg: Config, cwd: Path | None = None) -> str:
    """Resolve which profile to use based on cwd. Longest matching root wins."""
    if cwd is None:
        cwd = Path.cwd()

    cwd_str = str(cwd.resolve())
    best_match = ""
    best_len = 0

    for name, entry in cfg.profiles.items.items():
        for root in entry.roots:
            root_str = str(expand_path(root))
            if cwd_str.startswith(root_str) and len(root_str) > best_len:
                best_match = name
                best_len = len(root_str)

    return best_match if best_match else cfg.profiles.default
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/unit/test_profiles.py -v
```

Expected: all tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/lazy_harness/core/profiles.py tests/unit/test_profiles.py
git commit -m "feat: profile management (list, add, remove, resolve)"
```

---

## Task 5: Agent adapter protocol + Claude Code adapter

**Files:**
- Create: `src/lazy_harness/agents/__init__.py`
- Create: `src/lazy_harness/agents/base.py`
- Create: `src/lazy_harness/agents/claude_code.py`
- Create: `src/lazy_harness/agents/registry.py`
- Test: `tests/unit/test_agent_claude.py`

- [ ] **Step 1: Write failing tests**

`tests/unit/test_agent_claude.py`:

```python
"""Tests for Claude Code agent adapter."""

from __future__ import annotations

from pathlib import Path

import pytest


def test_claude_adapter_name() -> None:
    from lazy_harness.agents.claude_code import ClaudeCodeAdapter
    adapter = ClaudeCodeAdapter()
    assert adapter.name == "claude-code"


def test_claude_adapter_config_dir() -> None:
    from lazy_harness.agents.claude_code import ClaudeCodeAdapter
    adapter = ClaudeCodeAdapter()
    result = adapter.config_dir("~/.claude-personal")
    assert result == Path.home() / ".claude-personal"


def test_claude_adapter_supported_hooks() -> None:
    from lazy_harness.agents.claude_code import ClaudeCodeAdapter
    adapter = ClaudeCodeAdapter()
    hooks = adapter.supported_hooks()
    assert "session_start" in hooks
    assert "session_stop" in hooks
    assert "pre_compact" in hooks


def test_registry_get_claude() -> None:
    from lazy_harness.agents.registry import get_agent
    adapter = get_agent("claude-code")
    assert adapter.name == "claude-code"


def test_registry_unknown_agent() -> None:
    from lazy_harness.agents.registry import get_agent, AgentNotFoundError
    with pytest.raises(AgentNotFoundError):
        get_agent("unknown-agent")


def test_registry_list_agents() -> None:
    from lazy_harness.agents.registry import list_agents
    agents = list_agents()
    assert "claude-code" in agents
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/unit/test_agent_claude.py -v
```

Expected: ModuleNotFoundError.

- [ ] **Step 3: Implement agent modules**

`src/lazy_harness/agents/__init__.py` — empty file.

`src/lazy_harness/agents/base.py`:

```python
"""Agent adapter protocol — defines what an agent adapter must expose."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol, runtime_checkable


@runtime_checkable
class AgentAdapter(Protocol):
    """Protocol that all agent adapters must implement."""

    @property
    def name(self) -> str:
        """Unique identifier for this agent type."""
        ...

    def config_dir(self, profile_config_dir: str) -> Path:
        """Resolve the agent's config directory for a profile."""
        ...

    def supported_hooks(self) -> list[str]:
        """Return list of hook events this agent supports."""
        ...

    def generate_hook_config(self, hooks: dict[str, list[str]]) -> dict:
        """Generate agent-native hook config (e.g., settings.json for Claude Code)."""
        ...
```

`src/lazy_harness/agents/claude_code.py`:

```python
"""Claude Code agent adapter."""

from __future__ import annotations

from pathlib import Path

from lazy_harness.core.paths import expand_path


class ClaudeCodeAdapter:
    """Adapter for Claude Code (Anthropic's CLI agent)."""

    @property
    def name(self) -> str:
        return "claude-code"

    def config_dir(self, profile_config_dir: str) -> Path:
        return expand_path(profile_config_dir)

    def supported_hooks(self) -> list[str]:
        return [
            "session_start",
            "session_stop",
            "pre_compact",
            "pre_tool_use",
            "post_tool_use",
            "notification",
        ]

    def generate_hook_config(self, hooks: dict[str, list[str]]) -> dict:
        """Generate Claude Code settings.json hooks section."""
        hook_event_map = {
            "session_start": "SessionStart",
            "session_stop": "Stop",
            "pre_compact": "PreCompact",
            "pre_tool_use": "PreToolUse",
            "post_tool_use": "PostToolUse",
            "notification": "Notification",
        }
        settings_hooks: dict[str, list[dict]] = {}
        for event, scripts in hooks.items():
            cc_event = hook_event_map.get(event)
            if not cc_event:
                continue
            matchers = []
            for script in scripts:
                matchers.append({
                    "matcher": "",
                    "hooks": [{"type": "command", "command": script}],
                })
            settings_hooks[cc_event] = matchers
        return settings_hooks
```

`src/lazy_harness/agents/registry.py`:

```python
"""Agent discovery and registration."""

from __future__ import annotations

from lazy_harness.agents.base import AgentAdapter
from lazy_harness.agents.claude_code import ClaudeCodeAdapter


class AgentNotFoundError(Exception):
    """Raised when requested agent type is not registered."""


_AGENTS: dict[str, type] = {
    "claude-code": ClaudeCodeAdapter,
}


def get_agent(agent_type: str) -> AgentAdapter:
    """Get an agent adapter instance by type name."""
    cls = _AGENTS.get(agent_type)
    if cls is None:
        raise AgentNotFoundError(
            f"Agent '{agent_type}' not found. Available: {', '.join(_AGENTS)}"
        )
    return cls()


def list_agents() -> list[str]:
    """Return list of registered agent type names."""
    return list(_AGENTS.keys())
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/unit/test_agent_claude.py -v
```

Expected: all tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/lazy_harness/agents/ tests/unit/test_agent_claude.py
git commit -m "feat: agent adapter protocol + Claude Code adapter"
```

---

## Task 6: CLI skeleton with click

**Files:**
- Create: `src/lazy_harness/cli/__init__.py`
- Create: `src/lazy_harness/cli/main.py`
- Test: integration test via subprocess

- [ ] **Step 1: Create CLI entrypoint**

`src/lazy_harness/cli/__init__.py` — empty file.

`src/lazy_harness/cli/main.py`:

```python
"""Top-level CLI entrypoint for lazy-harness."""

from __future__ import annotations

import click

from lazy_harness import __version__


@click.group()
@click.version_option(__version__, prog_name="lazy-harness")
def cli() -> None:
    """lazy-harness — A cross-platform harnessing framework for AI coding agents."""


def register_commands() -> None:
    """Register all subcommands. Called after imports to avoid circular deps."""
    from lazy_harness.cli.init_cmd import init_cmd
    from lazy_harness.cli.profile_cmd import profile
    from lazy_harness.cli.doctor_cmd import doctor
    from lazy_harness.cli.deploy_cmd import deploy

    cli.add_command(init_cmd, "init")
    cli.add_command(profile, "profile")
    cli.add_command(doctor, "doctor")
    cli.add_command(deploy, "deploy")


register_commands()
```

- [ ] **Step 2: Verify lh --version works**

```bash
cd ~/repos/lazy/lazy-harness
uv run lh --version
```

Expected: `lazy-harness, version 0.1.0`

Note: this will fail until we create the subcommand modules (init_cmd, profile_cmd, etc.). Create stubs first:

`src/lazy_harness/cli/init_cmd.py`:

```python
"""lh init — interactive setup wizard."""

from __future__ import annotations

import click


@click.command("init")
def init_cmd() -> None:
    """Initialize lazy-harness configuration."""
    click.echo("TODO: init wizard")
```

`src/lazy_harness/cli/profile_cmd.py`:

```python
"""lh profile — profile management commands."""

from __future__ import annotations

import click


@click.group()
def profile() -> None:
    """Manage agent profiles."""


@profile.command("list")
def profile_list() -> None:
    """List all profiles."""
    click.echo("TODO: profile list")


@profile.command("add")
@click.argument("name")
def profile_add(name: str) -> None:
    """Add a new profile."""
    click.echo(f"TODO: add profile {name}")


@profile.command("remove")
@click.argument("name")
def profile_remove(name: str) -> None:
    """Remove a profile."""
    click.echo(f"TODO: remove profile {name}")
```

`src/lazy_harness/cli/doctor_cmd.py`:

```python
"""lh doctor — health check."""

from __future__ import annotations

import click


@click.command("doctor")
def doctor() -> None:
    """Check environment health."""
    click.echo("TODO: doctor")
```

`src/lazy_harness/cli/deploy_cmd.py`:

```python
"""lh deploy — deploy profiles, hooks, skills."""

from __future__ import annotations

import click


@click.command("deploy")
def deploy() -> None:
    """Deploy profiles, hooks, and skills."""
    click.echo("TODO: deploy")
```

- [ ] **Step 3: Verify lh --version and lh --help work**

```bash
uv run lh --version
uv run lh --help
uv run lh profile --help
```

Expected: version shows `0.1.0`, help shows all subcommands.

- [ ] **Step 4: Commit**

```bash
git add src/lazy_harness/cli/
git commit -m "feat: CLI skeleton with click (lh command)"
```

---

## Task 7: Implement `lh init` wizard

**Files:**
- Modify: `src/lazy_harness/cli/init_cmd.py`
- Test: `tests/integration/__init__.py`
- Test: `tests/integration/test_init.py`

- [ ] **Step 1: Write failing integration tests**

`tests/integration/__init__.py` — empty file.

`tests/integration/test_init.py`:

```python
"""Integration tests for lh init."""

from __future__ import annotations

from pathlib import Path

import pytest
from click.testing import CliRunner

from lazy_harness.cli.main import cli


def test_init_creates_config(home_dir: Path) -> None:
    runner = CliRunner()
    result = runner.invoke(cli, ["init"], input="personal\n\n\n\n")
    assert result.exit_code == 0
    config_file = home_dir / ".config" / "lazy-harness" / "config.toml"
    assert config_file.is_file()
    content = config_file.read_text()
    assert "[harness]" in content
    assert 'version = "1"' in content


def test_init_creates_profile_dir(home_dir: Path) -> None:
    runner = CliRunner()
    result = runner.invoke(cli, ["init"], input="personal\n\n\n\n")
    assert result.exit_code == 0
    profile_dir = home_dir / ".config" / "lazy-harness" / "profiles" / "personal"
    assert profile_dir.is_dir()


def test_init_noninteractive(home_dir: Path) -> None:
    runner = CliRunner()
    result = runner.invoke(cli, [
        "init",
        "--profile-name", "work",
        "--profile-config-dir", str(home_dir / ".claude-work"),
        "--agent", "claude-code",
        "--non-interactive",
    ])
    assert result.exit_code == 0
    config_file = home_dir / ".config" / "lazy-harness" / "config.toml"
    assert config_file.is_file()
    content = config_file.read_text()
    assert "work" in content


def test_init_refuses_overwrite(home_dir: Path) -> None:
    runner = CliRunner()
    runner.invoke(cli, ["init"], input="personal\n\n\n\n")
    result = runner.invoke(cli, ["init"], input="n\n")
    assert "already exists" in result.output.lower() or result.exit_code == 0
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/integration/test_init.py -v
```

Expected: tests fail (init_cmd is a stub).

- [ ] **Step 3: Implement init command**

Replace `src/lazy_harness/cli/init_cmd.py`:

```python
"""lh init — interactive setup wizard."""

from __future__ import annotations

from pathlib import Path

import click

from lazy_harness.core.config import Config, HarnessConfig, ProfileEntry, ProfilesConfig, save_config
from lazy_harness.core.paths import config_dir, config_file


@click.command("init")
@click.option("--profile-name", default=None, help="Default profile name")
@click.option("--profile-config-dir", default=None, help="Config directory for default profile")
@click.option("--agent", default="claude-code", help="Agent type")
@click.option("--non-interactive", is_flag=True, help="Skip interactive prompts")
def init_cmd(
    profile_name: str | None,
    profile_config_dir: str | None,
    agent: str,
    non_interactive: bool,
) -> None:
    """Initialize lazy-harness configuration."""
    cf = config_file()

    if cf.is_file():
        if non_interactive:
            click.echo(f"Config already exists at {cf}. Use --force to overwrite.")
            return
        if not click.confirm(f"Config already exists at {cf}. Overwrite?", default=False):
            return

    if non_interactive:
        name = profile_name or "personal"
        pdir = profile_config_dir or f"~/.claude-{name}"
    else:
        name = click.prompt("Default profile name", default=profile_name or "personal")
        default_dir = profile_config_dir or f"~/.claude-{name}"
        pdir = click.prompt(f"Config dir for '{name}'", default=default_dir)
        agent = click.prompt("Agent type", default=agent)
        click.echo()

    cfg = Config(
        harness=HarnessConfig(version="1"),
        agent=Config.__dataclass_fields__["agent"].default_factory()
        if not agent
        else type(Config().agent)(type=agent),
        profiles=ProfilesConfig(
            default=name,
            items={
                name: ProfileEntry(config_dir=pdir, roots=["~"]),
            },
        ),
    )

    # Save config
    save_config(cfg, cf)
    click.echo(f"Config written to {cf}")

    # Create profile skeleton
    profiles_dir = config_dir() / "profiles" / name
    profiles_dir.mkdir(parents=True, exist_ok=True)
    click.echo(f"Profile directory created at {profiles_dir}")

    click.echo()
    click.echo("Next steps:")
    click.echo(f"  1. Edit {cf}")
    click.echo(f"  2. lh profile list")
    click.echo(f"  3. lh doctor")
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/integration/test_init.py -v
```

Expected: all tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/lazy_harness/cli/init_cmd.py tests/integration/
git commit -m "feat: lh init wizard (interactive + non-interactive)"
```

---

## Task 8: Implement `lh profile list|add|remove`

**Files:**
- Modify: `src/lazy_harness/cli/profile_cmd.py`
- Test: `tests/integration/test_profile_cmd.py` (via CliRunner)

- [ ] **Step 1: Write failing tests**

`tests/integration/test_profile_cmd.py`:

```python
"""Integration tests for lh profile commands."""

from __future__ import annotations

from pathlib import Path

import pytest
from click.testing import CliRunner

from lazy_harness.cli.main import cli
from lazy_harness.core.config import (
    Config,
    HarnessConfig,
    ProfileEntry,
    ProfilesConfig,
    save_config,
)


def _setup_config(home_dir: Path) -> Path:
    """Create a valid config file and return its path."""
    config_path = home_dir / ".config" / "lazy-harness" / "config.toml"
    cfg = Config(
        harness=HarnessConfig(version="1"),
        profiles=ProfilesConfig(
            default="personal",
            items={
                "personal": ProfileEntry(
                    config_dir=str(home_dir / ".claude-personal"),
                    roots=["~"],
                ),
            },
        ),
    )
    save_config(cfg, config_path)
    return config_path


def test_profile_list(home_dir: Path) -> None:
    _setup_config(home_dir)
    runner = CliRunner()
    result = runner.invoke(cli, ["profile", "list"])
    assert result.exit_code == 0
    assert "personal" in result.output


def test_profile_add(home_dir: Path) -> None:
    _setup_config(home_dir)
    runner = CliRunner()
    result = runner.invoke(cli, [
        "profile", "add", "work",
        "--config-dir", str(home_dir / ".claude-work"),
        "--roots", "~/work",
    ])
    assert result.exit_code == 0
    assert "work" in result.output or "added" in result.output.lower()

    # Verify it persisted
    result2 = runner.invoke(cli, ["profile", "list"])
    assert "work" in result2.output


def test_profile_add_duplicate(home_dir: Path) -> None:
    _setup_config(home_dir)
    runner = CliRunner()
    result = runner.invoke(cli, [
        "profile", "add", "personal",
        "--config-dir", str(home_dir / ".claude-personal"),
    ])
    assert result.exit_code != 0 or "already exists" in result.output.lower()


def test_profile_remove(home_dir: Path) -> None:
    config_path = _setup_config(home_dir)
    # Add a second profile first
    from lazy_harness.core.config import load_config
    cfg = load_config(config_path)
    cfg.profiles.items["work"] = ProfileEntry(
        config_dir=str(home_dir / ".claude-work"), roots=["~/work"]
    )
    save_config(cfg, config_path)

    runner = CliRunner()
    result = runner.invoke(cli, ["profile", "remove", "work"])
    assert result.exit_code == 0

    result2 = runner.invoke(cli, ["profile", "list"])
    assert "work" not in result2.output


def test_profile_remove_default_fails(home_dir: Path) -> None:
    _setup_config(home_dir)
    runner = CliRunner()
    result = runner.invoke(cli, ["profile", "remove", "personal"])
    assert result.exit_code != 0 or "default" in result.output.lower()
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/integration/test_profile_cmd.py -v
```

Expected: tests fail (profile commands are stubs).

- [ ] **Step 3: Implement profile commands**

Replace `src/lazy_harness/cli/profile_cmd.py`:

```python
"""lh profile — profile management commands."""

from __future__ import annotations

import click
from rich.console import Console
from rich.table import Table

from lazy_harness.core.config import load_config, save_config, ConfigError
from lazy_harness.core.paths import config_file, contract_path, expand_path
from lazy_harness.core.profiles import (
    ProfileError,
    add_profile,
    list_profiles,
    remove_profile,
)


@click.group()
def profile() -> None:
    """Manage agent profiles."""


@profile.command("list")
def profile_list() -> None:
    """List all configured profiles."""
    cf = config_file()
    try:
        cfg = load_config(cf)
    except ConfigError as e:
        click.echo(f"Error: {e}", err=True)
        raise SystemExit(1)

    profiles = list_profiles(cfg)
    if not profiles:
        click.echo("No profiles configured. Run: lh init")
        return

    console = Console()
    table = Table(show_header=True, show_lines=False, pad_edge=False)
    table.add_column("Profile", style="bold")
    table.add_column("Config Dir")
    table.add_column("Roots")
    table.add_column("Status")

    for p in profiles:
        name = f"{p.name} (default)" if p.is_default else p.name
        status = "exists" if p.exists else "missing"
        style = "green" if p.exists else "red"
        table.add_row(
            name,
            contract_path(p.config_dir),
            ", ".join(p.roots),
            f"[{style}]{status}[/{style}]",
        )

    console.print(table)


@profile.command("add")
@click.argument("name")
@click.option("--config-dir", required=True, help="Agent config directory for this profile")
@click.option("--roots", default="", help="Comma-separated root paths")
def profile_add(name: str, config_dir: str, roots: str) -> None:
    """Add a new profile."""
    cf = config_file()
    try:
        cfg = load_config(cf)
    except ConfigError as e:
        click.echo(f"Error: {e}", err=True)
        raise SystemExit(1)

    roots_list = [r.strip() for r in roots.split(",") if r.strip()] if roots else []

    try:
        add_profile(cfg, name, config_dir, roots_list)
    except ProfileError as e:
        click.echo(f"Error: {e}", err=True)
        raise SystemExit(1)

    save_config(cfg, cf)
    click.echo(f"Profile '{name}' added.")


@profile.command("remove")
@click.argument("name")
def profile_remove(name: str) -> None:
    """Remove a profile."""
    cf = config_file()
    try:
        cfg = load_config(cf)
    except ConfigError as e:
        click.echo(f"Error: {e}", err=True)
        raise SystemExit(1)

    try:
        remove_profile(cfg, name)
    except ProfileError as e:
        click.echo(f"Error: {e}", err=True)
        raise SystemExit(1)

    save_config(cfg, cf)
    click.echo(f"Profile '{name}' removed.")
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/integration/test_profile_cmd.py -v
```

Expected: all tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/lazy_harness/cli/profile_cmd.py tests/integration/test_profile_cmd.py
git commit -m "feat: lh profile list/add/remove"
```

---

## Task 9: Implement `lh doctor`

**Files:**
- Modify: `src/lazy_harness/cli/doctor_cmd.py`
- Test: `tests/integration/test_doctor.py`

- [ ] **Step 1: Write failing tests**

`tests/integration/test_doctor.py`:

```python
"""Integration tests for lh doctor."""

from __future__ import annotations

from pathlib import Path

import pytest
from click.testing import CliRunner

from lazy_harness.cli.main import cli
from lazy_harness.core.config import (
    Config,
    HarnessConfig,
    ProfileEntry,
    ProfilesConfig,
    save_config,
)


def _setup_config(home_dir: Path, create_profile_dirs: bool = True) -> Path:
    config_path = home_dir / ".config" / "lazy-harness" / "config.toml"
    profile_dir = home_dir / ".claude-personal"
    cfg = Config(
        harness=HarnessConfig(version="1"),
        profiles=ProfilesConfig(
            default="personal",
            items={
                "personal": ProfileEntry(
                    config_dir=str(profile_dir),
                    roots=["~"],
                ),
            },
        ),
    )
    save_config(cfg, config_path)
    if create_profile_dirs:
        profile_dir.mkdir(parents=True, exist_ok=True)
    return config_path


def test_doctor_healthy(home_dir: Path) -> None:
    _setup_config(home_dir, create_profile_dirs=True)
    runner = CliRunner()
    result = runner.invoke(cli, ["doctor"])
    assert result.exit_code == 0
    assert "config" in result.output.lower()


def test_doctor_missing_config(home_dir: Path) -> None:
    runner = CliRunner()
    result = runner.invoke(cli, ["doctor"])
    assert result.exit_code != 0 or "not found" in result.output.lower() or "missing" in result.output.lower()


def test_doctor_missing_profile_dir(home_dir: Path) -> None:
    _setup_config(home_dir, create_profile_dirs=False)
    runner = CliRunner()
    result = runner.invoke(cli, ["doctor"])
    assert "missing" in result.output.lower()
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/integration/test_doctor.py -v
```

Expected: tests fail (doctor is a stub).

- [ ] **Step 3: Implement doctor command**

Replace `src/lazy_harness/cli/doctor_cmd.py`:

```python
"""lh doctor — environment health check."""

from __future__ import annotations

import shutil

import click
from rich.console import Console

from lazy_harness.agents.registry import get_agent, AgentNotFoundError
from lazy_harness.core.config import load_config, ConfigError
from lazy_harness.core.paths import config_file, contract_path, expand_path
from lazy_harness.core.profiles import list_profiles


@click.command("doctor")
def doctor() -> None:
    """Check environment health."""
    console = Console()
    ok = True

    # Check config file
    cf = config_file()
    if cf.is_file():
        console.print(f"[green]✓[/green] Config file: {contract_path(cf)}")
    else:
        console.print(f"[red]✗[/red] Config file not found: {contract_path(cf)}")
        console.print("  Run: lh init")
        raise SystemExit(1)

    try:
        cfg = load_config(cf)
    except ConfigError as e:
        console.print(f"[red]✗[/red] Config error: {e}")
        raise SystemExit(1)

    console.print(f"[green]✓[/green] Config version: {cfg.harness.version}")

    # Check agent
    try:
        agent = get_agent(cfg.agent.type)
        console.print(f"[green]✓[/green] Agent: {agent.name}")
    except AgentNotFoundError as e:
        console.print(f"[red]✗[/red] Agent: {e}")
        ok = False

    # Check profiles
    console.print()
    console.print("[bold]Profiles:[/bold]")
    profiles = list_profiles(cfg)
    for p in profiles:
        label = f"{p.name} (default)" if p.is_default else p.name
        if p.exists:
            console.print(f"  [green]✓[/green] {label} — {contract_path(p.config_dir)}")
        else:
            console.print(f"  [red]✗[/red] {label} — {contract_path(p.config_dir)} [red](missing)[/red]")
            ok = False

    # Check knowledge dir
    if cfg.knowledge.path:
        kp = expand_path(cfg.knowledge.path)
        if kp.is_dir():
            console.print(f"\n[green]✓[/green] Knowledge dir: {contract_path(kp)}")
        else:
            console.print(f"\n[red]✗[/red] Knowledge dir missing: {contract_path(kp)}")
            ok = False

    # Check QMD
    if cfg.knowledge.search.engine == "qmd":
        if shutil.which("qmd"):
            console.print("[green]✓[/green] QMD: found in PATH")
        else:
            console.print("[yellow]·[/yellow] QMD: not found in PATH (optional)")

    console.print()
    if ok:
        console.print("[green]All checks passed.[/green]")
    else:
        console.print("[red]Some checks failed. Review above.[/red]")
        raise SystemExit(1)
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/integration/test_doctor.py -v
```

Expected: all tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/lazy_harness/cli/doctor_cmd.py tests/integration/test_doctor.py
git commit -m "feat: lh doctor health check"
```

---

## Task 10: Implement `lh deploy` (symlinks for profiles)

**Files:**
- Create: `src/lazy_harness/deploy/__init__.py`
- Create: `src/lazy_harness/deploy/symlinks.py`
- Create: `src/lazy_harness/deploy/engine.py`
- Modify: `src/lazy_harness/cli/deploy_cmd.py`
- Test: `tests/integration/test_deploy.py`

- [ ] **Step 1: Write failing tests**

`tests/integration/test_deploy.py`:

```python
"""Integration tests for lh deploy."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from click.testing import CliRunner

from lazy_harness.cli.main import cli
from lazy_harness.core.config import (
    Config,
    HarnessConfig,
    ProfileEntry,
    ProfilesConfig,
    save_config,
)


def _setup_with_profile_content(home_dir: Path) -> Path:
    """Create config + profile content to deploy."""
    config_path = home_dir / ".config" / "lazy-harness" / "config.toml"
    profile_content_dir = home_dir / ".config" / "lazy-harness" / "profiles" / "personal"
    profile_content_dir.mkdir(parents=True)
    (profile_content_dir / "CLAUDE.md").write_text("# My profile\n")
    (profile_content_dir / "settings.json").write_text("{}\n")

    target_dir = home_dir / ".claude-personal"

    cfg = Config(
        harness=HarnessConfig(version="1"),
        profiles=ProfilesConfig(
            default="personal",
            items={
                "personal": ProfileEntry(
                    config_dir=str(target_dir),
                    roots=["~"],
                ),
            },
        ),
    )
    save_config(cfg, config_path)
    return config_path


def test_deploy_creates_profile_symlinks(home_dir: Path) -> None:
    _setup_with_profile_content(home_dir)
    runner = CliRunner()
    result = runner.invoke(cli, ["deploy"])
    assert result.exit_code == 0

    target = home_dir / ".claude-personal"
    assert target.is_dir()
    claude_md = target / "CLAUDE.md"
    assert claude_md.exists()
    assert claude_md.is_symlink()


def test_deploy_idempotent(home_dir: Path) -> None:
    _setup_with_profile_content(home_dir)
    runner = CliRunner()
    runner.invoke(cli, ["deploy"])
    result = runner.invoke(cli, ["deploy"])
    assert result.exit_code == 0


def test_deploy_creates_claude_symlink(home_dir: Path) -> None:
    _setup_with_profile_content(home_dir)
    runner = CliRunner()
    result = runner.invoke(cli, ["deploy"])
    assert result.exit_code == 0

    claude_link = home_dir / ".claude"
    assert claude_link.is_symlink()
    assert str(home_dir / ".claude-personal") in str(claude_link.resolve())
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/integration/test_deploy.py -v
```

Expected: tests fail (deploy is a stub).

- [ ] **Step 3: Implement deploy modules**

`src/lazy_harness/deploy/__init__.py` — empty file.

`src/lazy_harness/deploy/symlinks.py`:

```python
"""Cross-platform symlink management."""

from __future__ import annotations

import os
from pathlib import Path


def ensure_symlink(source: Path, target: Path) -> str:
    """Create or update a symlink. Returns status: 'created', 'updated', or 'exists'."""
    if target.is_symlink():
        if target.resolve() == source.resolve():
            return "exists"
        target.unlink()

    if target.exists():
        # Target exists but is not a symlink — back it up
        backup = target.with_suffix(target.suffix + ".bak")
        target.rename(backup)

    target.parent.mkdir(parents=True, exist_ok=True)
    os.symlink(source, target)
    return "created"
```

`src/lazy_harness/deploy/engine.py`:

```python
"""Deploy orchestration — symlinks profiles, hooks, skills."""

from __future__ import annotations

from pathlib import Path

import click

from lazy_harness.core.config import Config
from lazy_harness.core.paths import config_dir, expand_path
from lazy_harness.deploy.symlinks import ensure_symlink


def deploy_profiles(cfg: Config) -> None:
    """Deploy profile content as symlinks to agent config dirs."""
    profiles_src = config_dir() / "profiles"
    if not profiles_src.is_dir():
        click.echo("No profiles directory found. Run: lh init")
        return

    for name, entry in cfg.profiles.items.items():
        src_dir = profiles_src / name
        if not src_dir.is_dir():
            click.echo(f"  · Profile '{name}' has no content dir at {src_dir}")
            continue

        target_dir = expand_path(entry.config_dir)
        target_dir.mkdir(parents=True, exist_ok=True)

        for item in src_dir.iterdir():
            target = target_dir / item.name
            status = ensure_symlink(item, target)
            if status == "exists":
                click.echo(f"  · {name}/{item.name} (already linked)")
            else:
                click.echo(f"  ✓ {name}/{item.name}")


def deploy_claude_symlink(cfg: Config) -> None:
    """Create ~/.claude symlink to default profile's config dir."""
    default_name = cfg.profiles.default
    entry = cfg.profiles.items.get(default_name)
    if not entry:
        return

    home = Path.home()
    claude_link = home / ".claude"
    target = expand_path(entry.config_dir)

    status = ensure_symlink(target, claude_link)
    if status == "exists":
        click.echo(f"  · ~/.claude → {entry.config_dir} (already linked)")
    else:
        click.echo(f"  ✓ ~/.claude → {entry.config_dir}")
```

Replace `src/lazy_harness/cli/deploy_cmd.py`:

```python
"""lh deploy — deploy profiles, hooks, skills."""

from __future__ import annotations

import click

from lazy_harness.core.config import load_config, ConfigError
from lazy_harness.core.paths import config_file
from lazy_harness.deploy.engine import deploy_claude_symlink, deploy_profiles


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

    click.echo("Setting up ~/.claude symlink:")
    deploy_claude_symlink(cfg)
    click.echo()

    click.echo("Done.")
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/integration/test_deploy.py -v
```

Expected: all tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/lazy_harness/deploy/ src/lazy_harness/cli/deploy_cmd.py tests/integration/test_deploy.py
git commit -m "feat: lh deploy with profile symlinks"
```

---

## Task 11: Run full test suite + lint

**Files:** none (validation only)

- [ ] **Step 1: Run all tests**

```bash
cd ~/repos/lazy/lazy-harness
uv run pytest -v
```

Expected: all tests PASS.

- [ ] **Step 2: Run linter**

```bash
uv run ruff check src/ tests/
uv run ruff format --check src/ tests/
```

Expected: no errors. Fix any issues found.

- [ ] **Step 3: Manual smoke test**

```bash
# Clean slate test
export HOME=$(mktemp -d)
uv run lh init --profile-name test --profile-config-dir ~/.claude-test --agent claude-code --non-interactive
uv run lh profile list
uv run lh doctor
```

Expected: init creates config, list shows the profile, doctor reports status.

- [ ] **Step 4: Commit any fixes**

```bash
git add -A
git commit -m "fix: lint and smoke test fixes"
```

---

## Task 12: Write initial ADRs

**Files:**
- Create: `docs/architecture/adrs/001-hybrid-architecture.md`
- Create: `docs/architecture/adrs/002-python-uv-distribution.md`
- Create: `docs/architecture/adrs/003-toml-config-format.md`
- Create: `docs/architecture/adrs/004-agent-adapter-pattern.md`
- Create: `docs/architecture/adrs/007-parallel-bootstrap-migration.md`

- [ ] **Step 1: Create ADR directory**

```bash
mkdir -p ~/repos/lazy/lazy-harness/docs/architecture/adrs
```

- [ ] **Step 2: Write ADR-001 (hybrid architecture)**

`docs/architecture/adrs/001-hybrid-architecture.md`:

```markdown
# ADR-001: Hybrid Architecture (Framework + Dotfile Config)

**Status:** accepted
**Date:** 2026-04-12

## Context

lazy-harness needs to be both a reusable product and personally customizable. The user's profiles, skills, and agent instructions are personal content that shouldn't live in the framework repo.

## Decision

Framework installs as a Python package. User config lives in `~/.config/lazy-harness/` as standard dotfiles, managed by whatever dotfile tool the user prefers (chezmoi, stow, etc.).

## Alternatives Considered

- **Monorepo (framework + content):** Coupling, can't share framework without sharing personal config.
- **Template repo (fork & customize):** Updates are manual cherry-picks. Diverges fast.
- **Installer-only (no persistent framework):** No upgrade path, no shared hooks/skills.

## Consequences

- Users need no repo to use the framework — `lh init` is enough.
- Power users can version their `~/.config/lazy-harness/` with git or chezmoi.
- Framework updates are independent of user config (`uv tool upgrade`).
```

- [ ] **Step 3: Write ADR-002 (Python + uv)**

`docs/architecture/adrs/002-python-uv-distribution.md`:

```markdown
# ADR-002: Python with uv Distribution

**Status:** accepted
**Date:** 2026-04-12

## Context

The CLI needs to work on macOS, Linux, and Windows. The existing codebase has significant Python code (monitoring, stats) and bash scripts (hooks, deploy).

## Decision

Python 3.11+ for all framework code. Distribution via `uv tool install` (git clone initially, PyPI when stable). Bash scripts are rewritten in Python.

## Alternatives Considered

- **Node/TypeScript:** Claude Code is Node, but requiring Node as a dependency adds friction for non-JS users.
- **Go:** Zero-dependency binary, but higher development cost and no reuse of existing Python code.
- **Keep bash + Python mix:** Not cross-platform (Windows), harder to test, two languages to maintain.

## Consequences

- `uv` is the only prerequisite for installation.
- All code is testable with pytest.
- Windows support is feasible (no bash dependency).
- `tomllib` is built-in from Python 3.11 (no TOML parsing dependency).
```

- [ ] **Step 4: Write ADR-003 (TOML config)**

`docs/architecture/adrs/003-toml-config-format.md`:

```markdown
# ADR-003: TOML Config Format

**Status:** accepted
**Date:** 2026-04-12

## Context

The framework needs a single config file that users edit manually. It must support comments, nested sections, and be parseable without external dependencies.

## Decision

TOML at `~/.config/lazy-harness/config.toml`. Read with `tomllib` (stdlib), write with `tomli-w`.

## Alternatives Considered

- **YAML:** Needs PyYAML dependency. Footguns (Norway problem, implicit typing).
- **JSON:** No comments. Hostile for human-edited config.
- **INI:** No nested structures. Insufficient for profiles + hooks + monitoring config.

## Consequences

- No parsing dependency (tomllib is stdlib in 3.11+).
- One small write dependency (tomli-w) for `lh init` and config updates.
- Consistent with Python ecosystem tooling (pyproject.toml, ruff, uv).
```

- [ ] **Step 5: Write ADR-004 (agent adapter pattern)**

`docs/architecture/adrs/004-agent-adapter-pattern.md`:

```markdown
# ADR-004: Agent Adapter Pattern

**Status:** accepted
**Date:** 2026-04-12

## Context

lazy-harness is designed to support multiple AI coding agents. v1 only supports Claude Code, but the architecture must allow adding agents without restructuring.

## Decision

Python Protocol-based adapter pattern. Each agent implements `AgentAdapter` protocol: config dir resolution, session parsing, hook support, and hook config generation. A registry maps `config.toml`'s `[agent].type` to the adapter.

## Alternatives Considered

- **Agent-specific code throughout:** Fast for one agent, rewrite for each new one.
- **Plugin-only agents:** Too much indirection for v1. Adapters are simpler.

## Consequences

- Adding a new agent = implementing the protocol + registering it.
- Core framework code never references agent-specific details.
- The protocol is minimal — only what the framework actually needs from agents.
```

- [ ] **Step 6: Write ADR-007 (parallel bootstrap migration)**

`docs/architecture/adrs/007-parallel-bootstrap-migration.md`:

```markdown
# ADR-007: Parallel Bootstrap Migration

**Status:** accepted
**Date:** 2026-04-12

## Context

lazy-claudecode is a working personal setup. Migrating to lazy-harness must not break the existing workflow during transition.

## Decision

New repo (lazy-harness) built alongside the old one (lazy-claudecode). Components migrate one at a time. The old system keeps working until each replacement is validated with real use. Four phases: bootstrap → hooks/deploy → knowledge/QMD → cutover.

## Alternatives Considered

- **Big bang rewrite:** Months without a working system. High risk of abandonment.
- **In-place migration:** Messy gitignores, framework and personal content never fully separate.

## Consequences

- Two repos to maintain during transition (weeks, not months).
- Each phase has clear exit criteria and is independently testable.
- No downtime — the old system works until the new one proves itself.
```

- [ ] **Step 7: Commit ADRs**

```bash
git add docs/
git commit -m "docs: initial ADRs (001-004, 007)"
```

---

## Task 13: Final validation and tag

- [ ] **Step 1: Run full test suite**

```bash
cd ~/repos/lazy/lazy-harness
uv run pytest -v --tb=short
```

Expected: all tests PASS.

- [ ] **Step 2: Verify end-to-end workflow**

```bash
cd ~/repos/lazy/lazy-harness
uv run lh --version
uv run lh --help
```

Expected: version `0.1.0`, help shows `init`, `profile`, `doctor`, `deploy`.

- [ ] **Step 3: Tag the release**

```bash
git tag -a v0.1.0 -m "Phase 1: Framework bootstrap — config, profiles, CLI, deploy"
```

- [ ] **Step 4: Update lazy-claudecode spec with Phase 1 completion**

In `~/repos/lazy/lazy-claudecode/`, commit a note that Phase 1 is complete and Phase 2 (hooks + monitoring) is next.

"""Shared test fixtures for lazy-harness."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

import pytest


@dataclass(frozen=True)
class GitCheckout:
    """A real repo with the two shapes that fragment a naive project key.

    `subdir` stands in for a build- or tool-artifact directory the agent may
    be launched from; `worktree` is a linked worktree. Both must resolve back
    to `repo`.
    """

    repo: Path
    subdir: Path
    worktree: Path


@pytest.fixture(autouse=True)
def _isolate_agent_config_dir(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep the developer's own profile out of every test.

    `profile_name()` reads this variable, so without it a hook test records
    whatever profile the machine happens to run under — 'lazy' locally and ''
    in CI, from identical code. Tests that need a profile opt in via
    `active_profile`.
    """
    monkeypatch.delenv("CLAUDE_CONFIG_DIR", raising=False)


@pytest.fixture
def active_profile(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> str:
    """Point the agent at one of two configured profiles; return its name.

    Two are declared so a hook that records the *default* profile rather than
    the running one still fails.
    """
    lazy_dir = tmp_path / "claude-lazy"
    flex_dir = tmp_path / "claude-flex"
    lazy_dir.mkdir()
    flex_dir.mkdir()
    cfg = tmp_path / "profiles-config.toml"
    cfg.write_text(
        '[harness]\nversion = "1"\n\n[agent]\ntype = "claude-code"\n\n'
        '[profiles]\ndefault = "lazy"\n\n'
        f'[profiles.lazy]\nconfig_dir = "{lazy_dir}"\nroots = ["~"]\n\n'
        f'[profiles.flex]\nconfig_dir = "{flex_dir}"\nroots = ["~"]\n'
    )
    monkeypatch.setattr("lazy_harness.core.paths.config_file", lambda: cfg)
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(flex_dir))
    return "flex"


@pytest.fixture
def git_checkout(tmp_path: Path) -> GitCheckout:
    """Real git repo plus an artifact subdirectory and a linked worktree."""
    repo = tmp_path / "myrepo"
    repo.mkdir()
    base = ["git", "-c", "user.email=t@t", "-c", "user.name=t"]
    subprocess.run([*base, "init", "-q"], cwd=repo, check=True, capture_output=True)
    subprocess.run(
        [*base, "commit", "-q", "--allow-empty", "-m", "init"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    subdir = repo / "graphify-out"
    subdir.mkdir()
    worktree = repo / ".worktrees" / "feat"
    subprocess.run(
        [*base, "worktree", "add", "-q", str(worktree), "-b", "feat"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    return GitCheckout(repo=repo, subdir=subdir, worktree=worktree)


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

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

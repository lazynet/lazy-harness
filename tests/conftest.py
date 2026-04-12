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

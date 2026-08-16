"""Tests for the shared DB path resolver every writer and reader must agree on.

FINDING 1 (final whole-branch review, 2026-08-16): the loop_events writers
hard-coded `data_dir() / "metrics.db"` while every reader honours
`[monitoring] db` first. This resolver is the single source of truth both
sides now call.
"""

from __future__ import annotations

from pathlib import Path

import pytest


def test_honours_the_configured_monitoring_db(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    configured_db = tmp_path / "custom" / "metrics.db"
    cfg_file = tmp_path / "config.toml"
    cfg_file.write_text(f'[harness]\nversion = "1"\n\n[monitoring]\ndb = "{configured_db}"\n')

    from lazy_harness.core import paths as paths_mod

    monkeypatch.setattr(paths_mod, "config_file", lambda: cfg_file)

    from lazy_harness.monitoring.db import resolve_db_path

    assert resolve_db_path() == configured_db


def test_falls_back_to_data_dir_when_no_db_is_configured(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cfg_file = tmp_path / "config.toml"
    cfg_file.write_text('[harness]\nversion = "1"\n')

    from lazy_harness.core import paths as paths_mod

    monkeypatch.setattr(paths_mod, "config_file", lambda: cfg_file)
    monkeypatch.setattr(paths_mod, "data_dir", lambda: tmp_path / "data")

    from lazy_harness.monitoring.db import resolve_db_path

    assert resolve_db_path() == tmp_path / "data" / "metrics.db"


def test_falls_back_to_data_dir_when_config_is_unreadable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from lazy_harness.core import paths as paths_mod

    def _boom() -> Path:
        raise OSError("config unreadable")

    monkeypatch.setattr(paths_mod, "config_file", _boom)
    monkeypatch.setattr(paths_mod, "data_dir", lambda: tmp_path / "data")

    from lazy_harness.monitoring.db import resolve_db_path

    assert resolve_db_path() == tmp_path / "data" / "metrics.db"

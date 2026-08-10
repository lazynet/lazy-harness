"""Tests for the [knowledge] config-shape migration."""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest

_OLD = (
    "[harness]\n"
    'version = "1"\n\n'
    "[knowledge]\n"
    'path = "~/vault/Meta"\n\n'
    "[knowledge.sessions]\n"
    "enabled = true\n"
    'subdir = "sessions"\n\n'
    "[knowledge.learnings]\n"
    "enabled = true\n"
    'subdir = "Learnings"\n\n'
    "[compound_loop]\n"
    'learnings_subdir = "Learnings"\n'
    'lazymind_dir = "~/vault"\n'
)


def test_migrate_knowledge_path_to_root(tmp_path: Path) -> None:
    from lazy_harness.migrate.config_shape import migrate_knowledge_block

    cfg = tmp_path / "config.toml"
    cfg.write_text(_OLD, encoding="utf-8")
    migrate_knowledge_block(cfg, new_root="~/repos/lazy/lazy-knowledge")
    text = cfg.read_text(encoding="utf-8")
    assert 'root = "~/repos/lazy/lazy-knowledge"' in text
    assert "path =" not in text
    assert "subdir" not in text
    assert "learnings_subdir" not in text
    assert 'lazymind_dir = "~/vault"' in text


def test_migration_preserves_unrelated_keys(tmp_path: Path) -> None:
    from lazy_harness.migrate.config_shape import migrate_knowledge_block

    cfg = tmp_path / "config.toml"
    cfg.write_text(_OLD, encoding="utf-8")
    migrate_knowledge_block(cfg, new_root="~/k")
    raw = tomllib.loads(cfg.read_text(encoding="utf-8"))
    assert raw["harness"]["version"] == "1"
    assert raw["knowledge"]["sessions"]["enabled"] is True
    assert raw["knowledge"]["learnings"]["enabled"] is True
    assert raw["compound_loop"]["lazymind_dir"] == "~/vault"


def test_migrated_config_loads(tmp_path: Path) -> None:
    """The whole point: the rewritten file must pass the new parser."""
    from lazy_harness.core.config import load_config
    from lazy_harness.migrate.config_shape import migrate_knowledge_block

    cfg = tmp_path / "config.toml"
    cfg.write_text(_OLD, encoding="utf-8")
    migrate_knowledge_block(cfg, new_root="~/k")
    loaded = load_config(cfg)
    assert loaded.knowledge.root == "~/k"
    assert loaded.compound_loop.lazymind_dir == "~/vault"


def test_migration_is_idempotent(tmp_path: Path) -> None:
    from lazy_harness.migrate.config_shape import migrate_knowledge_block

    cfg = tmp_path / "config.toml"
    cfg.write_text(_OLD, encoding="utf-8")
    migrate_knowledge_block(cfg, new_root="~/k")
    once = cfg.read_text(encoding="utf-8")
    migrate_knowledge_block(cfg, new_root="~/k")
    assert cfg.read_text(encoding="utf-8") == once


def test_already_migrated_config_keeps_its_root(tmp_path: Path) -> None:
    """A second run must not clobber a root the user already set."""
    from lazy_harness.migrate.config_shape import migrate_knowledge_block

    cfg = tmp_path / "config.toml"
    cfg.write_text('[harness]\nversion = "1"\n\n[knowledge]\nroot = "~/mine"\n', encoding="utf-8")
    migrate_knowledge_block(cfg, new_root="~/k")
    assert 'root = "~/mine"' in cfg.read_text(encoding="utf-8")


def test_missing_file_raises(tmp_path: Path) -> None:
    from lazy_harness.migrate.config_shape import migrate_knowledge_block

    with pytest.raises(FileNotFoundError):
        migrate_knowledge_block(tmp_path / "nope.toml", new_root="~/k")

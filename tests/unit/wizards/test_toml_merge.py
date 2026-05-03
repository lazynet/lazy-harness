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


def test_merge_preserves_existing_sections(tmp_path: Path) -> None:
    import tomllib

    from lazy_harness.wizards._toml_merge import merge_into_config

    cfg_path = tmp_path / "config.toml"
    cfg_path.write_text('[harness]\nversion = "1"\n\n[agent]\ntype = "claude-code"\n')

    merge_into_config(cfg_path, {"memory": {"engram": {"enabled": True}}})

    parsed = tomllib.loads(cfg_path.read_text())
    assert parsed["harness"]["version"] == "1"
    assert parsed["agent"]["type"] == "claude-code"
    assert parsed["memory"]["engram"]["enabled"] is True


def test_merge_overlays_existing_keys(tmp_path: Path) -> None:
    import tomllib

    from lazy_harness.wizards._toml_merge import merge_into_config

    cfg_path = tmp_path / "config.toml"
    cfg_path.write_text("[memory.engram]\nenabled = false\ngit_sync = true\n")

    merge_into_config(cfg_path, {"memory": {"engram": {"enabled": True}}})

    parsed = tomllib.loads(cfg_path.read_text())
    assert parsed["memory"]["engram"]["enabled"] is True
    assert parsed["memory"]["engram"]["git_sync"] is True

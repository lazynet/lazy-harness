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


def test_merge_preserves_comments(tmp_path: Path) -> None:
    """`lh config <feature> --init` must not wipe hand-written rationale.

    The helper read the raw TOML so keys survived, but wrote it back through
    `tomli_w`, which emits no comments — the same defect the config writer
    carried until it moved to tomlkit.
    """
    from lazy_harness.wizards._toml_merge import merge_into_config

    cfg_path = tmp_path / "config.toml"
    cfg_path.write_text(
        "# why the engram MCP is off here\n"
        '[harness]\nversion = "1"\n\n'
        "# this sweep keeps the graph fresh\n"
        "[knowledge.structure]\n"
        "enabled = true\n"
    )

    merge_into_config(cfg_path, {"memory": {"engram": {"enabled": True}}})

    text = cfg_path.read_text()
    assert "# why the engram MCP is off here" in text
    assert "# this sweep keeps the graph fresh" in text


def test_merge_preserves_the_file_mode(tmp_path: Path) -> None:
    """mkstemp creates 0600 and os.replace carries that onto the target."""
    import stat

    from lazy_harness.wizards._toml_merge import merge_into_config

    cfg_path = tmp_path / "config.toml"
    cfg_path.write_text('[harness]\nversion = "1"\n')
    cfg_path.chmod(0o644)

    merge_into_config(cfg_path, {"memory": {"engram": {"enabled": True}}})

    assert stat.S_IMODE(cfg_path.stat().st_mode) == 0o644


def test_merge_leaves_unchanged_values_byte_identical(tmp_path: Path) -> None:
    """Only the merged block may change; everything else keeps its formatting."""
    from lazy_harness.wizards._toml_merge import merge_into_config

    original = (
        '[harness]\nversion = "1"\n\n'
        "[profiles.lazy]\n"
        'roots = ["~/repos/lazy", "~/repos/other"]\n'
    )
    cfg_path = tmp_path / "config.toml"
    cfg_path.write_text(original)

    merge_into_config(cfg_path, {"memory": {"engram": {"enabled": True}}})

    text = cfg_path.read_text()
    assert 'roots = ["~/repos/lazy", "~/repos/other"]' in text


def test_merge_removes_the_temp_file_when_writing_fails(tmp_path: Path, monkeypatch) -> None:
    """A failed write must not leave a stray `config.toml.*` beside the real one."""
    import pytest

    from lazy_harness.wizards import _toml_merge

    cfg_path = tmp_path / "config.toml"
    cfg_path.write_text('[harness]\nversion = "1"\n')

    def boom(*_args, **_kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(_toml_merge.Path, "write_bytes", boom)

    with pytest.raises(OSError, match="disk full"):
        _toml_merge.merge_into_config(cfg_path, {"memory": {"engram": {"enabled": True}}})

    strays = [p.name for p in tmp_path.iterdir() if p.name != "config.toml"]
    assert strays == []
    assert cfg_path.read_text() == '[harness]\nversion = "1"\n'



def test_migrate_knowledge_block_preserves_comments_and_mode(tmp_path) -> None:
    """`lh config migrate-knowledge` writes the live config.

    It went through tomli_w straight onto the real path — no comments, no
    temp file, so a failure mid-write truncated the config with no recovery.
    """
    import stat

    from lazy_harness.migrate.config_shape import migrate_knowledge_block

    cfg_path = tmp_path / "config.toml"
    cfg_path.write_text(
        "# why the store lives where it does\n"
        '[harness]\nversion = "1"\n\n'
        "[knowledge]\n"
        'path = "~/old/vault/path"\n'
    )
    cfg_path.chmod(0o644)

    migrate_knowledge_block(cfg_path, new_root="~/repos/lazy/lazy-knowledge")

    text = cfg_path.read_text()
    assert "# why the store lives where it does" in text
    assert stat.S_IMODE(cfg_path.stat().st_mode) == 0o644


def test_migrate_knowledge_block_leaves_the_config_intact_when_writing_fails(
    tmp_path, monkeypatch
) -> None:
    """No temp file meant a failed write destroyed the real config."""
    import pytest

    from lazy_harness.migrate import config_shape

    cfg_path = tmp_path / "config.toml"
    original = '[harness]\nversion = "1"\n\n[knowledge]\npath = "~/old"\n'
    cfg_path.write_text(original)

    def boom(*_a, **_k):
        raise OSError("disk full")

    monkeypatch.setattr(config_shape.tomlkit, "dumps", boom)

    with pytest.raises(OSError, match="disk full"):
        config_shape.migrate_knowledge_block(cfg_path, new_root="~/new")

    assert cfg_path.read_text() == original
    assert [p.name for p in tmp_path.iterdir()] == ["config.toml"]

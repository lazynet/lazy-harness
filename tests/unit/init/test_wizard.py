from pathlib import Path

import pytest

from lazy_harness.init.wizard import ExistingSetupError, check_existing_setup


def test_check_existing_no_setup(tmp_path: Path):
    check_existing_setup(
        home=tmp_path,
        lh_config=tmp_path / ".config" / "lazy-harness" / "config.toml",
    )


def test_check_existing_lh_config_present(tmp_path: Path):
    cfg = tmp_path / ".config" / "lazy-harness" / "config.toml"
    cfg.parent.mkdir(parents=True)
    cfg.write_text("")
    with pytest.raises(ExistingSetupError, match="already configured"):
        check_existing_setup(home=tmp_path, lh_config=cfg)


def test_check_existing_claude_dir(tmp_path: Path):
    claude = tmp_path / ".claude"
    claude.mkdir()
    (claude / "settings.json").write_text("{}")
    with pytest.raises(ExistingSetupError, match="migrate"):
        check_existing_setup(home=tmp_path, lh_config=tmp_path / "nonexistent.toml")


def test_check_existing_lazy_profile(tmp_path: Path):
    (tmp_path / ".claude-lazy").mkdir()
    (tmp_path / ".claude-lazy" / "settings.json").write_text("{}")
    with pytest.raises(ExistingSetupError, match="migrate"):
        check_existing_setup(home=tmp_path, lh_config=tmp_path / "nonexistent.toml")

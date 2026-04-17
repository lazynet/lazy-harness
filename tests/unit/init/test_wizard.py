from pathlib import Path

import pytest

from lazy_harness.init.wizard import (
    ExistingSetupError,
    WizardAnswers,
    check_existing_setup,
    run_wizard,
)


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


def test_run_wizard_generates_config(tmp_path: Path):
    answers = WizardAnswers(
        profile_name="personal",
        agent="claude-code",
        knowledge_path=tmp_path / "knowledge",
        enable_qmd=False,
    )
    cfg_path = tmp_path / ".config" / "lazy-harness" / "config.toml"
    run_wizard(answers, config_path=cfg_path)

    assert cfg_path.is_file()
    content = cfg_path.read_text()
    assert "[profiles.personal]" in content
    assert "claude-code" in content
    assert (tmp_path / "knowledge").is_dir()
    assert (tmp_path / "knowledge" / "sessions").is_dir()
    assert (tmp_path / "knowledge" / "learnings").is_dir()


def test_run_wizard_writes_pre_tool_use_hook_block(tmp_path: Path) -> None:
    import tomllib

    cfg = tmp_path / "config.toml"
    answers = WizardAnswers(
        profile_name="demo",
        agent="claude-code",
        knowledge_path=tmp_path / "kb",
        enable_qmd=False,
    )
    run_wizard(answers, config_path=cfg)
    parsed = tomllib.loads(cfg.read_text())
    block = parsed.get("hooks", {}).get("pre_tool_use", {})
    assert block.get("scripts") == ["pre-tool-use-security"]
    assert block.get("allow_patterns") == []


def test_run_wizard_writes_post_tool_use_hook_block(tmp_path: Path) -> None:
    import tomllib

    cfg = tmp_path / "config.toml"
    answers = WizardAnswers(
        profile_name="demo",
        agent="claude-code",
        knowledge_path=tmp_path / "kb",
        enable_qmd=False,
    )
    run_wizard(answers, config_path=cfg)
    parsed = tomllib.loads(cfg.read_text())
    block = parsed.get("hooks", {}).get("post_tool_use", {})
    assert block.get("scripts") == ["post-tool-use-format"]

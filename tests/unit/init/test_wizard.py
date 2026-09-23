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
        identity="personal",
        agent="claude-code",
        knowledge_path=tmp_path / "knowledge",
        enable_qmd=False,
    )
    cfg_path = tmp_path / ".config" / "lazy-harness" / "config.toml"
    run_wizard(answers, config_path=cfg_path)

    assert cfg_path.is_file()
    content = cfg_path.read_text()
    assert "[profiles.claude-personal]" in content
    assert "claude-code" in content
    assert (tmp_path / "knowledge").is_dir()
    assert (tmp_path / "knowledge" / "sessions").is_dir()
    assert (tmp_path / "knowledge" / "learnings").is_dir()


def test_run_wizard_writes_pre_tool_use_hook_block(tmp_path: Path) -> None:
    import tomllib

    cfg = tmp_path / "config.toml"
    answers = WizardAnswers(
        identity="demo",
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
        identity="demo",
        agent="claude-code",
        knowledge_path=tmp_path / "kb",
        enable_qmd=False,
    )
    run_wizard(answers, config_path=cfg)
    parsed = tomllib.loads(cfg.read_text())
    block = parsed.get("hooks", {}).get("post_tool_use", {})
    assert block.get("scripts") == ["post-tool-use-format", "post-tool-use-sync-system-doc"]


# --- agent-aware naming, config_dir + agent/billing_model fields ------------


def test_run_wizard_uses_claude_config_dir_convention_by_default(tmp_path: Path) -> None:
    from lazy_harness.core.config import load_config

    cfg_path = tmp_path / "config.toml"
    run_wizard(
        WizardAnswers(
            identity="personal",
            agent="claude-code",
            knowledge_path=tmp_path / "kb",
            enable_qmd=False,
        ),
        config_path=cfg_path,
    )

    cfg = load_config(cfg_path)
    assert cfg.profiles.items["claude-personal"].config_dir == "~/.claude-personal"


def test_run_wizard_uses_codex_config_dir_convention(tmp_path: Path) -> None:
    from lazy_harness.core.config import load_config

    cfg_path = tmp_path / "config.toml"
    run_wizard(
        WizardAnswers(
            identity="work",
            agent="codex",
            knowledge_path=tmp_path / "kb",
            enable_qmd=False,
        ),
        config_path=cfg_path,
    )

    cfg = load_config(cfg_path)
    assert cfg.profiles.items["codex-work"].config_dir == "~/.codex-work"


def test_run_wizard_uses_copilot_config_dir_convention(tmp_path: Path) -> None:
    from lazy_harness.core.config import load_config

    cfg_path = tmp_path / "config.toml"
    run_wizard(
        WizardAnswers(
            identity="cop",
            agent="copilot",
            knowledge_path=tmp_path / "kb",
            enable_qmd=False,
        ),
        config_path=cfg_path,
    )

    cfg = load_config(cfg_path)
    assert cfg.profiles.items["copilot-cop"].config_dir == "~/.copilot-cop"


def test_run_wizard_leaves_profile_agent_empty_for_the_default_agent(tmp_path: Path) -> None:
    """Empty means 'inherit [agent].type' — redundant to also stamp it here."""
    from lazy_harness.core.config import load_config

    cfg_path = tmp_path / "config.toml"
    run_wizard(
        WizardAnswers(
            identity="personal",
            agent="claude-code",
            knowledge_path=tmp_path / "kb",
            enable_qmd=False,
        ),
        config_path=cfg_path,
    )

    cfg = load_config(cfg_path)
    assert cfg.profiles.items["claude-personal"].agent == ""


def test_run_wizard_stamps_profile_agent_when_it_differs_from_the_default(tmp_path: Path) -> None:
    from lazy_harness.core.config import load_config

    cfg_path = tmp_path / "config.toml"
    run_wizard(
        WizardAnswers(
            identity="work",
            agent="codex",
            knowledge_path=tmp_path / "kb",
            enable_qmd=False,
        ),
        config_path=cfg_path,
    )

    cfg = load_config(cfg_path)
    assert cfg.profiles.items["codex-work"].agent == "codex"


def test_run_wizard_defaults_billing_model_to_per_token(tmp_path: Path) -> None:
    from lazy_harness.core.config import load_config

    cfg_path = tmp_path / "config.toml"
    run_wizard(
        WizardAnswers(
            identity="personal",
            agent="claude-code",
            knowledge_path=tmp_path / "kb",
            enable_qmd=False,
        ),
        config_path=cfg_path,
    )

    cfg = load_config(cfg_path)
    assert cfg.profiles.items["claude-personal"].billing_model == "per_token"


def test_run_wizard_writes_billing_model_when_answered(tmp_path: Path) -> None:
    """ADR-050 rejects a per-agent billing default — Codex is per_token too
    unless the user answers flat_rate explicitly."""
    from lazy_harness.core.config import load_config

    cfg_path = tmp_path / "config.toml"
    run_wizard(
        WizardAnswers(
            identity="work",
            agent="codex",
            knowledge_path=tmp_path / "kb",
            enable_qmd=False,
            billing_model="flat_rate",
        ),
        config_path=cfg_path,
    )

    cfg = load_config(cfg_path)
    assert cfg.profiles.items["codex-work"].billing_model == "flat_rate"


def test_wizard_writes_a_config_that_loads_and_a_marked_store(tmp_path: Path) -> None:
    """`lh init` must produce a config the parser accepts and a store with a marker."""
    from lazy_harness.core.config import load_config
    from lazy_harness.init.wizard import WizardAnswers, run_wizard

    store = tmp_path / "knowledge"
    config_path = tmp_path / "config.toml"
    run_wizard(
        WizardAnswers(
            identity="personal",
            agent="claude-code",
            knowledge_path=store,
            enable_qmd=False,
        ),
        config_path=config_path,
    )

    assert "path =" not in config_path.read_text(encoding="utf-8")
    cfg = load_config(config_path)
    assert cfg.knowledge.root

    assert (store / "knowledge.toml").is_file()
    assert (store / "sessions").is_dir()
    assert (store / "learnings").is_dir()


# --- profile identity (Task 6) ---------------------------------------------- #


def test_run_wizard_names_the_profile_by_agent_and_identity(tmp_path: Path) -> None:
    from lazy_harness.core.config import load_config

    cfg_path = tmp_path / "config.toml"
    profile_name = run_wizard(
        WizardAnswers(
            identity="work",
            agent="codex",
            knowledge_path=tmp_path / "kb",
            enable_qmd=False,
        ),
        config_path=cfg_path,
    )

    assert profile_name == "codex-work"
    cfg = load_config(cfg_path)
    assert "codex-work" in cfg.profiles.items
    assert cfg.profiles.items["codex-work"].identity == "work"
    assert cfg.profiles.items["codex-work"].config_dir == "~/.codex-work"
    assert cfg.profiles.default == "codex-work"


def test_run_wizard_written_config_round_trips(tmp_path: Path) -> None:
    """The written file must load back through the real parser, not just parse
    as TOML — the loader also validates the identity/name shape."""
    from lazy_harness.core.config import load_config

    cfg_path = tmp_path / "config.toml"
    run_wizard(
        WizardAnswers(
            identity="personal",
            agent="claude-code",
            knowledge_path=tmp_path / "kb",
            enable_qmd=False,
        ),
        config_path=cfg_path,
    )

    cfg = load_config(cfg_path)
    assert cfg.profiles.items["claude-personal"].identity == "personal"

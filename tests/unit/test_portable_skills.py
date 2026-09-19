"""ADR-059: portable skills project into each adapter's native root."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from lazy_harness.agents.claude_code import ClaudeCodeAdapter
from lazy_harness.agents.codex import CodexAdapter
from lazy_harness.agents.copilot import CopilotAdapter
from lazy_harness.core.config import Config, ProfileEntry
from lazy_harness.deploy.engine import deploy_profiles
from lazy_harness.deploy.ledger import LEDGER_RELATIVE, write_ledger
from lazy_harness.deploy.skills import SKILL_LEDGER_RELATIVE, SkillCollisionError


def _config(home: Path, profiles: dict[str, str]) -> Config:
    cfg = Config()
    cfg.agent.type = "claude-code"
    cfg.profiles.default = next(iter(profiles))
    cfg.profiles.items = {
        name: ProfileEntry(config_dir=str(home / f".{name}"), agent=agent)
        for name, agent in profiles.items()
    }
    return cfg


def _skill(profile: Path, segment: str, name: str, body: str) -> Path:
    skill = profile / segment / "skills" / name
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text(body)
    return skill


def test_each_adapter_declares_only_its_measured_native_skill_root(home_dir: Path) -> None:
    claude_home = home_dir / ".claude-work"
    codex_home = home_dir / ".codex-work"

    assert ClaudeCodeAdapter().skill_root(str(claude_home)) == claude_home / "skills"
    assert CodexAdapter().skill_root(str(codex_home)) == home_dir / ".agents" / "skills"
    assert CopilotAdapter().skill_root(str(home_dir / ".copilot-work")) is None


def test_codex_disables_the_root_when_host_skill_discovery_is_disabled(home_dir: Path) -> None:
    codex_home = home_dir / ".codex-work"
    codex_home.mkdir()
    (codex_home / "config.toml").write_text("[features]\nskip_host_skill_discovery = true\n")

    assert CodexAdapter().skill_root(str(codex_home)) is None


def test_codex_profiles_are_planned_together_and_link_each_skill_once(home_dir: Path) -> None:
    from lazy_harness.core.paths import config_dir

    profiles = config_dir() / "profiles"
    first = _skill(profiles / "one", "shared", "alpha", "alpha")
    second = _skill(profiles / "two", "codex", "beta", "beta")
    cfg = _config(home_dir, {"one": "codex", "two": "codex"})

    deploy_profiles(cfg)

    root = home_dir / ".agents" / "skills"
    assert (root / "alpha").is_symlink()
    assert (root / "alpha").resolve() == first.resolve()
    assert (root / "beta").is_symlink()
    assert (root / "beta").resolve() == second.resolve()
    ledger = root.parent / SKILL_LEDGER_RELATIVE
    assert json.loads(ledger.read_text())["links"] == ["alpha", "beta"]
    assert not (home_dir / ".one" / "skills").exists()
    assert not (home_dir / ".two" / "skills").exists()


def test_different_content_for_one_global_name_refuses_before_any_write(home_dir: Path) -> None:
    from lazy_harness.core.paths import config_dir

    profiles = config_dir() / "profiles"
    _skill(profiles / "one", "shared", "same", "one")
    _skill(profiles / "two", "codex", "same", "two")
    cfg = _config(home_dir, {"one": "codex", "two": "codex"})

    with pytest.raises(SkillCollisionError, match="same"):
        deploy_profiles(cfg)

    assert not (home_dir / ".agents").exists()
    assert not (home_dir / ".one").exists()
    assert not (home_dir / ".two").exists()


def test_identical_content_for_one_global_name_is_one_deterministic_link(home_dir: Path) -> None:
    from lazy_harness.core.paths import config_dir

    profiles = config_dir() / "profiles"
    first = _skill(profiles / "one", "shared", "same", "identical")
    _skill(profiles / "two", "codex", "same", "identical")
    cfg = _config(home_dir, {"one": "codex", "two": "codex"})

    deploy_profiles(cfg)

    link = home_dir / ".agents" / "skills" / "same"
    assert link.is_symlink()
    assert link.resolve() == first.resolve()


def test_agent_skill_wins_over_shared_skill_as_one_directory(home_dir: Path) -> None:
    from lazy_harness.core.paths import config_dir

    profile = config_dir() / "profiles" / "one"
    _skill(profile, "shared", "same", "shared")
    winner = _skill(profile, "codex", "same", "agent")

    deploy_profiles(_config(home_dir, {"one": "codex"}))

    link = home_dir / ".agents" / "skills" / "same"
    assert link.resolve() == winner.resolve()
    assert (link / "SKILL.md").read_text() == "agent"


def test_user_owned_entry_is_never_adopted_or_replaced(home_dir: Path) -> None:
    from lazy_harness.core.paths import config_dir

    profile = config_dir() / "profiles" / "one"
    _skill(profile, "shared", "mine", "managed")
    root = home_dir / ".agents" / "skills"
    owned = root / "mine"
    owned.mkdir(parents=True)
    (owned / "SKILL.md").write_text("user")

    with pytest.raises(SkillCollisionError, match="user-owned.*mine"):
        deploy_profiles(_config(home_dir, {"one": "codex"}))

    assert not owned.is_symlink()
    assert (owned / "SKILL.md").read_text() == "user"
    assert not (root.parent / SKILL_LEDGER_RELATIVE).exists()


def test_legacy_claude_skills_link_is_migrated_from_the_general_ledger(home_dir: Path) -> None:
    from lazy_harness.core.paths import config_dir

    profile = config_dir() / "profiles" / "one"
    skill = _skill(profile, "", "portable", "managed")
    target = home_dir / ".one"
    target.mkdir()
    (target / "skills").symlink_to(profile / "skills", target_is_directory=True)
    write_ledger(target, {Path("skills")})

    deploy_profiles(_config(home_dir, {"one": "claude-code"}))

    root = target / "skills"
    assert root.is_dir()
    assert not root.is_symlink()
    assert (root / "portable").is_symlink()
    assert (root / "portable").resolve() == skill.resolve()
    assert json.loads((target / SKILL_LEDGER_RELATIVE).read_text())["links"] == ["portable"]
    assert json.loads((target / LEDGER_RELATIVE).read_text())["links"] == []


def test_unrecorded_legacy_shaped_claude_skills_link_is_not_adopted(home_dir: Path) -> None:
    from lazy_harness.core.paths import config_dir

    profile = config_dir() / "profiles" / "one"
    _skill(profile, "", "portable", "managed")
    target = home_dir / ".one"
    target.mkdir()
    (target / "skills").symlink_to(profile / "skills", target_is_directory=True)

    with pytest.raises(SkillCollisionError, match="user-owned.*portable"):
        deploy_profiles(_config(home_dir, {"one": "claude-code"}))

    assert (target / "skills").is_symlink()


def test_a_noncolliding_user_owned_entry_is_left_alone(home_dir: Path) -> None:
    from lazy_harness.core.paths import config_dir

    profile = config_dir() / "profiles" / "one"
    _skill(profile, "shared", "managed", "managed")
    root = home_dir / ".agents" / "skills"
    user = root / "user"
    user.mkdir(parents=True)
    (user / "SKILL.md").write_text("user")

    deploy_profiles(_config(home_dir, {"one": "codex"}))

    assert not user.is_symlink()
    assert (user / "SKILL.md").read_text() == "user"
    assert (root / "managed").is_symlink()


def test_cleanup_removes_only_owned_links_still_pointing_into_profiles(home_dir: Path) -> None:
    from lazy_harness.core.paths import config_dir

    profile = config_dir() / "profiles" / "one"
    skill = _skill(profile, "shared", "gone", "managed")
    cfg = _config(home_dir, {"one": "codex"})
    deploy_profiles(cfg)

    root = home_dir / ".agents" / "skills"
    skill.rename(profile / "shared" / "retired")
    user_source = home_dir / "user-skill"
    user_source.mkdir()
    (user_source / "SKILL.md").write_text("user")
    (root / "gone").unlink()
    (root / "gone").symlink_to(user_source, target_is_directory=True)

    deploy_profiles(cfg)

    assert (root / "gone").is_symlink()
    assert (root / "gone").resolve() == user_source.resolve()
    assert json.loads((root.parent / SKILL_LEDGER_RELATIVE).read_text())["links"] == []


def test_cleanup_removes_an_owned_skill_that_is_no_longer_generated(home_dir: Path) -> None:
    from lazy_harness.core.paths import config_dir

    profile = config_dir() / "profiles" / "one"
    skill = _skill(profile, "shared", "gone", "managed")
    cfg = _config(home_dir, {"one": "codex"})
    deploy_profiles(cfg)
    root = home_dir / ".agents" / "skills"

    for child in skill.iterdir():
        child.unlink()
    skill.rmdir()
    deploy_profiles(cfg)

    assert not (root / "gone").is_symlink()
    assert json.loads((root.parent / SKILL_LEDGER_RELATIVE).read_text())["links"] == []


def test_an_adapter_without_a_skill_root_names_the_omission(
    home_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from lazy_harness.core.paths import config_dir

    profile = config_dir() / "profiles" / "one"
    _skill(profile, "shared", "portable", "body")

    deploy_profiles(_config(home_dir, {"one": "copilot"}))

    out = capsys.readouterr().out
    assert "skills omitted in 'one'" in out
    assert "agent 'copilot' declares no native skill root" in out
    assert not (home_dir / ".one" / "skills").exists()


def test_commands_remain_native_while_skills_use_the_capability(home_dir: Path) -> None:
    from lazy_harness.core.paths import config_dir

    profile = config_dir() / "profiles" / "one"
    _skill(profile, "codex", "portable", "body")
    command = profile / "codex" / "commands" / "native.md"
    command.parent.mkdir(parents=True)
    command.write_text("native")

    deploy_profiles(_config(home_dir, {"one": "codex"}))

    assert (home_dir / ".agents" / "skills" / "portable").is_symlink()
    assert (home_dir / ".one" / "commands").is_symlink()
    assert not (home_dir / ".one" / "skills").exists()

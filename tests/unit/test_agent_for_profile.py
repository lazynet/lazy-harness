"""Per-profile agent resolution — the one place that decides which agent a profile runs.

Parent design step 3: `agent_for_profile` is the minimum of per-profile agent
resolution that the step-4 contract gate needs, since a gate that cannot deploy
to a Codex profile cannot be performed at all.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from lazy_harness.core.config import (
    AgentConfig,
    Config,
    HarnessConfig,
    ProfileEntry,
    ProfilesConfig,
)


def _cfg(global_agent: str, profiles: dict[str, ProfileEntry]) -> Config:
    return Config(
        harness=HarnessConfig(version="1"),
        agent=AgentConfig(type=global_agent),
        profiles=ProfilesConfig(default=next(iter(profiles)), items=profiles),
    )


def test_a_profile_without_an_agent_inherits_the_global_one() -> None:
    from lazy_harness.agents.registry import agent_for_profile

    cfg = _cfg("claude-code", {"personal": ProfileEntry(config_dir="~/.claude-x")})

    assert agent_for_profile(cfg, "personal").name == "claude-code"


def test_a_profile_declaring_an_agent_overrides_the_global_one() -> None:
    from lazy_harness.agents.registry import agent_for_profile

    cfg = _cfg(
        "claude-code",
        {
            "personal": ProfileEntry(config_dir="~/.claude-x"),
            "experiment": ProfileEntry(config_dir="~/.other-x", agent="null"),
        },
    )

    assert agent_for_profile(cfg, "personal").name == "claude-code"
    assert agent_for_profile(cfg, "experiment").name == "null"


def test_an_unknown_profile_falls_back_to_the_global_agent() -> None:
    """Callers iterate cfg.profiles; an unknown name is a programming error, but
    silently resolving to nothing would deploy an empty config dir."""
    from lazy_harness.agents.registry import agent_for_profile

    cfg = _cfg("claude-code", {"personal": ProfileEntry(config_dir="~/.claude-x")})

    assert agent_for_profile(cfg, "nonexistent").name == "claude-code"


def test_an_unregistered_agent_name_is_refused_loudly() -> None:
    from lazy_harness.agents.registry import AgentNotFoundError, agent_for_profile

    cfg = _cfg("claude-code", {"personal": ProfileEntry(config_dir="~/.x", agent="no-such-agent")})

    with pytest.raises(AgentNotFoundError, match="no-such-agent"):
        agent_for_profile(cfg, "personal")


def test_envrc_deploy_resolves_the_agent_per_profile_not_once_globally(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The defect: `deploy_envrc_for_all_profiles` resolved the adapter once,
    before the profile loop, so every root got the default agent's env var."""
    from lazy_harness.agents import registry
    from lazy_harness.cli.profile_cmd import deploy_envrc_for_all_profiles

    class _OtherAdapter(registry.NullAdapter):
        @property
        def name(self) -> str:
            return "other"

        def env_var(self) -> str:
            return "OTHER_CONFIG_DIR"

    monkeypatch.setitem(registry._AGENTS, "other", _OtherAdapter)

    claude_root = tmp_path / "claude-root"
    other_root = tmp_path / "other-root"
    cfg = _cfg(
        "claude-code",
        {
            "personal": ProfileEntry(
                config_dir=str(tmp_path / ".claude-x"), roots=[str(claude_root)]
            ),
            "experiment": ProfileEntry(
                config_dir=str(tmp_path / ".other-x"),
                roots=[str(other_root)],
                agent="other",
            ),
        },
    )

    deploy_envrc_for_all_profiles(cfg)

    claude_envrc = (claude_root / ".envrc").read_text()
    other_envrc = (other_root / ".envrc").read_text()

    assert "CLAUDE_CONFIG_DIR" in claude_envrc
    assert "OTHER_CONFIG_DIR" in other_envrc, (
        f"the experiment profile declares agent='other' but its root got:\n{other_envrc}"
    )
    assert "CLAUDE_CONFIG_DIR" not in other_envrc


def test_envrc_dry_run_names_the_same_env_var_the_real_write_uses(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Two paths answer one question, so a test invokes both and asserts they agree.

    `lh profile envrc --dry-run` resolved the adapter from the global agent while
    the real write resolved it per profile: the preview would name a different
    env var than the deploy it is previewing.
    """
    from click.testing import CliRunner

    from lazy_harness.agents import registry
    from lazy_harness.cli import profile_cmd

    class _OtherAdapter(registry.NullAdapter):
        @property
        def name(self) -> str:
            return "other"

        def env_var(self) -> str:
            return "OTHER_CONFIG_DIR"

    monkeypatch.setitem(registry._AGENTS, "other", _OtherAdapter)

    other_root = tmp_path / "other-root"
    cfg = _cfg(
        "claude-code",
        {
            "experiment": ProfileEntry(
                config_dir=str(tmp_path / ".other-x"),
                roots=[str(other_root)],
                agent="other",
            ),
        },
    )
    monkeypatch.setattr(profile_cmd, "load_config", lambda *a, **k: cfg)

    result = CliRunner().invoke(profile_cmd.profile, ["envrc", "--dry-run"])
    assert result.exit_code == 0, result.output
    assert "OTHER_CONFIG_DIR" in result.output, result.output
    assert "CLAUDE_CONFIG_DIR" not in result.output

    profile_cmd.deploy_envrc_for_all_profiles(cfg)
    written = (other_root / ".envrc").read_text()

    assert "OTHER_CONFIG_DIR" in written
    assert ("CLAUDE_CONFIG_DIR" in result.output) == ("CLAUDE_CONFIG_DIR" in written)

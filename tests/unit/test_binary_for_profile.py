"""Per-profile launcher resolution — the one place that decides which installed
binary a profile's generated hook commands name.

Design decision 11 (2026-09-13 multi-agent blast radius): a beta profile needs
its hooks to reach a different binary than the daily profiles do, without
putting a path back into the command.
"""

from __future__ import annotations

from lazy_harness.core.config import (
    AgentConfig,
    Config,
    HarnessConfig,
    ProfileEntry,
    ProfilesConfig,
)


def _cfg(profiles: dict[str, ProfileEntry]) -> Config:
    return Config(
        harness=HarnessConfig(version="1"),
        agent=AgentConfig(type="claude-code"),
        profiles=ProfilesConfig(default=next(iter(profiles)), items=profiles),
    )


def test_a_profile_without_a_binary_gets_the_default_launcher() -> None:
    from lazy_harness.agents.registry import DEFAULT_HARNESS_BINARY, binary_for_profile

    cfg = _cfg({"personal": ProfileEntry(config_dir="~/.claude-x")})

    assert binary_for_profile(cfg, "personal") == DEFAULT_HARNESS_BINARY
    assert DEFAULT_HARNESS_BINARY == "lh"


def test_a_profile_declaring_a_binary_overrides_the_default() -> None:
    from lazy_harness.agents.registry import binary_for_profile

    cfg = _cfg(
        {
            "personal": ProfileEntry(config_dir="~/.claude-x"),
            "beta": ProfileEntry(config_dir="~/.agent-beta", harness_binary="lh-beta"),
        }
    )

    assert binary_for_profile(cfg, "personal") == "lh"
    assert binary_for_profile(cfg, "beta") == "lh-beta"


def test_an_unknown_profile_falls_back_to_the_default_launcher() -> None:
    """Same contract as `agent_for_profile`: callers iterate `cfg.profiles`, so
    an unknown name is a programming error, not a reason to emit an empty
    command that `execvp` cannot resolve."""
    from lazy_harness.agents.registry import binary_for_profile

    cfg = _cfg({"personal": ProfileEntry(config_dir="~/.claude-x")})

    assert binary_for_profile(cfg, "nonexistent") == "lh"


def test_declared_binaries_always_carries_the_default() -> None:
    """The classifier's allow-list. The default belongs in it even when no
    profile names it, so entries a previous deploy wrote under `lh` are still
    recognised as the harness's own after a profile switches binaries."""
    from lazy_harness.agents.registry import declared_binaries

    cfg = _cfg({"beta": ProfileEntry(config_dir="~/.agent-beta", harness_binary="lh-beta")})

    assert declared_binaries(cfg) == {"lh", "lh-beta"}


def test_declared_binaries_of_an_all_default_config_is_just_the_default() -> None:
    from lazy_harness.agents.registry import declared_binaries

    cfg = _cfg(
        {
            "personal": ProfileEntry(config_dir="~/.claude-x"),
            "work": ProfileEntry(config_dir="~/.claude-w"),
        }
    )

    assert declared_binaries(cfg) == {"lh"}

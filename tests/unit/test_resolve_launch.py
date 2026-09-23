"""`resolve_launch` failure kinds — the machine-readable tag `lh exec`'s
structured failure output and `lh run`'s exit path both key off.
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


def _cfg(tmp_path: Path) -> Config:
    return Config(
        harness=HarnessConfig(version="1"),
        agent=AgentConfig(type="claude-code"),
        profiles=ProfilesConfig(
            default="personal",
            items={"personal": ProfileEntry(config_dir=str(tmp_path / ".claude-personal"))},
        ),
    )


def test_a_bad_agent_flag_is_not_reported_as_unknown_profile(tmp_path: Path) -> None:
    """A typo'd `--agent` value is a bad flag, not a bad `--profile`: the two
    must not collapse onto the same `kind` (L4)."""
    from lazy_harness.agents.launch import LaunchError, resolve_launch

    cfg = _cfg(tmp_path)

    with pytest.raises(LaunchError) as excinfo:
        resolve_launch(cfg, cwd=tmp_path, agent="nope")

    assert excinfo.value.kind != "unknown-profile"


def test_a_bad_agent_flag_has_its_own_kind(tmp_path: Path) -> None:
    from lazy_harness.agents.launch import LaunchError, resolve_launch

    cfg = _cfg(tmp_path)

    with pytest.raises(LaunchError) as excinfo:
        resolve_launch(cfg, cwd=tmp_path, agent="nope")

    assert excinfo.value.kind == "unknown-agent-flag"

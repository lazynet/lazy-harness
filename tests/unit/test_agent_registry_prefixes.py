"""Tests for the agent-to-profile-prefix registry."""

from __future__ import annotations

import pytest

from lazy_harness.agents.registry import _AGENTS, PROFILE_PREFIXES, profile_prefix


def test_every_registered_agent_has_a_prefix() -> None:
    assert set(PROFILE_PREFIXES) == set(_AGENTS)


def test_prefixes_are_unique() -> None:
    assert len(set(PROFILE_PREFIXES.values())) == len(PROFILE_PREFIXES)


def test_claude_code_prefix_is_claude() -> None:
    assert profile_prefix("claude-code") == "claude"


def test_unknown_agent_is_refused() -> None:
    with pytest.raises(ValueError, match="'nope' has no profile prefix"):
        profile_prefix("nope")

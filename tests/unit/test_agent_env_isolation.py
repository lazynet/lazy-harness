"""The autouse isolation clears every adapter's config-dir variable.

`agent_runtime_dir` lets the adapter's variable win over a profile's own
`config_dir` (ADR-032), so one leaking in from the developer's shell points a
test at that machine's real profile. `CODEX_HOME` did: two doctor tests read
the real `~/.codex-lazy` engram metrics and failed locally, while CI, which
never sets the variable, stayed green.
"""

from __future__ import annotations

import os

import pytest

from lazy_harness.agents.registry import get_agent, list_agents
from tests.conftest import clear_agent_config_dirs


def test_every_adapters_config_dir_variable_is_cleared(monkeypatch: pytest.MonkeyPatch) -> None:
    names = {get_agent(agent).env_var() for agent in list_agents()} - {""}
    # Anchors the derivation: an empty registry would pass the check below vacuously.
    assert {"CLAUDE_CONFIG_DIR", "CODEX_HOME", "COPILOT_HOME"} <= names
    for name in names:
        monkeypatch.setenv(name, "/leaked/from/the/shell")

    clear_agent_config_dirs(monkeypatch)

    assert sorted(names & os.environ.keys()) == []

"""Protocol conformance — every registered adapter must implement all methods."""

from __future__ import annotations

import pytest

REGISTERED_AGENT_TYPES = ["claude-code"]


@pytest.mark.parametrize("agent_type", REGISTERED_AGENT_TYPES)
def test_adapter_satisfies_full_protocol(agent_type: str) -> None:
    from lazy_harness.agents.base import AgentAdapter
    from lazy_harness.agents.registry import get_agent

    adapter = get_agent(agent_type)
    assert isinstance(adapter, AgentAdapter), (
        f"{agent_type!r} adapter does not satisfy AgentAdapter Protocol"
    )


def test_null_adapter_satisfies_protocol() -> None:
    """NullAdapter returns None / empty-string sentinels — proves optional methods work."""
    from lazy_harness.agents.base import AgentAdapter
    from lazy_harness.agents.registry import get_agent

    adapter = get_agent("null")
    assert isinstance(adapter, AgentAdapter)
    assert adapter.global_config_link() is None
    assert adapter.mcp_config_file() == ""
    assert adapter.system_doc_name() == ""
    assert adapter.session_dirs() == {"sessions": "", "logs": "", "queue": ""}

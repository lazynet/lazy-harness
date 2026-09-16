"""`system_docs()` — the destinations an agent loads, not one recognised filename.

Decision 6 of the 2026-09-13 multi-agent design, ADR-043. `system_doc_name() ->
str` could answer for Claude Code and Codex and for nobody else: Copilot's
user-level destinations are `copilot-instructions.md` *and*
`instructions/**/*.instructions.md`, neither of which a single filename can
express, and one of which is not a filename at all.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from lazy_harness.agents.base import (
    AgentAdapter,
    HookDecision,
    HookEvent,
    HookOutput,
    HookSupport,
)
from lazy_harness.agents.registry import get_agent, list_agents


class _TwoDestinations:
    """An adapter that loads two files, which is the shape the `str` forbade."""

    @property
    def name(self) -> str:
        return "two-destinations"

    def config_dir(self, profile_config_dir: str) -> Path:
        return Path(profile_config_dir)

    def supported_hooks(self) -> list[str]:
        return []

    def hook_events(self) -> dict[str, HookSupport]:
        return {}

    def parse_hook_input(self, event: str, payload: dict, *, profile: str) -> HookEvent:
        raise NotImplementedError

    def format_hook_output(self, event: HookEvent, decision: HookDecision) -> HookOutput:
        raise NotImplementedError

    def resolve_binary(self) -> Path | None:
        return None

    def env_var(self) -> str:
        return ""

    def global_config_link(self) -> Path | None:
        return None

    def mcp_config_file(self) -> str:
        return ""

    def session_dirs(self) -> dict[str, str]:
        return {"sessions": "", "logs": "", "queue": ""}

    def system_docs(self) -> list[Path]:
        return [Path("copilot-instructions.md"), Path("instructions/harness.instructions.md")]

    def credentials_file(self) -> str | None:
        return None

    def process_name(self) -> str:
        return ""


def test_an_adapter_declaring_two_destinations_satisfies_the_protocol() -> None:
    """`runtime_checkable` checks attribute presence, so while the Protocol
    declares `system_doc_name` an adapter that answers only `system_docs` is
    *not* an `AgentAdapter` — which is the widening, stated as an assertion."""
    assert isinstance(_TwoDestinations(), AgentAdapter)


def test_the_protocol_no_longer_answers_with_a_single_name() -> None:
    """Two methods answering one question is the failure mode the repo's gate
    names; `system_doc_name` is removed rather than kept alongside."""
    assert not hasattr(AgentAdapter, "system_doc_name")


@pytest.mark.parametrize("agent_type", list_agents())
def test_every_registered_adapter_answers_with_paths(agent_type: str) -> None:
    docs = get_agent(agent_type).system_docs()
    assert isinstance(docs, list)
    assert all(isinstance(doc, Path) for doc in docs)


def test_claude_code_loads_only_claude_md() -> None:
    assert get_agent("claude-code").system_docs() == [Path("CLAUDE.md")]


def test_codex_loads_agents_md() -> None:
    assert get_agent("codex").system_docs() == [Path("AGENTS.md")]


def test_the_null_adapter_loads_no_system_doc() -> None:
    """The empty list is the sentinel `""` was; `bool([])` is the same gate."""
    assert get_agent("null").system_docs() == []

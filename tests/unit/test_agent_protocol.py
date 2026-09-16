"""Protocol conformance — every registered adapter must implement all methods."""

from __future__ import annotations

import pytest

from lazy_harness.agents.registry import list_agents

# Derived from the registry rather than retyped. A hand-maintained list is how a
# newly registered adapter ships without ever being checked against the Protocol
# — the sweep stays green because it never ran against the new name.
REGISTERED_AGENT_TYPES = [name for name in list_agents() if name != "null"]


def test_the_conformance_sweep_covers_every_registered_agent() -> None:
    assert set(REGISTERED_AGENT_TYPES) | {"null"} == set(list_agents())


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
    assert adapter.system_docs() == []
    assert adapter.session_dirs() == {"sessions": "", "logs": "", "queue": ""}
    assert adapter.process_name() == ""


def test_protocol_no_longer_declares_the_displaced_config_generators() -> None:
    """`plan_config` is the deploy surface, so the two `dict`-returning
    generators come off the Protocol (decision 4, 2026-09-13 multi-agent design).

    While they are declared, every new adapter must write two stubs whose `dict`
    return cannot express its own config — Codex needs `hooks.json` plus a TOML
    block, which is exactly the shape a single `dict` cannot carry.
    """
    from lazy_harness.agents.base import AgentAdapter

    assert not hasattr(AgentAdapter, "generate_hook_config")
    assert not hasattr(AgentAdapter, "generate_mcp_config")


def test_an_adapter_without_the_generators_still_satisfies_the_protocol() -> None:
    """The declaration coming off is only worth something if `isinstance` agrees.

    `runtime_checkable` checks attribute presence, so this is the assertion that
    would actually have failed before: an adapter that declines to write the two
    stubs is a conforming adapter.
    """
    from pathlib import Path

    from lazy_harness.agents.base import (
        AgentAdapter,
        HookDecision,
        HookEvent,
        HookOutput,
        HookSupport,
    )

    class Minimal:
        @property
        def name(self) -> str:
            return "minimal"

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
            return []

        def process_name(self) -> str:
            return ""

    assert isinstance(Minimal(), AgentAdapter)


def test_null_adapter_does_not_mirror_the_displaced_generators() -> None:
    """The sentinel adapter is what a new adapter is read as a template from.

    Leaving the two stubs on it re-teaches the removed requirement to whoever
    copies it, which is how a declaration comes back after being deleted once.
    """
    from lazy_harness.agents.registry import get_agent

    adapter = get_agent("null")
    assert not hasattr(adapter, "generate_hook_config")
    assert not hasattr(adapter, "generate_mcp_config")


# --- the optional Protocols an adapter may decline ------------------------


def test_codex_declares_neither_optional_protocol() -> None:
    """Two absences, two different reasons, and neither is an oversight.

    `SessionPinningAgent` is unimplementable: `codex exec` at 0.154.0 offers no
    `--session-id`, and `CODEX_SESSION_ID=<uuid> codex exec --json` exits 0 while
    `thread.started` carries a UUIDv7 Codex generated. `HeadlessAgent` is merely
    unclaimed: `codex exec --json` is read off the binary's strings and has never
    been driven end to end, so declaring it would route `lh exec` at a parser
    nobody has fed. Closing either by symmetry with `ClaudeCodeAdapter` is the
    guess this asserts against.
    """
    from lazy_harness.agents.base import HeadlessAgent, SessionPinningAgent
    from lazy_harness.agents.registry import get_agent

    codex = get_agent("codex")
    assert not isinstance(codex, SessionPinningAgent)
    assert not isinstance(codex, HeadlessAgent)


def test_claude_code_still_declares_both() -> None:
    """The control for the assertion above: `isinstance` against a
    `runtime_checkable` Protocol only checks method *names*, so a test that only
    ever sees `False` would pass against a Protocol nobody satisfies."""
    from lazy_harness.agents.base import HeadlessAgent, SessionPinningAgent
    from lazy_harness.agents.registry import get_agent

    claude = get_agent("claude-code")
    assert isinstance(claude, SessionPinningAgent)
    assert isinstance(claude, HeadlessAgent)


def test_the_sentinel_refuses_a_verdict_rather_than_emitting_nothing() -> None:
    """`NullAdapter`'s refusal path, exercised through the shipped sentinel.

    It delivers no event and therefore honours no verdict. Emitting an empty
    `HookOutput` for one would read, on a blocking hook, as approval — the exact
    shape of failure ADR-041 records for Codex's own invalid envelopes. The
    match is anchored on the event name the caller passed and on the agent's own
    name, which are the two facts a reader needs to locate the misconfiguration;
    the exception carries no structured attributes to assert on.
    """
    from lazy_harness.agents.base import HookDecision, Verdict
    from lazy_harness.agents.registry import get_agent

    adapter = get_agent("null")
    event = adapter.parse_hook_input("pre_tool_use", {}, profile="p")

    with pytest.raises(ValueError, match=r"null honours no verdict on 'pre_tool_use'"):
        adapter.format_hook_output(event, HookDecision(verdict=Verdict.DENY, reason="no"))


def test_the_sentinel_abstains_without_raising() -> None:
    """The other half: no verdict is not an error, it is the ordinary case."""
    from lazy_harness.agents.base import HookDecision
    from lazy_harness.agents.registry import get_agent

    adapter = get_agent("null")
    event = adapter.parse_hook_input("pre_tool_use", {}, profile="p")

    output = adapter.format_hook_output(event, HookDecision())

    assert (output.stdout, output.stderr, output.exit_code) == (None, "", 0)

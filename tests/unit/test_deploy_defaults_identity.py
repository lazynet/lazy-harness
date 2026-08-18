"""The effective hook set is pinned before it becomes derived data.

`DEFAULT_HOOKS` is about to be computed from the capability registry instead of
maintained as a literal. A hook that the registry believes is enabled but that
`lh deploy` no longer writes into `settings.json` is silently disabled: the
framework prints nothing and the agent simply stops running it. That failure
has happened in this repo before, which is why this fixture exists.

The fixture holds the *default* effective set only. The live profiles'
generated blocks carry absolute paths from the machine that produced them, and
this repository is public.
"""

from __future__ import annotations

import json
from pathlib import Path

_FIXTURE = (
    Path(__file__).resolve().parents[1]
    / "fixtures"
    / "settings-json"
    / "default-effective-hooks.json"
)


def test_the_default_effective_hook_set_is_unchanged() -> None:
    from lazy_harness.agents.registry import get_agent
    from lazy_harness.core.config import Config
    from lazy_harness.deploy.defaults import merge_with_defaults

    effective = merge_with_defaults(Config().hooks, get_agent("claude-code"))

    assert effective == json.loads(_FIXTURE.read_text())


def test_the_fixture_lists_every_event_the_defaults_declare() -> None:
    """A fixture that silently lost an event would certify its own gap."""
    from lazy_harness.deploy.defaults import DEFAULT_HOOKS

    assert set(json.loads(_FIXTURE.read_text())) == set(DEFAULT_HOOKS)


def test_an_agent_without_a_system_doc_drops_the_doc_hook() -> None:
    """The one place the effective set depends on the agent, so deriving
    `DEFAULT_HOOKS` from the registry must not flatten it away."""
    from lazy_harness.core.config import Config
    from lazy_harness.deploy.defaults import merge_with_defaults

    class NoDoc:
        def system_doc_name(self) -> str:
            return ""

    effective = merge_with_defaults(Config().hooks, NoDoc())

    assert "post-tool-use-sync-claude" not in effective["post_tool_use"]
    assert "post-tool-use-format" in effective["post_tool_use"]

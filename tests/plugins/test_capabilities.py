"""Tests for the capability registry — one enumerable surface for everything
that can be turned on."""

from __future__ import annotations

import pytest


def test_capability_without_a_binary_is_on_or_off() -> None:
    from lazy_harness.core.config import Config
    from lazy_harness.plugins.capabilities import (
        Capability,
        CapabilityRegistry,
        CapabilityState,
        Cardinality,
    )

    cap = Capability(
        name="context-inject",
        kind="hook",
        cardinality=Cardinality.MANY,
        config_path="context_inject.enabled",
        summary="Inject repo and session context at SessionStart",
    )
    reg = CapabilityRegistry()
    reg.register(cap)

    cfg = Config()
    cfg.context_inject.enabled = True
    assert reg.state(cap, cfg) is CapabilityState.ON

    cfg.context_inject.enabled = False
    assert reg.state(cap, cfg) is CapabilityState.OFF


@pytest.mark.parametrize(
    ("enabled", "installed", "expected"),
    [
        (True, True, "ACTIVE"),
        (False, True, "DORMANT"),
        (True, False, "BROKEN"),
        (False, False, "MISSING"),
    ],
)
def test_capability_with_a_binary_has_four_states(
    enabled: bool, installed: bool, expected: str
) -> None:
    """This is features.py's model, written once instead of three times."""
    from lazy_harness.core.config import Config
    from lazy_harness.plugins.capabilities import (
        Capability,
        CapabilityRegistry,
        CapabilityState,
        Cardinality,
    )

    cap = Capability(
        name="engram",
        kind="tool",
        cardinality=Cardinality.MANY,
        config_path="memory.engram.enabled",
        summary="Episodic memory backend",
        binary="engram",
        pinned_version="1.15.4",
    )
    reg = CapabilityRegistry()
    reg.register(cap)

    cfg = Config()
    cfg.memory.engram.enabled = enabled

    state = reg.state(cap, cfg, probe=lambda _name: installed)
    assert state is getattr(CapabilityState, expected)


def test_state_resolves_the_binary_probe_by_default() -> None:
    """Paired smoke test: always injecting `probe` leaves shutil.which untested."""
    from lazy_harness.core.config import Config
    from lazy_harness.plugins.capabilities import (
        Capability,
        CapabilityRegistry,
        CapabilityState,
        Cardinality,
    )

    cap = Capability(
        name="definitely-not-installed-xyz",
        kind="tool",
        cardinality=Cardinality.MANY,
        config_path="memory.engram.enabled",
        summary="probe smoke test",
        binary="definitely-not-installed-xyz",
    )
    reg = CapabilityRegistry()
    reg.register(cap)

    cfg = Config()
    cfg.memory.engram.enabled = False
    assert reg.state(cap, cfg) is CapabilityState.MISSING


def test_toggle_returns_a_new_config_and_writes_nothing(tmp_path) -> None:
    """The registry must never touch disk. Persistence is the caller's job."""
    from lazy_harness.core.config import Config
    from lazy_harness.plugins.capabilities import (
        Capability,
        CapabilityRegistry,
        Cardinality,
    )

    cap = Capability(
        name="engram",
        kind="tool",
        cardinality=Cardinality.MANY,
        config_path="memory.engram.enabled",
        summary="Episodic memory backend",
        binary="engram",
    )
    reg = CapabilityRegistry()
    reg.register(cap)

    cfg = Config()
    cfg.memory.engram.enabled = False
    updated = reg.toggle(cap, cfg, enabled=True)

    assert updated.memory.engram.enabled is True
    assert cfg.memory.engram.enabled is False, "the caller's Config must not be mutated"
    assert list(tmp_path.iterdir()) == []


def test_get_raises_on_an_unregistered_name() -> None:
    from lazy_harness.plugins.capabilities import CapabilityRegistry

    with pytest.raises(KeyError, match="nope"):
        CapabilityRegistry().get("nope")


def test_capabilities_filters_by_kind() -> None:
    from lazy_harness.plugins.capabilities import (
        Capability,
        CapabilityRegistry,
        Cardinality,
    )

    reg = CapabilityRegistry()
    for name, kind in (("engram", "tool"), ("context-inject", "hook"), ("qmd", "tool")):
        reg.register(
            Capability(
                name=name,
                kind=kind,
                cardinality=Cardinality.MANY,
                config_path="memory.engram.enabled",
                summary=name,
            )
        )

    assert [c.name for c in reg.capabilities(kind="tool")] == ["engram", "qmd"]
    assert len(reg.capabilities()) == 3


def test_registering_the_same_name_twice_is_refused() -> None:
    """Two capabilities under one name means `get` silently answers for the
    wrong one, and the registry is the thing every consumer trusts."""
    from lazy_harness.plugins.capabilities import (
        Capability,
        CapabilityRegistry,
        Cardinality,
    )

    cap = Capability(
        name="engram",
        kind="tool",
        cardinality=Cardinality.MANY,
        config_path="memory.engram.enabled",
        summary="Episodic memory backend",
    )
    reg = CapabilityRegistry()
    reg.register(cap)

    with pytest.raises(ValueError, match="engram"):
        reg.register(cap)


def test_state_raises_on_a_config_path_that_does_not_resolve() -> None:
    """A capability naming a key that is not in Config is a registration bug,
    and answering OFF would hide it behind a plausible-looking answer."""
    from lazy_harness.core.config import Config
    from lazy_harness.plugins.capabilities import (
        Capability,
        CapabilityRegistry,
        Cardinality,
    )

    cap = Capability(
        name="ghost",
        kind="tool",
        cardinality=Cardinality.MANY,
        config_path="memory.engram.not_a_real_key",
        summary="typo in the registration",
    )
    reg = CapabilityRegistry()
    reg.register(cap)

    with pytest.raises(AttributeError, match="not_a_real_key"):
        reg.state(cap, Config())


@pytest.mark.parametrize(("installed", "expected"), [(True, "ACTIVE"), (False, "MISSING")])
def test_a_capability_with_no_config_switch_is_presence_only(
    installed: bool, expected: str
) -> None:
    """Not every capability has an on/off key.

    `knowledge.search` carries only `engine`; qmd is reported purely on whether
    its binary is there. Inventing a `knowledge.search.enabled` to satisfy the
    model would be a config schema change smuggled into a refactor, so an empty
    `config_path` means "no switch — enabled whenever it is installed".
    """
    from lazy_harness.core.config import Config
    from lazy_harness.plugins.capabilities import (
        Capability,
        CapabilityRegistry,
        CapabilityState,
        Cardinality,
    )

    cap = Capability(
        name="qmd",
        kind="tool",
        cardinality=Cardinality.ONE,
        config_path="",
        summary="Semantic search over the knowledge dir",
        binary="qmd",
    )
    reg = CapabilityRegistry()
    reg.register(cap)

    state = reg.state(cap, Config(), probe=lambda _n: installed)
    assert state is getattr(CapabilityState, expected)


def test_toggling_a_capability_with_no_switch_is_refused() -> None:
    """There is nothing to write, and silently returning an unchanged Config
    would let a TUI show a toggle that does nothing."""
    from lazy_harness.core.config import Config
    from lazy_harness.plugins.capabilities import (
        Capability,
        CapabilityRegistry,
        Cardinality,
    )

    cap = Capability(
        name="qmd",
        kind="tool",
        cardinality=Cardinality.ONE,
        config_path="",
        summary="Semantic search over the knowledge dir",
        binary="qmd",
    )
    reg = CapabilityRegistry()
    reg.register(cap)

    with pytest.raises(ValueError, match="qmd"):
        reg.toggle(cap, Config(), enabled=True)


def test_a_capability_with_neither_a_switch_nor_a_binary_is_refused() -> None:
    """Nothing to read and nothing to probe is a registration mistake, and any
    state it returned would be invented."""
    from lazy_harness.core.config import Config
    from lazy_harness.plugins.capabilities import (
        Capability,
        CapabilityRegistry,
        Cardinality,
    )

    cap = Capability(
        name="nothing",
        kind="tool",
        cardinality=Cardinality.MANY,
        config_path="",
        summary="neither switch nor binary",
    )
    reg = CapabilityRegistry()
    reg.register(cap)

    with pytest.raises(ValueError, match="nothing"):
        reg.state(cap, Config())


def test_a_list_valued_config_path_is_refused_until_membership_exists() -> None:
    """`bool(["sqlite_local"])` is True for every capability sharing that path.

    Two metrics sinks registered against `metrics.sinks` both answered `ON`,
    including the one that was never added to the list. The registry has no
    per-capability identity to test membership against yet, and a confident
    wrong answer is worse here than an error: a checker that cannot check must
    not spell that as a result.
    """
    from lazy_harness.core.config import Config
    from lazy_harness.plugins.capabilities import (
        Capability,
        CapabilityRegistry,
        Cardinality,
    )

    cap = Capability(
        name="http_remote",
        kind="metrics_sink",
        cardinality=Cardinality.MANY,
        config_path="metrics.sinks",
        summary="Remote metrics sink",
    )
    reg = CapabilityRegistry()
    reg.register(cap)

    with pytest.raises(TypeError, match="metrics.sinks"):
        reg.state(cap, Config())


def test_a_config_path_through_a_dict_section_names_the_capability() -> None:
    """`Config.hooks` is a `dict`, so `getattr` fails on the event name and the
    bare AttributeError names only that key — not the capability, not the path.
    """
    from lazy_harness.core.config import Config
    from lazy_harness.plugins.capabilities import (
        Capability,
        CapabilityRegistry,
        Cardinality,
    )

    cap = Capability(
        name="pre-tool-use-security",
        kind="hook",
        cardinality=Cardinality.MANY,
        config_path="hooks.pre_tool_use.scripts",
        summary="Block dangerous shell invocations",
    )
    reg = CapabilityRegistry()
    reg.register(cap)

    with pytest.raises(AttributeError) as excinfo:
        reg.state(cap, Config())

    assert "pre-tool-use-security" in str(excinfo.value)
    assert "hooks.pre_tool_use.scripts" in str(excinfo.value)

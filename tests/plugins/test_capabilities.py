"""Tests for the capability registry — one enumerable surface for everything
that can be turned on."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from lazy_harness.core.config import Config


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


def test_a_path_that_stops_on_a_whole_section_is_refused() -> None:
    """A path naming a section rather than a switch has no honest reading, and
    answering from its truthiness would make every capability under it agree."""
    from lazy_harness.core.config import Config
    from lazy_harness.plugins.capabilities import (
        Capability,
        CapabilityRegistry,
        Cardinality,
    )

    cap = Capability(
        name="whole-section",
        kind="tool",
        cardinality=Cardinality.MANY,
        config_path="memory.engram",
        summary="path stops on a dataclass section",
    )
    reg = CapabilityRegistry()
    reg.register(cap)

    with pytest.raises(TypeError, match="memory.engram"):
        reg.state(cap, Config())


def test_an_unresolvable_path_names_the_capability_and_the_path() -> None:
    """A bare AttributeError names only the attribute it tried, which says
    nothing about which registration is wrong."""
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
        config_path="memory.engram.no_such_field",
        summary="Block dangerous shell invocations",
    )
    reg = CapabilityRegistry()
    reg.register(cap)

    with pytest.raises(AttributeError) as excinfo:
        reg.state(cap, Config())

    assert "pre-tool-use-security" in str(excinfo.value)
    assert "memory.engram.no_such_field" in str(excinfo.value)


def test_a_one_cardinality_capability_is_on_only_when_the_config_names_it() -> None:
    """The config holds the selected implementation's name, not a boolean.

    Read with truthiness, `bool("claude-code")` is True for every sibling, so
    both agents reported ON — the same lie the list case produced, one axis
    over.
    """
    from lazy_harness.core.config import Config
    from lazy_harness.plugins.capabilities import (
        Capability,
        CapabilityRegistry,
        CapabilityState,
        Cardinality,
    )

    reg = CapabilityRegistry()
    caps = {}
    for name in ("claude-code", "null"):
        caps[name] = Capability(
            name=name,
            kind="agent",
            cardinality=Cardinality.ONE,
            config_path="agent.type",
            summary=name,
        )
        reg.register(caps[name])

    cfg = Config()
    cfg.agent.type = "claude-code"

    assert reg.state(caps["claude-code"], cfg) is CapabilityState.ON
    assert reg.state(caps["null"], cfg) is CapabilityState.OFF


def test_a_one_cardinality_capability_with_a_binary_uses_the_four_states() -> None:
    """Selection and installation are still independent axes."""
    from lazy_harness.core.config import Config
    from lazy_harness.plugins.capabilities import (
        Capability,
        CapabilityRegistry,
        CapabilityState,
        Cardinality,
    )

    cap = Capability(
        name="ollama",
        kind="llm_backend",
        cardinality=Cardinality.ONE,
        config_path="compound_loop.backend",
        summary="Local inference",
        binary="ollama",
    )
    reg = CapabilityRegistry()
    reg.register(cap)

    cfg = Config()
    cfg.compound_loop.backend = "ollama"
    assert reg.state(cap, cfg, probe=lambda _n: False) is CapabilityState.BROKEN

    cfg.compound_loop.backend = "claude"
    assert reg.state(cap, cfg, probe=lambda _n: True) is CapabilityState.DORMANT


def test_toggling_a_one_cardinality_capability_selects_it_by_name() -> None:
    """Writing `True` into `agent.type` would produce an unloadable config."""
    from lazy_harness.core.config import Config
    from lazy_harness.plugins.capabilities import (
        Capability,
        CapabilityRegistry,
        Cardinality,
    )

    cap = Capability(
        name="null",
        kind="agent",
        cardinality=Cardinality.ONE,
        config_path="agent.type",
        summary="No agent",
    )
    reg = CapabilityRegistry()
    reg.register(cap)

    cfg = Config()
    cfg.agent.type = "claude-code"

    assert reg.toggle(cap, cfg, enabled=True).agent.type == "null"


def test_deselecting_a_one_cardinality_capability_is_refused() -> None:
    """There is no "off" for an exclusive choice — something has to be selected,
    and the registry cannot invent which sibling takes over."""
    from lazy_harness.core.config import Config
    from lazy_harness.plugins.capabilities import (
        Capability,
        CapabilityRegistry,
        Cardinality,
    )

    cap = Capability(
        name="null",
        kind="agent",
        cardinality=Cardinality.ONE,
        config_path="agent.type",
        summary="No agent",
    )
    reg = CapabilityRegistry()
    reg.register(cap)

    with pytest.raises(ValueError, match="null"):
        reg.toggle(cap, Config(), enabled=False)


# --- LLM capability follows the live role table (ADR-039) --------------------


def _cfg_deprecated_form() -> Config:
    from lazy_harness.core.config import Config

    cfg = Config()
    cfg.compound_loop.backend = "ollama"
    cfg.compound_loop.model = "llama3.2:3b"
    return cfg


def _cfg_role_table_form() -> Config:
    from lazy_harness.core.config import Config, LLMBackendConfig, LLMConfig

    cfg = Config()
    cfg.llm = LLMConfig(
        default_role="distill",
        backends={"local": LLMBackendConfig(type="ollama", model="qwen2.5-coder:7b")},
        roles={"distill": "local"},
    )
    return cfg


def _backends_reported_on(cfg: Config) -> list[str]:
    from lazy_harness.plugins.builtins import builtin_registry
    from lazy_harness.plugins.capabilities import CapabilityState

    reg = builtin_registry()
    return [
        cap.name
        for cap in reg.capabilities(kind="llm_backend")
        if reg.state(cap, cfg, probe=lambda _n: True)
        in (CapabilityState.ACTIVE, CapabilityState.ON)
    ]


def test_llm_capability_no_longer_points_at_the_deprecated_field() -> None:
    """A dotted path resolved by getattr gives no compile-time signal, so a
    stale one would report the deprecated value with the suite green."""
    from lazy_harness.plugins.builtins import builtin_registry

    caps = builtin_registry().capabilities(kind="llm_backend")
    assert caps
    assert all(cap.config_path != "compound_loop.backend" for cap in caps)


def test_registry_and_run_inference_agree_on_the_active_backend(
    expects_deprecated_compound_loop: None,
) -> None:
    """Two code paths answering the same question, over one config each."""
    from lazy_harness.llm.roles import resolve_role

    for cfg in (_cfg_deprecated_form(), _cfg_role_table_form()):
        assert _backends_reported_on(cfg) == [resolve_role(cfg, "distill").type]


def test_llm_capability_reads_the_role_table() -> None:
    assert _backends_reported_on(_cfg_role_table_form()) == ["ollama"]


# --- per-profile capabilities (design step 6) -------------------------------
#
# ADR-035 declares the agent `Cardinality.ONE` at `config_path="agent.type"`.
# With `[profiles.<name>].agent` the true cardinality is one *per profile*,
# which a single dotted path cannot express. `per_profile` is that declaration,
# and `state()` takes the profile it is being asked about.


def _two_agent_cfg() -> Config:
    from lazy_harness.core.config import (
        AgentConfig,
        Config,
        HarnessConfig,
        ProfileEntry,
        ProfilesConfig,
    )

    return Config(
        harness=HarnessConfig(version="1"),
        agent=AgentConfig(type="claude-code"),
        profiles=ProfilesConfig(
            default="lazy",
            items={
                "lazy": ProfileEntry(config_dir="~/.claude-lazy"),
                "work": ProfileEntry(config_dir="~/.codex-work", agent="codex"),
            },
        ),
    )


def test_a_per_profile_agent_reports_per_profile() -> None:
    """The defect: one answer for a config that has one answer per profile.

    `state()` read `agent.type` and nothing else, so a machine whose `work`
    profile runs Codex reported Claude Code enabled for the whole config —
    including for the profile that does not run it.
    """
    from lazy_harness.plugins.builtins import builtin_registry
    from lazy_harness.plugins.capabilities import CapabilityState

    reg = builtin_registry()
    cfg = _two_agent_cfg()
    claude = reg.get("claude-code")
    codex = reg.get("codex")

    assert reg.state(claude, cfg, profile="lazy") is CapabilityState.ON
    assert reg.state(codex, cfg, profile="lazy") is CapabilityState.OFF

    assert reg.state(codex, cfg, profile="work") is CapabilityState.ON
    assert reg.state(claude, cfg, profile="work") is CapabilityState.OFF


def test_a_per_profile_capability_without_a_profile_reports_the_global_default() -> None:
    """ "Nobody said" keeps the global answer rather than inventing a profile."""
    from lazy_harness.plugins.builtins import builtin_registry
    from lazy_harness.plugins.capabilities import CapabilityState

    reg = builtin_registry()
    cfg = _two_agent_cfg()

    assert reg.state(reg.get("claude-code"), cfg) is CapabilityState.ON
    assert reg.state(reg.get("codex"), cfg) is CapabilityState.OFF


def test_toggling_a_per_profile_capability_is_refused_and_names_the_key() -> None:
    """The decision: the registry REPORTS per-profile state and does not write it.

    `toggle` sets a value by walking `config_path` with getattr/setattr, and
    `[profiles.<name>].agent` is not on that path — the name is a runtime value
    and `ProfilesConfig.items` is a plain dict. Silently writing `[agent].type`
    instead is the failure this refusal exists to prevent: the user asks to
    switch agent, the default moves, and every profile declaring its own is
    unaffected with nothing saying so.
    """
    from lazy_harness.plugins.builtins import builtin_registry

    reg = builtin_registry()
    cfg = _two_agent_cfg()

    with pytest.raises(ValueError, match=r"\[profiles\.<name>\]\.agent"):
        reg.toggle(reg.get("codex"), cfg, enabled=True)


def test_every_registered_agent_is_a_registered_capability() -> None:
    """One answer in one importable place.

    The capability list was written by hand beside the agent registry and had
    drifted: `codex` resolves, deploys and runs, and no surface built on the
    registry could report it at all — a per-profile report for a Codex profile
    would have shown every agent off.
    """
    from lazy_harness.agents.registry import list_agents
    from lazy_harness.plugins.builtins import builtin_registry

    registered = {c.name for c in builtin_registry().capabilities(kind="agent")}
    assert registered == set(list_agents())


def test_a_system_doc_hook_is_reported_off_for_the_profile_that_cannot_load_it() -> None:
    """`requires_system_doc` is answered per profile too.

    The check read `[agent].type`, so a hook that only makes sense for an agent
    with a file-based system doc was reported ON for a profile running one that
    has none.
    """
    from lazy_harness.core.config import ProfileEntry
    from lazy_harness.plugins.capabilities import (
        Capability,
        CapabilityRegistry,
        CapabilityState,
        Cardinality,
    )

    cap = Capability(
        name="post-tool-use-sync-claude",
        kind="hook",
        cardinality=Cardinality.MANY,
        config_path="context_inject.enabled",
        summary="Regenerate the system doc",
        requires_system_doc=True,
    )
    reg = CapabilityRegistry()
    reg.register(cap)

    cfg = _two_agent_cfg()
    cfg.profiles.items["blank"] = ProfileEntry(config_dir="~/.blank", agent="null")
    cfg.context_inject.enabled = True

    assert reg.state(cap, cfg, profile="lazy") is CapabilityState.ON
    assert reg.state(cap, cfg, profile="blank") is CapabilityState.OFF

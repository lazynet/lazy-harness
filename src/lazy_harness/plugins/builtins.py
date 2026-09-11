"""Every builtin capability, in one table.

This file is the single place to look for "what can this harness do". Adding a
capability here is what makes it appear in `lh doctor` and `lh selftest`,
rather than editing each of them.

The pins are imported, not retyped: two homes for a version pin is how they
stop agreeing.
"""

from __future__ import annotations

from functools import lru_cache

from lazy_harness.knowledge import graphify
from lazy_harness.memory import engram
from lazy_harness.plugins.capabilities import Capability, CapabilityRegistry, Cardinality

_TOOLS = [
    Capability(
        name="qmd",
        kind="tool",
        cardinality=Cardinality.MANY,
        # Deliberately empty. `knowledge.search` carries only `engine`, so qmd
        # has no on/off key and is reported on presence alone — which is what
        # `_qmd_status` did. Pointing this at `knowledge.search.engine` would
        # make `bool("qmd")` the enabled test, and an uninstalled qmd would
        # report BROKEN where it has always reported missing.
        config_path="",
        summary="Semantic search across the knowledge store",
        binary="qmd",
        install_hint="Install QMD to enable semantic search across the knowledge dir.",
    ),
    Capability(
        name="engram",
        kind="tool",
        cardinality=Cardinality.MANY,
        config_path="memory.engram.enabled",
        summary="Episodic memory backend",
        binary="engram",
        pinned_version=engram.PINNED_VERSION,
        install_hint="Install Engram (pin {pin}) and set [memory.engram].enabled = true.",
    ),
    Capability(
        name="graphify",
        kind="tool",
        cardinality=Cardinality.MANY,
        config_path="knowledge.structure.enabled",
        summary="Code-structure index and call graph",
        binary="graphify",
        pinned_version=graphify.PINNED_VERSION,
        install_hint="Install Graphify (pin {pin}) and set [knowledge.structure].enabled = true.",
    ),
]


# Event -> the hooks that ship on under it. This table is what
# `deploy/defaults.py:DEFAULT_HOOKS` is computed from, so a hook added here
# starts being deployed without editing that file — the "registered but
# forgotten in the defaults" failure has no place left to happen.
#
# Four builtin hooks are deliberately absent. Three — `herdr-context-gauge`,
# `post-tool-use-ansible-lint` and `user-prompt-goal` — appear in no default
# list because no event is declared for them anywhere in the code: they
# attach wherever the operator puts them, and giving them a fixed
# `config_path` here would invent that event and then answer wrongly for
# anyone who configured them under a different one.
#
# `stop-verify-guard` has one fixed event (`Stop`) but is absent for a
# different reason: nothing in this repo yet emits the `verify_ran` event it
# waits for — that is meant to come from the `verify-before-done` skill,
# which lives outside this repo and today is a procedure document only. See
# docs/how/hooks.md. Defaulting it on before that producer exists would
# deploy a guard that always blocks once per session and never actually
# verifies anything.
_DEFAULT_ON_HOOKS: dict[str, list[str]] = {
    "session_start": ["context-inject", "session-start-preflight"],
    "session_stop": ["session-export", "compound-loop", "engram-persist"],
    "session_end": ["session-end"],
    "pre_compact": ["pre-compact"],
    "pre_tool_use": [
        "pre-tool-use-security",
        "pre-tool-use-git-scope",
        "pre-tool-use-memory-size",
        "pre-tool-use-read-size",
    ],
    "post_tool_use": ["post-tool-use-format", "post-tool-use-sync-claude"],
}

# Hooks that only make sense for an agent keeping a file-based system
# instruction doc. `merge_with_defaults` drops them for an agent without one,
# and `state()` reports them OFF for the same reason. One home: the set lived
# in `deploy/defaults.py` and was mirrored here, which is how two copies of a
# rule stop agreeing.
_SYSTEM_DOC_HOOKS = {"post-tool-use-sync-claude"}

_HOOKS = [
    Capability(
        name=name,
        kind="hook",
        cardinality=Cardinality.MANY,
        config_path=f"hooks.{event}.scripts",
        summary=f"Builtin {event.replace('_', ' ')} hook",
        enabled_by_default=True,
        requires_system_doc=name in _SYSTEM_DOC_HOOKS,
    )
    for event, names in _DEFAULT_ON_HOOKS.items()
    for name in names
]


# Membership in `metrics.sinks` is the enabled test. `PluginRegistry` still
# resolves the implementation classes — the two registries answer different
# questions and both stay.
_SINKS = [
    Capability(
        name="sqlite_local",
        kind="metrics_sink",
        cardinality=Cardinality.MANY,
        config_path="metrics.sinks",
        summary="Write session metrics to the local SQLite database",
        enabled_by_default=True,
    ),
    Capability(
        name="http_remote",
        kind="metrics_sink",
        cardinality=Cardinality.MANY,
        config_path="metrics.sinks",
        summary="Ship session metrics to a remote collector",
    ),
]

# Exclusive choices: the config field holds the selected name, and every
# sibling reads the same field.
_AGENTS = [
    Capability(
        name="claude-code",
        kind="agent",
        cardinality=Cardinality.ONE,
        config_path="agent.type",
        summary="Claude Code",
    ),
    Capability(
        name="null",
        kind="agent",
        cardinality=Cardinality.ONE,
        config_path="agent.type",
        summary="No agent — generate nothing",
    ),
]

_LLM_BACKENDS = [
    Capability(
        name=name,
        kind="llm_backend",
        cardinality=Cardinality.ONE,
        # The live answer, not the deprecated field. `[compound_loop].backend`
        # still parses, so a path left pointing at it would report the stale
        # value and let `toggle` write to a field nothing reads — silently,
        # because a dotted path resolved by getattr has no compile-time check.
        config_path="active_llm_backend",
        summary=f"{name} inference backend for the compound loop",
    )
    for name in ("claude", "ollama", "mlx", "openai-compatible")
]

# The scheduler backends are deliberately absent. `scheduler.backend` defaults
# to `"auto"`, which names no implementation: which one runs is decided at
# install time by probing the machine. Registering them against that field
# would report all three OFF on a machine where one is demonstrably running
# six jobs, and `CapabilityState` has no word for "chosen at runtime".


@lru_cache(maxsize=1)
def builtin_registry() -> CapabilityRegistry:
    """The one registry, built once.

    Cached because `register` refuses a duplicate name: rebuilding the table
    on every call would raise on the second one.
    """
    reg = CapabilityRegistry()
    for cap in (*_TOOLS, *_HOOKS, *_SINKS, *_AGENTS, *_LLM_BACKENDS):
        reg.register(cap)
    return reg

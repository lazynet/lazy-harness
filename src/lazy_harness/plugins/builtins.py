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


@lru_cache(maxsize=1)
def builtin_registry() -> CapabilityRegistry:
    """The one registry, built once.

    Cached because `register` refuses a duplicate name: rebuilding the table
    on every call would raise on the second one.
    """
    reg = CapabilityRegistry()
    for cap in _TOOLS:
        reg.register(cap)
    return reg

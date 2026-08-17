# ADR-035: Capability registry — cardinality and external dependency as the two axes

**Status:** proposed
**Date:** 2026-08-17
**Design:** [`specs/designs/2026-08-17-capability-registry-design.md`](../designs/2026-08-17-capability-registry-design.md)

## Context

The framework accumulated six independent ways to turn something on, across four hand-rolled registries, with no single place that can answer "what can this harness do, and what is currently active".

- Hooks: `deploy/defaults.py:DEFAULT_HOOKS` merged with `[hooks.<event>].scripts` (ADR-031).
- Metrics sinks: `[metrics].sinks` resolved through `plugins/registry.py:PluginRegistry`.
- Agent adapter: `[agent].type` through `agents/registry.py:_AGENTS` (ADR-004).
- Scheduler backend: `[scheduler].backend` through a dict literal in `scheduler/manager.py` (ADR-013).
- LLM backend: `[compound_loop].backend` through `llm/registry.py` (ADR-033).
- External tools: `enabled = true` plus a `shutil.which` probe, for QMD (ADR-016), Engram (ADR-022) and Graphify (ADR-023).

`PluginRegistry` was built for the first of these and never acquired a second consumer — outside `plugins/` nothing imports it. ADR-018 deferred its own implementation until a second extension point existed, and `docs/roadmap.md` Theme 4 records the same gate.

Two things forced the question now. First, `features.py` implements the same four-state model (`active`/`dormant`/`missing`/`broken`) three times, once per external tool, differing only in which config key and which binary each consults — duplication that already exists rather than duplication that is predicted. Second, an interactive configuration surface (the TUI design) has to enumerate every one of the six surfaces, and a design where it special-cases all six is six code paths that drift.

A constraint shapes the answer: the user base is a single operator across several machines. There is no third-party plugin author. Anything justified only by "someone else might extend this" is out.

## Decision

Introduce a `CapabilityRegistry` that enumerates every activatable thing in the framework, where each capability is classified along **two orthogonal axes** rather than one plugin-type enum.

**Axis 1 — cardinality.** `ONE` (exactly one implementation active: agent, scheduler backend, LLM backend) or `MANY` (any subset active: hooks, metrics sinks, external tools).

**Axis 2 — external dependency.** Whether activation requires a binary that may be absent. Capabilities without one have two states (`on`/`off`). Capabilities with one have the four states `features.py` already implements (`active`/`dormant`/`broken`/`missing`).

A capability is a frozen dataclass carrying its name, kind, cardinality, the dotted config path that controls it, its optional binary and version pin, and whether it is on by default. Every consumer — `lh doctor`, `lh selftest`, `lh deploy`, the TUI — dispatches on cardinality instead of on which of the six surfaces it is looking at.

Three properties are load-bearing:

1. **The registry never writes to disk.** `toggle` returns a new `Config`; persistence belongs to the caller. This keeps it unit-testable without a filesystem and keeps config-writing behind exactly one seam.
2. **Binary probing is an injected parameter with a real default.** Testing a `broken` state must not require uninstalling a tool.
3. **`enabled_by_default` on the capability supersedes the `DEFAULT_HOOKS` literal**, which becomes derived data. A hook can no longer be registered and forgotten in the defaults.

Migration proceeds one kind per change, ordered by blast radius: external tools first (it collapses the `features.py` triplication and `lh doctor`'s output is a byte-exact acceptance test), then hooks, then metrics sinks, then the three `ONE`-cardinality kinds.

### Explicit non-goals

- **No public plugin API.** No versioned contract, no stability promise, no plugin-authoring documentation.
- **`discover_entry_points` is not extended.** It remains as written, used only by `metrics_sink`.
- **No manifest files.** Capabilities are declared in Python beside the code they describe.
- **No new user-facing config shape.** Every capability points at a key that already exists.

### Prerequisite

`save_config` currently destroys config. `load_config` reads 14 top-level sections; `_config_to_dict` emits 10, several partially. Measured against a live config: 51 keys lost, including every declared scheduler job, the entire `[compound_loop]`, `[memory.engram]` and `[lazynorth]` sections, and `hooks.pre_tool_use.allow_patterns`.

The fix is read-modify-write over the raw TOML rather than completing the serializer, so unmodelled and future sections survive by construction. This is already the pattern in `wizards/_toml_merge.py`, which is why the wizards do not corrupt config while `lh profile` does.

Independently, `ContextInjectConfig` declares `qmd_suggest_enabled`, `qmd_suggest_top_k` and `graphify_surface_enabled`; `hooks/builtins/context_inject.py` reads all three; and `load_config` populates none of them from the file. The three switches are permanently pinned to their defaults. Fixed in the same change.

## Alternatives considered

- **Treat only hooks as plugins.** The smallest change — hooks are the most numerous surface (15) and the one a user most plausibly toggles. Rejected because the TUI would still need four special cases, and because it leaves the `features.py` triplication, which is the duplication that actually exists today.
- **A single `PluginKind` enum with a third `FLAG` value.** Rejected: `FLAG` is not a third cardinality, it is `MANY` combined with an external dependency. Encoding two independent properties in one enum makes their combinations unrepresentable — a `ONE`-cardinality capability with an external binary (an LLM backend requiring a local Ollama) has no spelling.
- **Manifest-driven plugins (TOML or YAML per capability, with declared schema and dependencies).** The most flexible and the standard answer for a real plugin ecosystem. Rejected as machinery with no consumer: with one operator and no third-party authors, a manifest layer adds a parser, a schema validator, and a discovery path to express what a frozen dataclass already expresses.
- **Extend `PluginRegistry` in place rather than adding a second registry.** Rejected because the two answer different questions. `PluginRegistry.resolve(kind, name)` returns an implementation class for instantiation; `CapabilityRegistry` enumerates what exists and reports whether it is on. Merging them would give one object two unrelated responsibilities, and `PluginRegistry`'s `ext:` prefixing and conflict semantics only make sense for the resolution half.
- **Complete `_config_to_dict` instead of read-modify-write.** Rejected: correct on the day it ships and silently wrong the first time a section is added and the serializer is not updated. The failure is invisible, which is why it has recurred.
- **Do nothing; let the TUI special-case six surfaces.** The honest fallback, and it remains the escape hatch if migration proves larger than expected. Rejected as the plan because the six code paths would drift, and because it leaves the config-loss bug — which the TUI cannot route around — unfixed either way.

## Consequences

- ADR-018's deferred implementation trigger is met. Its `accepted-deferred` posture closes, and `docs/roadmap.md` Theme 4's "identify and ship the second extension point" is answered: the second extension point is the unification of the five that already exist, not a new plugin type.
- `features.py` collapses from three ~30-line probe functions to a table iteration. `lh doctor`'s Features section keeps its exact current output; that identity is the acceptance test.
- `DEFAULT_HOOKS` stops being a literal maintained alongside `_BUILTIN_HOOKS` and becomes derived from it, removing one instance of the "implemented but never wired" failure class.
- A selftest check becomes possible that asserts every capability's declared config path survives a save/load round trip. That single check would have caught all 51 lost keys and all three ignored `context_inject` switches.
- Three features that were permanently on become genuinely configurable. Their current effective values equal their defaults, so no behaviour changes on upgrade — the switches simply start working.
- Adding a seventh activatable thing later becomes a `Capability` registration rather than a design exercise, and it appears in `lh doctor`, `lh selftest` and the TUI without any of them being modified.
- The cost is a refactor touching six modules with no user-visible feature attached. It is justified by the TUI that depends on it and by the duplication it removes, not by extensibility that nobody has asked for. If step 1 lands and steps 2–4 stall, the codebase is still better off and the TUI is still buildable against the fallback.
- `plugins/contracts.py` — `MetricEvent`, `METRIC_EVENT_SCHEMA_VERSION`, the `MetricsSink` Protocol — is unchanged. This ADR adds a registry; it does not revisit the metrics sink contract.

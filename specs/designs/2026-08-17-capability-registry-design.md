# Capability registry: one enumerable surface for everything that can be turned on

**Status:** proposed
**Date:** 2026-08-17
**Decision record:** [ADR-035](../adrs/035-capability-registry.md)
**Relates to:** [ADR-018](../adrs/018-config-discoverability.md) (feature discoverability), [ADR-025](../adrs/025-doctor-features-section.md), [ADR-026](../adrs/026-config-wizards.md), [ADR-031](../adrs/031-default-hooks-merge.md), [ADR-004](../adrs/004-agent-adapter-pattern.md), [ADR-033](../adrs/033-llm-backend-abstraction.md)

## Problem

The harness already has a plugin system. `src/lazy_harness/plugins/` ships `PluginRegistry` with built-in registration, entry-point discovery, `ext:` name prefixing, `PluginConflict` on collision, and a test that pins "discovery is not activation" (`tests/plugins/test_discovery_not_activation.py`).

Outside that package, **nothing imports `PluginRegistry`.** Five modules import `plugins.contracts` — all of them under `monitoring/`, all of them for the `MetricEvent` dataclass. The registry itself has exactly zero production callers.

Meanwhile there are four hand-rolled registries:

| Location | Contents |
|---|---|
| `hooks/loader.py:47` `_BUILTIN_HOOKS` | 15 hooks, dict literal |
| `agents/registry.py:59` `_AGENTS` | 2 adapters, dict literal |
| `scheduler/manager.py:20` | 3 backends, dict literal inside a function |
| `llm/registry.py` | LLM backends |

And six different ways to turn something on:

| Surface | Mechanism | How many can be active |
|---|---|---|
| Hooks | `DEFAULT_HOOKS` merged with `[hooks.<event>].scripts` | many |
| Metrics sinks | `[metrics].sinks = [...]` | many |
| Agent adapter | `[agent].type` | exactly one |
| Scheduler backend | `[scheduler].backend` | exactly one |
| LLM backend | `[compound_loop].backend` | exactly one |
| External tools (qmd, engram, graphify) | `enabled = true` + binary on PATH | flag + dependency |

The cost of this is not hypothetical. `features.py` contains three functions — `_qmd_status`, `_engram_status`, `_graphify_status` — that implement the same four-state model (`active` / `dormant` / `missing` / `broken`) three times, ~30 lines each, differing only in which config key and which binary they consult. That triplication is the concrete evidence that a table is missing. It is not a prediction about future extension points; it is duplication that already exists.

The second cost lands on the TUI (see the [config TUI design](2026-08-17-config-tui-design.md)): a configuration pane that has to special-case six surfaces is six code paths that drift independently.

`docs/roadmap.md` Theme 4 states the trigger for this work: *"Identify and ship the second extension point... Selection criterion is concrete user need, not speculative design."* ADR-018 is held at the same gate. The concrete user need is now on the table — an interactive surface that has to enumerate what exists and what is on.

### The prerequisite nobody can skip

`core/config.py:load_config` reads 14 top-level sections. `_config_to_dict` emits 10, and several of those partially. Every `save_config()` call therefore destroys config.

Measured against the live config on this machine: **51 keys lost**, including all six declared scheduler jobs.

```
compound_loop.*                    (10 keys — the entire section)
memory.engram.*                    (5 keys — the entire section)
lazynorth.*                        (3 keys — the entire section)
knowledge.structure.*              (4 keys)
scheduler.jobs.*                   (6 jobs × 2 keys + 6 table headers = 18 keys)
context_inject.qmd_suggest_enabled
context_inject.qmd_suggest_top_k
context_inject.graphify_surface_enabled
hooks.pre_tool_use.allow_patterns
profiles.<name>.lazynorth_doc      (× 2 profiles)
```

This has not caused visible damage yet only because `save_config` has a single production caller (`lh profile`), and the wizards deliberately route around it through `wizards/_toml_merge.py`, which merges into the raw TOML instead. A TUI that writes config cannot route around it.

A second, independent defect sits in the same area. `ContextInjectConfig` declares `qmd_suggest_enabled`, `qmd_suggest_top_k`, and `graphify_surface_enabled`, and `hooks/builtins/context_inject.py` reads all three at lines 779, 787 and 790. But `load_config`'s `[context_inject]` parse block never populates them from the file. Verified:

```
max_body_chars             pedido=4242   cargado=4242   OK
qmd_suggest_enabled        pedido=False  cargado=True   <-- IGNORADA
qmd_suggest_top_k          pedido=99     cargado=3      <-- IGNORADA
graphify_surface_enabled   pedido=False  cargado=True   <-- IGNORADA
```

Three switches exist in the dataclass, are consumed by a live hook, and cannot be moved from the config file. QMD suggestion and the graphify surface are permanently on. This is the failure the repo's gate names directly: *a config field that promises automatic behaviour must have that behaviour implemented.* A registry that enumerates capabilities from config keys would surface this class of defect by construction, because a capability whose config path does not round-trip fails its own contract test.

## Non-goals

These are the boundaries the scope conversation set, and they are what keeps this from becoming a platform.

- **No public plugin API.** The user base is one operator across several machines. There is no third-party plugin author to serve, so: no versioned public contract, no stability promise, no "how to write a plugin" documentation, no expansion of entry-point groups.
- **`discover_entry_points` is not extended.** It stays exactly as written, exercised only by `metrics_sink` and its existing tests. It is not deleted — it works and it is tested — but nothing new is routed through it.
- **No manifest files.** Capabilities are declared in Python next to the code they describe. A TOML or YAML manifest layer is machinery with no consumer.
- **No new user-facing config shape.** Every capability points at a config key that already exists. This refactor changes who reads those keys, not what a user writes.
- **`lh doctor` output does not change.** Its current Features section is the acceptance test for the first migration step, byte for byte.

## Design

### D1 — Two orthogonal axes, not one enum

The six surfaces differ along two independent dimensions. Collapsing them into a single "plugin kind" enum was considered and rejected — it produces a three-valued enum where one value (`FLAG`) is secretly a combination of the other two.

**Axis 1 — cardinality.** How many implementations of this kind can be active at once.

```python
class Cardinality(StrEnum):
    ONE = "one"    # exactly one active: agent, scheduler backend, LLM backend
    MANY = "many"  # any subset active: hooks, metrics sinks, external tools
```

**Axis 2 — external dependency.** Whether activation requires a binary that may or may not be installed.

A capability with no external dependency has two states: `on` or `off`. A capability with one has the four states `features.py` already implements:

```python
class CapabilityState(StrEnum):
    ON = "on"            # enabled; no external dependency
    OFF = "off"          # disabled; no external dependency
    ACTIVE = "active"    # enabled and its binary is installed
    DORMANT = "dormant"  # installed but not enabled
    BROKEN = "broken"    # enabled but the binary is missing
    MISSING = "missing"  # neither enabled nor installed
```

The four-state half is not new logic. It is `_qmd_status` / `_engram_status` / `_graphify_status` written once.

### D2 — The `Capability` record

```python
@dataclass(frozen=True)
class Capability:
    name: str                    # "engram", "context-inject", "systemd"
    kind: str                    # "tool" | "hook" | "metrics_sink" | "agent" | "scheduler" | "llm_backend"
    cardinality: Cardinality
    config_path: str             # dotted path into config.toml
    summary: str                 # one line, shown by doctor and the TUI
    binary: str = ""             # external binary to probe; "" = no external dependency
    pinned_version: str = ""
    enabled_by_default: bool = False
    install_hint: str = ""
```

`config_path` is a dotted path resolved against the loaded `Config` — `"memory.engram.enabled"`, `"knowledge.structure.enabled"`, `"context_inject.qmd_suggest_enabled"`. For `MANY` capabilities whose config is a list rather than a boolean (hooks under `[hooks.<event>].scripts`, sinks under `[metrics].sinks`), the path names the list and membership is the enabled test.

`enabled_by_default` absorbs `deploy/defaults.py:DEFAULT_HOOKS`. That literal becomes derived data — `DEFAULT_HOOKS` is computed from the registry rather than maintained beside it — so a hook can no longer be registered and forgotten in the defaults, which is the "implemented but never wired" failure the repo has already recorded once.

### D3 — Registry API: pure, in-memory, never writes

```python
class CapabilityRegistry:
    def register(self, cap: Capability) -> None: ...
    def capabilities(self, *, kind: str | None = None) -> list[Capability]: ...
    def get(self, name: str) -> Capability: ...
    def state(self, cap: Capability, cfg: Config, *, probe: Probe = which_probe) -> CapabilityState: ...
    def toggle(self, cap: Capability, cfg: Config, *, enabled: bool) -> Config: ...
```

Two constraints make this safe to build a TUI on:

1. **`toggle` returns a new `Config` and touches no disk.** Persistence belongs to the caller, through the fixed serializer in D5. A registry that writes files is a registry you cannot unit-test without a filesystem, and it would put the config-loss bug behind two layers instead of one.
2. **`probe` is injected.** Binary detection is a parameter with a real default, not a hardcoded `shutil.which`. Testing a `BROKEN` state must not require uninstalling engram.

Per the repo's CLI-test gate, every explicit-`probe` test is paired with a default-resolution smoke test, so the `which_probe` path is not left uncovered by always injecting a fake.

### D4 — Consumers collapse

| Consumer | Before | After |
|---|---|---|
| `features.py` | 3 hand-written probe functions, ~90 lines | iterate `registry.capabilities(kind="tool")` |
| `cli/doctor_cmd.py` Features section | consumes `FeatureStatus` | consumes `CapabilityState`, same rendering |
| `deploy/defaults.py` `DEFAULT_HOOKS` | dict literal | derived from `enabled_by_default` |
| `hooks/loader.py` `_BUILTIN_HOOKS` | dict literal | each entry also registers a `Capability` |
| `selftest/checks/*` | per-area ad hoc checks | can assert every registered capability's config path resolves |
| TUI configure pane | would need 6 code paths | one, dispatching on `Cardinality` |

The selftest row is worth calling out. Once capabilities declare their config path, a check can assert that **every declared path survives a save/load round trip**. That single check would have caught all 51 lost keys and all three ignored `context_inject` switches.

### D5 — Prerequisite: config persistence that cannot lose sections

Two candidate fixes:

**(a) Complete `_config_to_dict`.** Add the missing sections and sub-trees. Correct today, wrong again the first time section 15 is added and someone forgets. The failure mode is silent, which is what makes it recur.

**(b) Read-modify-write over the raw TOML.** `save_config` reads the existing file, applies only the fields it models, and writes the merged result. Sections the loader does not model — and sections a future version adds — survive by construction rather than by vigilance.

**(b) is the choice**, on two grounds. It is correct by construction rather than by maintenance. And it is already the pattern in this repo: `wizards/_toml_merge.py` does exactly this, which is why the wizards do not corrupt config while `lh profile` does. The repo's own rule applies — *repo patterns outrank the text of a plan* — and here the plan and the pattern agree.

No signature change: `save_config(cfg, path)` reads `path` before writing it, and falls back to writing from scratch when the file is absent.

Three tests gate this, and each one must be proven to fail before the fix:

1. **Round-trip identity.** For a fixture containing every section the loader reads: `load(save(load(f))) == load(f)`.
2. **No key loss.** Parse the raw TOML before and after `save_config`; assert the key set is not reduced. This is the test that reproduces the 51 measured keys.
3. **Double round trip.** save → load → save → load. A deserializer that supplies a default the serializer omits drops it on the *second* rewrite, not the first, and a single round trip cannot see it. The repo's gate on config changes requires this explicitly.

The `[context_inject]` parse gap is fixed in the same change: the three unread keys are wired into the parse block, with a test asserting a non-default value in the file reaches the hook. That test fails today.

### D6 — Migration order

One kind per change, each under TDD, each independently revertible. Ordered by blast radius, smallest first.

| # | Step | Why here |
|---|---|---|
| 0 | Config round-trip fix + `[context_inject]` parse gap | Prerequisite. Nothing else is safe to build until `save_config` stops destroying config. |
| 1 | `tool` kind — qmd, engram, graphify | Collapses the `features.py` triplication. Acceptance: `lh doctor` output is byte-identical before and after. Highest value, smallest surface, and the output diff is the test. |
| 2 | `hook` kind — 15 entries | Largest count but mechanical. `merge_with_defaults` keeps its semantics; config still wins over defaults. `DEFAULT_HOOKS` becomes derived. |
| 3 | `metrics_sink` | Already has a registry; this is re-registration into the unified one. `MetricsSink` Protocol and `MetricEvent` are untouched. |
| 4 | `agent`, `scheduler`, `llm_backend` | The `ONE`-cardinality kinds. Three lines each; last because they are trivial and because the scheduler one is easier after the [Linux parity work](2026-08-17-linux-parity-design.md) lands. |
| 5 | Selftest check: every capability's config path round-trips | The regression net for step 0. |

Steps 1–4 are behaviour-preserving refactors. If any of them proves larger than expected, stopping after step 1 still leaves the codebase better than it started and the TUI still buildable — its configure pane would special-case the four unmigrated kinds, which is the fallback that was considered and set aside.

## Verification

The repo's gate applies with unusual force here, because a registry refactor is exactly the kind of change where tests keep passing while behaviour rots.

- **Prove each new test fails first.** For step 0 in particular: run the key-loss test against unmodified `save_config` and record that it reports the 51 keys. A test that passes with and without the fix covers nothing.
- **`lh doctor` diff is the acceptance test for step 1.** Capture output before, migrate, capture after, assert identical. Not "looks the same" — a stored fixture.
- **After step 2, verify the deployed artefact, not the checkout.** Toggle a hook off, run `lh deploy`, and grep the profile's `settings.json` to confirm it is gone. A hook that a registry believes is disabled but that is still wired in `settings.json` is the divergence the repo has already been bitten by.
- **Grep for orphaned config keys once the registry exists.** Every key `load_config` reads should belong to a capability or be explicitly exempt. The three ignored `context_inject` keys were found by hand; after this work a check finds them.

## Consequences

- ADR-018's deferred implementation trigger — *"the first extension point that needs an interactive wizard"* — is met by the TUI, and this design is what makes that wizard generic instead of six-branched.
- `docs/roadmap.md` Theme 4 item "Identify and ship the second extension point" is answered: the second extension point is not a new plugin type, it is the unification of the five that already exist. Theme 4's second item — "Document the extension-point contract once two exist in code" — becomes writable, though it stays internal given the no-public-API non-goal.
- `_config_to_dict` shrinks rather than grows. The read-modify-write approach means adding a config section no longer requires touching the serializer, which removes an entire category of "forgot to add it to the writer" bug.
- Three permanently-on features (`qmd_suggest`, `graphify_surface`, and `qmd_suggest_top_k`) become genuinely configurable. Since their current effective values equal their defaults on this machine, no behaviour changes on upgrade — but the switches start working.
- `specs/backlog.md`'s "ADR-018 implementation epic — `accepted-deferred`" entry closes.
- The plugin package keeps its existing public surface. `MetricEvent`, `METRIC_EVENT_SCHEMA_VERSION`, and the `MetricsSink` Protocol are unchanged; `CapabilityRegistry` is added alongside `PluginRegistry` rather than replacing it, because the two answer different questions — one resolves an implementation by name, the other enumerates what exists and whether it is on.

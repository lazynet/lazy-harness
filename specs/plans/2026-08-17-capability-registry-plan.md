# Capability registry Implementation Plan (wave 6)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Collapse six activation surfaces and four hand-rolled registries into one enumerable registry, so `lh doctor`, `lh selftest` and the TUI dispatch on cardinality instead of special-casing each surface.

**Architecture:** A frozen `Capability` record classified along two orthogonal axes — cardinality (`ONE`/`MANY`) and whether activation needs an external binary. The registry is pure: it never touches disk, and `toggle` returns a new `Config`. Migration proceeds one kind per commit, smallest blast radius first, each behaviour-preserving and each proven so by an identity fixture.

**Tech Stack:** Python 3.11+ stdlib, `pytest`, `ruff`.

**Spec:** [`specs/designs/2026-08-17-capability-registry-design.md`](../designs/2026-08-17-capability-registry-design.md) / [ADR-035](../adrs/035-capability-registry.md)

**Branch:** `refactor/capability-registry` — PR title `refactor: unify activation surfaces behind a capability registry`. **Cuts no release**; it ships with wave 7's `0.41.0`.

## Global Constraints

- **Blocked by wave 1.** Task 8's selftest check asserts every capability's config path round-trips, which is what wave 1 fixes. Do not start before `fix/config-round-trip` has merged.
- **May run in parallel with waves 2–4** in its own worktree. This plan touches `plugins/`, `features.py`, `hooks/loader.py`, `deploy/defaults.py`; the Linux plan touches `scheduler/` and `monitoring/views/`. Disjoint.
- **Every step here is behaviour-preserving.** The PR is titled `refactor:`, and the rule that makes that safe is the identity fixture: captured output before, byte-identical after. If a task cannot preserve behaviour, stop and re-title the PR — do not relax the fixture.
- Strict TDD, every new test observed failing first.
- Probing is an injected parameter with a real default. Every explicit-`probe` test is paired with a parameter-less smoke test so the default `shutil.which` path is exercised.
- `/tdd-check` before every commit. No AI trailers.

## Explicit non-goals

Carried from ADR-035, restated because they are what bounds this work: no public plugin API, no versioned contract, no plugin-authoring docs, no expansion of `discover_entry_points`, no manifest files, no new user-facing config shape. `plugins/contracts.py` is not touched.

## File Structure

| File | Responsibility |
|---|---|
| `src/lazy_harness/plugins/capabilities.py` | **new** — `Cardinality`, `CapabilityState`, `Capability`, `CapabilityRegistry` |
| `src/lazy_harness/plugins/builtins.py` | **new** — every builtin `Capability` registration, one table |
| `src/lazy_harness/features.py` | three probe functions collapse to a table iteration |
| `src/lazy_harness/hooks/loader.py` | `_BUILTIN_HOOKS` entries also register a `Capability` |
| `src/lazy_harness/deploy/defaults.py` | `DEFAULT_HOOKS` derived from `enabled_by_default` |
| `src/lazy_harness/selftest/checks/config_check.py` | new check: every capability's config path resolves and round-trips |
| `tests/plugins/test_capabilities.py` | **new** |
| `tests/fixtures/settings-json/` | **new** — the identity fixture for Task 5 |

---

### Task 1: The two axes and the `Capability` record

**Interfaces:**
- Produces: `Cardinality` (`ONE`, `MANY`); `CapabilityState` (`ON`, `OFF`, `ACTIVE`, `DORMANT`, `BROKEN`, `MISSING`); `Capability` frozen dataclass with fields `name`, `kind`, `cardinality`, `config_path`, `summary`, `binary=""`, `pinned_version=""`, `enabled_by_default=False`, `install_hint=""`

- [ ] **Step 1: Write the failing test**

Create `tests/plugins/test_capabilities.py`:

```python
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
    assert list(tmp_path.iterdir()) == []
```

- [ ] **Step 2: Run and confirm all fail**

Run: `uv run pytest tests/plugins/test_capabilities.py -v`
Expected: `ModuleNotFoundError: lazy_harness.plugins.capabilities`.

- [ ] **Step 3: Implement**

Create `src/lazy_harness/plugins/capabilities.py` with `Cardinality` and `CapabilityState` as `StrEnum`s, the frozen `Capability` dataclass, and `CapabilityRegistry` exposing `register`, `capabilities(kind=None)`, `get(name)`, `state(cap, cfg, *, probe=which_probe)` and `toggle(cap, cfg, *, enabled)`.

`config_path` resolution walks the dotted path against the `Config` dataclass with `getattr`. `toggle` deep-copies the `Config` before setting, so the caller's object is never mutated in place.

- [ ] **Step 4: Run, then commit**

```bash
uv run pytest tests/plugins/test_capabilities.py -v
git add src/lazy_harness/plugins/capabilities.py tests/plugins/test_capabilities.py
git commit -m "feat: capability registry with cardinality and dependency axes"
```

---

### Task 2: Capture the `lh doctor` identity fixture

This must happen **before** any migration. It is the acceptance test for Task 3, and it cannot be captured after the code changes.

- [ ] **Step 1: Capture**

```bash
mkdir -p tests/fixtures/doctor-output
uv run lh doctor > tests/fixtures/doctor-output/features-before.txt 2>&1
grep -A20 "^Features" tests/fixtures/doctor-output/features-before.txt
```

- [ ] **Step 2: Write the test that pins it**

```python
def test_doctor_features_section_is_unchanged_by_the_registry_migration() -> None:
    """The migration is behaviour-preserving. This is what makes that claim checkable."""
    from pathlib import Path

    from lazy_harness.core.config import Config
    from lazy_harness.features import collect_feature_statuses

    expected = Path("tests/fixtures/doctor-output/features-before.txt").read_text()
    statuses = collect_feature_statuses(Config())
    for status in statuses:
        assert status.name in expected
```

The fixture depends on what is installed on this machine, so the assertion checks that every name still appears rather than diffing the whole file. The full-file diff is a manual step in Task 3.

- [ ] **Step 3: Commit**

```bash
git add tests/fixtures/doctor-output/ tests/unit/test_features.py
git commit -m "test: pin the lh doctor Features section before the registry migration"
```

---

### Task 3: Migrate the `tool` kind

Highest value, smallest surface. Collapses `_qmd_status`, `_engram_status` and `_graphify_status` — roughly 90 lines implementing the same four-state model three times — into a table.

**Files:**
- Create: `src/lazy_harness/plugins/builtins.py`
- Modify: `src/lazy_harness/features.py`

- [ ] **Step 1: Write the failing test**

```python
def test_the_three_tools_are_registered_as_capabilities() -> None:
    from lazy_harness.plugins.builtins import builtin_registry

    names = {c.name for c in builtin_registry().capabilities(kind="tool")}
    assert names == {"qmd", "engram", "graphify"}


def test_every_tool_capability_declares_a_binary_and_a_config_path() -> None:
    from lazy_harness.plugins.builtins import builtin_registry

    for cap in builtin_registry().capabilities(kind="tool"):
        assert cap.binary, f"{cap.name} has no binary to probe"
        assert cap.config_path, f"{cap.name} has no config path"
```

- [ ] **Step 2: Run, confirm failure.**

- [ ] **Step 3: Write the table**

`src/lazy_harness/plugins/builtins.py`:

```python
"""Every builtin capability, in one table.

Registration lives beside nothing in particular on purpose: this file is the
single place to look for "what can this harness do". Adding a capability here
makes it appear in `lh doctor`, `lh selftest` and the TUI without editing any
of them.
"""

from __future__ import annotations

from functools import lru_cache

from lazy_harness.plugins.capabilities import Capability, CapabilityRegistry, Cardinality

_TOOLS = [
    Capability(
        name="qmd",
        kind="tool",
        cardinality=Cardinality.MANY,
        config_path="knowledge.search.engine",
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
        pinned_version="1.15.4",
        install_hint="Install Engram and set [memory.engram].enabled = true.",
    ),
    Capability(
        name="graphify",
        kind="tool",
        cardinality=Cardinality.MANY,
        config_path="knowledge.structure.enabled",
        summary="Code-structure index and call graph",
        binary="graphify",
        pinned_version="0.9.38",
        install_hint="Install Graphify and set [knowledge.structure].enabled = true.",
    ),
]


@lru_cache(maxsize=1)
def builtin_registry() -> CapabilityRegistry:
    reg = CapabilityRegistry()
    for cap in _TOOLS:
        reg.register(cap)
    return reg
```

The `pinned_version` values must match `memory/engram.py:PINNED_VERSION` and `knowledge/graphify.py:PINNED_VERSION`. Import them rather than retyping the literals, so the pin has one home.

- [ ] **Step 4: Rewrite `collect_feature_statuses` over the table.** Delete `_qmd_status`, `_engram_status`, `_graphify_status`. Keep `FeatureStatus` as the return type so `cli/doctor_cmd.py` needs no change.

- [ ] **Step 5: Diff the real output — this is the acceptance test**

```bash
uv run lh doctor > /tmp/features-after.txt 2>&1
diff tests/fixtures/doctor-output/features-before.txt /tmp/features-after.txt
```
Expected: empty. Any difference means the migration was not behaviour-preserving; fix it rather than updating the fixture.

- [ ] **Step 6: Run the suite and commit**

```bash
uv run pytest -q
git add src/lazy_harness/plugins/builtins.py src/lazy_harness/features.py tests/plugins/test_capabilities.py
git commit -m "refactor: derive lh doctor Features from the capability registry"
```

---

### Task 4: Capture the `settings.json` identity fixture

Before touching hooks. This is the most important fixture in the plan: a hook the registry believes is enabled but that `lh deploy` no longer writes is silently disabled, with no warning from the framework and no error from the agent.

- [ ] **Step 1: Capture the generated hook block for both profiles**

```bash
mkdir -p tests/fixtures/settings-json
for p in lazy flex; do
  python3 -c "
import json,sys
h = json.load(open('$HOME/.claude-$p/settings.json')).get('hooks',{})
json.dump(h, sys.stdout, indent=2, sort_keys=True)
" > "tests/fixtures/settings-json/$p-hooks-before.json"
done
wc -l tests/fixtures/settings-json/*.json
```

- [ ] **Step 2: Write the test that regenerates and compares**

```python
def test_generated_hook_block_is_unchanged_by_the_registry_migration(tmp_path) -> None:
    """`merge_with_defaults` + the adapter must emit exactly what they emitted before.

    A hook that disappears here stops running with no error anywhere.
    """
    import json
    from pathlib import Path

    from lazy_harness.agents.registry import get_agent
    from lazy_harness.core.config import Config
    from lazy_harness.deploy.defaults import merge_with_defaults

    agent = get_agent("claude-code")
    effective = merge_with_defaults(Config().hooks, agent)
    expected = json.loads(
        Path("tests/fixtures/settings-json/default-effective-hooks.json").read_text()
    )
    assert effective == expected
```

Generate `default-effective-hooks.json` from the current code before changing anything:

```bash
uv run python -c "
import json
from lazy_harness.agents.registry import get_agent
from lazy_harness.core.config import Config
from lazy_harness.deploy.defaults import merge_with_defaults
print(json.dumps(merge_with_defaults(Config().hooks, get_agent('claude-code')), indent=2, sort_keys=True))
" > tests/fixtures/settings-json/default-effective-hooks.json
```

- [ ] **Step 3: Commit**

```bash
git add tests/fixtures/settings-json/ tests/unit/test_deploy_defaults.py
git commit -m "test: pin the effective hook set before deriving it from the registry"
```

---

### Two gaps Task 1 uncovered, which Tasks 5 and 6 must close first

Measured on the branch, not inferred:

1. **A dotted path cannot traverse a `dict`.** `Config.hooks` and
   `ProfilesConfig.items` are plain dicts, so `_resolve` walking with `getattr`
   raises on the event name. `hooks.pre_tool_use.scripts` — the exact shape
   Task 5 specifies below — fails with
   `AttributeError: 'dict' object has no attribute 'pre_tool_use'`. `_resolve`
   now names the capability and the whole path in that error, but it still
   cannot walk it. Task 5 must add mapping traversal first.

2. **There is no membership test, only truthiness.** `state()` reads the
   resolved value with `bool()`. Registering `sqlite_local` and `http_remote`
   both at `metrics.sinks` made **both** report `ON` against the default
   config, where the list holds only `sqlite_local`. A capability claiming to
   be enabled when it is not is worse than a crash, because nothing announces
   it. `state()` now refuses a list-, tuple-, set- or dict-valued path rather
   than answering; Task 6 replaces that refusal with a real membership test,
   which needs a per-capability identity to compare against (the script name
   for a hook, the sink name for a sink) that the `Capability` record does not
   carry yet.

Neither blocks Task 3: the `tool` kind uses only scalar and presence-only paths.

### Task 5: Migrate the `hook` kind

15 entries. Mechanical, but it is the one that touches `lh deploy`.

- [ ] **Step 1:** Extend `_BUILTIN_HOOKS` entries in `hooks/loader.py` so each also carries a `Capability` with `kind="hook"`, `cardinality=Cardinality.MANY`, `config_path=f"hooks.{event}.scripts"`, and `enabled_by_default` set from the current `DEFAULT_HOOKS` membership.
- [ ] **Step 2:** Make `deploy/defaults.py:DEFAULT_HOOKS` derived — compute it from `builtin_registry().capabilities(kind="hook")` filtered on `enabled_by_default`. `merge_with_defaults` keeps its exact semantics: user config still wins, an explicit empty list is still an opt-out distinct from "not configured", and `_SYSTEM_DOC_HOOKS` filtering still applies when `agent.system_doc_name()` is empty.
- [ ] **Step 3:** Run `tests/unit/test_deploy_defaults.py` and the Task 4 fixture test. Both must pass unchanged.
- [ ] **Step 4: Regenerate and diff against the real profiles**

```bash
uv run lh deploy
for p in lazy flex; do
  python3 -c "
import json,sys
h = json.load(open('$HOME/.claude-$p/settings.json')).get('hooks',{})
json.dump(h, sys.stdout, indent=2, sort_keys=True)
" > "/tmp/$p-hooks-after.json"
  diff "tests/fixtures/settings-json/$p-hooks-before.json" "/tmp/$p-hooks-after.json" \
    && echo "  $p unchanged" || echo "  $p CHANGED — stop"
done
```
Both must report unchanged. A hook that vanished is a regression, not a cleanup.

- [ ] **Step 5:** Commit as `refactor: derive the default hook set from the capability registry`.

---

### Task 6: Migrate `metrics_sink`

- [ ] Register `sqlite_local` and `http_remote` as `kind="metrics_sink"`, `cardinality=Cardinality.MANY`, `config_path="metrics.sinks"`. Membership in the list is the enabled test. `PluginRegistry` keeps resolving the implementation classes — the two registries answer different questions and both stay. `plugins/contracts.py` is untouched. Commit as `refactor: register metrics sinks as capabilities`.

---

### Task 7: Migrate the three `ONE`-cardinality kinds

- [ ] Register `claude-code` and `null` (`kind="agent"`, `config_path="agent.type"`); `launchd`, `systemd`, `cron` (`kind="scheduler"`, `config_path="scheduler.backend"`); and the LLM backends (`kind="llm_backend"`, `config_path="compound_loop.backend"`). All `Cardinality.ONE`.
- [ ] Add a test that `state` on a `ONE` capability returns `ON` only for the name the config selects, and `OFF` for its siblings. Commit as `refactor: register agent, scheduler and LLM backends as capabilities`.

---

### Task 8: Selftest — every capability's config path resolves and round-trips

The permanent net, and the reason this wave is blocked by wave 1.

- [ ] **Step 1: Write the failing test**

```python
def test_capability_paths_check_fails_when_a_path_does_not_resolve(tmp_path) -> None:
    """A capability pointing at a config key that does not exist is a broken contract."""
    from lazy_harness.plugins.capabilities import (
        Capability,
        CapabilityRegistry,
        Cardinality,
    )
    from lazy_harness.selftest.checks.config_check import check_capability_paths
    from lazy_harness.selftest.result import CheckStatus

    reg = CapabilityRegistry()
    reg.register(
        Capability(
            name="bogus",
            kind="tool",
            cardinality=Cardinality.MANY,
            config_path="memory.engram.no_such_field",
            summary="points at nothing",
        )
    )

    cfg_path = tmp_path / "config.toml"
    cfg_path.write_text('[harness]\nversion = "1"\n')

    results = check_capability_paths(config_path=cfg_path, registry=reg)
    assert results[0].status == CheckStatus.FAILED
    assert "memory.engram.no_such_field" in results[0].message
```

- [ ] **Step 2:** Implement `check_capability_paths` in `selftest/checks/config_check.py`. For each capability: resolve `config_path` against a loaded `Config`, and assert the key survives the `save_config` round trip from wave 1 Task 8. Register it in `cli/selftest_cmd.py` — a check that is implemented but not registered passes every test and never runs.
- [ ] **Step 3:** `uv run lh selftest 2>&1 | grep capability` must show a PASSED row naming a count. Commit as `feat: selftest check that every capability config path resolves`.

---

### Where the executed wave departed from this plan

Each of these was forced by the code, and each would have changed `lh doctor`
or `lh deploy` output in a wave that promises not to.

1. **qmd declares no config path.** The plan gave it
   `config_path="knowledge.search.engine"`. That field holds `"qmd"`, so
   truthiness makes it permanently enabled and an uninstalled qmd reports
   `BROKEN` — where `_qmd_status` has always reported `missing`, and where it
   never consulted config at all. It is registered presence-only.

2. **`install_hint` keeps the pin.** The plan's literal was
   `"Install Engram and set [memory.engram].enabled = true."`; the code emits
   `"Install Engram (pin 1.15.4) and set ..."`. The hint is now a template the
   pin is formatted into, so there is still one home for the version.

3. **Three builtin hooks are not registered.** `herdr-context-gauge`,
   `post-tool-use-ansible-lint` and `user-prompt-goal` appear in no default
   list, so no event is declared for them anywhere. A fixed `config_path` would
   invent one and then answer wrongly for anyone who configured them elsewhere.
   A test asserts they are knowingly absent, so the omission cannot rot into an
   oversight.

4. **The scheduler backends are not registered.** `scheduler.backend` defaults
   to `"auto"`, which names no implementation — the choice is made at install
   time by probing the machine. Registering the three against that field
   reports all of them OFF on a machine demonstrably running six jobs, and
   `CapabilityState` has no word for "chosen at runtime".

5. **`ONE` cardinality needed selection semantics.** With truthiness,
   `bool("claude-code")` is True for every sibling reading `agent.type`, so
   both agents reported ON at once. `state` now compares the resolved name; and
   `toggle` writes the capability's *name* rather than `True`, and refuses to
   deselect — an exclusive choice has no "off", and the registry cannot invent
   which sibling takes over.

6. **The identity fixture holds the default hook set only.** The plan asked for
   the two live profiles' generated blocks. Those carry absolute paths from the
   machine that produced them, and this repository is public. The live
   comparison was run before and after instead, against the real config.

### Task 9: Wave 6 gate and PR

- [ ] `/tdd-check`.
- [ ] Re-run both identity diffs (Task 3 Step 5, Task 5 Step 4). Both empty.
- [ ] Push as `refactor: unify activation surfaces behind a capability registry`. **No release is cut.** The code sits in `main` until wave 7 releases `0.41.0`, which is extra soak time, but it means the post-deploy hook comparison in the release train's wave-5/6 gate must be run after that release — not after this merge.

---

## Self-review

**Spec coverage.** D1 → Task 1. D2 → Task 1. D3 → Task 1 (purity and probe injection both have their own test). D4 → Tasks 3, 5, 6, 7, 8. D5 is wave 1, referenced as a blocker. D6's migration order is Tasks 3 → 5 → 6 → 7 → 8, matching the spec's table exactly.

**Placeholders.** Tasks 6 and 7 compress to step lists because they are three-line registrations following the pattern Tasks 3 and 5 establish in full. Both name their files, their config paths and their acceptance.

**Type consistency.** `Cardinality`, `CapabilityState`, `Capability`, `CapabilityRegistry` in `plugins/capabilities.py`; `builtin_registry() -> CapabilityRegistry` in `plugins/builtins.py`; `state(cap, cfg, *, probe) -> CapabilityState`; `toggle(cap, cfg, *, enabled) -> Config`; `check_capability_paths(*, config_path, registry) -> list[CheckResult]`. `FeatureStatus` survives Task 3 unchanged so `cli/doctor_cmd.py` is not edited.

**Open risk.** If Task 5's `settings.json` diff is not empty, the hook migration is not behaviour-preserving and the PR must be re-titled `fix:` so it releases and deploys on its own rather than bundling with wave 7. That is the fallback ADR-035 anticipated: stopping after Task 3 still removes the `features.py` triplication and still leaves the TUI buildable against four special-cased kinds.

# ADR-018: Feature discoverability and configuration — `lh doctor` + `lh config <feature>`

**Status:** accepted
**Date:** 2026-04-14
**Implementation:** accepted in 2026-05 via ADR-025 (`lh doctor` Features section) and ADR-026 (`lh config <feature> --init` wizards). The triple stack (QMD/Engram/Graphify) drove the concrete UX.

## Context

The framework is acquiring extension points (metrics sinks, knowledge backends, agent adapters, hook providers). Each new extension point adds configuration surface that a user may want to opt into, and the question arises: *how does a user discover that a new capability exists, and how do they configure it without reading every release note?*

The naive answer — "run a wizard at install time and again after every upgrade" — sounds user-friendly but violates two invariants the project has committed to elsewhere:

1. **No behavior change on upgrade (ADR-018 a.k.a. this one).** A user who ran `uv tool upgrade lazy-harness` from `0.5.x` to `0.6.x` in the background, or who had release-please merge a release PR overnight, must not find that their next `lh` invocation prompts them to configure new remote sinks. That is user-hostile *and* it makes automated environments (CI, hooks, cron) fragile. This is the same principle behind the `[metrics]` default-local invariant introduced with the plugin system slice — features are off by default, activation is explicit, no surprise egress.
2. **Hooks and CI invocations must remain non-interactive.** The harness runs inside Claude Code hooks that the user does not see interactively. Any wizard firing from a hook would either hang the agent or produce corrupt output. A post-upgrade wizard cannot distinguish a human-in-terminal invocation from a hook-invocation without heuristics that will eventually get it wrong.

At the same time, leaving discovery entirely to `CHANGELOG.md` is not good enough. Users do miss features they would have adopted, and "read the release notes" does not scale past two or three extension points.

## Decision

Feature discoverability and configuration are split into **two dedicated surfaces**, both explicit and user-initiated. Neither runs automatically on install or upgrade.

### 1. `lh doctor` is the discoverability surface

`lh doctor` already exists as the on-machine health check. It gains a new section — **"Features"** — that enumerates every extension point the current binary supports, shows which ones are active in the current profile, and which ones are available but dormant. For remote-capable features it also prints the configured URL (this is the "Network egress" section already shipped in the metrics sink slice — it generalizes).

Example output:

```
Features
  metrics_sink (active)
    ✓ sqlite_local  (built-in, always on)
    ✓ http_remote   → https://metrics.flex.internal/ingest
  knowledge_backend (dormant)
    ? qmd_mcp       available — run `lh config knowledge --init` to enable
  session_export (dormant)
    ? obsidian_vault available — run `lh config session_export --init` to enable
```

The user runs `lh doctor` when they feel like checking on their setup — never on a schedule, never on upgrade. This respects the "no surprises" rule: nothing happens unless the user asked.

### 2. `lh config <feature> --init` is the wizard surface

A new `lh config` command group provides interactive init wizards on a per-feature basis. Each feature owns a subcommand that walks the user through opt-in, collects the required options, and writes a correct TOML block into the active profile's config file.

- `lh config metrics --init` — interactively builds a `[metrics]` block (which sinks, which URL for http_remote, identity resolution)
- `lh config knowledge --init` — will interactively build a `[knowledge]` block once that slice lands
- `lh config <future-feature> --init` — each extension point defines its own init flow when it ships

These commands are **only ever invoked by the human user on the terminal**. They do not run in hooks, CI, or on upgrade. They have no cron companion. They do not modify config files silently — they always preview the TOML they are about to add and ask for confirmation.

`lh config <feature> --show` and `lh config <feature> --reset` round out the surface for inspection and rollback but are out of scope of this ADR; they are implementation details of the future slice.

### 3. Upgrades print at most one non-blocking notice

On the first invocation after an upgrade that introduced a new extension point, the harness prints exactly one line to stderr:

```
lazy-harness upgraded to v0.7.0 — 2 new features available. Run `lh doctor` for details.
```

The notice is printed once and suppressed thereafter (tracked via a small state file under `<data_dir>/upgrade-notices.txt` keyed by version). It never runs a wizard, it never prompts, it does not block the command the user actually asked for. If stderr is redirected (e.g. inside a hook), the notice is silently written to the logfile instead of printed.

## Alternatives considered

- **Wizard on every upgrade.** Rejected. Violates the "no behavior change on upgrade" invariant, breaks in hook/CI contexts, user-hostile for automated install flows.
- **Wizard only on first install.** Kept partially — `lh init` continues to exist as the initial bootstrap wizard and can gain an "Optional features" step. But the main discoverability mechanism for post-install feature adoption is `lh doctor`, not a bigger `lh init`.
- **Discoverability via `CHANGELOG.md` only.** Rejected. Does not scale, users do not read changelogs for minor versions, and it provides no machine-level verification that "you know about X" matches "X is configured correctly".
- **Environment-variable-driven activation (`LH_ENABLE_METRICS_REMOTE=1`).** Rejected. Environment variables bypass the config file as source of truth. The metrics sink ADR already chose the profile as the single source of truth and rejected a global kill switch; a global "feature flag" via env var is the mirror image and has the same drawbacks.
- **Auto-detection of "would you benefit from feature X".** Considered briefly, rejected. Heuristics that guess user intent generate false positives that annoy more than they help, and they violate "no automation of the creative choices" (naming, architecture, **configuration**).

## Consequences

- `lh doctor` becomes the single, canonical place users look to audit what is installed and what is active. This is cheap to maintain because every extension point must already expose its `name`, its active/dormant state, and (for networked features) its egress URL — the same metadata the plugin registry keeps for resolution.
- The upgrade path stays zero-surprise. A `uv tool upgrade lazy-harness` followed by a scheduled hook invocation behaves identically to before the upgrade, modulo the one-shot stderr notice that is also silenced inside non-TTY contexts.
- Feature adoption requires one explicit command per feature (`lh config <feature> --init`). This is more friction than "wizard on upgrade" but the friction is wanted: it is a consent boundary, not a paper cut.
- Each new extension point ships with three things: the plugin code, a `lh doctor` row, and an `lh config <feature>` subcommand. The contract is uniform and predictable; adding a new extension point becomes a checklist, not a design exercise.
- The `lh config` command group does not exist yet. Implementation is deferred to a dedicated spec + plan that will arrive after one or two extension points have shipped and the actual wizard UX can be driven by concrete examples rather than speculation. Until then, users opt into features by hand-editing their `config.toml` and using `lh doctor` to verify the result — which is the mechanism already exercised by the metrics sink slice and works fine for a single maintainer.
- `lh init` stays focused on the initial bootstrap (identity, default profile, knowledge dir). It does not grow to include every extension point. Extension-point configuration belongs to `lh config <feature>`, not to `lh init`, so that the init flow stays short and every extension point can be configured independently at any point in the harness lifecycle.
- Implementation is intentionally not scheduled. This ADR locks the approach so that the first extension point that needs an interactive wizard (likely `knowledge_backend` given the QMD-vs-alternative choice) can be implemented against a known target.

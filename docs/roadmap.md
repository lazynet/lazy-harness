# Roadmap

Where `lazy-harness` is heading. This is a **curated list of committed themes**, not a wishlist. Items land here only when they are concrete enough to execute and the author intends to do them; exploratory ideas live in the internal backlog instead.

## How to read this document

- Each **theme** groups related work that ships together or builds on a shared mechanism.
- Items are written as short, checkable deliverables. They get ticked off as PRs merge.
- The roadmap is revised whenever a theme closes or when priorities shift. There are no dates — `lazy-harness` is a single-maintainer project and ship-when-ready beats commit-to-a-date.
- Finer-grained work (bugs, nice-to-haves, scratch notes) is not here. It lives in the internal backlog under `specs/backlog.md`.

## Theme 1 — Stability & quality gates

The pre-commit gate defined in [`CLAUDE.md`](https://github.com/lazynet/lazy-harness/blob/main/CLAUDE.md) requires `pytest`, `ruff check`, `ruff format --check`, and `mkdocs build --strict` to all pass cleanly. That invariant is the floor every other change builds on.

- [x] Rewrite `tests/unit/test_version.py` to compare `pyproject.toml` and `src/lazy_harness/__init__.py` against each other (no hardcoded expected value).
- [x] Resolve 23 preexisting `ruff check src tests` findings — auto-fix the fixable, justify or exclude the rest.
- [x] Make the pre-commit gate green on `main` and keep it green.
- [x] Add a GitHub Actions workflow that runs the gate on every PR and blocks merge on failure. All four checks are enforced: [`tests.yml`](https://github.com/lazynet/lazy-harness/blob/main/.github/workflows/tests.yml) runs `pytest`, `ruff check` and `ruff format --check` across four OS/Python combinations and builds the docs with `mkdocs build --strict` in a `docs` job of its own — [`docs.yml`](https://github.com/lazynet/lazy-harness/blob/main/.github/workflows/docs.yml) publishes the site on push to `main` and never sees a pull request, so the fourth check has to live here.

## Theme 2 — Knowledge pipeline maturity

The compound-loop worker is the framework's memory engine. Two known issues today cause lost learnings — they share an underlying mechanism (per-session delta tracking) and should land together.

- [x] Implement `★ Insight ─` block extraction as first-class compound-loop output. Spec: [`specs/designs/2026-04-13-compound-loop-insight-capture.md`](https://github.com/lazynet/lazy-harness/blob/main/specs/designs/2026-04-13-compound-loop-insight-capture.md).
- [x] Fix "learnings lost on long sessions" by storing the last processed message index per session in `insights/.cursor.json` and re-scanning only the delta on subsequent Stop hooks.
- [x] Add a contract test that pins the exact marker characters the `explanatory` output style emits, so a template change forces a visible failure.
- [x] **Close the two missing memory-pipeline stages.** Built — [ADR-040](https://github.com/lazynet/lazy-harness/blob/main/specs/adrs/040-memory-reconcile-and-decay.md) adds reconcile and decay, shipped as `lh memory reconcile` and `lh memory decay`. Without them the pipeline could only append: schema drift in `decisions.jsonl` went unreported, and a learning nothing referenced stayed as current as one cited daily.

## Theme 3 — Open architecture decisions

Decisions the audit surfaced that are waiting on real evidence before being promoted or rejected. Each one has a concrete trigger for revisiting.

- [x] **Legacy ADR-010 Ollama backend.** Promoted and superseded twice over. [ADR-033](https://github.com/lazynet/lazy-harness/blob/main/specs/adrs/033-llm-backend-abstraction.md) made inference provider-agnostic (implemented 2026-06-11); [ADR-039](https://github.com/lazynet/lazy-harness/blob/main/specs/adrs/039-role-routed-inference.md) routes it per named role, so a local model can serve cheap work without taking over the calls where output quality is the point.
- [ ] **Legacy ADR-013 Proactivity levels.** Decide: promote as per-profile configuration, or reject and keep proactivity encoded as prose in each profile's `CLAUDE.md`. Trigger: when a third profile (beyond `lazy` and `flex`) is added and the difference in autonomy stops fitting in prose.
- [x] **ADR-018 implementation.** Built — `lh doctor` exposes a Features section ([ADR-025](https://github.com/lazynet/lazy-harness/blob/main/specs/adrs/025-doctor-features-section.md)) and `lh config <feature> --init` ships wizards for `memory` and `knowledge` ([ADR-026](https://github.com/lazynet/lazy-harness/blob/main/specs/adrs/026-config-wizards.md)).

## Theme 4 — Framework extensibility

The plugin system (metrics sinks, ADR-004 agent adapters) is the framework's growth surface. The second extension point is chosen: it is not a new plugin kind but the unification of the five that already exist, specified in [ADR-035](https://github.com/lazynet/lazy-harness/blob/main/specs/adrs/035-capability-registry.md). The concrete consumer justifying it is the configuration pane of the TUI, which without a registry would need six separate code paths.

- [x] **Identify the second extension point.** Chosen 2026-08-17 — the capability registry of ADR-035, driven by a real consumer rather than speculative design.
- [x] **Ship the capability registry and migrate the five existing plugin kinds onto it.** Landed 2026-08-17 — `plugins/capabilities.py` holds the registry and `plugins/builtins.py` registers all five kinds (tools, hooks, metrics sinks, agents, LLM backends). The sixth surface, the scheduler backend, is deliberately left out: its selection is a platform probe, not a user-facing activation.
- [ ] Document the extension-point contract. The original trigger — "once two exist in code" — was met and passed: `plugins/builtins.py` registers five kinds against one registry, so the data points the contract was waiting on are already there. What is left is the writing, and it is no longer gated on anything.

## Theme 5 — More than one coding agent

The framework's hook, deploy and transcript layers were all written against a single agent's wire format. Supporting a second one is not a plugin: it is a contract — what a hook may decide, which of those decisions an agent actually honours, and which config documents the agent owns. The design is [`specs/designs/2026-09-13-multi-agent-harness-design.md`](https://github.com/lazynet/lazy-harness/blob/main/specs/designs/2026-09-13-multi-agent-harness-design.md); the decision is [ADR-041](https://github.com/lazynet/lazy-harness/blob/main/specs/adrs/041-multi-agent-hook-contract.md), `accepted` since the freezing gate passed on 2026-09-15.

The contract was **not** frozen until a second, non-identity adapter had run against it — hardening an abstraction against one agent and only then meeting a second reproduces the mistake this theme exists to fix. That gate ran on 2026-09-15 and passed, so the contract is frozen and the items after it are unblocked.

- [x] **Identify harness-owned hooks by canonical name, not command text.** Released in 0.60.0. The classifier matched a path the command generator had stopped emitting, so every harness hook was being read as another tool's; a redeploy after any change in command format would have installed each one twice.
- [x] **Freeze the contract types.** Released in 0.61.0 — `HookEvent`, `HookDecision`, `Verdict`, `HookOutput`, `Operation`, `Signal`, `ConfigArtifact` and `WriteOp` in `agents/base.py`, with the Claude Code adapter implementing them.
- [x] **Make `lh hook <name> --profile <p>` the runner.** Released across 0.62.0 and 0.63.0 — three builtins migrated onto the event contract rather than all eighteen, plus a per-profile transcript reader so a hook asks the adapter for a signal instead of parsing a session file itself.
- [x] **Move config merging behind the adapter.** Released in 0.65.0 — the adapter names the documents it owns and returns merged text; the deploy engine only discovers, reads, plans once per profile, and writes. `lh deploy --profile <name>` lands with it, so a single profile can be deployed without touching the others.
- [x] **Skip — and name — hooks whose declared signals the profile's agent cannot deliver.** Released in 0.67.0. `BuiltinHookSpec.signals` had been inert *for the deploy* — `lh doctor` already read it: `stop-verify-guard` on an agent with no goal marker installed, ran, found nothing to verify and passed, green because it could not fail. The deploy now omits those entries, naming each one in its output before it is an absence in the artifact, and exits 0 rather than aborting. `lh doctor` reports the same signal gaps over the same profiles, from the one rule in `hooks/signal_gaps.py`, and `tests/integration/test_deploy_signal_agreement.py` asserts the two agree in both directions.
- [x] **Run the contract gate against a throwaway second adapter.** Closed 2026-09-15, across 0.66.0 to 0.67.1. A throwaway `CodexAdapter` ran the migrated builtins against a disposable Codex profile, in three runs, and **the pass is composite rather than one green run**. Run 2, on 0.67.0, settled the first three properties through a real `codex exec`: a hook fires, a blocking hook actually refuses, and a hook whose required signal the second agent cannot supply is omitted from the artifact, named in the deploy output and named again by `lh doctor`. It failed on the property the earlier runs never looked at, and run 3 settled that one on the installed 0.67.1 binary rather than a worktree: a hook invoked with `--profile <p>` writes its log line under that profile's directory and nowhere else. Five defects came out of the runs, all of one shape — an answer derived from the global agent where the profile's agent is the source. Three limits are recorded rather than papered over: no single binary has passed all four properties in one run; `stop-verify-guard` writes no log, so the isolation half asserts two builtins and not three; and of the fifteen unmigrated builtins the eight that write a log still leak it, counted on every run as a known gap and tracked to the next item.
- [ ] Migrate the remaining fifteen builtins onto the contract, each declaring the operations it covers and the signals it needs.
- [ ] Make agent selection per profile throughout. Both readers under `deploy/` now resolve it per profile — the global symlink in 0.67.0 and the deploy snapshot alongside it — so the remaining work is the rest of the codebase, which still reads one global setting. The pair moved early because they answer one question between them: a snapshot that resolves the agent differently from the deploy is a rollback that misses an artifact.
- [ ] Ship a real second adapter, replacing the throwaway, with its trust and capability state reported by `lh doctor`.

## Closed themes

- **2026-05 — ADR-018 feature discoverability.** Closed by [ADR-025](https://github.com/lazynet/lazy-harness/blob/main/specs/adrs/025-doctor-features-section.md) (`lh doctor` Features section) and [ADR-026](https://github.com/lazynet/lazy-harness/blob/main/specs/adrs/026-config-wizards.md) (`lh config <feature> --init` wizards). Originally Theme 3, moved here as the implementation landed across the 0.10-0.20 release line.

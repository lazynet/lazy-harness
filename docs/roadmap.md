# Roadmap

Where `lazy-harness` is heading. This is a **curated list of committed themes**, not a wishlist. Items land here only when they are concrete enough to execute and the author intends to do them; exploratory ideas live in the internal backlog instead.

## How to read this document

- Each **theme** groups related work that ships together or builds on a shared mechanism.
- Items are written as short, checkable deliverables. They get ticked off as PRs merge.
- The roadmap is revised whenever a theme closes or when priorities shift. There are no dates — `lazy-harness` is a single-maintainer project and ship-when-ready beats commit-to-a-date.
- Finer-grained work (bugs, nice-to-haves, scratch notes) is not here. It lives in the internal backlog under `specs/backlog.md`.

## Theme 1 — Stability & quality gates

The pre-commit gate defined in [`CLAUDE.md`](https://github.com/lazynet/lazy-harness/blob/main/CLAUDE.md) requires `pytest`, `ruff`, and `mkdocs build --strict` to all pass cleanly. That invariant is the floor every other change builds on.

- [x] Rewrite `tests/unit/test_version.py` to compare `pyproject.toml` and `src/lazy_harness/__init__.py` against each other (no hardcoded expected value).
- [x] Resolve 23 preexisting `ruff check src tests` findings — auto-fix the fixable, justify or exclude the rest.
- [x] Make the pre-commit gate green on `main` and keep it green.
- [ ] Add a GitHub Actions workflow that runs `pytest` and `ruff` on every PR and blocks merge on failure. The docs build is already enforced by [`docs.yml`](https://github.com/lazynet/lazy-harness/blob/main/.github/workflows/docs.yml); pytest and ruff still run locally only.

## Theme 2 — Knowledge pipeline maturity

The compound-loop worker is the framework's memory engine. Two known issues today cause lost learnings — they share an underlying mechanism (per-session delta tracking) and should land together.

- [ ] Implement `★ Insight ─` block extraction as first-class compound-loop output. Spec: [`specs/designs/2026-04-13-compound-loop-insight-capture.md`](https://github.com/lazynet/lazy-harness/blob/main/specs/designs/2026-04-13-compound-loop-insight-capture.md).
- [ ] Fix "learnings lost on long sessions" by tracking `last_insight_message_index` per session and re-scanning only the delta on subsequent Stop hooks.
- [ ] Add a contract test that pins the exact marker characters the `explanatory` output style emits, so a template change forces a visible failure.

## Theme 3 — Open architecture decisions

Decisions the audit surfaced that are waiting on real evidence before being promoted or rejected. Each one has a concrete trigger for revisiting.

- [ ] **Legacy ADR-010 Ollama backend.** Decide: promote to active ADR as a configurable alternative, or reject with a "revisit if cost/rate-limit pressure appears" note. Trigger: if you hit Claude API cost or throttling limits driving compound-loop failures in practice.
- [ ] **Legacy ADR-013 Proactivity levels.** Decide: promote as per-profile configuration, or reject and keep proactivity encoded as prose in each profile's `CLAUDE.md`. Trigger: when a third profile (beyond `lazy` and `flex`) is added and the difference in autonomy stops fitting in prose.
- [x] **ADR-018 implementation.** Built — `lh doctor` exposes a Features section ([ADR-025](https://github.com/lazynet/lazy-harness/blob/main/specs/adrs/025-doctor-features-section.md)) and `lh config <feature> --init` ships wizards for `memory` and `knowledge` ([ADR-026](https://github.com/lazynet/lazy-harness/blob/main/specs/adrs/026-config-wizards.md)).

## Theme 4 — Framework extensibility

The plugin system (metrics sinks, ADR-004 agent adapters) is the framework's growth surface. The next extension point is not yet chosen; the one that ships will inform ADR-018 implementation in Theme 3.

- [ ] Identify and ship the second extension point (candidates: knowledge backend, hook providers, session-export targets). Selection criterion is concrete user need, not speculative design.
- [ ] Document the extension-point contract once two exist in code — three data points beats an abstract spec.

## Closed themes

- **2026-05 — ADR-018 feature discoverability.** Closed by [ADR-025](https://github.com/lazynet/lazy-harness/blob/main/specs/adrs/025-doctor-features-section.md) (`lh doctor` Features section) and [ADR-026](https://github.com/lazynet/lazy-harness/blob/main/specs/adrs/026-config-wizards.md) (`lh config <feature> --init` wizards). Originally Theme 3, moved here as the implementation landed across the 0.10-0.20 release line.

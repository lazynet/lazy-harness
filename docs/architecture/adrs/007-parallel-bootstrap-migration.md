# ADR-007: Parallel-bootstrap migration from the predecessor project

**Status:** accepted
**Date:** 2026-04-12

## Context

`lazy-harness` did not start from a blank repo. It replaces a working personal setup that had been running daily for months: hooks, profiles, knowledge pipeline, monitoring — the whole stack, implemented as a mix of Python modules and bash scripts glued together. Abandoning the old setup to build the new one would have meant weeks without a functioning harness, and the usual result of weeks-without-a-working-system is that you quietly stop using the replacement.

At the same time, we did not want to in-place refactor. The predecessor had accumulated coupling between framework code and personal content (see [ADR-001](001-hybrid-architecture.md)) that could not be teased apart inside the same repository without losing history or breaking paths.

## Decision

**Build the replacement in parallel, in a new repo, and let the old system keep running until each piece of the replacement is proven.**

Four phases, each independently reversible:

1. **Phase 1 — Bootstrap.** New repo, Python package layout, `lh init`, config loader, path resolution, selftest scaffold. No behaviour replicated yet; the old system is untouched.
2. **Phase 2 — Hooks and deploy.** Reimplement the hook engine, port the four built-in hooks (`compound-loop`, `context-inject`, `pre-compact`, `session-export`), and ship the deploy engine that symlinks profiles into the agent's expected location. At the end of this phase, `lh deploy` can produce a working Claude Code setup from scratch.
3. **Phase 3 — Knowledge and QMD.** Port session export, compound-loop worker, and the QMD wrapper. Knowledge directory becomes authoritative; the predecessor stops writing to its own learnings.
4. **Phase 4 — Cutover.** `lh migrate` takes any existing predecessor installation and converts it in-place to a `lazy-harness` installation with full rollback. Predecessor repo gets archived. Framework and public docs get renamed. A soak week follows before the next version bump.

Each phase has an exit criterion that the author can validate on their own machine under real use. No phase is "done" until the old system could be switched off without anyone noticing.

## Alternatives considered

- **Big-bang rewrite.** Rewrite everything, release once. The months-long downtime kills the daily driver during the rewrite, and the replacement has no real-world validation until launch day. High abandonment risk.
- **In-place migration inside the predecessor repo.** Tried briefly in late 2025. Could not draw a clean boundary between framework code and personal content without a fresh `.gitignore` layout and a re-rooted history — at which point it is cheaper to create a new repo.
- **Fork-then-clean.** Fork the old repo, delete the personal content, rename. Loses the clean boundary by construction — personal content is still in history, the framework/dotfile split is muddled, and `uv tool install` cannot cleanly target a fork with vendored personal files.
- **Write `lh migrate` first and use it to bootstrap the new layout.** Chicken-and-egg: the migration engine is non-trivial and testing it requires a working framework. Reversed the order deliberately.

## Consequences

- Two repos live at once for a bounded window (weeks, not months). Each has a clear role.
- Each phase is independently testable and independently releasable. Rollbacks happen at phase granularity, not at the end.
- `lh migrate` exists as a real user-facing command, not as a one-off script the author ran once. Other users with the predecessor installed get the same upgrade path.
- The `docs/history/` and `docs/architecture/decisions/legacy/` trees preserve the predecessor's ADRs and session notes verbatim as archival material. They are intentionally not edited for consistency with the new nomenclature, and they are excluded from the public nav — accessible on the repo but not surfaced in the rendered site.
- After cutover, the predecessor repo is archived and readonly. All new development flows through `lazy-harness`.

# ADR-062: SessionEnd publishes bounded project state

**Status:** proposed
**Date:** 2026-09-19
**Supersedes:** —
**Superseded by:** —
**Related:** ADR-019 (SessionEnd handoff), ADR-021 (response grading)

## Context

SessionEnd currently forces compound-loop evaluation, but successful sessions
never update a PRJ. Only a poor or issue-bearing grade can append one backlog
line, and that path leaves frontmatter `updated` untouched.

## Decision

An optional structured compound-loop result replaces one pre-existing,
generated `## Última sesión` section in the matching PRJ. It never creates a
project or rewrites human-curated sections. `updated` changes only with real
content, and every refusal is a logged fail-soft no-op.

Poor-grade backlog escalation remains independent, gains deduplication and
bumps `updated` when it writes.

## Alternatives considered

Rewriting `Estado actual` gives inferred output too much authority. Appending
every session grows an unbounded second transcript. Relying on the interactive
agent to call a skill before exit cannot cover abrupt or non-Claude sessions.

## Consequences

- PRJ freshness becomes explicit and testable across agents.
- A project must opt in by carrying the generated section.
- Existing oversized PRJs need reviewed archival before rollout.


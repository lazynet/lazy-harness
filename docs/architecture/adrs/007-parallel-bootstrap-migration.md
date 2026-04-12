# ADR-007: Parallel Bootstrap Migration

**Status:** accepted
**Date:** 2026-04-12

## Context

lazy-claudecode is a working personal setup. Migrating to lazy-harness must not break the existing workflow during transition.

## Decision

New repo (lazy-harness) built alongside the old one (lazy-claudecode). Components migrate one at a time. The old system keeps working until each replacement is validated with real use. Four phases: bootstrap, hooks/deploy, knowledge/QMD, cutover.

## Alternatives Considered

- **Big bang rewrite:** Months without a working system. High risk of abandonment.
- **In-place migration:** Messy gitignores, framework and personal content never fully separate.

## Consequences

- Two repos to maintain during transition (weeks, not months).
- Each phase has clear exit criteria and is independently testable.
- No downtime — the old system works until the new one proves itself.

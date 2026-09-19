# ADR-060: AGENTS.md is the portable repository contract

**Status:** proposed
**Date:** 2026-09-19
**Supersedes:** —
**Superseded by:** —
**Related:** ADR-043 (system docs by role), ADR-059 (portable skills)

## Context

Owned repositories treat `CLAUDE.md` as shared while Codex discovers
`AGENTS.md`. Complete copies drift; redirecting `AGENTS.md` to `CLAUDE.md`
makes a runtime-specific surface canonical.

## Decision

Portable repository instructions live in `AGENTS.md`. `CLAUDE.md` imports it
with `@AGENTS.md` and keeps only a Claude-specific appendix. Nested files use
the same sibling relationship.

Migration starts with lazy-harness, lazy-ai-tools and dotfiles. Static
duplicate detection plus live root/nested probes in both agents gate the rest
of the fleet. Profile system documents and skills remain under ADR-043/059.

## Alternatives considered

Keeping `CLAUDE.md` canonical leaks runtime syntax. Generating two complete
files hides the editable source. A symlink is less portable than the documented
import and leaves no clean native appendix.

## Consequences

- Shared rules have one source.
- Agent-only commands remain possible.
- Three manual pilots contain classification risk before automation.


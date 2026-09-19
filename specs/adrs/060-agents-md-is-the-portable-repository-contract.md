# ADR-060: AGENTS.md is the portable repository contract

**Status:** accepted
**Date:** 2026-09-19
**Supersedes:** —
**Superseded by:** —
**Related:** ADR-043 (system docs by role), ADR-059 (portable skills)

## Context

Owned repositories treat `CLAUDE.md` as shared while Codex discovers
`AGENTS.md`. Complete copies drift; redirecting `AGENTS.md` to `CLAUDE.md`
makes a runtime-specific surface canonical.

## Decision

Portable repository instructions live only in `AGENTS.md`. Claude-specific
notes use a labelled conditional section in that file. `CLAUDE.md` is rejected:
on Claude Code 2.1.278 it shadows the direct parent-chain discovery of
`AGENTS.md`, while imports in a parent `CLAUDE.md` are not expanded.

Migration starts with lazy-harness, lazy-ai-tools and dotfiles. Static
duplicate detection plus live root/nested probes in both agents gate the rest
of the fleet. Profile system documents and skills remain under ADR-043/059.

## Alternatives considered

Keeping `CLAUDE.md` canonical leaks runtime syntax. Generating two complete
files hides the editable source. Imports and symlinks both reintroduce a second
runtime-specific surface; labelled conditional sections are visible but keep
one source and preserve nested discovery.

## Consequences

- Shared rules have one source.
- Agent-only commands remain possible as conditional sections.
- Three manual pilots contain classification risk before automation.
- The guarantee covers root and nested sessions. Probes on `2.1.278` show that
  direct `AGENTS.md` reading walks the parent chain, while a `CLAUDE.md` loaded
  from a parent leaves its imports unexpanded. Evidence and the correction:
  [repo-instruction-discovery-evidence.md](../designs/repo-instruction-discovery-evidence.md).

## Status of the pilots

lazy-harness migrated 2026-09-19, with `lh repo instructions` as the static
gate. lazy-ai-tools and dotfiles are pending.

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

- **Evolution (2026-09-22):** an ancestor `CLAUDE.md` or `.claude/CLAUDE.md`
  also stops Claude Code 2.1.280 loading the repository `AGENTS.md`. The
  deploy's `~/.claude -> ~/.claude-<default>` link put one above every
  repository under `$HOME`, so the pilot never reached Claude sessions. Claude
  Code now owns no global link (`default_home()` keeps unprofiled resolution on
  `~/.claude`), and the gate reports `ancestor-claude-md-shadows-agents`.
  Probes: [the rollout plan](../plans/2026-09-22-agent-neutral-instructions-rollout-plan.md) §Phase 0.
- **Evolution (2026-09-22, Phase 2):** the gate takes any number of
  repositories, `lh doctor` runs the ancestor check on `$HOME`, and
  `lh memory rightsize` plus the memory-size hook treat `AGENTS.md` as a
  contract under the same 200-line / 12 KB ceiling as `CLAUDE.md`.
- **Evolution (2026-09-23):** removing the link had a second casualty.
  Claude Code's plugin registries (`plugins/known_marketplaces.json`,
  `plugins/installed_plugins.json`) had recorded paths through
  `~/.claude/plugins/...`, which stopped existing with the link, so every
  plugin failed to load with `cache-miss`. `lh deploy` now repoints such paths
  into the profile and `lh doctor` reports any that dangle (#447).

## Status of the pilots

Wave 1 migrated 2026-09-22: lazy-harness, lazy-ai-tools, dotfiles, lazy-ansible
and lazy-desktop-manager. Each passes `lh repo instructions` and a sentinel
probe from its root and one nested directory in both Claude Code 2.1.280 and
Codex. The seven-working-day window restarts on 2026-09-22, since no earlier
Claude session saw the pilot.

# ADR-059: Portable skills are projected; commands and agents remain native

**Status:** accepted-deferred
**Date:** 2026-09-19
**Supersedes:** —
**Superseded by:** —
**Related:** ADR-043 (system docs by role), ADR-052 (profile assets per agent)

## Context

ADR-052 prevents one agent from receiving another agent's assets by splitting
a profile into `shared/` and `<agent>/` layers. That isolation is correct, but
it does not answer which assets can be authored once and projected into the
native discovery path of several runtimes.

Three superficially similar trees have different contracts:

- skills are `SKILL.md` directories whose content is portable once placed in a
  runtime's discovery root;
- slash commands are a runtime-specific invocation and frontmatter format;
- subagent definitions encode runtime-specific tools, models, and delegation
  semantics.

Codex 0.154.0 was probed in both directions. `codex debug prompt-input` listed
`~/.agents/skills` as a first-class root; adding a throwaway skill made it
appear without restart, and removing it made it disappear. A live run saw the
same catalog. This is measured behaviour, not a documented stability promise,
and `skip_host_skill_discovery` can disable it.

## Decision

### Skills are the only portable asset class

A future adapter capability will declare the native skill discovery directory
for a profile. Deploy will resolve the existing `shared/skills/` and
`<agent>/skills/` layers with ADR-052 precedence, then project the resulting
skill directories into that native root.

Claude Code's root remains `<config_dir>/skills`. Codex's measured root is
`~/.agents/skills` while host discovery is enabled. Copilot declares no root
until an equivalent positive-and-negative probe exists.

The capability is narrow — a skill root, not a generic asset mapping. A generic
mapping would imply that commands and agents are portable when their file
formats alone do not establish compatible behaviour.

### A global root has global collision semantics

Codex's host skill root is shared by every profile. Before writing any link,
deploy must plan all selected Codex profiles together and refuse if two sources
claim the same skill name with different content. First-profile-wins would make
the effective skill depend on deployment order.

The ownership ledger records each projected link. Deploy removes only links it
created and only while they still point into a managed profile source, matching
ADR-052's existing rule. A user-owned entry in `~/.agents/skills` is never
adopted merely because its name collides.

### Commands become skills when their behaviour is portable

A reusable slash command is migrated to a skill rather than copied into every
runtime's command syntax. Commands that rely on a native command channel remain
under `<agent>/commands/`. There is no shared command projection.

### Agent definitions remain agent-specific

Subagent definitions stay under their agent segment. Model routing, tool
permissions, lifecycle, and wire format are part of the definition; translating
the filename while leaving those semantics unresolved would create a portable
looking asset that behaves differently.

## Deferral trigger

The decision is locked, but implementation waits until a profile-owned skill
must run under a non-Claude profile. The current Codex catalog is already
managed directly at `~/.agents/skills`, while current profile-owned skills are
intentionally under `claude-code/skills`; moving either before that trigger
would add a second owner without changing a running profile.

At implementation time the acceptance test must use the installed Codex binary
and `codex debug prompt-input` in both directions: the projected skill appears,
then disappears when its link is removed. It must also exercise two profiles
claiming one global name and prove the deploy refuses before the first write.

If Codex removes host discovery or defaults
`skip_host_skill_discovery = true`, its adapter returns no root and deploy names
the omission. The harness does not silently fall back to an unmeasured path.

## Alternatives considered

### Put every portable asset in `shared/`

Rejected. `shared/` says every agent may receive an asset, not that every agent
understands its schema. That equivalence holds for skills after placement and
does not hold for commands or subagents.

### Link the whole skills directory

Rejected for a global Codex root. It would replace user-owned catalog entries
and make two profiles mutually exclusive. File-level links plus a ledger keep
ownership explicit.

### Treat `~/.agents/skills` as a permanent Codex API

Rejected. The behaviour is probed and version-scoped. The acceptance test and
feature-state check are part of the contract because the upstream surface is
not documented as stable.

## Consequences

- Skills get one portable authoring model without pretending all agent assets
  are interchangeable.
- Existing `claude-code/commands/`, `claude-code/skills/`, and future agent
  definitions remain valid during the deferral.
- Implementation will widen the adapter and deploy planner only for skill
  placement; it will not introduce a general asset translation framework.


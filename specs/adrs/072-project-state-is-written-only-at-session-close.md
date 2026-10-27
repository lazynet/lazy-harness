# ADR-072: Project state is written only by the projects skill at session close

**Status:** accepted
**Date:** 2026-10-26
**Implemented:** 2026-10-26 — `knowledge/project_state.py`, `publish_project_state`,
the name-only PRJ resolver and the `project_update` field of the evaluation
prompt are removed; the worker no longer writes to, or logs about, any PRJ.
**Supersedes:** ADR-062
**Superseded by:** —
**Related:** ADR-019 (SessionEnd handoff), ADR-021 (response grading)

## Context

ADR-062 had the compound-loop worker replace one opt-in generated
`## Última sesión` section in the matching PRJ after every evaluated session.
In the five weeks after it shipped (2026-09-19) that write never ran:

- No PRJ ever carried the generated marker. The vault's backup history has no
  commit containing it, so the write path had nothing to replace.
- The vault's own project contract fixes seven sections and does not include
  `Última sesión`; its template deliberately leaves it out, and the roadmap step
  that would have opted the first project in stayed open.
- The worker resolved a repository to a PRJ by name alone, while the projects
  skill resolves by the PRJ's `repo:` frontmatter first. They disagreed on about
  half the repositories seen in the worker logs, so two codebases gave two
  answers to one question.
- Every evaluation still paid output tokens for a `project_update` object, and
  every session logged a refusal note for the designed opt-out as if it were a
  failure.

## Decision

PRJ state has one writer: the `lazymind-projects` skill, run by the interactive
agent when a session closes. The worker emits no project snapshot and touches no
PRJ. `[compound_loop].lazymind_dir` is still parsed but no longer read.

## Alternatives considered

Adding the section to the vault contract and migrating every PRJ would make the
ADR-062 path run, at the cost of an eighth section overlapping `Estado actual`,
a last-writer-wins snapshot under parallel sessions, and a resolver that still
needed to learn `repo:`. Writing into `Estado actual` was already rejected by
ADR-062 and would give two writers one section.

ADR-062 rejected relying on the interactive agent because it cannot cover abrupt
or non-Claude sessions. That coverage was never delivered: the path wrote
nothing for either. The handoff and decisions the worker still records survive
an abrupt exit for the next session to fold in, and the projects skill is
reachable from Codex as well. A read-only staleness signal — a handoff item when
a session ends in a repository whose PRJ was not touched — remains possible as a
separate change.

## Consequences

- One writer owns PRJ state; the worker's output is the knowledge store only.
- The evaluation prompt is smaller and the worker log loses two notes per
  session.
- A session that ends without running the skill leaves its PRJ stale until the
  next close.

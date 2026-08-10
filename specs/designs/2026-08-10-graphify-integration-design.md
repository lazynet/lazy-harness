# Graphify integration: wire the tool, do not reimplement it

**Status:** accepted
**Date:** 2026-08-10

## Problem

`[knowledge.structure]` has shipped `auto_rebuild_on_commit` since the config
wizard landed. The reference docs state that `lh deploy` installs a per-repo
`post-commit` hook when it is true. No such code exists: the field is written by
the wizard, parsed into the dataclass, and read by nobody.

The observable result is that structure graphs go stale and stay stale. In a
representative install, six repositories out of a hundred-plus had a
`graphify-out/` directory; one held a current `graph.json`, three were frozen at
the date they were first built by hand, one had no `graph.json` at all, and one
was empty. Meanwhile `context_inject` faithfully rendered a staleness banner
that nothing ever acted on.

This is the same failure shape as the hooks that resolved project directories
from `cwd`: a component that reports success while doing nothing.

## Decision

Integrate Graphify's own surface. Do not build a parallel one.

Graphify ships the pieces the harness was about to write:

| Capability | Graphify surface |
|---|---|
| Rebuild from AST, no LLM | `graphify update <path>` |
| Bootstrap a graph, no API key | `graphify extract <path> --code-only` |
| Staleness check, cron-safe | `graphify check-update <path>` |
| Structural queries | `query`, `affected`, `god-nodes`, `explain`, `path` |
| Agent-facing query surface | `graphify-mcp` (MCP server) |

The harness contributes what Graphify cannot know: which profiles exist, where
their agent runtime directories live, and which pinned version is expected.

## Scope

1. **Register `graphify-mcp` per profile.** `lh deploy` already writes MCP
   server entries for the knowledge and memory features into each profile's
   agent config. Graphify becomes a third entry, gated on
   `[knowledge.structure] enabled`.
2. **Delete `auto_rebuild_on_commit`.** Remove the field, its wizard prompt, and
   the three documentation passages that describe the hook it never installed.
   A config key that lies is worse than a missing feature.
3. **Move the pinned version forward.** The pin trailed the released version by
   four minor releases while the installed binary trailed the pin. Pin to the
   version the integration is verified against.

## Non-goals

- **`graphify hook install` is not used.** It resolves the hooks directory with
  `git rev-parse --git-path hooks`, which honours a global `core.hooksPath`.
  Installs that set one — a common pattern for machine-wide commit guards —
  would receive the hook in *every* repository on the machine, including
  read-only third-party clones. Per-repository rebuild automation, if wanted
  later, belongs behind an explicit opt-in list.
- **`graphify claude install` is not used.** It appends a section to the agent's
  system-instruction file. Profiles that generate that file from segments would
  overwrite the section on the next sync. The equivalent guidance belongs in the
  shared segment instead.
- **No rebuild scheduling.** Rebuild stays demand-driven: the agent refreshes
  the graph when a structural question needs it and the graph is stale.

## Consequences

Graph freshness stops depending on a promise the harness never kept and starts
depending on a command that exists. The harness sheds a subsystem it would have
had to maintain against an upstream that moves fast — four minor releases
arrived while the pin sat still.

The MCP surface also removes the reason the tool went unused: querying structure
previously meant loading a very large skill document into context. Ten MCP tools
cost nothing until called.

One limitation carries over. `update` re-extracts code only; graphs whose value
is mostly semantic — documentation corpora, papers — keep nodes that AST
rebuilds cannot refresh. Those repositories need a full extraction to update,
and nothing in this design detects that gap.

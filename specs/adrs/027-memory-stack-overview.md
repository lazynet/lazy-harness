# ADR-027: Memory stack overview — five-layer model

**Status:** accepted
**Date:** 2026-05-03

## Context

ADR-016 added the knowledge directory and optional QMD. ADR-022 added Engram for episodic memory. ADR-023 added Graphify for code-structure memory. ADR-024 added the MCP deploy seam that wires all three into each profile's `settings.json`. Each ADR is correct for its own scope, but no single document explains how the resulting layers fit together at the user level.

The framework now ships three MCP-backed memory services plus two file-based stores (`MEMORY.md` and the `decisions.jsonl` / `failures.jsonl` pair), and the user-facing question — "I want to ask the agent X, which layer answers it?" — has no canonical answer in the repo. The information is scattered across four ADRs, the `_common/CLAUDE.common.md` governance surface in user dotfiles, and the per-tool docs.

This ADR consolidates the model. It does not introduce new mechanism; it names what is already there so future ADRs and `docs/` pages can reference the layer model by name instead of re-deriving it.

## Decision

**Adopt the five-layer memory model below as the canonical user-facing description of agent memory in `lazy-harness`. Reference the layers by their canonical names from this ADR in any future ADR, doc page, wizard prompt, or `lh doctor` output that needs to disambiguate which store is being discussed.**

| Layer | Tool | Storage | Scope | Lifecycle |
|---|---|---|---|---|
| Curated semantic | `MEMORY.md` | `<config_dir>/projects/<slug>/memory/MEMORY.md` | per-project | Stop-hook prompt → user-edited; loaded at SessionStart |
| Distilled episodic | `decisions.jsonl` / `failures.jsonl` | same dir, append-only | per-project | Compound-loop worker writes; surfaced by `context_inject` |
| Raw episodic | Engram (MCP `engram`) | `~/.engram/engram.db` (SQLite + FTS5) | per-project (auto-detected from git remote / cwd) | Agent-driven via MCP `save` / `search` / `timeline` |
| Searchable semantic | QMD (MCP `qmd`) | `~/.cache/qmd/index.sqlite` (BM25 + vectors + AST chunks) | per-collection (configured in `~/.config/qmd/index.yml`) | Scheduled `lh knowledge sync` / `embed` |
| Structural | Graphify (MCP `graphify`) | `<repo>/graphify-out/graph.json` | per-repo (commitable, multi-repo via `merge-graphs`) | Manual `/graphify` rebuild or optional `auto_rebuild_on_commit` |

The five layers map cleanly to three distinct memory archetypes from the literature:

- **Episodic** (what happened): "Distilled episodic" + "Raw episodic". Two layers because the distilled file is human-readable and portable; the raw store is agent-rich and queryable.
- **Semantic** (what we know): "Curated semantic" + "Searchable semantic". Two layers because curated is per-project governance and searchable is global recall over the vault.
- **Procedural / structural** (how the code is shaped): "Structural" only. Code structure is not memory of an event; it is a navigable index of artifacts.

User-facing rule: pick the layer first, then the tool. The `_common/CLAUDE.common.md` table is the default trigger for that selection at session-start time.

## Alternatives considered

- **Collapse "Curated" and "Distilled" into one layer.** Both live in the same directory and both are human-revisable, but they have different write paths: `MEMORY.md` is consolidated by the user once a session under prompting, while the JSONL files are continuously appended by an automated worker. Merging them would either lose the append-only contract or pollute a 200-line budget with raw events.
- **Collapse Engram into the JSONL pair.** The ADR-022 alternatives section already rejected this; reaffirmed here because the layer model would otherwise hide why two episodic stores coexist. Engram is the agent's working memory; the JSONLs are the historical archive.
- **One global layer instead of separating per-project from per-collection.** Conflates blast radius. Per-project memory is automatically scoped by the agent's CWD and travels with the project; per-collection memory is intentionally global and triangulates across collections. Treating them the same would force users to re-decide scope each query.
- **Defer documenting the model until first user confusion.** Already happened — the in-session question that triggered this ADR was "where does each memory live and how do I use them across agents". Writing it down now prevents the same question from recurring across sessions.

## Consequences

- Future ADRs and `docs/` pages reference layers by name (e.g. "the curated semantic layer", "the structural layer") instead of by tool. That keeps the user model stable when a tool is replaced — `[knowledge.structure].engine` already anticipates a non-Graphify backend, and `[memory]` is a thin wrapper for the same reason.
- `lh doctor` and the `lh config <feature> --init` wizards (ADR-025, ADR-026) can group their output by layer. Today they list tools; the layer view is one rendering step away.
- The `_common/CLAUDE.common.md` Memoria section in user dotfiles becomes the canonical user-facing copy of the table. The ADR is the contributor view (the "why"); the dotfile section is the agent-loaded view (the "what to do at run time").
- Adding a sixth layer (e.g. agent-shared cross-machine memory, or a procedural runbook store) becomes a new ADR that supersedes nothing and registers itself in the same table. The table is open for extension.
- Removing a layer requires explicit ADR — no quiet deletions. This is the same contract the existing ADRs already give for individual tools; the layer model just makes the surface explicit.
- Public `docs/architecture/` does not gain a new page in this ADR. If a future contributor needs a public-site view of the model, the source of truth is this ADR; a docs page can render it without re-deriving.

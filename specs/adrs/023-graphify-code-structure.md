# ADR-023: Graphify as optional code-structure index

**Status:** accepted
**Date:** 2026-05-03

## Context

The harness covers semantic memory (QMD, ADR-016) and episodic memory (Engram, ADR-022) but does not capture the third memory layer flagged in the literature review: code-structure or procedural memory. For multi-repo solutions where a single product spans tens of repositories, the agent has no compact way to ask "where does function X live, what calls it, and which file is the central node of this subsystem".

Graphify (https://github.com/safishamsi/graphify) is a tree-sitter based knowledge-graph builder for code, supporting 25 languages. It runs the AST extraction locally (no API cost), produces queryable JSON + interactive HTML + a markdown report, and exposes an MCP server for natural-language graph queries from the agent. Multi-repo workflows are first-class via `graphify merge-graphs` and the convention of committing the `graphify-out/` directory per repo so teammates reuse the index without re-building.

Graphify is the third tool converging on the harness's MCP deploy seam (ADR-024); together with QMD (ADR-016, semantic) and Engram (ADR-022, episodic), it covers the structural layer.

## Decision

**Add `src/lazy_harness/knowledge/graphify.py` as a thin CLI wrapper, gated behind `shutil.which("graphify")` and a config opt-in (`[knowledge.structure].enabled = true`). Wire it into the existing MCP deploy collector so `lh deploy` ships a `graphify` entry to each profile's `settings.json` when both gates are open. Pin Graphify to version `0.6.9` in config; `check_version()` exposes the comparison for `lh doctor` to use later.**

Concretely:

- `src/lazy_harness/knowledge/graphify.py` — `is_graphify_available()`, `_build_command(action, target=None)`, `run_graphify(action, target=None, timeout=600)`, `mcp_server_config()` returning `{"command": "graphify", "args": ["mcp"]}`, `check_version()` returning `(matches, current_version)`. Module-level `PINNED_VERSION = "0.6.9"` constant. Default timeout is 600s because graph builds on large repos can take minutes.
- `src/lazy_harness/core/config.py` — new `KnowledgeStructureConfig` dataclass (`engine` defaulting to `"graphify"`, `enabled`, `auto_rebuild_on_commit`, `version` with `0.6.9` default), added as a `structure` field on `KnowledgeConfig`. Parsed inline by `load_config` next to the existing `search` sub-table.
- `src/lazy_harness/deploy/engine.py` — `_collect_mcp_servers(cfg)` extends with `if cfg.knowledge.structure.enabled and graphify.is_graphify_available(): servers["graphify"] = graphify.mcp_server_config()`.
- The `auto_rebuild_on_commit` flag is exposed but no code branches on it in this PR. Graphify's own `graphify hook install` writes a git `post-commit` hook directly into `.git/hooks/`; wiring that from `lh deploy` is deferred to the Fase 3 ADR.
- The `engine` field on `KnowledgeStructureConfig` exists so a future structural backend (e.g. a ctags-based or Sourcegraph-style alternative) can plug into the same seam without breaking the namespace.

## Alternatives considered

- **Build the graph inside the harness with our own tree-sitter wrapper.** Reinvents an actively maintained tool that already supports 25 languages. Rejected on maintenance grounds.
- **Make Graphify a hard dependency.** Breaks the optionality contract from ADR-016. Same `shutil.which` gate keeps the framework installable without it.
- **Auto-install Graphify or auto-install the post-commit hook on `lh init`.** Out of scope. Per the user-confirmed plan, the wizard prints the install command but does not run it. The hook install is a separate opt-in (`auto_rebuild_on_commit = true` plus a future `lh deploy` step).
- **Place Graphify under `memory/` next to Engram.** Rejected. Graphify indexes code structure, not agent activity. It belongs next to QMD under `knowledge/` because both answer "what do we know about this codebase / domain", just at different layers.
- **Invoke MCP via `python -m graphify.serve` instead of `graphify mcp`.** The Python module form requires the right Python on PATH; the CLI form is symmetric with QMD and Engram and matches the conventional MCP pattern. If a future Graphify release breaks `graphify mcp`, the canonical command can be exposed as a config override in a follow-up ADR.

## Consequences

- A user who installs Graphify (`pip install graphify` or equivalent) and sets `[knowledge.structure].enabled = true` gets the `graphify` MCP server wired into every profile on the next `lh deploy`. Removing Graphify and re-running `lh deploy` removes the entry on the next merge — `_collect_mcp_servers` rebuilds the dict from scratch each call.
- Pinning the version in config (`version = "0.6.9"`) gives `lh doctor` (future ADR) a single source of truth for compatibility checks. `check_version()` returns the tuple it needs.
- For multi-repo solutions, the convention is to commit `graphify-out/` per repo and use `graphify merge-graphs *.json` to query across repos. The harness does not orchestrate the merge — that lives at the repo level.
- The post-commit auto-rebuild hook (Graphify's `graphify hook install`) is intentionally not wired from `lh deploy` in this PR. Doing so is a Fase 3 concern that needs its own design — `lh deploy` writing to `.git/hooks/` of arbitrary repos is a different blast radius from writing to `~/.claude-<profile>/settings.json`.
- The `[knowledge.structure]` namespace mirrors `[knowledge.search]`. Both are sub-tables of `[knowledge]` because both answer "what do we know about this codebase". Episodic memory stays under `[memory]` because it is a different concept (what the agent did, not what we know).

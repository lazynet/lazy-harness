# ADR-024: MCP server orchestration via `lh deploy`

**Status:** accepted
**Date:** 2026-05-03

## Context

The harness already detects optional knowledge tools (QMD) and gates them behind `shutil.which` (ADR-016). What it did not do until now was **deploy** those tools to the agent — the user still had to hand-edit `~/.claude/settings.json` to declare an `mcpServers` block.

Three tools are converging on the MCP standard for agent-side memory and knowledge:

- **QMD** (already wired as the optional semantic indexer in ADR-016) exposes an MCP server for hybrid BM25 + vector + rerank queries against the knowledge directory.
- **Engram** (planned as ADR-022) provides episodic memory with an MCP server that the agent invokes to save and recall what it did.
- **Graphify** (planned as ADR-023) exposes code-structure queries over a tree-sitter graph through its own MCP server.

Without a single seam in the deploy pipeline, every new MCP tool would force the user to edit profile settings by hand and remember to keep the entry in sync with what is actually installed.

## Decision

**Extend the `AgentAdapter` Protocol with `generate_mcp_config(servers) -> dict`. Each tool wrapper exposes a `mcp_server_config()` returning a declarative entry. `deploy/engine.py` adds `deploy_mcp_servers(cfg)` which probes detected tools, asks the active adapter to format the block, and merges it into each profile's `settings.json` next to the existing `hooks` block. `lh deploy` invokes it after `deploy_hooks`.**

Concretely:

- `src/lazy_harness/agents/base.py` — Protocol gains `generate_mcp_config(self, servers: dict[str, dict]) -> dict`. The canonical shape of an entry is `{"command": str, "args": list[str], "env": dict[str, str] | None}`.
- `src/lazy_harness/agents/claude_code.py` — `ClaudeCodeAdapter.generate_mcp_config` returns `{"mcpServers": {<name>: <normalized-entry>}}` ready to merge into `settings.json`.
- `src/lazy_harness/knowledge/qmd.py` — `mcp_server_config()` returns `{"command": "qmd", "args": ["mcp"]}`. Future tool wrappers expose the same function.
- `src/lazy_harness/deploy/engine.py` — `_collect_mcp_servers(cfg)` probes each tool's `is_<tool>_available()`. `deploy_mcp_servers(cfg)` writes the result to each profile's `settings.json`, preserving the existing `hooks` block.
- `src/lazy_harness/cli/deploy_cmd.py` — calls `deploy_mcp_servers(cfg)` between hooks and the `~/.claude` symlink. The CLI handler is split into a thin Click wrapper plus a `_run_deploy(cfg)` helper so the orchestration is testable without a real config file.

## Alternatives considered

- **Hand-edited `mcpServers` in profile templates.** Reproducible until a tool is uninstalled — the entry stays, the agent fails to start the missing server, and the user has to remember to clean up. Rejected because the install-uninstall cycle has no obvious trigger to keep the file in sync.
- **A dedicated `lh mcp` subcommand.** Splits the surface unnecessarily; users would have to remember to run it after every install. Folding it into `lh deploy` keeps one command as the source of truth, mirroring how `deploy_hooks` already works.
- **Generate a separate `mcp.json` per agent.** Some agents support standalone files, but Claude Code reads `mcpServers` from `settings.json`. One file is simpler and keeps merge semantics localized.
- **Auto-install missing tools from the wizard.** Out of scope for this ADR. Detection-only matches the ADR-016 pattern: the harness reports what it found and degrades to a no-op for what it did not.

## Consequences

- New tools that want to ship as MCP servers expose `mcp_server_config()` plus a `is_<tool>_available()` probe — same shape as the QMD precedent. No new abstraction required for ADR-022 and ADR-023.
- Adapters for new agents (Codex, Gemini CLI, Copilot) implement `generate_mcp_config` to translate the canonical dict into their native format. The Protocol is the contract; today only `ClaudeCodeAdapter` exists.
- `lh deploy` is now responsible for both hooks and MCP. The two share the `settings.json` merge logic, which keeps idempotency invariant: re-running deploy converges on the same state regardless of starting state.
- Removing a tool and re-running `lh deploy` removes its entry on the next merge — `_collect_mcp_servers` rebuilds the dict from scratch each call, so stale entries do not survive.
- The harness still does not write any MCP entry for tools that are not installed. The probe is the source of truth, not a config flag — consistent with ADR-016.
- The `_run_deploy(cfg)` extraction keeps `deploy_cmd.py` testable without `CliRunner` end-to-end fixtures. Future deploy steps slot into the same helper.

# Memory model

Claude Code has one memory primitive: the `CLAUDE.md` file, loaded at session start as static context. `lazy-harness` adds **five more layers** on top of that, sourced from a mix of files written by the framework and external tools that the harness orchestrates when present. Together they produce three classic memory archetypes — episodic, semantic, and structural — across short and long time horizons.

The canonical model is described in [ADR-027](https://github.com/lazynet/lazy-harness/blob/main/specs/adrs/027-memory-stack-overview.md). This page is the user-facing view.

## The five layers

| Layer | Backend | Provided by | What it answers |
|---|---|---|---|
| **Curated semantic** | `MEMORY.md` (file, ≤ 200 lines) | shipped — `<config_dir>/projects/<slug>/memory/` | "What rules and patterns govern this project?" |
| **Distilled episodic** | `decisions.jsonl` / `failures.jsonl` (append-only) | shipped — written by the compound-loop worker | "What did we decide? What broke and why?" |
| **Raw episodic** | [Engram](https://github.com/Gentleman-Programming/engram) — SQLite + FTS5, MCP server | external CLI, auto-wired when installed | "What did we do in this project last week, and when?" |
| **Searchable semantic** | [QMD](https://github.com/tobi/qmd) — BM25 + vectors, MCP server | external CLI, auto-wired when installed | "Where did I see this pattern across all my notes and repos?" |
| **Structural** | [Graphify](https://github.com/safishamsi/graphify) — tree-sitter call graph (`graphify-out/graph.json`) | external CLI, detected and exposed via `lh doctor` and the `/graphify` skill | "What calls X? What does this module look like?" |

The two file-based layers ship inside the framework. The three external tools are detected by `lh doctor` and, where applicable, wired into every profile's `mcpServers` block automatically by the deploy engine ([ADR-024](https://github.com/lazynet/lazy-harness/blob/main/specs/adrs/024-mcp-server-orchestration.md)) — you install them once, the agent picks them up.

## Episodic — what happened

Two layers, because the distilled file is human-readable and portable while the raw store is agent-rich and queryable. They coexist by design: each answers a different shape of question.

### Distilled episodic — `decisions.jsonl` / `failures.jsonl`

Structured, append-only JSONL files capture:

- **Decisions:** what was decided, alternatives considered, rationale, timestamp.
- **Failures:** what broke, root cause, prevention, topic.

These are the history the agent can `grep` directly. When you ask "why did we pick X over Y three weeks ago?", it does not need to remember — it reads the file. The `compound-loop` hook extracts entries automatically at session end, with heuristics to filter out trivial sessions.

Both files are append-only and human-friendly. Treat them as the durable distilled record that travels with the project.

### Raw episodic — Engram

Engram is an external MCP server that stores per-project episodic memory in a local SQLite database with FTS5 full-text search. The agent calls it directly — `mem_save` to record an observation, `mem_search` to recall, `mem_timeline` to walk a session window, `mem_context` to load recent activity.

Where the JSONL pair holds the **distilled** record (decisions, failures, learnings — the things worth keeping forever), Engram holds the **raw** record (every save the agent thought was worth flagging during the session). The two coexist because they answer different questions: "what was the rationale behind decision X?" reads JSONL; "what were we exploring two days ago in this repo?" calls Engram.

When Engram is not installed the layer is simply absent — the rest of the stack carries on unchanged.

## Semantic — what we know

Two layers again: curated content the user authors deliberately, and searchable content that grows with use.

### Curated semantic — `MEMORY.md`

Every project gets a `MEMORY.md` file at `<config_dir>/projects/<project-slug>/memory/MEMORY.md`. It is an index: one line per persistent fact, each line linking to a memory file with frontmatter and a body. Facts are typed (`user`, `feedback`, `project`, `reference`) and updated as Claude learns them during sessions.

Unlike `CLAUDE.md` (static, human-authored), `MEMORY.md` is written by the agent. It is the agent's own notepad about what it has learned about you and the project. The file is capped at 200 lines because it is loaded into every session-start context — anything larger gets truncated, so consolidation is part of the contract.

### Searchable semantic — knowledge directory + QMD

A single filesystem directory (`~/Documents/lazy-harness-knowledge` by default, configurable) contains:

- `sessions/` — exported session transcripts (clean markdown with frontmatter).
- `learnings/` — distilled weekly reviews and cross-session patterns.
- Anything else you drop there.

This is the union of everything the harness has learned across every project and every profile. Without QMD, it is a plain markdown tree you can `rg`, edit and back up. With [QMD](https://github.com/tobi/qmd) installed, `lazy-harness` configures a collection pointing at the directory and the agent gains semantic recall over the whole archive — "when did I last debug a circular import in Python?" returns the specific session from six months ago.

QMD is opt-in: install the binary, run `lh knowledge sync` once, and the search layer wakes up. Without it the rest of the pipeline still works — exports keep happening, learnings still accumulate; only cross-session semantic search is missing.

## Structural — how the code is shaped

One layer, because code structure is not memory of an event — it is a navigable index of artifacts.

### Graphify

[Graphify](https://github.com/safishamsi/graphify) is a tree-sitter based knowledge-graph builder for code, supporting 25 languages. It runs AST extraction locally (no API cost) and produces a queryable JSON graph plus an interactive HTML report under `graphify-out/` per repo. The directory is meant to be committed so teammates reuse the index without rebuilding.

The harness detects Graphify via `lh doctor` and exposes the `/graphify` skill so any session can rebuild or query the graph. The agent uses it for "what calls this function?", "explain this module", or "show me the dependency neighbourhood of X" without the agent having to read every file end-to-end.

If Graphify is not installed the layer is absent — agent navigation falls back to grep.

## Session-level mechanics

These are the hooks that move data into and out of the layers above.

### Session-start context injection

The `context-inject` hook runs when Claude Code starts a session. It gathers:

- Git state (current branch, dirty files, last commit).
- Project info (name, type, recent activity).
- The tail of the project's `MEMORY.md` and the last handoff note.
- "Last session" summary line (timestamp, message count, topic).

This is injected as additional context alongside your first user message, so the agent starts every session already knowing where you left off.

### Pre-compact summaries

When Claude Code approaches its context window limit it compacts old messages into a summary before dropping them. The default compaction is a generic LLM summary; the `pre-compact` hook intercepts that moment and extracts a structured summary (decisions made, files touched, open questions) that is persisted to the project's session export. The raw conversation is lost; the distilled intent is not.

### Session export

Every interactive session that crosses a message threshold gets exported to `sessions/YYYY-MM-DD-<session-id>.md` — a clean transcript with frontmatter (topic, tools used, duration, cost). These exports live in the knowledge directory and feed the searchable semantic layer.

## How the layers compose

A new session starts:

1. **Short-horizon fills:** the `context-inject` hook pulls `MEMORY.md`, the last handoff and recent JSONL entries into the first prompt.
2. **Medium-horizon is queryable on demand:** the agent reads `decisions.jsonl` / `failures.jsonl` directly when the task calls for it, or queries Engram for richer episodic context.
3. **Long-horizon is queryable on demand:** for unfamiliar territory the agent reaches into QMD across the entire knowledge directory, or into Graphify for code shape.

Every session also **produces** memory: exports flow into the knowledge directory, decisions and failures are appended to JSONL, `MEMORY.md` is updated by the agent, and Engram captures raw episodic state. The loop closes on every session boundary.

## What this means in practice

Without `lazy-harness`, the typical session pattern is:

> "Hey Claude, remember we decided X last week? No, not that, the other one. OK, the context is..."

With it:

> "Continue."

That is the goal of the memory model.

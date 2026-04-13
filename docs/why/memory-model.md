# Memory model

Claude Code has a memory primitive: the `CLAUDE.md` file. It is loaded at session start and provides static context. That is one layer of memory. `lazy-harness` adds five more, arranged across three temporal scales.

## Three scales

| Scale | Question it answers | Mechanism |
|---|---|---|
| **Short-term** — within a single session | "What is this specific session about right now?" | `CLAUDE.md`, session-start context injection, pre-compact summaries |
| **Medium-term** — across sessions in the same project | "What did I decide last time? What broke last month?" | `MEMORY.md`, `decisions.jsonl`, `failures.jsonl`, session export |
| **Long-term** — across projects, semantic | "Where did I see this pattern before? What did I learn in 2024 about X?" | Knowledge directory, QMD semantic index, distilled learnings |

## Short-term: within a session

### Session-start context injection

The `context-inject` hook runs when Claude Code starts a session. It gathers:
- Git state (current branch, dirty files, last commit)
- Project info (name, type, recent activity)
- The tail of the project's `MEMORY.md` and the last handoff note
- "Last session" summary line (timestamp, message count, topic)

This is injected as additional context alongside your first user message, so the agent starts every session already knowing where you left off. Before lazy-harness, the first 5 minutes of every session were context reconstruction. After, they are work.

### Pre-compact summaries

When Claude Code approaches its context window limit, it compacts old messages into a summary before dropping them. The default compaction is a generic LLM summary. lazy-harness's `pre-compact` hook intercepts that moment and extracts a structured summary (decisions made, files touched, open questions) that is persisted to the project's session export. The raw conversation is lost; the distilled intent is not.

## Medium-term: across sessions, same project

### `MEMORY.md` — self-maintained project memory

Every project gets a `MEMORY.md` file at `~/.claude-<profile>/projects/<project-slug>/memory/MEMORY.md`. It is an index: one line per persistent fact, each line linking to a memory file with frontmatter and a body. Facts are typed (`user`, `feedback`, `project`, `reference`) and are updated as Claude learns them during sessions.

Unlike `CLAUDE.md` (static, human-authored), `MEMORY.md` is written by Claude. It is the agent's own notepad about what it has learned about you and the project.

### Episodic memory: `decisions.jsonl` and `failures.jsonl`

Structured, append-only JSONL files that capture:
- **Decisions:** what was decided, alternatives considered, rationale, timestamp
- **Failures:** what broke, root cause, prevention, topic

These are the history the agent can grep. When you ask "why did we pick X over Y three weeks ago?", the agent doesn't have to remember; it can read it.

The `compound-loop` hook extracts these entries automatically at session end, with heuristics to filter out trivial sessions.

### Session export

Every interactive session that crosses a message threshold gets exported to `sessions/YYYY-MM-DD-<session-id>.md` — a clean transcript with frontmatter (topic, tools used, duration, cost). These exports live in the knowledge directory and can be indexed semantically.

## Long-term: across projects, semantic

### Knowledge directory

A single filesystem directory (`~/Documents/lazy-harness-knowledge` by default, configurable) contains:
- `sessions/` — exported session transcripts
- `learnings/` — distilled weekly reviews and cross-session patterns
- Anything else you drop there

This is the union of everything the harness has learned across every project, every profile.

### QMD indexing

If you have [QMD](https://github.com/lazynet/qmd) installed, `lazy-harness` configures a collection pointing at the knowledge directory. QMD indexes markdown semantically and exposes a `recall` command that works across your entire history.

The critical affordance: you can ask "when did I last debug a circular import in Python?" and get back the specific session from six months ago. The short-term memory model is stateless by design; the long-term one is where the lessons accumulate.

## How the scales compose

A new session starts:

1. **Short-term fills:** the `context-inject` hook pulls `MEMORY.md`, the last handoff, and git state.
2. **Medium-term is queryable:** Claude can read `decisions.jsonl` and `failures.jsonl` if the task warrants it.
3. **Long-term is queryable:** if the task touches unfamiliar territory, Claude can `qmd query` against the knowledge directory.

Every session also **produces** memory: exports go to knowledge, decisions/failures are appended, `MEMORY.md` is updated by the agent. The loop closes.

## What this means in practice

Before lazy-harness, my typical session pattern was:
> "Hey Claude, remember we decided X last week? No, not that, the other one. OK, the context is..."

After lazy-harness:
> "Continue."

That is the goal of the memory model.

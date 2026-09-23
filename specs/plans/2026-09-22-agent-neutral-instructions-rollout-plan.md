# Agent-Neutral Instructions Rollout Plan

**Goal:** Every instruction the operator writes — profile system documents and
repository contracts — reads correctly for any coding agent (Claude Code,
Codex, or the next one). Runtime-specific rules live only in labelled
runtime sections.

**Spec:** [ADR-060](../adrs/060-agents-md-is-the-portable-repository-contract.md),
[portable repository instructions design](../designs/2026-09-19-portable-repository-instructions-design.md),
ADR-043 (system docs by role).

**Out of scope (postponed 2026-09-22):** `~/repos/flex/*` repositories
(including the `ydi-data-layer` `CLAUDE.md -> AGENTS.md` symlink) and a Codex
variant of the `flex` profile. ADR-059 skill projection stays its own lane.

## Phase 0 — Blocker found 2026-09-22: an ancestor `CLAUDE.md` disables `AGENTS.md`

Claude Code 2.1.280 stops loading a repository's `AGENTS.md` when **any**
ancestor directory carries `CLAUDE.md` or `.claude/CLAUDE.md`. `lh deploy` links
`~/.claude -> ~/.claude-lazy` (20 Sep 11:05), which holds the profile's
`CLAUDE.md`, so under `CLAUDE_CONFIG_DIR=~/.claude-<profile>` every repository below
`$HOME` loses its `AGENTS.md` — lazy-harness included. Codex is unaffected.

Sentinel probes (`claude -p`, file tools disallowed):

| Fixture | cwd | Result |
|---|---|---|
| `AGENTS.md` only, outside `$HOME` | root | sentinel |
| same content, under `~/repos/lazy/` | root | `NONE` |
| same content, under `~/` | root | `NONE` |
| scratch `parent/.claude/CLAUDE.md` + `parent/repo/AGENTS.md` | root, `sub/` | `NONE`, `NONE` |
| scratch `parent/CLAUDE.md` + `parent/repo/AGENTS.md` | root | `NONE` |
| lazy-harness, lazy-ai-tools (migrated) | root, nested | `NONE` |

Consequences: the ADR-060 pilot has not reached Claude sessions since at least
2026-09-20, so the seven-day window has no valid Claude observation yet; and
`lh repo instructions` checks only inside the repository, so it cannot see the
cause. Fix: stop projecting `CLAUDE.md` into `~/.claude/`, and extend the gate
with an ancestor-chain check.

**Resolved 2026-09-22:** the operator removed the link, `ClaudeCodeAdapter`
owns none (`default_home()` keeps unprofiled resolution on `~/.claude`), and
the gate reports `ancestor-claude-md-shadows-agents`. It also stopped walking
nested checkouts (`.claude/worktrees/*`), which had flagged another branch's
`CLAUDE.md`.

## Phase 1 — Neutral `_common/common.md`

`profiles/_common/common.md` is concatenated into every profile's system
document, whatever the agent. It still carries Claude Code-only facts:

| Line (2026-09-22) | Content | Destination |
|---|---|---|
| chezmoi section | `claude.common` / `post-tool-use-sync-system-doc` hook example | stays, reworded as harness-level (the hook is the harness's, not the agent's) |
| Gotchas | permission rules match string prefixes | `_common/claude-code.md` |
| Memory table | curated memory = `MEMORY.md` under `~/.claude-<profile>/` | stale: the store is `lazy-knowledge/memory/...` (`lh memory status`); the native auto-memory note moved to `claude-code.md` |
| Memory bullets | `context_inject` loads MEMORY.md at session start | stays: `lazy-codex` runs `context-inject` too |
| chezmoi section | `claude.common` no longer exists | renamed to `_common/*.md` |

**Done when:** the regenerated `lazy-codex` `AGENTS.md` names no Claude Code
tool, path or setting outside a section addressed to Claude Code, and the
`lazy` and `flex` `CLAUDE.md` lost no rule (diff shows moves only).
Done 2026-09-22 (dotfiles `0774823`).

## Phase 2 — Gate every migrated repository

`lh repo instructions` already runs in lazy-harness CI through
`tests/docs/test_repo_instructions_gate.py` inside `pytest`. The Wave 1
repositories have no CI, so the gate runs from the operator's side:

- `lh repo instructions` takes any number of repositories, and the
  `audit-harness` skill runs it over every repo under `~/repos/lazy/` with a
  root `AGENTS.md`, listing the `CLAUDE.md`-only ones as the next wave's queue;
- `lh doctor` runs the ancestor check on `$HOME`, so a machine that still
  carries the legacy `~/.claude` link fails there even if no gate runs;
- `lh memory rightsize` and the memory-size hook measure `AGENTS.md`
  contracts, including a Codex profile's system doc;
- each migrated repository names the gate in its own `AGENTS.md`.

Done 2026-09-22. Measuring `AGENTS.md` surfaced four contracts over the ceiling:
the `lazy-codex` system doc (229 lines / 12.7 KB), `lazy` and `flex` (204 / 202,
pushed over by Phase 1), and the `AGENTS.md` of lazy-desktop-manager and
lazy-harness. The system docs now share one `tail.md` for `lazy`/`lazy-codex`,
keep the chezmoi procedure and Codex runtime facts in conditional docs under
`profiles/_common/docs/`, and cite every conditional doc by absolute path —
Codex never had the `docs/` link the old relative paths assumed.

## Phase 3 — Wave 1 (manual)

| Repository | State 2026-09-22 |
|---|---|
| lazy-harness | migrated 2026-09-19; Claude probe passes only after Phase 0 |
| lazy-ai-tools | migrated 2026-09-22 |
| dotfiles | migrated 2026-09-22; `.chezmoiignore` also excludes `AGENTS.md` |
| lazy-ansible | migrated 2026-09-22 |
| lazy-desktop-manager | migrated 2026-09-22 |

Probes after Phase 0: every repository answers its own `# AGENTS.md — <repo>`
heading from the root and one nested directory, in both agents.

Per repository, the design's migration algorithm:

1. classify each line as portable, Claude-only, obsolete or local;
2. `git mv CLAUDE.md AGENTS.md`, so history follows the file;
3. move Claude-only lines into `## When the agent is Claude Code`, and add a
   Codex section only for measured Codex facts;
4. `lh repo instructions <repo>` returns zero findings;
5. probe root and one nested directory in both `claude -p` and `codex exec`
   for a sentinel sentence, recording the result in the commit body;
6. run the repository's existing verification before committing.

## Phase 4 — Wave 2 (after the window)

The seven-working-day window opens when the last Wave 1 repository lands.
It closes with no `CLAUDE.md` restored in any Wave 1 repository (gate output
from Phase 2). Wave 2 then covers lazent, lazy-everythingapp, lazy-finance,
lazy-hamradio, lazy-hermes, lazy-popopen and the LazyMind vault, whose
`CLAUDE.md` governs lazy-ai-tools' article processing. lazy-bookreader already carries
only `AGENTS.md`. JimsGarage, lazy-knowledge and lazynet.github.io carry
neither file and are inventoried only.

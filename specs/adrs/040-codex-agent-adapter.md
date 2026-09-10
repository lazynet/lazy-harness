# ADR-040: Codex as a second agent — agents become plural per profile

**Status:** proposed
**Date:** 2026-09-09
**Design:** [`specs/designs/2026-09-09-codex-agent-adapter-design.md`](../designs/2026-09-09-codex-agent-adapter-design.md)
**Supersedes:** —
**Superseded by:** —
**Related:** ADR-004 (agent-adapter-pattern), ADR-032 (agent-adapter-completeness),
ADR-009 (profile-symlink-deploy), ADR-031 (default-hooks-merge),
ADR-035 (capability-registry), ADR-039 (role-routed-inference)

## Context

ADR-004 built the agent seam and promised that a second agent would cost "one new file, one registry entry, zero changes elsewhere." ADR-032 closed seven leaks so the promise would hold. ADR-039 then made the *inference* axis pluggable and explicitly deferred the *agent* axis: "A second agent adapter (Codex, Gemini CLI) in the same change. Out of scope."

This is that change, and attempting it finds three things neither prior ADR anticipated.

**The config has no way to say "both."** `[agent].type` is one global string and `ProfileEntry.config_dir` is one path. The schema encodes one agent per profile, so `lh deploy` writes for exactly one and `lh run` launches exactly one. Running Claude Code and Codex side by side — the actual requirement — has no representation.

**Hook deployment is Claude-shaped outside the adapter.** `deploy/engine.py:200-241` hardcodes the filename `settings.json`, `json.loads` and `json.dumps`. Codex reads `[[hooks.<Event>]]` from `$CODEX_HOME/config.toml`, a file it also shares with `[mcp_servers.*]`. None of the filename, parser or serializer is reachable from an adapter. Call it **L8**, unlisted by ADR-032.

**The built-in hooks speak Claude's tool vocabulary.** Three hooks branch on literal tool names — `Read`, `Edit`, `Write`, `Bash`, `NotebookEdit` — read from the payload's `tool_name`. Codex reports `apply_patch` for a file edit. Deployed as-is, `post_tool_use_format` matches nothing and exits 0, and `pre_tool_use_security` falls through every branch and **allows everything**, while `lh doctor` reports both ON. Call it **L9**. It is the more important of the two, because L8 fails loudly and L9 fails green.

A constraint shapes what this ADR can honestly decide: **Codex is not installed on the development machine.** The event names, hook payload fields, config table shapes and tool-name vocabulary below come from published documentation, not from a captured payload. The design document enumerates all eleven as A1–A11 with the consequence of each being wrong.

## Decision

**A profile declares a config directory per agent; the adapter owns its settings file end to end; and the built-in hooks match a canonical tool vocabulary the adapter translates into.**

### Agents become plural

`[agent]` gains `enabled` — the list `lh deploy` writes for. `ProfileEntry` gains an `agents` table mapping an agent type to its `config_dir`. The flat `config_dir` is not deprecated; it normalizes at load time to `{cfg.agent.type: <flat>}`, so an untouched config behaves exactly as today. Declaring both the flat key and an `agents` entry for the same agent is a **load error**, not a precedence rule — two sources for one path is how a reader and a writer end up disagreeing.

`[agent].type` survives as the answer to "which agent when the caller named none," validated to be a member of `enabled`. `lh run` and `lh exec` gain `--agent`.

### The adapter owns its settings file

Four methods join the Protocol: `settings_file()`, `parse_settings(text)`, `serialize_settings(doc, previous="")`, and `tool_aliases()`. The merge and repair logic in `deploy/engine.py` does not move — it operates on a plain `dict`, and the two agents' in-memory hook shapes are structurally identical (an event maps to matcher groups, each with a `matcher` and a `hooks` list of `{type, command}`).

`serialize_settings` takes the file's prior text because the two files are not the same kind of artifact. `settings.json` is generated and harness-owned; `~/.codex-lazy/config.toml` is written by the *user* and holds `model`, `sandbox_mode`, `[permissions.*]` and their comments. Round-tripping it through `tomli_w` would parse, serialize and validate perfectly while deleting every comment — a clean exit code and a destroyed config. The trivia-preserving merge already exists at `core/config.py:917` and is reused rather than duplicated.

### Tool names are canonical, and the adapter translates

`tool_aliases()` maps an agent's native `tool_name` values onto the harness's canonical set, which is Claude Code's — because that is what every builtin already reads and what every deployed `matcher` already says. `ClaudeCodeAdapter` returns `{}`. Every tool-use hook routes `payload["tool_name"]` through one helper in `hooks/builtins/_shared.py`.

An unrecognized name is treated as **not exempt**: `pre_tool_use_security` applies its path checks rather than falling through, so an incomplete alias table degrades toward blocking, never toward allowing.

### Only what a documented contract can support ships here

`CodexAdapter` does not implement `HeadlessAgent`. `lh exec --agent codex` is refused up front by machinery that already exists — the same "refuse rather than exec something whose output we cannot parse" behaviour ADR-004 specified. Transcript-derived features (session export, compound loop, `metrics.db` ingest, pricing) are likewise out of scope. Both are deferred not because they are lower value but because specifying a parser against a schema summary rather than a captured payload is how this repo has produced artifacts that passed every test and were rejected by the real consumer.

The verification plan therefore opens with installing Codex and **capturing raw hook payloads into `tests/fixtures/codex/`**. A test written against a payload we invented proves only that we can parse our own invention.

## Alternatives considered

- **Derive the config directory by convention** (`~/.<agent>-<profile>`), adding no config at all. Rejected. `config_dir` is a value the user sets today; making it a convention silently relocates the directory of anyone whose value does not match the pattern. Three lines of explicit table keeps the path authoritative.

- **One profile per agent**, moving `[agent].type` to the profile. Rejected on profile resolution: both profiles would declare the same `roots`, and resolution by cwd is exactly how `lh run` picks one. Two profiles matching one directory has no correct answer, and `roots`/`lazynorth_doc` would be duplicated.

- **Write Codex hooks to `hooks.json`** instead of inline TOML, sidestepping the TOML writer and the shared-file ordering constraint. Rejected because the MCP table must go into `config.toml` regardless, so the TOML write path is needed either way and this only splits the output across two files. Retained as the documented fallback if the inline-TOML assumption proves wrong.

- **Register Codex as an `LLMBackend`.** Rejected for the mirror image of ADR-039's reasoning. That ADR rejected Ollama as an `AgentAdapter` because an HTTP endpoint satisfies none of a subprocess-shaped Protocol. Codex is the opposite — a binary with a config dir, hooks, a system doc and a session lifecycle. The two axes stay orthogonal: a user may run Codex as their agent and route distillation to Claude, or the reverse.

- **Fix L9 by rewriting each builtin's literals per agent.** Rejected. It duplicates the tool vocabulary across three hooks and two adapters, and the copy that drifts is a security hook.

- **Defer L9 and deploy the tool-use hooks to Codex anyway.** Rejected outright. `pre_tool_use_security` would exit 0 on every Codex call while `lh doctor` reported it ON. A security hook that is inert on one of two configured agents is worse than one not deployed there, because the report is what people act on.

- **Wait for a second agent that needs no schema change.** Considered, since Gemini CLI might have fit the existing shape. Rejected: the leaks L8 and L9 are properties of *this* codebase, not of Codex, and any second agent surfaces both. Discovering them now, with one adapter to fix, is the cheap version.

## Consequences

**Positive**

- The ADR-004 promise becomes true in a stronger sense than ADR-032 achieved: after this change, the third agent really is one file and one registry entry.
- The tool vocabulary gets one owner instead of five copies, which is the difference between a security hook that is portable and one that is Claude-only by accident.
- A user can run both agents against the same profile — same roots, same knowledge store, same hooks — without duplicating configuration.
- `serialize_settings` gives every future adapter a way to write into a file it does not own without destroying it.

**Negative**

- Four more Protocol methods. Mitigated: all four have obvious values for an agent that behaves like Claude Code, and `test_agent_protocol.py` fails automatically when an adapter misses one.
- `ProfileEntry` grows a second way to express one thing during the compatibility window. The load-time error on declaring both bounds the damage, but the normalization is genuine complexity in `core/config.py`.
- `deploy_hooks` and `deploy_mcp_servers` now write the same file under Codex. Each must read-modify-write against disk state at call time, and `deploy` must not hold a parsed copy across the two. This is a new ordering constraint with no analogue under Claude Code.
- Eleven documented assumptions carry into implementation. Any of them being wrong invalidates part of the adapter. The design document names each with its blast radius, and the verification plan gates the code on a captured payload rather than on the documentation.

## Implementation

Sequenced so each gate can fail before the work depending on it exists.

1. Install Codex; capture raw hook payloads for every event into `tests/fixtures/codex/`. Confirm or correct A1–A10 — in particular, **what `tool_name` a shell call carries** (A10), which decides whether the security hook is safe to deploy at all.
2. Add the four Protocol methods to `agents/base.py`; implement them on `ClaudeCodeAdapter` and `NullAdapter` with today's hardcoded values. No behaviour change.
3. Replace the hardcoded `settings.json`/`json` calls in `deploy/engine.py` with adapter calls. Still no behaviour change; the Claude output must be byte-identical.
4. Add `canonical_tool` to `hooks/builtins/_shared.py` and route the three tool-use hooks through it. Prove the guard by deleting an alias entry and watching a test fail.
5. Add `ProfileAgentEntry`, `ProfileEntry.agents`, `AgentConfig.enabled`, the normalization and the both-declared error.
6. Loop `lh deploy` over enabled agents; add `--agent` to `lh run` and `lh exec`; extend `lh doctor` to report per-agent coverage.
7. Write `agents/codex.py` against the captured fixtures; register it.
8. Verify the generated `config.toml` with **Codex's own parser**, not `tomlkit`. Deploy twice and assert the MCP table and a hand-written comment both survive.

The milestone closes when `lh selftest` passes with both agents enabled, a Codex session fires every deployed hook, and `pre_tool_use_security` blocks a captured Codex shell payload carrying a blocked command.

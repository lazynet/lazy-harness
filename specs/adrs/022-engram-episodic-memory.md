# ADR-022: Engram as optional episodic memory backend

**Status:** accepted
**Date:** 2026-05-03

## Context

The harness covers semantic memory (the knowledge directory + optional QMD index, ADR-016) but does not address episodic memory: "what did the agent do in this project, when, and why". An on-machine audit of multi-repo projects flagged this as the most acute pain — most repos have no per-project agent diary, so every session re-explains decisions that the previous session already made.

Engram (https://github.com/Gentleman-Programming/engram) is a SQLite + FTS5 episodic-memory store with a built-in MCP server that the agent calls to save and recall what it did. It runs fully local by default, exposes an HTTP API on port 7437, and keeps memories scoped per project via a `--project` flag. Optional git sync ships compressed memory chunks under `.engram/chunks/` per repo, so a team's decision history travels with the code.

Engram is one of three tools converging on the harness's MCP deploy seam (ADR-024); the others are QMD (ADR-016, already wired) and Graphify (ADR-023, planned next). Each addresses a different memory layer; Engram covers the episodic layer specifically.

## Decision

**Add `src/lazy_harness/memory/engram.py` as a thin CLI wrapper, gated behind `shutil.which("engram")` and a config opt-in (`[memory.engram].enabled = true`). Wire it into the existing MCP deploy collector so `lh deploy` ships an `engram` entry to each profile's `settings.json` when both gates are open. Pin Engram to version `1.15.4` in config; `check_version()` exposes the comparison for `lh doctor` to use later.**

Concretely:

- `src/lazy_harness/memory/engram.py` — `is_engram_available()`, `_build_command(action, project=None)`, `run_engram(action, project=None, timeout=300)`, `mcp_server_config()` returning `{"command": "engram", "args": ["mcp"]}`, `check_version()` returning `(matches, current_version)`. Module-level `PINNED_VERSION = "1.15.4"` constant.
- `src/lazy_harness/core/config.py` — new `EngramConfig` dataclass (`enabled`, `git_sync`, `cloud`, `version` with `1.15.4` default), wrapped in a `MemoryConfig` table, exposed as `Config.memory`. Parsed by `_parse_memory` from the optional `[memory]` block in `config.toml`.
- `src/lazy_harness/deploy/engine.py` — `_collect_mcp_servers(cfg)` extends with `if cfg.memory.engram.enabled and engram.is_engram_available(): servers["engram"] = engram.mcp_server_config()`.
- The cloud sync flag is exposed (`cloud: bool = False`) but no code branches on it in this PR. Engram itself decides cloud behavior at the daemon level.

## Alternatives considered

- **Replace the existing `decisions.jsonl` / `failures.jsonl` files with Engram.** Rejected for now. The JSONL files are human-readable, version-controllable, and portable across machines without Engram installed. They are not redundant with Engram — Engram is the agent-facing real-time memory, the JSONLs are the post-session distilled record.
- **Make Engram a hard dependency.** Breaks the optionality contract from ADR-016. Users who do not install Engram would have a broken `lh deploy`. Same `shutil.which` gate keeps the framework installable without it.
- **Auto-install Engram during `lh init`.** Out of scope. Per the user-confirmed plan, the wizard prints the install command but does not run it. Detection-only, consistent with QMD.
- **Default the cloud sync to `true`.** Rejected. Engram cloud sync is opt-in by design. The harness reflects that with `cloud: bool = False` and a comment in the ADR; the user can flip it explicitly per project.

## Consequences

- A user who installs Engram (`brew install engram` or equivalent) and sets `[memory.engram].enabled = true` gets the `engram` MCP server wired into every profile on the next `lh deploy`. Removing Engram and re-running `lh deploy` does **not** remove the entry: `_collect_mcp_servers` rebuilds its dict from scratch, but the merge into the agent's MCP file adds and overwrites without removing, so a stale entry is deleted by hand (ADR-024, Evolution 2026-09-12).
- Pinning the version in config (`version = "1.15.4"`) gives `lh doctor` (future ADR) a single source of truth for compatibility checks. `check_version()` returns the tuple it needs.
- The wizard step (`enable_engram`) and `lh doctor` reporting are intentionally deferred to the Fase 3 ADR. This PR ships the runtime mechanism only, mirroring how ADR-016 left wizard discovery to ADR-018.
- The `[memory]` config namespace is new. `MemoryConfig` is intentionally a thin wrapper today — it exists so future episodic backends slot in next to `engram` without breaking the namespace.

## Evolution — 2026-08-18: the pin lives in the module, and the MCP file moved

- **The pin is `memory/engram.py:PINNED_VERSION`, currently `1.20.0`, not
  `1.15.4`.** Since #192 `EngramConfig.version` imports the module constant
  instead of restating it, so the two cannot drift; the Decision's `1.15.4` is
  the value at the time of writing.
- **The MCP entry does not go to `settings.json`.** ADR-032 L2 put the file
  name behind the adapter and `ClaudeCodeAdapter.mcp_config_file()` returns
  `.claude.json` (ADR-024, Evolution 2026-09-12).

## Evolution — 2026-09-24: pin bumped to 2.1.0

- **`PINNED_VERSION` moved to `2.1.0`.** Probed the release tarball's `save`
  behaviour against a copy of the live Mac DB first — same CLI contract
  (`engram save <title> <content> --type T --project P --scope project`),
  exit 0, `manual-save-<project>` session with `project_owned` ownership —
  see `specs/designs/engram-evidence.md` and
  `specs/designs/2026-09-24-engram-2-migration.md`.
- **`mcp_server_config()` now mirrors engram's own MCP entry shape** —
  `{"command": <absolute engram binary>, "args": ["mcp", "--tools=agent"]}` —
  so enabling `[memory.engram]` does not trip 2.x's exact-match conflict
  check in `setup claude-code --mcp-only` (plan §1.4, §5.2 item 3).

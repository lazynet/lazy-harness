# ADR-006: Hooks as subprocess executables with JSON over stdin/stdout

**Status:** accepted
**Date:** 2026-04-13

## Context

Claude Code's hook model fires a command when specific events happen (`SessionStart`, `Stop`, `PreCompact`, `PreToolUse`, `PostToolUse`, `Notification`). The framework needs to ship built-in hooks, let users add their own, and keep both shapes interchangeable — there cannot be two classes of hooks with different capabilities.

We also need hooks to survive language and lifecycle constraints that are not ours to decide:

- The agent spawns the hook as a detached subprocess; we do not control the parent process.
- The hook has a short time budget (seconds, not minutes). If it blocks, the agent is frozen.
- The hook must never crash the session — an exception in a built-in hook must surface as a log line, not a torn-down Claude Code window.
- The hook is invoked by Claude Code directly, not by `lazy-harness`. The framework only writes the wiring; the agent runs the command.

Any design that required hooks to be Python classes inside a long-lived `lh` daemon would break all four constraints.

## Decision

A hook is **any executable that reads a JSON event payload on stdin and optionally writes JSON output on stdout**. Nothing else. The built-in hooks are Python scripts under `src/lazy_harness/hooks/builtins/`; user hooks can be any language as long as they follow the same stdin/stdout contract.

Wiring:

- **Discovery.** `src/lazy_harness/hooks/loader.py` resolves hook names to file paths. Built-ins are looked up first (`_BUILTIN_HOOKS` dict mapping hook name to its module file); if no built-in matches, the loader falls back to `~/.config/lazy-harness/hooks/<name>.py`.
- **Registration.** Users declare hooks in `config.toml` under `[hooks.<event>]` with a `scripts = [...]` list. Example:
  ```toml
  [hooks.session_start]
  scripts = ["context-inject"]

  [hooks.session_stop]
  scripts = ["session-export", "compound-loop"]
  ```
- **Deployment.** `lh deploy` walks the config, resolves each declared hook to a path, and writes the agent-native hook config. For Claude Code that means generating the `hooks` section of `settings.json` with entries like `{"type": "command", "command": "<python> <hook-path>"}`. See `src/lazy_harness/deploy/engine.py` and `ClaudeCodeAdapter.generate_hook_config`.
- **Execution.** At runtime the agent itself spawns the hook. The framework never runs hooks in-process. `src/lazy_harness/hooks/engine.py` exists for programmatic testing (`lh hooks run`, test suite) and is not on the normal execution path.
- **Output shape.** Hooks that inject additional context print a JSON object with `hookSpecificOutput.additionalContext` and optional `systemMessage` (see `context-inject` and `pre-compact`). Hooks that only perform side effects print nothing and exit 0. Hooks **always exit 0** — any failure is logged to `~/.claude/logs/hooks.log` but never propagates to the agent.

## Alternatives considered

- **Hooks as Python classes loaded in a long-lived `lh` daemon.** Would give us richer APIs and no subprocess cost per event, but requires a persistent process the framework does not otherwise have. Rejected — the non-daemon constraint is set by the agent, not by us.
- **Hooks as import-time plugins via Python entry points.** Locks hooks to Python and requires each user hook to be a pip-installable package. Rejected as too heavy for users who just want "a small script".
- **Hooks called via HTTP to a local service.** Same daemon objection, plus an extra network hop and port management. Rejected.
- **Shell-only hooks (no JSON protocol).** Rejected because Claude Code ships events as JSON and we want hooks to inspect typed fields, not parse ad-hoc env vars.
- **Typed RPC (gRPC, JSON-RPC) between agent and hook.** Overengineered for unidirectional event data.

## Consequences

- Writing a user hook is trivial: any script that reads `sys.stdin`, does its work, and optionally prints JSON. Tests live under `tests/hooks/` and invoke the script file directly with a fake payload.
- Built-in and user hooks are indistinguishable at the execution layer. The only difference is the lookup in `resolve_hook()`.
- Each hook owns its own error handling and logging. The built-ins write to `~/.claude/logs/hooks.log` via a small helper pattern; failures there are still swallowed, because the contract is "always exit 0".
- Because hooks are independent subprocess invocations, they cannot share in-memory state. State that needs to persist across events goes through the filesystem: `compound-loop` drops task files in `~/.claude/queue/`, `pre-compact` writes `memory/pre-compact-summary.md`, `session-export` writes into the knowledge directory.
- The JSON protocol is the interoperability hinge. Adding a second agent ([ADR-004](004-agent-adapter-pattern.md)) does not require touching any hook — the adapter translates `cfg.hooks` events to that agent's native format.

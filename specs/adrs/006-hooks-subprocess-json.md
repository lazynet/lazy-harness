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
- **Output shape.** Hooks that inject additional context print a JSON object with `hookSpecificOutput.additionalContext` and optional `systemMessage` (see `context-inject` and `pre-compact`). Hooks that only perform side effects print nothing and exit 0. An **informational hook always exits 0** — it logs its failures and never propagates them to the agent. A *blocking* hook inverts that: `BuiltinHookSpec.blocking` marks it, and it exits 2 to refuse the tool call, because exit 0 with no output is how a hook says "no objection" and degrading a guard to 0 would turn every crash of it into an approval.

## Alternatives considered

- **Hooks as Python classes loaded in a long-lived `lh` daemon.** Would give us richer APIs and no subprocess cost per event, but requires a persistent process the framework does not otherwise have. Rejected — the non-daemon constraint is set by the agent, not by us.
- **Hooks as import-time plugins via Python entry points.** Locks hooks to Python and requires each user hook to be a pip-installable package. Rejected as too heavy for users who just want "a small script".
- **Hooks called via HTTP to a local service.** Same daemon objection, plus an extra network hop and port management. Rejected.
- **Shell-only hooks (no JSON protocol).** Rejected because Claude Code ships events as JSON and we want hooks to inspect typed fields, not parse ad-hoc env vars.
- **Typed RPC (gRPC, JSON-RPC) between agent and hook.** Overengineered for unidirectional event data.

## Consequences

- Writing a user hook is trivial: any script that reads `sys.stdin`, does its work, and optionally prints JSON. Tests live under `tests/hooks/` and invoke the script file directly with a fake payload.
- Built-in and user hooks are indistinguishable at the execution layer. The only difference is the lookup in `resolve_hook()`.
- Each hook owns its own error handling and logging. The built-ins write to `logs/hooks.log` under the agent runtime directory, via a small helper pattern; failures there are still swallowed, because auditing must never break the hook. That directory resolves from the agent's environment variable first and only then from the profile. Since the step 5 migrations closed (#314→#328) every builtin that resolves a runtime dir does so through `_shared.py:agent_dir_for(cfg, event.profile)` — thirteen of the eighteen call it, exactly once each — rather than off the global `[agent].type`.
- Because hooks are independent subprocess invocations, they cannot share in-memory state. State that needs to persist across events goes through the filesystem: `compound-loop` drops task files in the agent's `queue/` directory (`~/.claude/queue/` on a single-profile Claude Code install — see the path note in [ADR-008](008-compound-loop-async-worker.md)), `pre-compact` writes `memory/pre-compact-summary.md`, `session-export` writes into the knowledge directory.
- The JSON protocol is the interoperability hinge. Adding a second agent ([ADR-004](004-agent-adapter-pattern.md)) does not require touching any hook — the adapter translates `cfg.hooks` events to that agent's native format.

## Evolution

**2026-09-15 — four claims above describe a runner that no longer exists.** The
decision stands: hooks are still subprocesses, still fed JSON on stdin. What
moved is who generates their command, what they may print, and how they refuse.

This ADR was missed when the same mechanism was annotated elsewhere, and the
reason is worth recording: [ADR-004](004-agent-adapter-pattern.md),
[ADR-024](024-mcp-server-orchestration.md) and
[ADR-032](032-agent-adapter-completeness.md) were found by grepping the *symbol*
that had been removed. This ADR describes the hook contract without naming that
symbol in its Decision, so the grep did not reach it — the widest-scoped document
of the five was the one left stale. Grep the mechanism, not the identifier.

- **The command is `lh hook <name> --profile <p>`, not `<python> <hook-path>`.**
  `deploy/engine.py:hook_command` builds `<binary> hook <name> --profile
  <profile>`, with the binary resolved per profile by `binary_for_profile`. The
  runner taking a `--profile` argument is step 2 of the 2026-09-13 multi-agent
  design ([ADR-041](041-multi-agent-hook-contract.md)).
- **`lh deploy` no longer writes the agent-native hook config; the adapter
  does.** Step 3 put merging behind the optional `ConfigPlanner` protocol:
  `config_targets()` names the documents an adapter owns and `plan_config()`
  returns their final text, leaving `deploy/engine.py` doing only I/O. The
  pointer in the *Deployment* bullet to `ClaudeCodeAdapter.generate_hook_config`
  names a symbol that no longer exists — it came off the Protocol at step 4 and
  survives as the private `_generate_hook_config`, called from `_plan_settings`.
- **`pre-compact` prints plain text, never JSON.** The *Output shape* bullet
  lists it beside `context-inject`, and that was wrong before it was written:
  `PreCompact` has no `hookSpecificOutput` variant, so a JSON payload fails
  schema validation, which marks the hook failed and discards its output
  entirely. The executor concatenates whatever the hook prints and hands it to
  the summariser as `newCustomInstructions`. Settled as D2 of
  [ADR-036](036-compact-hooks-use-real-channels.md); `hooks/builtins/pre_compact.py`
  says so in its own module docstring. `context-inject` is unaffected.
- **Hooks do not always exit 0 — exit 2 is the deny channel.** The contract is
  that a hook never propagates an *error* to the agent, which is not the same
  statement. A blocking decision reaches Claude Code as the reason on stderr with
  exit 2, and that is the adapter's business now: `format_hook_output` returns
  `exit_code=2` for a verdict the agent honours. `pre-tool-use-git-scope` was the
  last hook exiting 2 directly; since #326 it returns
  `HookDecision(verdict=Verdict.DENY, …)` like the rest, and there is no
  `sys.exit` left in the module. The *Consequences* bullet that derives "failures are
  swallowed, because the contract is always exit 0" keeps its conclusion —
  failures are still swallowed — but not via that premise.
- **Adding a second agent did require touching hooks.** The last *Consequences*
  bullet claimed the adapter alone absorbs a new agent because it translates
  `cfg.hooks` events to a native format. That held only for *deployment*. The
  adapter was never on the path a hook *ran* on, so eighteen builtins each
  carried one agent's wire format — the defect ADR-041 exists to fix, and the
  reason three builtins were migrated onto a typed event contract rather than
  none. Step 5 closed on 2026-09-16 and the bullet is true for all eighteen:
  every builtin exposes `main(event: HookEvent) -> HookDecision`, with
  `test_every_builtin_main_takes_an_event_and_returns_a_decision` in
  `tests/unit/hooks/test_builtin_registry.py` asserting that contract over the
  whole registry.

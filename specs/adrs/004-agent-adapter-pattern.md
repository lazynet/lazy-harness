# ADR-004: Agent adapter pattern

**Status:** accepted
**Date:** 2026-04-12

## Context

`lazy-harness` is explicitly designed to outlive any single AI coding agent. Today Claude Code is the only supported target, but the whole motivation of extracting the framework out of the predecessor project was to make it agent-agnostic — if the next obvious agent ships tomorrow, we want to add it in a file, not rewrite the core.

The agent-specific things we care about are narrow and concrete:

- Where does the agent look for its config on disk?
- What environment variable selects an alternate config dir (for profile switching)?
- What format does the agent expect its hook configuration in?
- Which hook events does the agent actually support?
- Where is the agent binary installed on disk, and how do we find it without risking recursion into our own wrapper?

Everything else — profiles, config, knowledge, monitoring, scheduling, migrations — should not care which agent is underneath.

## Decision

A Python `Protocol` defines the adapter interface at `src/lazy_harness/agents/base.py`:

```python
class AgentAdapter(Protocol):
    @property
    def name(self) -> str: ...
    def config_dir(self, profile_config_dir: str) -> Path: ...
    def env_var(self) -> str: ...
    def resolve_binary(self) -> Path | None: ...
    def supported_hooks(self) -> list[str]: ...
    def generate_hook_config(self, hooks: dict[str, list[str]]) -> dict: ...
```

A registry in `src/lazy_harness/agents/registry.py` maps the `[agent].type` value from `config.toml` (`"claude-code"` today) to a concrete adapter implementation. `ClaudeCodeAdapter` is the only implementation and lives at `src/lazy_harness/agents/claude_code.py`.

The rest of the codebase never imports a concrete adapter. Deploy, hooks, and migration all go through `get_agent(cfg.agent.type)` and call protocol methods. Agent-specific quirks (Claude Code's `SessionStart` vs `Stop` event names, its `settings.json` hook format, its `~/.local/share/claude/versions/` versioning scheme) are isolated inside the adapter.

## Alternatives considered

- **Agent-specific code sprinkled throughout.** Fast for v1 when there is only one agent, catastrophic the first time we add a second. Every file would need a `if agent == "claude-code":` branch. Rejected on maintainability grounds before writing a single line.
- **Full plugin system with entry points.** Overkill for v1. Adapters are small Python classes; pay the complexity when we have more than one in the same release, not before.
- **Adapters as dataclasses / configuration only (no code).** Cannot express the hook-config generation logic, which is agent-specific serialization. Rejected.
- **Skip the abstraction entirely and wait for the second agent.** The predecessor tried this. Once Claude Code assumptions were everywhere, untangling was half the cost of the `lazy-harness` extraction itself. Building the seam up-front is cheaper than retrofitting it later.

## Consequences

- Adding a second agent = one new file (`agents/<name>.py`), one registry entry, zero changes elsewhere. The test suite will prove this the first time we do it.
- The protocol is minimal by design. If a new agent needs something the protocol does not expose, that is a signal to extend the protocol deliberately, not to leak agent-specific paths into core modules.
- `resolve_binary` carries a subtle constraint documented in the protocol: it must avoid resolving to a shim that would recurse back into `lh run`. `ClaudeCodeAdapter.resolve_binary` implements this by preferring the version-manager directory (`~/.local/share/claude/versions/`) over a raw `shutil.which("claude")` lookup.
- The adapter is the only place where "which events exist" is defined. `deploy_hooks` iterates `cfg.hooks` (user-declared event names) and calls `agent.generate_hook_config` — a user that declares an unsupported event for their agent gets a silent drop, which is intentional forward-compat: newer config can target older agents.
- The agent layer is intentionally thin. It is not an abstraction over chat — the framework never proxies messages. It is an abstraction over the tiny surface area the framework actually touches: filesystem paths, event names, and settings serialization.

## Evolution

**2026-09-15 — the two config generators came off the Protocol.** `plan_config`
replaced them as the deploy surface (decision 4 of the 2026-09-13 multi-agent
harness design): a `dict` return cannot express "N files in two formats", which
is what a second agent needs — Codex declares its hooks in `hooks.json`, not in
a Claude-shaped `settings.json`. They survive as private serialisers inside
`ClaudeCodeAdapter` (`_generate_hook_config`, `_generate_mcp_config`). The
Protocol block quoted above is kept as written, because it records the decision
as it was made; the live surface is `agents/base.py`.

Two further claims outside that block had gone stale with it, and are corrected
here rather than rewritten in place:

- **`ClaudeCodeAdapter` is no longer the only implementation.** `agents/registry.py`
  registers three: `claude-code`, `codex` — the throwaway adapter of step 4's
  contract gate, deliberately the smallest thing that can carry three builtins to
  a real Codex session — and `null`, the sentinel. The *Context* sentence that
  Claude Code is "the only supported target" reads as of 2026-04-12.
- **`deploy_hooks` does not call `agent.generate_hook_config`.** Since step 3 the
  engine only does I/O; the adapter plans its own documents through
  `ConfigPlanner.plan_config`. The *silent drop* of an event a user declares and
  the agent does not support is unchanged and still deliberate — it is now
  `hook_events()` that decides, and an absent key is what forward-compat rides on.

The *Consequences* promise — one new file, one registry entry, zero changes
elsewhere — was tested for the first time by `CodexAdapter` and did not hold
unassisted: the Protocol had to shed two methods first. That is the promise
working as a signal, which is what the second *Consequences* bullet asks for.

**2026-09-16 — the recursion constraint is an ordering, not a filter.** The
`resolve_binary` bullet above reads as though a shim is rejected. Nothing
rejects one: `claude_code.py` prefers the version-manager directory and then
returns `shutil.which("claude")` unfiltered, so with that directory absent a
PATH `claude` wrapping `lh run` is returned and exec'd. The constraint is
recorded here as **accepted**, not fixed, on two measurements. Keying a filter
on the `lh` entrypoint directory would reject the genuine binary — `uv tool
install` puts `lh` and `claude` in the same `~/.local/bin`, and the resulting
`LaunchError("binary-not-found")` breaks `lh run` outright, a worse failure
than the one it prevents. And the recursion needs the version dir absent *and*
an executable wrapper on PATH; the ordinary spelling of re-entry is a shell
alias or function, which `shutil.which` cannot see. Both branches are pinned by
`test_a_recursive_claude_shim_on_path_loses_to_the_versioned_build` and
`test_a_recursive_claude_shim_is_returned_when_no_versioned_build_exists`, so
closing the risk later means changing a test that asserts it is open.

**2026-09-16 — deploy, hooks and `lh run` resolve the adapter per profile.**
The *Decision* section above says "Deploy, hooks, and migration all go through
`get_agent(cfg.agent.type)`." Since #342 (0.68.0) that is no longer the seam:
each resolves through `agents/registry.py:agent_for_profile`, keyed on
`(cfg, profile_name)`, rather than the single global `[agent].type`.
`get_agent(cfg.agent.type)` survives only as the global fallback for the five
call sites recorded in [ADR-041](041-multi-agent-hook-contract.md) §3, none of
which sit on the deploy/hooks/run path this ADR's *Decision* names.

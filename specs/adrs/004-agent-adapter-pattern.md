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

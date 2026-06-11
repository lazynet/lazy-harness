# ADR-032: Agent adapter completeness — closing Claude-specific leaks

**Status:** accepted
**Date:** 2026-05-27
**Implemented:** 2026-06-11 — Protocol gaps (PR #88) and L3/L4 leak closures (PR #96) are merged.
**Supersedes:** —
**Superseded by:** —
**Related:** ADR-004 (agent-adapter-pattern), ADR-032 (llm-backend-abstraction)

## Context

ADR-004 defined the `AgentAdapter` Protocol and explicitly stated that adding a
second agent equals "one new file, one registry entry, zero changes elsewhere."
That contract holds at the adapter seam itself — `deploy_hooks`, `deploy_mcp_servers`,
and `lh run` all go through `get_agent(cfg.agent.type)`.

However, a survey of the codebase ahead of a planned multi-provider extension
found **seven Claude-specific assumptions** that bypass the adapter layer entirely.
These leaks would force every new adapter to also patch unrelated modules,
violating the ADR-004 guarantee.

### Leaks identified

| # | Leak | Location | Nature |
|---|------|----------|--------|
| L1 | `~/.claude` symlink hardcoded | `deploy/engine.py:deploy_claude_symlink` | Path specific to Claude Code |
| L2 | `.claude.json` as MCP config file | `deploy/engine.py:deploy_mcp_servers` | File name specific to Claude Code |
| L3 | `CLAUDE_CONFIG_DIR` env var read directly | `doctor_cmd.py`, `knowledge_cmd.py`, `hooks/builtins/compound_loop.py` | Should go through `agent.env_var()` |
| L4 | `logs/`, `queue/`, `projects/` subdir layout hardcoded | `knowledge_cmd.py`, `hooks/builtins/compound_loop.py` | Layout specific to Claude Code |
| L5 | `CLAUDE.md` filename hardcoded | `core/sync_claude.py`, `cli/profile_cmd.py` | Different agents use different filenames (e.g. `GEMINI.md`) |
| L6 | `post-tool-use-sync-claude` as a default hook name | `deploy/defaults.py` | Should be conditional on agent type |
| L7 | `_hook_commands` comments reference "Claude Code hooks block" | `deploy/engine.py` | Cosmetic; the structure is already agent-generated |

L3 is the highest-frequency leak: three separate modules resolve the agent config
directory by reading `CLAUDE_CONFIG_DIR` directly instead of calling
`agent.env_var()` and `agent.config_dir()`. A Gemini CLI adapter would export
`GEMINI_CONFIG_DIR`; those modules would silently fall back to the wrong directory.

L5 is architecturally interesting: `CLAUDE.md` (and its `head/tail` segmented
layout) is a Claude Code concept. Gemini CLI uses `GEMINI.md`; other agents
may use a system prompt file, an `.agentrc`, or nothing at all. The `sync-agent-md`
feature must become per-adapter, not per-filename.

## Decision

Extend the `AgentAdapter` Protocol with the minimum set of methods required to
close all seven leaks. No existing behaviour changes for `ClaudeCodeAdapter`
users — each new method on `ClaudeCodeAdapter` returns the value that was
previously hardcoded.

### New protocol methods

```python
class AgentAdapter(Protocol):
    # --- existing methods unchanged ---
    @property
    def name(self) -> str: ...
    def config_dir(self, profile_config_dir: str) -> Path: ...
    def env_var(self) -> str: ...
    def resolve_binary(self) -> Path | None: ...
    def supported_hooks(self) -> list[str]: ...
    def generate_hook_config(self, hooks: dict[str, list[str]]) -> dict: ...
    def generate_mcp_config(self, servers: dict[str, dict]) -> dict: ...

    # --- new methods ---
    def global_config_link(self) -> Path | None:
        """Canonical global symlink for this agent (e.g. ~/.claude).

        Return None if the agent does not use a global symlink convention.
        `lh deploy` only creates the symlink when this is non-None.
        """
        ...

    def mcp_config_file(self) -> str:
        """Filename inside the config dir that holds MCP server config.

        Claude Code: '.claude.json'.  Return empty string if MCP config
        is merged into the main settings file (some adapters do this).
        """
        ...

    def session_dirs(self) -> dict[str, str]:
        """Subdirectory names for agent-managed session artefacts.

        Returns a mapping with at least the keys the framework uses:
          'sessions'  — dir holding per-project session JSONL files
          'logs'      — dir holding raw event logs
          'queue'     — dir holding compound-loop task queue

        Agents that do not support a given concept return an empty string
        for that key; callers must treat empty strings as "not available".

        Claude Code: {'sessions': 'projects', 'logs': 'logs', 'queue': 'queue'}
        """
        ...

    def system_doc_name(self) -> str:
        """Filename of the agent's primary system-instruction document.

        Claude Code: 'CLAUDE.md'.  Gemini CLI: 'GEMINI.md'.
        Return empty string for agents that use a different injection
        mechanism (system prompt via API, etc.) — `sync-agent-md` becomes
        a no-op for those adapters.
        """
        ...
```

### Leak-to-method mapping

| Leak | Resolved by |
|------|-------------|
| L1 (`~/.claude` symlink) | `global_config_link()` |
| L2 (`.claude.json`) | `mcp_config_file()` |
| L3 (`CLAUDE_CONFIG_DIR` direct reads) | existing `env_var()` + `config_dir()` |
| L4 (`logs/`, `queue/`, `projects/`) | `session_dirs()` |
| L5 (`CLAUDE.md` filename) | `system_doc_name()` |
| L6 (`sync-claude` default hook) | guard with `agent.system_doc_name() != ""` |
| L7 (cosmetic comments) | comment update only |

### `ClaudeCodeAdapter` additions (zero behaviour change)

```python
def global_config_link(self) -> Path | None:
    return Path.home() / ".claude"

def mcp_config_file(self) -> str:
    return ".claude.json"

def session_dirs(self) -> dict[str, str]:
    return {"sessions": "projects", "logs": "logs", "queue": "queue"}

def system_doc_name(self) -> str:
    return "CLAUDE.md"
```

### `core/sync_claude.py` rename

`sync_claude.py` → `sync_agent_md.py`. Public API stays: `sync_profiles(cfg)`.
Internally, the function resolves the target filename via `agent.system_doc_name()`
instead of the hardcoded `"CLAUDE.md"`. The `head/tail` source filenames in the
profiles directory follow the same convention:
`CLAUDE.head.md` / `CLAUDE.tail.md` → `<system_doc_name>.head.md` /
`<system_doc_name>.tail.md`. For `ClaudeCodeAdapter` the filenames are identical
to today; no migration needed.

## Alternatives considered

- **Leave the leaks and document "Claude Code only" for now.** Rejected. The
  leaks are small and localized today. Deferring means each new adapter author
  must rediscover and patch all seven locations. ADR-004 made an explicit promise
  ("one file, zero changes elsewhere"); honouring it now is cheaper than breaking
  it later.

- **One big `agent_context()` method returning all the strings.** Rejected.
  A single fat method cannot be partially implemented: an adapter for an agent
  without a global symlink would still need to return a placeholder for the
  symlink key. Fine-grained methods with explicit `None`/empty-string sentinels
  are more honest about "this agent does not have this concept".

- **Encode the subdir layout in config.toml instead of the adapter.** Considered.
  It would let power users override the layout without touching Python. Rejected
  because the layout is not user-configurable on the agent side — it is an
  implementation detail of the agent binary. Putting it in config would imply
  the user can set it to anything, which is false. The adapter is the right
  place for agent-internal constants.

- **Make `system_doc_name()` return a list to handle agents that load multiple
  files.** Considered (some agents support both `CLAUDE.md` and `.claude/instructions.md`).
  Deferred. Claude Code's multi-file support is already handled by the profile
  symlink deploy (ADR-009). The method returns the *primary* document name;
  multi-file support, if needed, can be addressed by a separate method without
  breaking this contract.

## Consequences

**Positive**

- The ADR-004 guarantee ("one file, zero changes elsewhere") becomes true.
  Adding a `GeminiCLIAdapter` requires no changes outside `agents/`.
- All seven Claude-specific assumptions are centralized in `ClaudeCodeAdapter`,
  which is the only file that should know about them.
- `sync_agent_md.py` becomes a generic tool; users of future adapters get
  segmented system-doc support for free.
- The test suite can verify the Protocol contract against any adapter without
  mocking internals of other modules.

**Negative**

- Four new Protocol methods increase the surface every adapter author must
  implement. Mitigated by the fact that all four have obvious defaults (`None`
  for the symlink if not applicable, empty string for "not available").
- `sync_claude.py` → `sync_agent_md.py` is a rename with a blast radius across
  `cli/profile_cmd.py`, `hooks/builtins/post_tool_use_sync_claude.py`, and
  `deploy/defaults.py`. All are mechanical changes; the logic is unchanged.
- Existing profiles using `CLAUDE.head.md` / `CLAUDE.tail.md` filenames do not
  need migration (ClaudeCodeAdapter returns `"CLAUDE.md"`, so the lookup remains
  identical). The rename is additive.

## Implementation

This ADR must ship before any second adapter is added. Recommended sequence:

1. Add the four Protocol methods to `agents/base.py` (type-check only, no
   behaviour change).
2. Implement all four on `ClaudeCodeAdapter` with the hardcoded values extracted.
3. Update callers: `deploy/engine.py`, `doctor_cmd.py`, `knowledge_cmd.py`,
   `hooks/builtins/compound_loop.py`.
4. Rename `sync_claude.py` → `sync_agent_md.py`; update the three call sites.
5. Gate the `post-tool-use-sync-claude` default in `deploy/defaults.py` on
   `agent.system_doc_name() != ""`.
6. Bump tests: one `test_agent_protocol.py` that verifies every registered
   adapter satisfies all Protocol methods. This test fails automatically
   when a new adapter is added without implementing the full Protocol.

Each step is independently reviewable. The milestone closes when `lh selftest`
passes with a stub `NullAdapter` (returns `None`/`""` for all optional methods)
registered alongside `ClaudeCodeAdapter`.

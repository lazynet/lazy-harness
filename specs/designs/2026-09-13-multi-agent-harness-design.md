# Multi-agent harness: what actually has to be abstracted

**Status:** proposed
**Date:** 2026-09-13
**Relates to:** [ADR-004](../adrs/004-agent-adapter-pattern.md) (agent adapter pattern), [ADR-032](../adrs/032-agent-adapter-completeness.md) (adapter completeness), [ADR-035](../adrs/035-capability-registry.md) (capability registry), [ADR-009](../adrs/009-profile-symlink-deploy.md) (profile symlink deploy), [ADR-031](../adrs/031-default-hooks-merge.md) (default hooks merge)

## Problem

ADR-004 promised that adding a second agent costs "one new file, one registry
entry, zero changes elsewhere". ADR-032 closed seven leaks to make that true.
Neither was ever tested against a real second agent, because there was none.

There is now more than one. The question this design answers is not "can we add
an adapter" — the seam exists — but **which of the harness's assumptions survive
contact with an agent that is not Claude Code**, and which turn out to be
Claude Code's shape mistaken for the shape of the problem.

The answer is narrower than expected in one direction and wider in another.
Narrower: the canonical hook vocabulary the harness already uses is, empirically,
the vocabulary the ecosystem converged on. Wider: the adapter is unidirectional —
it knows how to *write* an agent's config and nothing about how to *read* what the
agent produces — and every feature that makes the harness worth running lives on
the reading side.

## What the survey found

### The hook contract is a de facto standard, and nobody designed it as one

Claude Code's hook wire format has been adopted, unmodified, by competitors:

| Agent | Evidence |
|---|---|
| **Codex CLI** | Ships the identical payload field names (`session_id`, `turn_id`, `transcript_path`, `hook_event_name`, `tool_name`, `tool_input`, `tool_use_id`, `tool_response`, `permission_mode`, `stop_hook_active`) and the identical response fields (`hookSpecificOutput`, `permissionDecision`, `permissionDecisionReason`, `additionalContext`, `systemMessage`, `continue`, `stopReason`, `suppressOutput`). Also defines `CLAUDE_PLUGIN_ROOT` / `CLAUDE_PLUGIN_DATA` and bundles an importer for `.claude/settings.json`, `CLAUDE.md` and `.claude.json`. |
| **Qwen Code** | A fork of gemini-cli that *abandoned its own upstream's* event names (`BeforeTool`/`AfterTool`) to adopt `PreToolUse`/`PostToolUse`/`UserPromptSubmit`/`SubagentStart`/`SubagentStop`/`PreCompact`/`PostCompact`. |
| **Crush** | Implements exactly one hook event, and named it `PreToolUse`. |
| **DeepSeek Harness (`dsh`)** | Defines no hook vocabulary of its own. Ships a plugin that executes an unmodified Claude Code `hooks.json`. |

The harness's own canonical vocabulary — `session_start`, `session_stop`,
`session_end`, `pre_compact`, `post_compact`, `pre_tool_use`, `post_tool_use`,
`notification`, `user_prompt_submit`, `permission_request` — matches Codex's
snake_case event set almost exactly, including the unusual members
(`post_compact`, `permission_request`).

**Consequence: the abstraction to build is wire translation, not concept
invention.** A canonical vocabulary designed in 2026-04 for one agent turned out
to be the industry's. That is luck, not foresight, but it collapses the expected
cost of this work by roughly an order of magnitude.

### `AGENTS.md` is a real standard that Claude Code does not implement

`AGENTS.md` was formalised in 2025-08 and donated to the Agentic AI Foundation in
2025-12. Codex, opencode, Amp, Crush and `dsh` all read it. Several read
`AGENTS.md` *and* `CLAUDE.md` together — the formats stack rather than compete.
Claude Code reads only `CLAUDE.md`.

`system_doc_name() -> str` cannot express "two files, two scopes, concatenated".
ADR-032 deferred exactly this and named the deferral; three agents now force it.

### ACP is not a substitute for this work

The Agent Client Protocol has genuine multi-vendor adoption (Zed, JetBrains,
Claude Code, Codex, Gemini CLI, `dsh`). It covers the editor↔agent surface:
session, prompt, tool calls, permissions, filesystem, terminal. It covers
**neither config deployment nor telemetry**. It does not overlap with what this
framework does, and adopting it would not remove the need for adapters.

### MCP is the most converged surface of all

Every agent with external tool support uses a `mcpServers`/`mcp` mapping and the
`mcp__<server>__<tool>` naming convention. Only the file and its serialisation
differ. `generate_mcp_config` already models this correctly; the gap is that its
caller assumes JSON, and Codex wants TOML.

## Decision

### 1. Three tiers, declared as a capability

```python
class HookDelivery(StrEnum):
    NATIVE = "native"          # same event literals and payload fields as canonical
    TRANSLATED = "translated"  # same concepts, different wire; adapter maps both ways
    NONE = "none"              # no declarative hook mechanism
```

| Tier | Agents | Adapter work |
|---|---|---|
| `NATIVE` | Codex, Qwen Code, Crush (partial), `dsh` | Near-identity. Event names and payload pass through. |
| `TRANSLATED` | Copilot CLI, Gemini CLI | Real bidirectional mapping of names and fields. |
| `NONE` | opencode, Amp, Aider | No hooks. Config, system docs, MCP and transcript only. |

`hook_delivery()` joins the `AgentAdapter` Protocol and the capability registry
(ADR-035). A `NONE` agent is not a failure: `lh deploy` writes no hook config for
it and `lh doctor` reports the absence explicitly.

This replaces today's silent behaviour, where `deploy_hooks` drops an event the
agent does not support with no output. ADR-004 called that "intentional
forward-compat"; it is defensible for one unsupported event on one agent and
indefensible as the answer to "this agent has no hooks at all".

**Out of scope, deliberately:** generating a JavaScript plugin shim so that
`NONE`-tier agents with a plugin runtime (opencode, Amp) can reach
`lh hooks run`. It is a code generator in a Python project and a second hook
mechanism to maintain. Revisit as its own ADR once a `TRANSLATED` adapter ships.

### 2. Four Protocol methods: the inbound seam

```python
def hook_delivery(self) -> HookDelivery: ...

def hook_event_names(self) -> dict[str, str]:
    """Canonical event name -> the agent's native name.

    `supported_hooks()` becomes `hook_event_names().keys()`, which also makes it
    honest: today it returns canonical names while `generate_hook_config`
    re-maps them internally, so the mapping exists twice.
    """

def parse_hook_input(self, raw: dict) -> HookEvent:
    """The agent's inbound wire format -> normalised payload."""

def format_hook_output(self, decision: HookDecision) -> dict:
    """Normalised decision -> the agent's outbound wire format."""
```

```python
@dataclass(frozen=True)
class HookEvent:
    event: str                      # canonical name
    session_id: str
    cwd: Path
    transcript_path: Path | None
    tool_name: str | None = None
    tool_input: dict | None = None
    tool_response: dict | None = None
    prompt: str | None = None
    model: str | None = None
    permission_mode: str | None = None
    raw: dict | None = None         # the untranslated payload, for adapters
```

`format_hook_output` is the method most easily missed and the one that matters
most. The harness's **blocking** hooks — `pre_tool_use_security`,
`pre_tool_use_git_scope`, `stop_verify_guard` — do not block by writing a file.
They block with exit 2 and a response document. Codex speaks that document
natively; Copilot does not. Without this method those hooks run on a
`TRANSLATED` agent, report success, and **enforce nothing**.

That is the repo's standing gate — *a tool's exit code is not proof of its
effect* — in a form the gate's current wording does not catch: the hook executes,
the file is written, the process exits 0, and the governance silently does not
exist. The acceptance test is therefore behavioural, not structural: for every
adapter with `hook_delivery() != NONE`, exercise each exit-2 path and assert the
agent actually refused the action.

### 3. System docs become a scoped list

```python
@dataclass(frozen=True)
class SystemDoc:
    name: str
    scope: Literal["global", "repo"]

def system_docs(self) -> list[SystemDoc]: ...
```

`system_doc_name() -> str` is removed rather than kept alongside. Two methods
answering one question is the failure mode the repo's own gate names — *every
reader of a derived answer resolves it the same way* — and the segmented
`<name>.head.md` / `<name>.tail.md` lookup in `sync_agent_md.py` is exactly such a
reader.

### 4. `post_deploy()`, and the Codex hook-trust landmine

Codex persists a per-hook hash and refuses to run a hook whose content changed
until it is re-trusted (`trustStatus`, `currentHash`,
`--dangerously-bypass-hook-trust`). **A `lh deploy` that rewrites `hooks.json`
therefore disables every hook it just installed**, with a successful exit code
and a correct file on disk.

The adapter gains a generic `post_deploy(config_dir: Path) -> None`, a no-op for
every adapter but Codex's. Naming it `register_hook_trust` would leak one agent's
concept into the Protocol; the general shape is "the agent must be told its
config changed", and other agents will have their own version of it.

This must be verified empirically before the Codex adapter is called done: write
a hook, confirm it fires, change its command, re-run, and confirm it is skipped
until re-trusted. An adapter whose `post_deploy` was never observed to matter is
an adapter whose hooks are not known to run.

### 5. `TranscriptReader` as a separate optional Protocol

Modelled on `HeadlessAgent`: an agent with no readable transcript does not
implement it, and `lh exec`-style refusal applies — `session_export` skips it
rather than parsing something whose shape it is guessing.

```python
@runtime_checkable
class TranscriptReader(Protocol):
    def locate_sessions(self, since: datetime | None) -> Iterator[Path]: ...
    def read(self, path: Path) -> Iterator[TranscriptEvent]: ...
```

The on-disk formats share nothing. The *concepts* — turn, tool call, tokens,
cost — are common, and that is what `TranscriptEvent` normalises. Today this
logic is spread across `session_export`, the metrics sinks, `engram_persist` and
the handoff path, each parsing Claude Code's JSONL directly; the reader is where
it collapses.

### 6. Config: a profile is an (agent, identity) pair

```toml
[profiles.personal]
config_dir = "~/.agent-personal"
agent = "claude-code"
memory_key = "personal"

[profiles.work]
config_dir = "~/.agent-work"
agent = "claude-code"
memory_key = "work"

[profiles.work-copilot]
config_dir = "~/.agent-work-copilot"
agent = "copilot"
memory_key = "work"          # same value = same memory
```

`[agent].type` stays as the default for profiles that do not override it, so
existing configs keep working unchanged and the capability keeps `ONE`
cardinality per profile.

`memory_key` is a flat string, deliberately not a `shares_memory_with` pointer.
A pointer forms a directed graph and brings cycles, transitivity and ownership
with it; equal values express the same intent with none of that. It defaults to
the profile name, so present-day profiles are unaffected.

### 7. Permissions are per-agent by design

```
Claude Code   permissions.allow = ["Bash(git:*)"]        string prefixes
Codex         sandbox_mode + approval_policy             sandbox policy
Copilot CLI   --allow-tool / allowedUrls                 flags and lists
opencode      permission: {bash: {"git *": "allow"}}     per-tool globs
```

These are four different conceptual models, not four encodings of one. A unified
model would be a lie in all four directions, and the failure mode of a lying
permission abstraction is a permission that silently does not apply.

`[permissions]` is therefore declared per agent and serialised by each adapter,
with no cross-agent translation attempted. This is the one place where the
framework accepts duplication as the honest answer.

## Per-agent reference

Every row is marked with how it was established. `local` means observed on an
installed binary; `source` means read from the vendor's published docs or source
and **not yet confirmed against a running binary**.

| | Claude Code | Codex 0.154 | Copilot CLI 1.0.83 | opencode |
|---|---|---|---|---|
| `env_var()` | `CLAUDE_CONFIG_DIR` | `CODEX_HOME` (local) | `COPILOT_HOME` (local) | `OPENCODE_CONFIG_DIR` (source) |
| config file | `settings.json` | `config.toml` (local) | `config.json` / `settings.json` (local) | `opencode.json(c)` (source) |
| `system_docs()` | `CLAUDE.md` ×2 scopes | `AGENTS.md` ×2 scopes (source) | `.github/copilot-instructions.md` repo (local) | `AGENTS.md` + `CLAUDE.md` ×2 (source) |
| `hook_delivery()` | `NATIVE` | `NATIVE` (local) | `TRANSLATED` (local) | `NONE` (source) |
| hook config | `settings.json:hooks` | `hooks.json`, `.codex/hooks.json`, or `[hooks]` in `config.toml` (local+source) | `~/.copilot/hooks/*.json`, `.github/hooks/*.json`, or `hooks` in config (local) | plugins in JS/TS (source) |
| `mcp_config_file()` | `.claude.json` | `config.toml` `[mcp_servers.<id>]` (local+source) | `mcp-config.json` (local) | `opencode.json` `mcp` (source) |
| transcript | `projects/**/*.jsonl` | `$CODEX_HOME/sessions/YYYY/MM/DD/rollout-*.jsonl` (source) | `session-state/<uuid>/events.jsonl` (local) | SQLite + JSON, undocumented (source) |
| headless | `-p --output-format json` | `codex exec --json` (local) | `-p` (local) | `opencode run --format json`, `serve` (source) |
| `post_deploy()` | no-op | register hook trust (local) | no-op | n/a |

Codex hook events, from the binary (local) and its published schemas (source):
`PreToolUse`, `PermissionRequest`, `PostToolUse`, `PreCompact`, `PostCompact`,
`SessionStart`, `SessionEnd`, `UserPromptSubmit`, `SubagentStart`,
`SubagentStop`, `Stop`, `Interrupt` — each with a snake_case alias matching the
harness's canonical names.

Copilot hook types, observed firing in local session logs (local):
`postToolUse`, `userPromptSubmitted`, `notification`, `agentStop`. Its
`session.shutdown` event carries `conversationTokens`, `modelMetrics`,
`totalPremiumRequests`, `totalApiDurationMs` and `codeChanges` — a more complete
per-session cost record than Claude Code's transcript provides.

## What the existing profile content costs to port

Measured against the deployed profile sources rather than estimated:

| Asset | Portable as-is | Work |
|---|---|---|
| Hooks (Python, invoked as `lh hooks run <name>`) | yes | none — only the *declaration* changes, and `lh deploy` generates it |
| MCP servers | yes | none — already declared in `config.toml` |
| Skills (`SKILL.md` directories) | yes | placement only; `~/.agents/skills` is already scanned by Codex and opencode |
| Slash commands (Markdown + frontmatter) | yes | placement only |
| System document | 193 of 199 lines | a split, not a rewrite |
| Permissions | no | per-agent, by the decision above |

The six agent-specific lines reference `TaskCreate`/`TodoWrite`, the subagent
tool's model routing, and `/rewind` / `/compact` / `/clear`. Everything else —
identity, writing style, prohibitions, stack defaults, context economy, the
memory stack — applies to any agent unchanged.

So the system document gains a **second axis**, not a rewrite. It is split by
identity today (`head` / `common` / `tail`); it gains a split by agent, and those
six lines move to an agent-specific segment. `sync_agent_md.py` — already renamed
for this purpose by ADR-032 — assembles both axes.

## Alternatives considered

- **Invent a canonical event vocabulary.** Unnecessary: the harness already has
  one and the ecosystem independently converged on it. Designing a second would
  add a translation layer between two things that already agree.

- **Adopt ACP as the abstraction.** Rejected on scope, not on quality. ACP covers
  the editor↔agent surface and explicitly does not cover config deployment or
  telemetry — the two things this framework is.

- **Unify the permission model.** Rejected. Four genuinely different conceptual
  models, and a permission abstraction that quietly fails to apply is worse than
  no abstraction.

- **`shares_memory_with` as a pointer.** Rejected for `memory_key`. A directed
  edge introduces cycles, transitive resolution and an ownership question, all to
  express set membership.

- **Generate a JS plugin shim for `NONE`-tier agents.** Deferred, not rejected.
  It would cover opencode and Amp from day one, at the cost of a JavaScript code
  generator inside a Python package and a second hook delivery mechanism. Revisit
  once a `TRANSLATED` adapter is shipped and the normalised payload has been
  proven against a second wire format.

- **Keep `system_doc_name()` alongside `system_docs()`.** Rejected: two readers of
  one derived answer is the drift the repo's own gates exist to prevent.

## Consequences

**Positive**

- The ADR-004 guarantee becomes testable for the first time, against two real
  adapters rather than a `NullAdapter`.
- The hook implementations — the bulk of the framework's value — are written once
  and run on every `NATIVE` and `TRANSLATED` agent.
- Features degrade explicitly instead of silently. A `NONE`-tier agent is a
  reported state, not an empty config file.
- `TranscriptReader` collapses transcript parsing that is currently duplicated
  across four call sites.

**Negative**

- The Protocol grows by six methods. Four have obvious identity implementations
  for `NATIVE` agents; `parse_hook_input` and `format_hook_output` are real work
  per `TRANSLATED` adapter.
- `system_doc_name()` removal has a blast radius across `sync_agent_md.py`,
  `cli/profile_cmd.py` and `deploy/defaults.py`.
- Every adapter now has a correctness property that no unit test can establish:
  whether its hooks actually fire and actually block. That has to be verified
  against the installed binary, per agent, per release.

## Implementation sequence

Ordered so each step is independently reviewable and the cheap validation comes
first.

1. `HookDelivery`, `HookEvent`, `HookDecision` and the six Protocol methods in
   `agents/base.py`. Type-check only, no behaviour change.
2. Implement them on `ClaudeCodeAdapter` with today's hardcoded values extracted;
   `parse_hook_input` and `format_hook_output` are identity.
3. `system_docs()` replaces `system_doc_name()`; update the three call sites.
4. `memory_key` and per-profile `agent` in the config schema, with a full
   save/load/save/load round trip on both the new-document and merge-on-existing
   paths.
5. **`CodexAdapter`** — the `NATIVE` tier. Validates that the canonical vocabulary
   claim holds with minimal code, and forces `post_deploy` and the hook-trust
   behaviour to be resolved. Verifiable without an account: deploy, run, observe.
6. `TranscriptReader` Protocol, with Claude Code and Codex implementations.
7. **`CopilotAdapter`** — the `TRANSLATED` tier. The first real exercise of
   `parse_hook_input` and `format_hook_output`, and the first chance for the
   normalised payload to be proven wrong.
8. Register `hook_delivery` in the capability registry and surface it in
   `lh doctor`.

## Verification gates

These are checks, not principles. Each one corresponds to a way this design can
ship broken while every test passes.

- **A hook that runs is not a hook that blocks.** For every adapter with
  `hook_delivery() != NONE`, exercise each exit-2 path against the real binary
  and assert the agent refused the action. A successful hook invocation proves
  nothing about enforcement.
- **A written `hooks.json` is not an installed hook.** Confirm `post_deploy`
  matters by observing the untrusted case: change a hook's command, re-run, and
  watch it be skipped. An adapter whose trust registration was never seen to
  fail has not been tested.
- **Adapters are verified against installed binaries, not docs.** Every value in
  the per-agent reference table marked `source` is a claim awaiting confirmation.
  Vendor documentation lagged the binary in more than one case during this
  survey.
- **A transcript schema is only valid for the version it was read from.** Pin the
  agent version alongside any parser, and re-extract the schema on upgrade. The
  Copilot event schema in this document was extracted from 1.0.40-era session
  logs while 1.0.83 is installed.
- **A static list that should mirror the registry is derived from it.**
  `supported_hooks()` becomes `hook_event_names().keys()` rather than a second
  literal, with a test asserting the two cannot diverge.

## Open questions

- Whether `codex exec` lets the caller pin a new session id, or only resume an
  existing one. Determines whether `CodexAdapter` can implement
  `SessionPinningAgent` or must reconcile the id after the fact.
- The minimum Codex version that carries the hook system. It appears recent; an
  adapter that assumes it will fail confusingly on an older install, so the
  adapter should probe rather than assume.
- Whether Copilot's hook input schema at 1.0.83 still matches what 1.0.40 emitted.
- Whether opencode's session storage is stable enough to read at all, or whether
  its `serve` HTTP API is the only defensible source. Current evidence says the
  on-disk format is undocumented and in migration.

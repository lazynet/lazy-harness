# Multi-agent harness: what actually has to be abstracted

**Status:** proposed (revised 2026-09-13 after audit against the installed binaries and the code)
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

The first draft of this design answered that at the level of the `AgentAdapter`
Protocol and stopped there. The audit that produced this revision found that the
Protocol is the cheap half. The expensive half is that **the adapter is never
consulted at the moment a hook runs**: a hook is a process the agent spawns,
it reads stdin itself, it writes its verdict itself, and nothing in that path
knows which agent spawned it. Six new Protocol methods with no caller are the
repo's own "implemented but never wired" failure class, designed in advance.

## What the survey found

### The hook contract is a de facto standard, and nobody designed it as one

Claude Code's hook wire format has been adopted, unmodified, by competitors:

| Agent | Evidence |
|---|---|
| **Codex CLI** | Ships the identical payload field names (`session_id`, `turn_id`, `transcript_path`, `hook_event_name`, `tool_name`, `tool_input`, `tool_use_id`, `tool_response`, `permission_mode`, `stop_hook_active`) and the identical response fields (`hookSpecificOutput`, `permissionDecision`, `permissionDecisionReason`, `additionalContext`, `systemMessage`, `continue`, `stopReason`, `suppressOutput`). Also defines `CLAUDE_PLUGIN_ROOT` / `CLAUDE_PLUGIN_DATA` and bundles an importer for `.claude/settings.json`, `CLAUDE.md` and `.claude.json`. |
| **Copilot CLI** | The 1.0.40 application bundle carries `permissionDecision`, `permissionDecisionReason`, `additionalContext`, `systemMessage` and `"deny"`/`"ask"` literals. The *response* vocabulary is Claude Code's; only the event names differ (`preToolUse`, `postToolUse`, `userPromptSubmitted`, `sessionStart`, `sessionEnd`, `agentStop`, `preCompact`, `subagentStart`, `subagentStop`, `permissionRequest`, `errorOccurred`, `notification`). |
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
cost of the *translation* by roughly an order of magnitude. It does nothing for
the cost of the *plumbing*, which the next section measures.

### The adapter is not on the path a hook actually takes

Measured against `src/lazy_harness/hooks/builtins/` and its callers:

| Fact | Count | Where |
|---|---|---|
| Builtin hooks that read stdin themselves (`json.load(sys.stdin)`) | 18 of 18 | `hooks/builtins/*.py` |
| Hooks that build their `hookSpecificOutput` / `systemMessage` document by hand | 7 | same |
| Hooks that hardcode `get_agent("claude-code")` | 9 | `pre_tool_use_security.py:314`, `context_inject.py:754`, `session_end.py:89`, `session_export.py:44`, … |
| Modules that read the global `cfg.agent.type` | 18 | hooks, `cli/*`, `deploy/engine.py`, `monitoring/statusline.py` |
| Distinct blocking mechanisms | 2 | stderr + `exit 2` (`pre_tool_use_security`, `pre_tool_use_git_scope`); `{"decision": "block"}` on stdout with exit 0 (`stop_verify_guard`) |

The hook command the agent runs is `lh hook <name>` (`deploy/engine.py:hook_command`),
which imports the builtin and calls its `main()`. `main()` reads stdin, decides,
prints, exits. The adapter appears nowhere on that path.

Two further consequences of the same fact:

- `_shared.py:profile_name()` identifies the running profile by reading
  `get_agent(cfg.agent.type).env_var()` from the environment and matching it
  against `profiles.*.config_dir`. The moment `agent` becomes a per-profile
  field, that resolution is circular: the agent is needed to find the profile
  and the profile is needed to know the agent.
- `_shared.py:_TRANSCRIPT_KEYS = ("transcript_path", "transcriptPath", "input")`
  is already an ad-hoc translation layer, growing one key per agent, in a
  helper that was meant to be agent-neutral.

ADR-032 closed seven leaks. The `get_agent("claude-code")` literal in nine hooks
is the eighth, and the global `cfg.agent.type` is the ninth. Neither was in
ADR-032's table because ADR-032 audited the deploy side only.

### `AGENTS.md` is a real standard that Claude Code does not implement

`AGENTS.md` was formalised in 2025-08 and donated to the Agentic AI Foundation in
2025-12. Codex, opencode, Amp, Crush, `dsh` and — per its bundle — Copilot CLI
all read it. Several read `AGENTS.md` *and* `CLAUDE.md` together; the formats
stack rather than compete. Claude Code reads only `CLAUDE.md`.

`system_doc_name() -> str` cannot express "two files, concatenated".
ADR-032 deferred exactly this and named the deferral; four agents now force it.

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
caller (`deploy/engine.py:deploy_mcp_servers`) does `json.loads` / `json.dumps`
on the target file, and Codex's target is `config.toml`.

## Decision

### 1. `lh hook` becomes the runner, and it knows its profile

This is the decision the first draft lacked, and every other one depends on it.

`deploy` writes the hook command as `lh hook <name> --profile <profile>`.
The profile — not an environment variable, not a global config key — is the
one fact a running hook needs, because the profile names the agent, the config
dir, the memory scope and the metrics label.

`lh hook` then does what the 18 hooks do today by hand:

```
stdin  ──► adapter.parse_hook_input(raw)  ──► HookEvent
                                                 │
                                          builtin.main(event) ──► HookDecision
                                                 │
       ◄── adapter.format_hook_output(decision) ◄┘
       (stdout document + exit code)
```

Builtins change signature from `main() -> None` to
`main(event: HookEvent) -> HookDecision`. The Claude Code adapter's
`parse_hook_input` and `format_hook_output` are identity, so the wire bytes
Claude Code sees do not change; that identity is the acceptance test for the
migration (see verification gates).

`_shared.py:profile_name()`, `_TRANSCRIPT_KEYS`, and the nine
`get_agent("claude-code")` literals are deleted by this step, not worked around.

### 2. `HookEvent` and `HookDecision`, including the exit code

```python
@dataclass(frozen=True)
class HookEvent:
    event: str                      # canonical name
    profile: str
    session_id: str
    cwd: Path
    transcript_path: Path | None
    tool_name: str | None = None
    tool_input: dict | None = None
    tool_use_id: str | None = None
    tool_response: dict | None = None
    prompt: str | None = None
    permission_mode: str | None = None
    source: str | None = None       # session_start: startup|resume|clear|compact
    trigger: str | None = None      # pre_compact: manual|auto
    stop_hook_active: bool = False
    message: str | None = None      # notification
    raw: dict | None = None         # untranslated payload; adapters only


class Verdict(StrEnum):
    ALLOW = "allow"
    DENY = "deny"
    ASK = "ask"
    BLOCK = "block"                 # stop-class events: keep the agent working


@dataclass(frozen=True)
class HookDecision:
    verdict: Verdict = Verdict.ALLOW
    reason: str = ""
    additional_context: str = ""
    system_message: str = ""
    stop: bool = False              # `continue: false`
    suppress_output: bool = False


def format_hook_output(self, event: HookEvent, decision: HookDecision) -> tuple[dict | str | None, int]:
    """Normalised decision -> (document for stdout, exit code)."""
```

The return type is a pair because **the exit code is part of the wire**.
Claude Code reads exit 2 on `PreToolUse` as a refusal and ignores stdout in that
case; it reads `{"decision": "block"}` with exit 0 on `Stop`. A method returning
only a dict cannot express the first, and the first is how every blocking hook
in this repo works. `pre_compact` emits plain text, which is why the document
is `dict | str | None`.

`HookEvent` carries every field a Claude Code payload can name. The first
draft left out `source`, `trigger`, `stop_hook_active`, `tool_use_id` and
`message`; a hook needing one of those would have reached into `raw`, and at
that point the normalisation is a fiction. `raw` exists for adapters, not for
hooks, and a test asserts no builtin reads it.

### 3. Hook support is declared per event, and so is the ability to block

```python
@dataclass(frozen=True)
class HookSupport:
    native_name: str
    can_block: bool                 # the agent honours a deny/block verdict here

def hook_events(self) -> dict[str, HookSupport]:
    """Canonical event name -> how this agent delivers it. Absent = unsupported."""
```

`supported_hooks()` becomes `hook_events().keys()`, which also makes it honest:
today it returns canonical names while `generate_hook_config` re-maps them in a
second literal, so the mapping exists twice.

The first draft declared one `HookDelivery` tier per agent (`NATIVE` /
`TRANSLATED` / `NONE`). That is too coarse in both directions. Copilot's local
session logs show `postToolUse`, `userPromptSubmitted`, `notification` and
`agentStop` firing, and its bundle names `preToolUse` — but not `postCompact`;
opencode has no hooks at all. Support is a property of the (agent, event) pair.

`can_block` is the property that matters. A `PreToolUse` hook that runs but
whose deny is ignored is worse than no hook: `pre_tool_use_security` reports
success, the audit log records a block, and the command runs. `lh doctor`
reports, per profile, which of the three blocking hooks are actually enforced.

The tier survives only as a derived label for `lh doctor`: `native` when every
`parse`/`format` is identity, `translated` otherwise, `none` when
`hook_events()` is empty. A `none` agent is not a failure: `lh deploy` writes no
hook config for it and `lh doctor` reports the absence explicitly, replacing
today's behaviour where `generate_hook_config` drops an unsupported event with
no output.

**Out of scope, deliberately:** generating a JavaScript plugin shim so that
agents with a plugin runtime but no hooks (opencode, Amp) can reach `lh hook`.
It is a code generator in a Python project and a second hook mechanism to
maintain. Revisit as its own ADR once a non-identity adapter ships.

### 4. Hook and MCP config are artifacts the adapter names and serialises

```python
@dataclass(frozen=True)
class ConfigArtifact:
    relative_path: Path             # inside the profile's config dir
    content: str                    # already serialised
    merge_key: str | None = None    # top-level key the harness owns, for read-modify-write

def hook_config(self, hooks: dict[str, list[HookEntry]]) -> list[ConfigArtifact]: ...
def mcp_config(self, servers: dict[str, dict]) -> list[ConfigArtifact]: ...
```

`deploy/engine.py:deploy_hooks` hardcodes `settings.json` and merges with a
function shaped like Claude Code's `matcher` / `hooks[]` block. Codex wants a
separate `hooks.json`; Copilot wants one file per hook set under `hooks/`;
Codex's MCP block lives in TOML. A `dict` return cannot express "N files in
two formats", so `generate_hook_config` and `generate_mcp_config` are replaced,
not extended. The engine's job shrinks to writing artifacts and preserving
foreign entries under `merge_key`, which is the part that is genuinely
agent-neutral.

The existing repair logic — entries Claude Code would reject, backups, the
"preserved N entries not managed by the harness" report — moves behind the
Claude Code adapter's `merge_key` handling. It stays byte-identical for
existing profiles; that identity is the acceptance test.

### 5. Codex hook trust is a config value, not a lifecycle method

Codex persists a per-hook trust status and refuses to run a hook whose content
changed until it is re-trusted. From the 0.154.0 binary: trust is written
through `config/batchWrite` into the user `config.toml`, the TUI offers "Trust
all and continue" / "Continue without trusting (hooks won't run)", and there is
both a CLI flag `--dangerously-bypass-hook-trust` and a config override
`bypass_hook_trust` ("must be a boolean"), documented as "intended only for
automation that already vets hook sources".

The harness *is* that automation. The Codex adapter therefore emits
`bypass_hook_trust = true` as part of its `ConfigArtifact` for `config.toml`,
and there is no `post_deploy()`. The first draft's method would have leaked one
agent's concept into the Protocol to solve a problem the agent already exposes
as a config key.

This still has to be observed, not inferred: deploy with the key absent, change
a hook's command, start a session, confirm the hook is skipped; then deploy with
the key present and confirm it fires. An adapter whose trust handling was never
seen to matter is an adapter whose hooks are not known to run.

### 6. System docs become a list, without a scope field yet

```python
def system_docs(self) -> list[str]: ...
```

`system_doc_name() -> str` is removed rather than kept alongside. Two methods
answering one question is the failure mode the repo's own gate names — *every
reader of a derived answer resolves it the same way* — and the segmented
`<name>.head.md` / `<name>.tail.md` lookup in `sync_agent_md.py` is exactly such a
reader.

The first draft attached `scope: Literal["global", "repo"]` to each entry. No
consumer exists for `"repo"`: the harness writes system docs into the profile's
config dir and nowhere else, and it does not manage files inside user
repositories. A field with no reader is a config promise with no
implementation, which the repo's gates forbid. The scope returns when `lh
deploy` learns to write into a repo, as its own decision.

### 7. Config: a profile is an (agent, identity) pair

```toml
[profiles.personal]
config_dir = "~/.agent-personal"
agent = "claude-code"

[profiles.work]
config_dir = "~/.agent-work"
agent = "claude-code"

[profiles.work-copilot]
config_dir = "~/.agent-work-copilot"
agent = "copilot"
```

`[agent].type` stays as the default for profiles that do not set `agent`, so
existing configs keep working unchanged.

**This changes ADR-035.** The registry declares the agent as
`Cardinality.ONE` at `config_path="agent.type"` (`plugins/builtins.py:144`).
With a per-profile field the true cardinality is *one per profile*, which the
registry cannot express. The registry gains a `per_profile: bool` on
`Capability`, and `lh doctor` / `lh selftest` iterate profiles for those. The
18 readers of `cfg.agent.type` move to a single `agent_for_profile(cfg, name)`
in `core/config.py`, which is the one importable place the gate asks for.

**`memory_key` is dropped from this design.** The first draft added it so that
two profiles could share memory. Since 2026-08-18 the knowledge store is keyed
by git remote, not by profile; nothing profile-scoped remains except the
metrics `profile` label and the legacy `<profile>/projects/*/memory` dirs that
`lh memory migrate` exists to drain. A key that keys nothing is a config
promise with no implementation. If a profile-scoped resource reappears, it
gets its own decision with the resource named.

### 8. Permissions are per-agent by design

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

Every row is marked with how it was established:

- `binary` — read from the installed binary's strings, on this machine.
- `log` — observed in a session log on this machine, with the version that wrote it.
- `source` — vendor docs or source, **not confirmed against a running binary**.
- `none` — not observed at all; the first draft's `local` label was wrong.

| | Claude Code | Codex 0.154.0 | Copilot CLI 1.0.83 | opencode |
|---|---|---|---|---|
| `env_var()` | `CLAUDE_CONFIG_DIR` | `CODEX_HOME` (binary) | `COPILOT_HOME` (binary) | `OPENCODE_CONFIG_DIR` (source) |
| config file | `settings.json` | `config.toml` (binary) | `config.json` (present on disk) | `opencode.json(c)` (source) |
| `system_docs()` | `CLAUDE.md` | `AGENTS.md` (source) | `.github/copilot-instructions.md`, `AGENTS.md`, `CLAUDE.md` (binary, 1.0.40 bundle) | `AGENTS.md` + `CLAUDE.md` (source) |
| hook events | 10 canonical | 12 incl. `Interrupt`, snake_case aliases (binary) | 12 camelCase incl. `errorOccurred` (binary, 1.0.40 bundle); 4 seen firing (log, 1.0.40) | none (source) |
| hook config | `settings.json:hooks` | `hooks.json`, `.codex/hooks` (binary) | `.github/hooks` (binary, 1.0.40); `~/.copilot/hooks/` exists and is **empty** (none) | plugins in JS/TS (source) |
| hook trust | n/a | `bypass_hook_trust` config + `--dangerously-bypass-hook-trust` (binary) | n/a | n/a |
| MCP | `.claude.json` | `config.toml` `[mcp_servers.<id>]` (binary) | `mcp-config.json` (present on disk) | `opencode.json` `mcp` (source) |
| transcript | `projects/**/*.jsonl` | `sessions/…/rollout-*.jsonl` (source) — **migration to SQLite in flight**: `rollout-migrationsstaged`, `background_paginated_rollout_migration`, `state_5.sqlite` (binary + disk) | `session-state/<uuid>/events.jsonl` (log, 1.0.40, newest 2026-05-14) plus `session-store.db` (disk) | SQLite + JSON, undocumented (source) |
| headless | `-p --output-format json` | `codex exec --json` (binary); `--oss` with ollama/lmstudio (binary) | `-p` (source) | `opencode run --format json`, `serve` (source) |

Two facts about the Copilot column change what can be claimed from it:

- The 1.0.83 cask binary is a launcher. Its strings contain no hook vocabulary
  at all; the application is `~/.copilot/pkg/universal/1.0.40/app.js`, which is
  where every `binary` mark in that column comes from. Nothing about 1.0.83's
  behaviour has been observed.
- The newest local session log predates the installed version by four months.
  The four hook types seen firing are 1.0.40 behaviour.

Codex's `sessions/` layout has not been observed either: no session has run on
this machine, `~/.codex` holds only SQLite state, and the binary carries
rollout-migration strings. The transcript row is a claim about a moving target.

## What the existing profile content costs to port

Measured against the deployed profile sources rather than estimated:

| Asset | Portable as-is | Work |
|---|---|---|
| Hooks (Python, invoked as `lh hook <name>`) | yes, after decision 1 | the runner migration is the work; the declaration is generated |
| MCP servers | yes | none — already declared in `config.toml` |
| Skills (`SKILL.md` directories) | yes | placement only; `~/.agents/skills` scanned by Codex and opencode (source) |
| Slash commands (Markdown + frontmatter) | yes | placement only |
| System document | 193 of 199 lines | a split, not a rewrite |
| Permissions | no | per-agent, by the decision above |

The six agent-specific lines reference `TaskCreate`/`TodoWrite`, the subagent
tool's model routing, and `/rewind` / `/compact` / `/clear`. Everything else —
identity, writing style, prohibitions, stack defaults, context economy, the
memory stack — applies to any agent unchanged.

So the system document gains a **second axis**, not a rewrite. It is split by
identity today (`head` / `common` / `tail`); it gains a split by agent, and those
six lines move to an agent-specific segment. `sync_agent_md.py` assembles both.

## Alternatives considered

- **Six Protocol methods, hooks unchanged (the first draft).** Rejected after
  measuring: 18 hooks read stdin directly and nothing on the hook's execution
  path consults the adapter, so the methods would exist without a caller. The
  runner is the design; the Protocol methods are its interface.

- **Identify the agent at runtime from the environment** (each adapter's
  `env_var()` present in the hook's environment). Rejected: it is what
  `profile_name()` does today and it becomes circular once the agent is
  per-profile. The profile on the command line is one fact, written once by
  the same deploy that knows it.

- **One `HookDelivery` tier per agent.** Rejected as too coarse: support and
  blocking are properties of (agent, event), and the case that matters — a
  `PreToolUse` whose deny is ignored — is invisible at agent granularity.

- **`post_deploy()` for Codex hook trust.** Rejected: the binary exposes trust
  bypass as a config key, which the adapter already serialises. A lifecycle
  method would generalise one agent's workaround into the Protocol.

- **`format_hook_output -> dict`.** Rejected: cannot express exit 2, which is
  how two of the three blocking hooks block.

- **`memory_key` / `shares_memory_with`.** Dropped: no profile-keyed memory
  exists since the knowledge store moved to git-remote keys.

- **`SystemDoc.scope`.** Dropped until a consumer exists.

- **Invent a canonical event vocabulary.** Unnecessary: the harness already has
  one and the ecosystem independently converged on it.

- **Adopt ACP as the abstraction.** Rejected on scope, not on quality. ACP covers
  the editor↔agent surface and explicitly does not cover config deployment or
  telemetry — the two things this framework is.

- **Unify the permission model.** Rejected. Four genuinely different conceptual
  models, and a permission abstraction that quietly fails to apply is worse than
  no abstraction.

- **Generate a JS plugin shim for agents without hooks.** Deferred, not
  rejected. Revisit once a non-identity adapter has proven the normalised
  payload against a second wire format.

## Consequences

**Positive**

- The ADR-004 guarantee becomes testable for the first time, against a real
  adapter rather than a `NullAdapter`.
- The hook implementations — the bulk of the framework's value — are written once
  and run on every agent whose `hook_events()` names the event.
- Features degrade explicitly instead of silently. An agent without hooks is a
  reported state; a hook that cannot block is a reported state.
- Nine hardcoded `get_agent("claude-code")`, one ad-hoc key-translation tuple,
  a circular profile resolver and two duplicated event-name literals are deleted.
- `TranscriptReader` (below) collapses transcript parsing that is currently
  spread across 20 modules, not the four the first draft counted.

**Negative**

- Every one of the 18 builtin hooks changes signature. This is the single
  largest step and the reason the sequence puts it second.
- `system_doc_name()` removal has a blast radius across `sync_agent_md.py`,
  `cli/profile_cmd.py`, `deploy/defaults.py` and `plugins/capabilities.py`.
- ADR-035's registry gains a per-profile dimension, which touches `lh doctor`,
  `lh selftest` and the TUI design.
- Every adapter now has a correctness property that no unit test can establish:
  whether its hooks actually fire and actually block. That has to be verified
  against the installed binary, per agent, per release.

## Scope and kill criteria

This is infrastructure for agents that are not yet in daily use: Codex is
installed without a subscription, Copilot only in the work profile. ADR-035's
argument against machinery with no consumer applies here with the same force.

- **Baseline:** zero sessions on any non-Claude agent through the harness.
- **Horizon:** eight weeks after the Codex adapter merges.
- **Adoption check:** sessions per week on a non-Claude profile, from the
  metrics store's `profile` label.
- **Kill threshold:** fewer than five such sessions in the last four weeks of
  the horizon. Below it, the adapters are removed and the runner (decision 1)
  stays — it is a correctness improvement for Claude Code on its own.

## `TranscriptReader` as a separate optional Protocol

Modelled on `HeadlessAgent`: an agent with no readable transcript does not
implement it, and `session_export` skips it rather than parsing something whose
shape it is guessing.

```python
@runtime_checkable
class TranscriptReader(Protocol):
    def locate_sessions(self, since: datetime | None) -> Iterator[Path]: ...
    def read(self, path: Path) -> Iterator[TranscriptEvent]: ...
```

The on-disk formats share nothing. The *concepts* — turn, tool call, tokens,
cost — are common, and that is what `TranscriptEvent` normalises. Twenty
modules touch `.jsonl` today (`knowledge/*`, `monitoring/*`, `core/memory_store.py`, `core/memory_migration.py`,
`core/reconcile.py`, four CLI commands and five hooks); the reader is where they
collapse. It is last in the sequence because both non-Claude transcript
formats are in migration and a reader written against either today is written
against a version that will not ship.

## Implementation sequence

Ordered so each step is independently reviewable, the runner lands before any
adapter needs it, and Claude Code behaviour is byte-identical at every step.

1. `HookEvent`, `HookDecision`, `Verdict`, `HookSupport`, `ConfigArtifact` and
   the Protocol methods in `agents/base.py`. `ClaudeCodeAdapter` implements
   them with today's hardcoded values extracted; `parse_hook_input` and
   `format_hook_output` are identity. Type-check only.
2. **`lh hook <name> --profile <p>` becomes the runner.** Migrate the 18 builtins
   to `main(event) -> HookDecision`. Golden test per hook: the bytes on stdout
   and the exit code are identical before and after, for every branch the hook
   has. Delete `profile_name()`, `_TRANSCRIPT_KEYS` and the nine literals.
3. `agent` per profile, `agent_for_profile()`, `per_profile` on `Capability`,
   the 18 `cfg.agent.type` readers. Full save/load/save/load round trip on the
   new-document and merge-on-existing paths.
4. `hook_config()` / `mcp_config()` returning artifacts; `deploy_hooks` and
   `deploy_mcp_servers` write artifacts. Existing `settings.json` and
   `.claude.json` output byte-identical.
5. `system_docs()` replaces `system_doc_name()`; update the four call sites.
6. **`CodexAdapter`**, verified with `--oss` against a local model so no account
   is needed: deploy, observe a hook fire, observe `pre_tool_use_security`
   refuse a command, observe the trust-bypass key matter (decision 5).
7. `hook_events()` surfaced in `lh doctor` per profile, with `can_block` per
   blocking hook.
8. **`CopilotAdapter`**, only after running 1.0.83 once and re-extracting its
   event schema from a fresh `events.jsonl`. The first non-identity
   `parse_hook_input` / `format_hook_output`, and the first chance for the
   normalised payload to be proven wrong.
9. `TranscriptReader`, Claude Code first, the others when their storage stops
   moving.

## Verification gates

These are checks, not principles. Each one corresponds to a way this design can
ship broken while every test passes.

- **The runner migration is proven by bytes, not by tests passing.** For each
  builtin, capture stdout and exit code on every branch before the migration;
  assert identity after. A hook whose golden file was never captured was never
  migrated safely.
- **A hook that runs is not a hook that blocks.** For every (adapter, event)
  with `can_block=True`, exercise the exit-2 or block path against the real
  binary and assert the agent refused the action. Then flip `can_block` to
  `False` in the adapter and assert `lh doctor` reports the hook unenforced.
- **A written hook file is not an installed hook.** Observe the Codex untrusted
  case before claiming the bypass key works: change a hook's command with the
  key absent and watch it be skipped.
- **Adapters are verified against installed binaries, not docs.** Every value in
  the per-agent reference marked `source` or `none` is a claim awaiting
  confirmation. Vendor documentation lagged the binary in more than one case
  during this survey, and the first draft of this document mislabelled two
  Copilot rows as locally observed when one was an empty directory.
- **A transcript schema is only valid for the version it was read from.** Pin
  the agent version alongside any parser, and re-extract on upgrade. Both
  non-Claude formats are in migration at the time of writing.
- **`raw` is for adapters.** A test greps every builtin for `event.raw` and
  fails on any hit.
- **A static list that should mirror the registry is derived from it.**
  `supported_hooks()` is `hook_events().keys()`, never a second literal, with a
  test asserting the two cannot diverge.
- **The kill criteria are measured at the horizon**, from the metrics store,
  not from memory.

## Open questions

- Whether `codex exec` lets the caller pin a new session id, or only resume an
  existing one. Determines whether `CodexAdapter` can implement
  `SessionPinningAgent` or must reconcile the id after the fact.
- The minimum Codex version that carries the hook system and the
  `bypass_hook_trust` key. The adapter should probe rather than assume.
- Where Codex's transcript will live once the rollout-to-SQLite migration
  lands, and whether the SQLite schema (`state_5`) is stable enough to read.
- Whether Copilot's 1.0.83 hook input and event schema match the 1.0.40 bundle
  this document was read from. Nothing about 1.0.83 has been observed.
- Whether Copilot honours `permissionDecision: "deny"` on `preToolUse` — the
  literal exists in the bundle; enforcement has not been seen.
- Whether opencode's session storage is stable enough to read at all, or whether
  its `serve` HTTP API is the only defensible source.

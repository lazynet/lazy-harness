# Codex as a second agent: two agent surfaces live in one profile

**Status:** proposed
**Date:** 2026-09-09
**Decision record:** [ADR-040](../adrs/040-codex-agent-adapter.md)
**Relates to:** [ADR-004](../adrs/004-agent-adapter-pattern.md) (agent adapter pattern), [ADR-032](../adrs/032-agent-adapter-completeness.md) (adapter completeness), [ADR-009](../adrs/009-profile-symlink-deploy.md) (profile symlink deploy), [ADR-031](../adrs/031-default-hooks-merge.md) (default hooks merge), [ADR-035](../adrs/035-capability-registry.md) (capability registry), [ADR-039](../adrs/039-role-routed-inference.md) (role-routed inference — the *inference* axis, deliberately not this one)

## Scope

This is the first of three specs. It covers **making Codex a deployable agent of the harness**: config, adapter, hook and MCP deployment, and launching. It does not cover headless invocation or transcript-derived features, which need a running binary to specify honestly. See [Out of scope](#out-of-scope) for the split and the reason.

## Problem

ADR-004 promised that adding a second agent would be "one new file, one registry entry, zero changes elsewhere." ADR-032 closed seven leaks to make that promise true. Attempting the second agent for real surfaces three things that promise did not anticipate.

### The config cannot express two agents at once

`[agent].type` is a single global string (`core/config.py:41`) and `ProfileEntry.config_dir` is a single path (`core/config.py:28`). Together they encode "one agent, one directory per profile." Running Claude Code and Codex side by side in the same profile has no representation: whichever value `[agent].type` holds is the only agent `lh deploy` writes for, and the only binary `lh run` can launch.

### Hook deployment is written in Claude's file format, outside the adapter

`generate_hook_config` lives in the adapter, correctly. But everything that turns its return value into a file does not:

```python
# deploy/engine.py:200-241  (abridged)
settings_file = target_dir / "settings.json"          # filename hardcoded
settings = json.loads(settings_file.read_text())      # format hardcoded
settings["hooks"] = merged
settings_file.write_text(json.dumps(settings, indent=2) + "\n")
```

Codex reads `[[hooks.<Event>]]` from `$CODEX_HOME/config.toml`, a TOML file it shares with `[mcp_servers.*]`. Neither the filename, the parser, nor the serializer is reachable from an adapter. This is **leak L8**, unlisted by ADR-032.

### Built-in hooks are written in Claude's tool vocabulary

The tool-use hooks branch on literal Claude tool names:

| Hook | Line | Predicate |
|---|---|---|
| `pre_tool_use_read_size` | `builtins/pre_tool_use_read_size.py:79` | `payload["tool_name"] != "Read"` → exit |
| `post_tool_use_format` | `builtins/post_tool_use_format.py:34` | `tool_name not in ("Edit", "Write")` → exit |
| `pre_tool_use_security` | `builtins/pre_tool_use_security.py:183,322` | `FILE_TOOLS = {"Read","Edit","Write","NotebookEdit"}`, `if tool == "Bash"` |

Codex reports `tool_name: "apply_patch"` for a file edit. Under Codex, `post_tool_use_format` matches nothing and exits 0 — a formatter that never runs, with no error anywhere. `pre_tool_use_security` is the same shape with worse stakes: a security hook that falls through every branch **allows everything, silently**. This is **leak L9**, and it is the one that fails green.

That last failure mode is the one this repo's verification gates name directly: *"A test that passes with and without the thing it claims to cover, covers nothing."* A hook deployed to Codex today would satisfy every existing test and protect nothing.

## What is verified and what is assumed

Codex is **not installed on the development machine**. Everything below is sourced from the published configuration reference and the hooks reference, not from observed behaviour. The table separates the two so no reader mistakes a documented claim for a measured one.

**Verified against this repository** (read from source at the cited line):

| Fact | Evidence |
|---|---|
| `AgentAdapter` has 12 methods; `HeadlessAgent` and `SessionPinningAgent` are separate opt-in Protocols | `agents/base.py` |
| `deploy_hooks` hardcodes `settings.json`, `json.loads`, `json.dumps` | `deploy/engine.py:200-241` |
| `_merge_hook_blocks` operates on a plain `dict` and identifies harness-owned entries by the `lazy_harness/hooks/builtins/` substring in the command | `deploy/engine.py:79-158` |
| `merge_with_defaults` already drops system-doc hooks when `agent.system_doc_name()` is empty | `deploy/defaults.py:45-77` |
| `Capability.requires_system_doc` already gates a hook on an adapter trait | `plugins/capabilities.py:77` |
| `tomlkit` is already a dependency and `core/config.py:917` already implements a trivia-preserving deep merge | `pyproject.toml:13`, `core/config.py:917-1022` |
| `~/.config/lazy-harness/config.toml` is a chezmoi `.tmpl` | `chezmoi source-path` → `dotfiles/dot_config/lazy-harness/config.toml.tmpl` |

**Assumed from Codex documentation** — each must be re-checked against a running binary before the corresponding code is written:

| # | Assumption | Source | If wrong |
|---|---|---|---|
| A1 | `CODEX_HOME` selects the config directory, defaulting to `~/.codex` | config reference | Profile isolation breaks; every profile writes the same file |
| A2 | Hooks live in `config.toml` as `[[hooks.<Event>]]` with a `matcher` and a nested `hooks` array of `{type="command", command=…}` | hooks reference | `generate_hook_config` emits a shape Codex rejects |
| A3 | `hooks.json` in the same directory is an equivalent alternative to inline TOML | hooks reference | Fallback path unavailable (see [Alternatives](#alternatives-considered)) |
| A4 | Event names are `SessionStart`, `SessionEnd`, `PreToolUse`, `PostToolUse`, `PermissionRequest`, `PreCompact`, `PostCompact`, `UserPromptSubmit`, `SubagentStart`, `SubagentStop`, `Stop`, `Interrupt` — and there is **no** `Notification` | hooks reference | The event map drops or invents an event |
| A5 | Hook stdin carries `session_id`, `cwd`, `hook_event_name`, `transcript_path`, `model`, `permission_mode`, plus `tool_name`/`tool_input`/`tool_use_id` on tool events | hooks reference | Every builtin's payload read degrades to its default |
| A6 | Exit 2 blocks; stdout JSON accepts `additionalContext`, `systemMessage`, `continue`, `decision` | hooks reference | `context_inject` and `pre_tool_use_security` lose their channel |
| A7 | MCP servers live in the same `config.toml` under `[mcp_servers.<id>]` with `command`/`args`/`env` | config reference | MCP deploy writes an ignored table |
| A8 | `features.hooks` defaults to enabled and can be forced off in `requirements.toml` | config reference | Hooks deploy successfully and never fire |
| A9 | A file edit reports `tool_name: "apply_patch"`, while a matcher may spell it `apply_patch`, `Edit` or `Write` | community hooks reference | The L9 vocabulary map is wrong in its most important entry |
| A10 | A shell call matches the matcher `Bash`; **the `tool_name` the payload carries for it is unconfirmed** | community hooks reference | `pre_tool_use_security` falls through and allows everything |
| A11 | Rollout/session files live under `$CODEX_HOME/sessions/`; `history.jsonl` holds history | config reference | Only affects PRJ-3, which is out of scope here |

**A10 is the assumption that decides whether the security hook is safe to deploy.** It is also the one the docs are least explicit about — the matcher vocabulary and the payload vocabulary are described in different places and are not stated to be the same. The verification plan treats it as a hard gate, not a detail.

## Decision

### 1. A profile declares a config directory per agent

`ProfileEntry` gains an `agents` mapping. `[agent]` gains `enabled`.

```toml
[agent]
type = "claude-code"                      # the default for commands that need exactly one
enabled = ["claude-code", "codex"]        # every agent lh deploy writes for

[profiles.lazy]
roots = ["~/repos/lazy"]
lazynorth_doc = "LazyNorth-Lazy.md"

[profiles.lazy.agents.claude-code]
config_dir = "~/.claude-lazy"

[profiles.lazy.agents.codex]
config_dir = "~/.codex-lazy"

[profiles.flex]                            # legacy shape, still valid
config_dir = "~/.claude-flex"
roots = ["~/repos/flex"]
```

```python
@dataclass
class ProfileAgentEntry:
    config_dir: str = ""


@dataclass
class ProfileEntry:
    config_dir: str = ""                    # legacy; reads as agents[cfg.agent.type]
    roots: list[str] = field(default_factory=list)
    lazynorth_doc: str = ""
    agents: dict[str, ProfileAgentEntry] = field(default_factory=dict)

    def dir_for(self, agent_type: str) -> str | None:
        """Config dir for one agent, or None when this profile does not serve it."""
```

Three rules, and each exists to prevent a specific silent failure:

- **The flat `config_dir` is not deprecated; it is a shorthand.** At load time, a profile with a flat `config_dir` and no `agents` table is normalized to `agents = {cfg.agent.type: {config_dir: <flat>}}`. Martin's current config keeps working untouched, which matters because it lives in a chezmoi template.
- **Declaring both the flat key and an `agents` entry for the same agent is a load error**, not a precedence rule. Two sources for one path is how a reader and a writer end up disagreeing — the failure mode the gates already name.
- **An agent in `[agent].enabled` with no entry in a given profile is skipped for that profile, and `lh doctor` reports it.** A profile may legitimately serve only one agent; a *typo* in an agent name must not read as that.

`[agent].type` survives as the answer to "which agent when the caller named none" — `lh run` with no `--agent`, `lh exec` with no `--agent`. It is validated to be a member of `enabled`.

### 2. `CodexAdapter`

One new file, `agents/codex.py`, one registry entry. The values, with the assumption each rests on:

| Method | Value | Rests on |
|---|---|---|
| `name` | `"codex"` | — |
| `config_dir(d)` | `expand_path(d)` | — |
| `env_var()` | `"CODEX_HOME"` | A1 |
| `resolve_binary()` | `shutil.which("codex")`, skipping the `lh` entrypoint dir | — |
| `supported_hooks()` | the harness events Codex maps (below) | A4 |
| `generate_hook_config(h)` | `{"SessionStart": [{"matcher": …, "hooks": [{"type": "command", "command": …}]}]}` | A2 |
| `generate_mcp_config(s)` | `{"mcp_servers": {name: {command, args, env}}}` | A7 |
| `global_config_link()` | `Path.home() / ".codex"` | A1 |
| `mcp_config_file()` | `"config.toml"` | A7 |
| `session_dirs()` | `{"sessions": "sessions", "logs": "", "queue": ""}` | A11 |
| `system_doc_name()` | `"AGENTS.md"` | — |
| `process_name()` | `"codex"` | — |

Two of those three keys are `""` deliberately, and `""` already means "not available" to every caller (ADR-032). `queue` is empty because the compound-loop queue is a harness concept the adapter does not own, and PRJ-3 decides where a Codex queue lives. `logs` is empty because Codex's log location is a *config key* (`log_dir`), not a fixed subdirectory name — an adapter returning a constant here would be guessing at a value the user can change. Reading `log_dir` out of the deployed `config.toml` is possible and is PRJ-3's problem, since nothing in this spec consumes it.

**The event map is where the two agents actually differ.** The harness's internal vocabulary is snake_case (`agents/claude_code.py:78-89`); each adapter maps it to its own spelling.

| Harness event | Claude Code | Codex | Note |
|---|---|---|---|
| `session_start` | `SessionStart` | `SessionStart` | |
| `session_stop` | `Stop` | `Stop` | |
| `session_end` | `SessionEnd` | `SessionEnd` | |
| `pre_compact` | `PreCompact` | `PreCompact` | |
| `post_compact` | `PostCompact` | `PostCompact` | |
| `pre_tool_use` | `PreToolUse` | `PreToolUse` | |
| `post_tool_use` | `PostToolUse` | `PostToolUse` | |
| `user_prompt_submit` | `UserPromptSubmit` | `UserPromptSubmit` | |
| `permission_request` | `PermissionRequest` | `PermissionRequest` | |
| `notification` | `Notification` | — | dropped by the existing `if not cc_event: continue` |

The framework's existing behaviour on an unmapped event is a silent drop, which ADR-004 declared intentional forward-compat. Here it is also *backward* compat: a config written for Claude deploys to Codex minus the events Codex lacks, with no error and no invented event.

Codex's `SubagentStart`, `SubagentStop` and `Interrupt` have no harness event today. They are reachable through `[hooks.<event>].external` — which `deploy_hooks` already emits verbatim (`deploy/engine.py:190`) — without a schema change. Promoting any of them to a first-class harness event is a separate decision with its own builtins.

### 3. Closing L8: the adapter owns the settings file, not just its contents

The merge logic is genuinely generic and stays where it is. Only three things are agent-specific, and each becomes a Protocol method:

```python
def settings_file(self) -> str:
    """Filename inside config_dir that holds the hook configuration."""

def parse_settings(self, text: str) -> dict:
    """Parse that file. Must not raise: unparseable input returns {}."""

def serialize_settings(self, doc: dict, *, previous: str = "") -> str:
    """Render the merged document. `previous` is the file's prior text, so an
    implementation that can preserve comments and key order has what it needs."""
```

| | Claude Code | Codex |
|---|---|---|
| `settings_file()` | `"settings.json"` | `"config.toml"` |
| `parse_settings` | `json.loads` | `tomlkit.parse` |
| `serialize_settings` | `json.dumps(indent=2) + "\n"` | trivia-preserving overlay onto `previous` |

**`previous` is the parameter that earns its place.** `settings.json` is a generated file the harness owns; `~/.codex-lazy/config.toml` is a file the *user* writes, holding `model`, `sandbox_mode`, `[permissions.*]` and their comments. Round-tripping it through `tomli_w.dumps` would parse, serialize and validate perfectly while deleting every comment in the file — a clean exit code and a destroyed config, which is precisely the failure the gates describe as *"a tool's exit code is not proof of its effect."* The trivia-preserving merge already exists at `core/config.py:917`; `serialize_settings` reuses it rather than growing a second one.

`_merge_hook_blocks` and `_normalize_entry` need no change. Both operate on a plain `dict`, and the two agents' in-memory hook shapes are structurally identical: an event maps to a list of matcher groups, each with a `matcher` string and a `hooks` list of `{type, command}`. The null-matcher repair is a no-op under TOML (TOML has no null) and stays as written rather than growing a branch for a case that cannot occur.

**One ordering constraint is new.** Under Claude Code, `deploy_hooks` writes `settings.json` and `deploy_mcp_servers` writes `.claude.json` — different files, order irrelevant. Under Codex both write `config.toml`. Each must read-modify-write against the file as it is on disk at that moment, and `deploy` must not hold a parsed copy across the two calls. The verification plan tests exactly this: deploy twice and assert the second run preserves the first run's MCP table.

### 4. `lh deploy` iterates enabled agents

`deploy_hooks`, `deploy_mcp_servers` and the symlink deploy each grow an outer loop over `cfg.agent.enabled`, resolving the per-agent directory through `profile.dir_for(agent_type)` and skipping profiles that do not declare it.

`global_config_link()` is already per-adapter, so `~/.claude` and `~/.codex` are created independently and neither is special-cased.

`merge_with_defaults(user_hooks, agent)` is already parameterized by adapter and is called once per agent. It needs no change: `requires_system_doc` is satisfied by both agents (`CLAUDE.md` and `AGENTS.md`), so the system-doc hooks deploy to both.

### 5. Closing L9: canonical tool names

The hooks stop matching agent-native strings. A new Protocol method declares the mapping:

```python
def tool_aliases(self) -> dict[str, str]:
    """Agent-native `tool_name` values → the harness's canonical names.

    Canonical names are Claude Code's, because they are what every builtin
    already reads and what every `matcher` in a deployed config already says.
    An agent whose names already match returns {}.
    """
```

| Adapter | Value |
|---|---|
| `ClaudeCodeAdapter` | `{}` |
| `CodexAdapter` | `{"apply_patch": "Edit", "shell": "Bash", "local_shell": "Bash", "read_file": "Read"}` — **provisional, gated on A9/A10** |

`hooks/builtins/_shared.py` gains one helper that every tool-use hook routes through:

```python
def canonical_tool(payload: dict) -> str:
    """`tool_name` translated through the active adapter's alias table."""
```

Then `post_tool_use_format.py:34` becomes `if canonical_tool(payload) not in ("Edit", "Write")`, and the other two hooks change the same way. The literals stay Claude's; only the lookup moves.

**The failure this must not have is a missing alias reading as "some other tool".** A canonical name that is not in the table and is not already canonical means the adapter's map is incomplete, which is a registration bug, not a tool the hook should ignore. `pre_tool_use_security` treats an unrecognized `tool_name` as *not exempt* — it applies its path-based checks rather than falling through — so an incomplete map degrades toward blocking, never toward allowing.

### 6. `lh run --agent` and `lh exec --agent`

`LaunchPlan` already carries `adapter` (`agents/launch.py:34`). `resolve_launch` gains an `agent_override: str | None` and resolves the config dir through the profile's `agents` table instead of its flat `config_dir`. Both commands gain `--agent`, defaulting to `cfg.agent.type`.

`lh exec` refuses `--agent codex` in this spec: `CodexAdapter` does not implement `HeadlessAgent`, and `resolve_launch(require_headless=True)` already raises before locating the binary — the existing "refuse up front rather than exec something whose output we cannot parse" behaviour, unchanged. Making that refusal *stop* being correct is exactly what PRJ-2 delivers.

## Blast radius

| File | Change |
|---|---|
| `core/config.py` | `ProfileAgentEntry`, `ProfileEntry.agents` + `dir_for`, `AgentConfig.enabled`, normalization of the flat shape, the both-declared load error |
| `agents/base.py` | `settings_file`, `parse_settings`, `serialize_settings`, `tool_aliases` on the Protocol |
| `agents/claude_code.py` | the four new methods, returning today's hardcoded values |
| `agents/codex.py` | new |
| `agents/registry.py` | one entry; `NullAdapter` gains the four methods |
| `agents/launch.py` | `agent_override`, per-agent dir resolution |
| `deploy/engine.py` | outer loop over enabled agents; `settings.json`/`json` calls replaced by adapter calls |
| `hooks/builtins/_shared.py` | `canonical_tool` |
| `hooks/builtins/{pre_tool_use_read_size,post_tool_use_format,pre_tool_use_security}.py` | route `tool_name` through `canonical_tool` |
| `cli/{run_cmd,exec_cmd}.py` | `--agent` |
| `cli/doctor_cmd.py` | report enabled agents, per-profile coverage, and a missing binary per agent |
| `dotfiles/.../config.toml.tmpl` | the new `[profiles.lazy.agents.*]` tables — **edited in the chezmoi source, closed with `chezmoi apply`** |

`monitoring/statusline.py:57` derives a profile name from a `.claude-<x>` directory basename. It is untouched here and stays correct, because Claude Code remains the only agent that feeds it a statusline payload. PRJ-3 revisits it.

## Migration

No migration step. The flat `config_dir` normalizes at load time, so an untouched `config.toml` produces exactly today's behaviour: one agent, one directory, one set of deployed hooks. Opting in is adding two tables and one `enabled` line to the chezmoi source.

## Verification

Ordered so that each gate can fail before the work that depends on it is written.

**Before any adapter code:**

1. `uv tool install codex` (or the vendor's installer), then `codex --version`. Until this passes, A1–A11 are unverifiable and the adapter is not written.
2. Deploy a single no-op hook by hand to `~/.codex-probe/config.toml`, run one Codex turn with `CODEX_HOME=~/.codex-probe`, and **capture the raw stdin payload of each event to a file**. That capture, checked into `tests/fixtures/codex/`, is what A4, A5, A6, A9 and A10 are verified against — and what every parser test then runs on. A test written against a payload we invented proves only that we can parse our own invention.
3. From that capture, confirm A10 specifically: **what `tool_name` does a shell call carry?** If it is not `Bash`, the `tool_aliases` entry changes and `pre_tool_use_security` gets a regression test naming the real value.

**Adapter and deploy:**

4. `tests/agents/test_agent_protocol.py` already asserts every registered adapter satisfies the Protocol; it now covers four more methods and fails automatically if `CodexAdapter` or `NullAdapter` misses one.
5. **Parse generated output with Codex's own parser, not `tomlkit`.** Run `codex --config-check` (or the closest equivalent the binary offers; if none exists, start a session against the generated file and assert it does not fall back to defaults). A syntactically valid file that the target rejects at load time is this repo's most-repeated artifact failure.
6. Deploy twice. Assert the second run preserves the first run's `[mcp_servers.*]` table, and that a hand-written comment above `model = …` survives both.
7. Deploy with `[agent].enabled = ["claude-code"]` and assert nothing is written under `~/.codex-*`.
8. Deploy a profile that declares `claude-code` only while `enabled` names both; assert Codex is skipped and `lh doctor` says so.
9. Assert the flat-`config_dir` shape and the explicit-`agents` shape produce byte-identical `settings.json` for the Claude path.

**L9, in both directions:**

10. Feed `post_tool_use_format` a captured Codex `apply_patch` payload and assert the formatter runs. Then delete the alias entry and assert the test fails. A guard that cannot be proven absent was never proven present.
11. Feed `pre_tool_use_security` a captured Codex shell payload carrying a blocked command and assert exit 2. Then feed it a payload whose `tool_name` is a string absent from the alias table and assert it still applies path checks rather than exiting 0.

**Whole-suite:** `uv run pytest`, `uv run ruff check src tests`, `uv run --group docs mkdocs build --strict`, and `lh selftest` with both agents enabled.

**Never run `uv` against live profiles from a worktree.** Deploy with the installed tool; a worktree venv path baked into a deployed hook is a recorded failure here.

## Out of scope

Split out because they cannot be specified from documentation, not because they are lower value.

**PRJ-2 — Codex headless.** `HeadlessAgent` over `codex exec --json`: mapping `HEADLESS_TIERS` to Codex models, parsing the JSONL event stream (`thread.started`, `turn.completed.usage` with `input_tokens`, `cached_input_tokens`, `output_tokens`, `reasoning_output_tokens`), and `SessionPinningAgent` over `codex exec resume <thread_id>`. Blocked on a captured stream: `parse_headless_result` must not raise on any real output, and "any real output" is not knowable from a schema summary. Note that Codex reports token counts but no cost figure, where `ClaudeCodeAdapter` passes through Claude's own `total_cost_usd` verbatim and deliberately does not recompute it — so `HeadlessResult.cost_usd` is `None` for Codex until PRJ-3 supplies a pricing table. `reasoning_output_tokens` has no field in `HeadlessResult`; whether it folds into `output_tokens` or earns its own field is PRJ-2's call, and folding silently would corrupt a cost figure that prices reasoning differently.

**PRJ-3 — Transcript, memory and cost.** Session export, the compound loop, `metrics.db` ingest and OpenAI pricing. The largest of the three and the most dependent on real rollout files. Transcript parsing is not on the Protocol at all today (`knowledge/session_export.py` decodes Claude's project-dir naming scheme inline); extracting that seam is PRJ-3's central design question. The statusline is expected to stay Claude-only — Codex exposes `notify` and `tui.notifications`, neither of which is the payload-piped-to-a-command contract `monitoring/statusline.py` implements.

**Not planned.** Promoting `SubagentStart`, `SubagentStop` or `Interrupt` to first-class harness events; they are reachable through `external` hooks today and none has a builtin that wants them.

## Alternatives considered

**Derive the config directory by convention** (`~/.<agent>-<profile>`), adding no config at all. Rejected. `config_dir` is a value the user sets today; turning it into a convention the harness imposes silently relocates the directory of anyone whose value does not match the pattern. The explicit table costs three lines and keeps the path authoritative.

**One profile per agent** (`profiles.lazy` and `profiles.lazy-codex`, with `[agent].type` moved to the profile). Rejected on profile resolution: both would declare `roots = ["~/repos/lazy"]`, and resolution by cwd is precisely how `lh run` picks a profile. Two profiles matching one directory has no correct answer, and duplicating `roots` and `lazynorth_doc` forks the truth.

**Write Codex hooks to `hooks.json` instead of inline TOML** (A3). Tempting — it sidesteps the TOML writer and the shared-file ordering constraint, and `json.dumps` already works. Rejected because it splits the harness's output across two files for one agent while the MCP table still has to go into `config.toml`, so the TOML write path is needed regardless. Kept as the documented fallback if A2 turns out to be wrong or if trivia-preserving merge proves unreliable against Codex's parser.

**Register Codex as an `LLMBackend` rather than an `AgentAdapter`.** Rejected for the mirror image of ADR-039's reasoning. That ADR rejected registering Ollama as an `AgentAdapter` because an HTTP endpoint satisfies none of the subprocess-shaped Protocol. Codex is the opposite: a binary with a config dir, hooks, a system doc and a session lifecycle. It satisfies `AgentAdapter` almost exactly and `LLMBackend` barely at all. The two axes stay orthogonal — a user may run Codex as their agent and route distillation to Claude, or the reverse.

**Do L9 by rewriting the builtins' literals per agent.** Rejected. It duplicates the tool vocabulary across three hooks and two adapters, and the duplicate that drifts is a security hook. One alias table on the adapter is the only copy.

**Defer L9 and deploy the tool-use hooks to Codex anyway.** Rejected outright. `pre_tool_use_security` would exit 0 on every Codex call while `lh doctor` reported it ON. Shipping a security hook that is inert on one of two configured agents is worse than not deploying it there, because the report is what people act on.

# The agent contract

Supporting a second coding agent is not a plugin. It is a contract: what a hook
may decide, which of those decisions an agent actually honours, what it can be
asked to report, and which config documents it owns. That contract is
[ADR-041](https://github.com/lazynet/lazy-harness/blob/main/specs/adrs/041-multi-agent-hook-contract.md),
and this page is what it looks like from outside the code.

## One runner, one event shape

Every built-in hook is invoked the same way, whatever agent is running:

```bash
lh hook <name> --profile <profile>
```

The profile decides the adapter. The adapter parses the agent's native hook
payload into a canonical `HookEvent`, the hook returns a `HookDecision`, and the
adapter formats that decision back into the channels its agent actually reads.
A hook never touches stdin, never learns which agent it is running under, and
never parses a transcript itself.

This is why `--profile` matters more than it looks: before it existed, a hook
answered questions about the *global* agent while running under a different
one. Five defects of exactly that shape came out of the contract's acceptance
gate.

## The four vocabularies

The contract is small on purpose. Four enums carry everything agent-specific.

**`Verdict`** — what a hook may decide: `allow`, `deny`, `ask`, `block`. Not
every agent honours every verdict on every event, so an adapter declares per
event which ones it can express. A verdict an agent cannot honour is refused at
deploy time rather than discovered at runtime.

**`Operation`** — what a tool call *does*, in the three terms the built-ins
reason about: `run_command`, `read_file`, `modify_file`. Derived from what the
hooks consume, not from what a tool API offers. Each adapter maps its agent's
native tool names onto these.

**`Signal`** — what a hook needs to read out of a transcript: `messages`,
`tool_calls`, `token_usage`, `goal_status`. Declared as four named signals
rather than a single `requires_transcript: bool`, and that choice is the whole
point — a reader that delivers messages and tokens but has no concept of an
explicit goal must not silently re-enable a guard that would then pass every
session.

**`Bypass`** — how far a launch may step outside the permission prompts:
`enable`, `activate`, `no_sandbox`. See [the matrix](index.md#capability-matrix).

## Gaps are resolved before anything is written

Two kinds of gap exist between a hook and an agent, and `lh deploy` resolves
both before it writes a profile's config.

**Signal gaps — the hook is left out entirely.** `stop-verify-guard` needs
`goal_status`. Nothing in a Codex rollout marks an explicit goal, so
`CodexAdapter` declares three signals and rejects the fourth. Deploy omits the
hook from that profile's artifact and names the omission on stdout; `lh doctor`
reports the same gap from the same resolver, and an integration test asserts the
two agree in both directions.

Left installed instead, that hook would run on every Stop, find nothing to
verify, and pass — green because it *could not fail*. That is the failure mode
the mechanism exists to prevent.

**Operation gaps — the hook installs but is partly blind.** `lh doctor`'s
**Hook operations** section names each deployed hook whose declared operations
the profile's agent cannot produce. `pre-tool-use-security` loses `read_file`
on Codex, whose tool map has no read tool at all; `pre-tool-use-read-size`
declares nothing else, so it installs, is consulted on every tool call, and
passes all of them. The section says which of the two a row is. Closing it is
the agent's business, never the harness's.

## Per-profile resolution, everywhere

`agent_for_profile(cfg, profile)` is the single resolver: it reads
`[profiles.<name>].agent` and falls back to the global `[agent].type` only when
a profile does not declare one. Deploy's readers, the launcher, the hook runner,
the compound-loop worker and the CLI all go through it.

Three call sites still read the global agent, and each one is answering a
question that is itself global — the top-line `Agent:` display in `lh doctor`,
a statusline with no profile in scope, and a memory command behind an early
return taken whenever a profile is present. A test walks every built-in's AST
for a global `get_agent` call rather than grepping for a spelling, because the
grep missed two sites written as conditional expressions.

## The adapter surface

`AgentAdapter` is a `Protocol`. The required members cover identification
(`name`, `config_dir`, `env_var`, `resolve_binary`, `process_name`), hooks
(`supported_hooks`, `hook_events`, `parse_hook_input`, `format_hook_output`),
launch (`bypass_argv`), and the places the harness reads or writes
(`system_docs`, `skill_root`, `mcp_config_file`, `session_dirs`,
`credentials_file`, `global_config_link`, `default_home`). `default_home` is
where the agent keeps state with no profile — the last resort of runtime-dir
resolution — and is deliberately separate from the deploy's global link.

Five optional Protocols sit beside it, and an adapter is tested for each with
`isinstance` rather than by name — a capability test, never a hardcoded list:

| Protocol | What implementing it buys | Who has it |
|---|---|---|
| `ConfigPlanner` | `lh deploy` can write this agent's own config documents | all three |
| `TranscriptReader` | `lh metrics ingest` can meter this agent | Claude Code, Codex |
| `TranscriptIdentity` | rows carry the right session and project | Claude Code, Codex |
| `HeadlessAgent` | `lh exec` can run this agent non-interactively | Claude Code |
| `SessionPinningAgent` | a run can be pinned to an existing session | Claude Code |

`ConfigPlanner` is separate from the base Protocol because one `dict` return
cannot express "N files in two formats": Claude Code wants `settings.json` plus
`.claude.json`, Codex wants `hooks.json` plus a merged `config.toml`. One
`plan_config` call returns every write and delete for a profile, and the engine
refuses the **whole plan** — rather than locking a file — if any target's
`(mtime_ns, size)` moved between read and apply. Deletion keys on an ownership
stamp, not on the file existing
([ADR-042](https://github.com/lazynet/lazy-harness/blob/main/specs/adrs/042-multi-file-config-planning.md)).

## Tracing a dispatch

When a hook's behaviour under a given agent is in question, set
`LH_HOOK_TRACE=1`. The runner writes one dispatch line per invocation into the
agent's own runtime directory — for Codex, `$CODEX_HOME/logs/hooks.log`.

## Adding an agent

One adapter file, one registry entry. Nothing else in the framework touches
agent-specific concerns. What the contract asks in return is that every row be
**measured** — from a real run or a real log — rather than read off a vendor
doc. [`CopilotAdapter`](copilot.md) is the worked example of that discipline:
eleven hook event names encoded because sixteen candidates were tried and five
were rejected by the binary.

## See also

- [How hooks work](../how/hooks.md) — every built-in, with the per-agent notes inline.
- [How profiles and deploy work](../how/profiles-and-deploy.md) — the deploy flow end to end.
- [Portable assets](portable-assets.md) — what follows a profile across agents.
- [`lh doctor`](../reference/cli.md#lh-doctor) — every section that reports an agent gap.

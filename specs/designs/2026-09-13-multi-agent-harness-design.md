# Multi-agent harness: what actually has to be abstracted

**Status:** proposed (revision 3, 2026-09-13 — after external review by Codex CLI and Copilot CLI; every provider claim below re-verified against pinned vendor source, and every claim about this repo against the code)
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
| **Codex CLI** | Ships the identical payload field names (`session_id`, `turn_id`, `transcript_path`, `hook_event_name`, `tool_name`, `tool_input`, `tool_use_id`, `tool_response`, `permission_mode`, `stop_hook_active`) and the identical response field *names* (`hookSpecificOutput`, `permissionDecision`, `permissionDecisionReason`, `additionalContext`, `systemMessage`, `continue`, `stopReason`, `suppressOutput`). Also defines `CLAUDE_PLUGIN_ROOT` / `CLAUDE_PLUGIN_DATA` and bundles an importer for `.claude/settings.json`, `CLAUDE.md` and `.claude.json`. |
| **Copilot CLI** | The 1.0.40 application bundle carries `permissionDecision`, `permissionDecisionReason`, `additionalContext`, `systemMessage` and `"deny"`/`"ask"` literals. The *response* vocabulary is Claude Code's; the event names differ (`preToolUse`, `postToolUse`, `userPromptSubmitted`, `sessionStart`, `sessionEnd`, `agentStop`, `preCompact`, `subagentStart`, `subagentStop`, `permissionRequest`, `errorOccurred`, `notification`), and a PascalCase event name selects a separate Claude-compatible payload shape. |
| **Qwen Code** | A fork of gemini-cli that *abandoned its own upstream's* event names (`BeforeTool`/`AfterTool`) to adopt `PreToolUse`/`PostToolUse`/`UserPromptSubmit`/`SubagentStart`/`SubagentStop`/`PreCompact`/`PostCompact`. |
| **Crush** | Implements exactly one hook event, and named it `PreToolUse`. |
| **DeepSeek Harness (`dsh`)** | Defines no hook vocabulary of its own. Ships a plugin that executes an unmodified Claude Code `hooks.json`. |

The harness's own canonical vocabulary — `session_start`, `session_stop`,
`session_end`, `pre_compact`, `post_compact`, `pre_tool_use`, `post_tool_use`,
`notification`, `user_prompt_submit`, `permission_request` — matches Codex's
event *set* almost exactly, including the unusual members (`post_compact`,
`permission_request`). It does not match its casing: Codex accepts PascalCase
only.

```rust
// codex-rs/config/src/hook_config.rs @ 6b9826e (rust-v0.154.0)
#[serde(rename = "PreToolUse", default)] pub pre_tool_use: Vec<MatcherGroup>,
```

The first two drafts of this document claimed "snake_case aliases (binary)" for
Codex. That claim came from snake_case strings in the binary which are Rust
struct field names, not wire aliases. Nothing deserialises them.

**Consequence: the abstraction to build is wire translation, not concept
invention.** A canonical vocabulary designed in 2026-04 for one agent turned out
to name the same *events* the industry names. That collapses the cost of
inventing a vocabulary to zero. It does not collapse the cost of translation,
which the next section bounds, nor of the plumbing, which the one after
measures.

### Where the convergence stops: same names, different semantics

Every claim in this section is pinned to vendor source or current vendor docs.
The first two drafts asserted the opposite of each of them, in every case by
reading a *name* out of a binary and inferring a *behaviour*.

| Claim the earlier drafts made | What the source says |
|---|---|
| Codex ships "the identical response fields", so an identity adapter is plausible | Codex honours `deny` only. `allow` without `updatedInput` and `ask` are both rejected as `"unsupported permissionDecision"` and **fail open** (`codex-rs/hooks/src/events/pre_tool_use.rs:442,556` @ `6b9826e`). `allow` *with* `updatedInput` is an input rewrite, not an approval. |
| Claude Code "ignores stdout" on exit 2 | "Claude Code still reads any valid JSON output on stdout." Since v2.1.214, exit 2 with schema-invalid JSON still blocks, using stderr as the reason. |
| Exiting 0 silently is an `allow` | "Exit code 0 with no output means the hook has no decision to report… The hook can deny the call, but **staying silent doesn't approve it**." |
| Several agents read `AGENTS.md` *and* `CLAUDE.md`; "the formats stack rather than compete" | opencode takes the **first match and breaks**, globally and per project: `for (const file of globalFiles) { if (exists) { paths.add(...); break } }` — with the comment *"so we don't stack AGENTS.md/CLAUDE.md from every ancestor"* (`packages/opencode/src/session/instruction.ts:114-131`). Copilot *does* combine, with no defined precedence. Stacking is per-agent, not a property of the format. |
| Copilot's bundle names `CLAUDE.md`, so it is a deployable target | Copilot's only user-level instruction destinations are `$COPILOT_HOME/copilot-instructions.md` and `$COPILOT_HOME/instructions/**/*.instructions.md`. `.github/copilot-instructions.md`, `AGENTS.md`, `CLAUDE.md` and `GEMINI.md` are **repository-discovered**. Writing them into a config dir installs nothing. |
| Copilot's compatible payload is Claude's payload | `PostToolUse` compat delivers `tool_result: {result_type, text_result_for_llm}`, not `tool_response`; `tool_input` is typed `unknown`, not an object. The compat layer also *maps* runtime tool names to Claude's (`view`→`Read`, `create`→`Write`, `apply_patch`→`Edit`) — version-sensitive translation, not recasing. |

**The generalisable failure:** a string present in a binary proves a *name*
exists. It proves nothing about semantics, persistence, or destination. The
repo's own gate already says *grep every identifier a doc names* — but only in
the direction that catches invented identifiers. It does not catch a real
identifier whose promised behaviour was assumed. That gate is widened below.

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
2025-12. Codex, opencode, Amp, Crush, `dsh` and Copilot CLI all read it. Claude
Code reads only `CLAUDE.md`.

The previous revision went one step further and said the formats "stack rather
than compete". They do not, uniformly: **whether an agent stacks or falls back
is a per-agent property**, and it is the property that decides how many files
the harness writes.

| Agent | Behaviour with both files present |
|---|---|
| Copilot CLI | Combines every applicable file, deduplicating identical content, with **no defined precedence** |
| opencode | First match wins, then `break` — `AGENTS.md` is used and `CLAUDE.md` is never read |
| Claude Code | Reads `CLAUDE.md` only |

`system_doc_name() -> str` cannot express either shape. ADR-032 deferred exactly
this and named the deferral; the agents now force it — but into a list of
*destinations* (decision 6), not a list of recognised names.

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
       HookOutput(stdout, stderr, exit_code)
```

Builtins change signature from `main() -> None` to
`main(event: HookEvent) -> HookDecision`. The Claude Code adapter's
`parse_hook_input` and `format_hook_output` are identity, so the wire bytes
Claude Code sees do not change; that identity is the acceptance test for the
migration (see verification gates).

`_shared.py:profile_name()`, `_TRANSCRIPT_KEYS`, and the nine
`get_agent("claude-code")` literals are deleted by this step, not worked around.

**There are two callers of `main()`, not one, and neither passes arguments.**
Verified in the code:

- `cli/hooks_cmd.py:97` — `hook_invoke` imports the builtin and calls `main_fn()`
  with zero arguments. This is the deployed path: `deploy/engine.py:33` writes
  `f"lh hook {hook.name}"`.
- `hooks/engine.py:27-33` — `execute_hook` runs
  `subprocess.run([sys.executable, str(hook.path)], input=input_data, …)`,
  reached from `lh hooks run` (`cli/hooks_cmd.py:124-133`). It executes the hook
  *file*, so a builtin whose `main` now requires an argument breaks at
  `if __name__ == "__main__"`.

A migration that changes only the 18 builtins and `hook_invoke` leaves
`lh hooks run` broken and silent. Both entry points move in the same step, and
`lh hooks run` becomes a thin wrapper over the runner rather than a second
execution mechanism.

**Deployed commands from before this change must be recognised, and today they
are not.** `deploy/engine.py:86`:

```python
def _is_harness_owned(command: str) -> bool:
    return "lazy_harness/hooks/builtins/" in command.replace("\\", "/")
```

The generated command is `lh hook <name>` — it has never contained that
substring, so the predicate returns `False` for every harness hook in every
deployed profile today. Harness entries survive redeploy only by exact string
equality against the freshly generated list (`engine.py:149`). The moment the
command gains `--profile <p>`, equality fails, the old entry is classified as
foreign and preserved, the new one is seeded from `generated` (`engine.py:122`),
and **every one of the 18 hooks is installed twice** — firing twice, and
double-counting in metrics.

This is a latent defect on `main`, not a consequence of this design: any change
to the command format triggers it, and no test in
`tests/unit/test_deploy_engine.py` covers a changed command. Fixing
`_is_harness_owned` to recognise harness ownership by a stable identity — not by
the command text — is a prerequisite of this design and ships before it.

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
    ALLOW = "allow"                 # explicit approval, skipping the prompt
    DENY = "deny"
    ASK = "ask"
    BLOCK = "block"                 # stop-class events: keep the agent working


@dataclass(frozen=True)
class HookDecision:
    verdict: Verdict | None = None  # None = abstain: no permission decision
    reason: str = ""
    additional_context: str = ""
    system_message: str = ""
    stop: bool = False              # `continue: false`
    suppress_output: bool = False


@dataclass(frozen=True)
class HookOutput:
    stdout: dict | str | None
    stderr: str
    exit_code: int


def format_hook_output(self, event: HookEvent, decision: HookDecision) -> HookOutput: ...
```

Two corrections the first two drafts got backwards, both load-bearing.

**Abstention is not approval.** The default was `Verdict.ALLOW`. Claude Code's
docs are explicit that these are different states:

> "Exit code 0 with no output means the hook has no decision to report, so the
> tool call continues through the normal permission flow. The hook can deny the
> call, but staying silent doesn't approve it."

And `pre_tool_use_security.py:339-340` is exactly that state:

```python
if decision is None:
    sys.exit(0)
```

No stdout, no JSON. Migrating that branch to `Verdict.ALLOW` converts every
command the security hook merely fails to object to into an explicit,
prompt-skipping approval — the single most dangerous possible regression from
this design, delivered by a default value. `verdict: Verdict | None = None` is
the fix, and the adapter emits no `permissionDecision` for `None`.

Keeping `ALLOW` in the enum is still right: a future hook may want to
pre-approve, and Copilot honours it. But it must be reached deliberately.

**The output contract is three channels, not two.** The first drafts justified
`(document, exit_code)` with "Claude Code reads exit 2 … and ignores stdout in
that case". That is false in current Claude Code:

> "On events that can block, exit 2 blocks whether or not you print JSON … Claude
> Code still reads any valid JSON output on stdout."
> "The blocking message is the reason from your JSON's blocking decision when it
> makes one, and **your stderr text otherwise**."

Both blocking hooks in this repo take the stderr path —
`pre_tool_use_security.py:342` and `pre_tool_use_git_scope.py:389` both
`sys.stderr.write(...)` then `sys.exit(2)`. A pair with no stderr slot silently
drops the refusal reason the user reads. `HookOutput` carries all three, and the
golden tests capture all three.

`pre_compact` emits plain text on stdout, which is why `stdout` is
`dict | str | None`.

`HookEvent` carries every field a Claude Code payload can name. The first
draft left out `source`, `trigger`, `stop_hook_active`, `tool_use_id` and
`message`; a hook needing one of those would have reached into `raw`, and at
that point the normalisation is a fiction. `raw` exists for adapters, not for
hooks, and a test asserts no builtin reads it.

### 3. Hook support is declared per event, and so is the ability to block

```python
@dataclass(frozen=True)
class HookSupport:
    native_name: str                # the wire name, with the agent's own casing
    verdicts: frozenset[Verdict]    # which decisions this agent honours here
    abstain_is_safe: bool = True    # emitting nothing leaves the default flow intact

    @property
    def can_block(self) -> bool:
        return bool(self.verdicts & {Verdict.DENY, Verdict.BLOCK})

def hook_events(self) -> dict[str, HookSupport]:
    """Canonical event name -> how this agent delivers it. Absent = unsupported."""
```

`can_block: bool` was the first draft's field and it is too narrow — derived,
not declared. Codex is the counterexample that forces the set:

```
deny                      honoured, blocks
allow  (no updatedInput)  "unsupported permissionDecision:allow"  → fails open
ask                       "unsupported permissionDecision:ask"    → fails open
allow  + updatedInput     rewrites the input; not an approval
```

A hook emitting `ASK` on Codex does not get a prompt — it gets a warning in the
log and the tool runs. With `verdicts` declared, `lh doctor` can say *which
decision this hook needs and whether this agent honours it*, and the runner can
refuse to emit a verdict the adapter has not declared rather than failing open
silently. `native_name` carries the agent's own casing because Codex is
PascalCase-only and Copilot is camelCase with a PascalCase compatibility mode.

`supported_hooks()` becomes `hook_events().keys()`, which also makes it honest:
today it returns canonical names while `generate_hook_config` re-maps them in a
second literal, so the mapping exists twice.

The first draft declared one `HookDelivery` tier per agent (`NATIVE` /
`TRANSLATED` / `NONE`). That is too coarse in both directions. Copilot's local
session logs show `postToolUse`, `userPromptSubmitted`, `notification` and
`agentStop` firing, and its bundle names `preToolUse` — but not `postCompact`;
opencode has no hooks at all. Support is a property of the (agent, event) pair.

The honoured-verdict set is the property that matters. A `PreToolUse` hook that
runs but whose deny is ignored is worse than no hook: `pre_tool_use_security`
reports success, the audit log records a block, and the command runs. Codex
makes this concrete and silent — an unsupported decision produces a log line and
the tool proceeds. `lh doctor` reports, per profile, which of the three blocking
hooks are actually enforced, and against which verdicts.

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

Both reviewers rejected the first draft's version of this independently, and
they were right: `content: str` plus `merge_key: str` cannot merge anything.
The engine would need to parse JSON *and* TOML, know which nested entries the
harness owns, and reserialise without disturbing the rest — which is to say the
engine would need everything the adapter knows. A top-level key does not
identify nested ownership, and nothing said what happens to entries the harness
used to generate and no longer does.

**Merging is an adapter operation. Writing is an engine operation.**

```python
@dataclass(frozen=True)
class ConfigArtifact:
    relative_path: Path             # inside the profile's config dir
    content: str                    # the fully merged document, ready to write


@dataclass(frozen=True)
class MergeResult:
    artifact: ConfigArtifact
    preserved: list[str]            # foreign entries kept, for the deploy report
    dropped: list[str]              # harness entries no longer generated
    repaired: list[str]             # entries the agent would have rejected


def hook_config(self, hooks: dict[str, list[HookEntry]], existing: str | None) -> list[MergeResult]: ...
def mcp_config(self, servers: dict[str, dict], existing: str | None) -> list[MergeResult]: ...
```

The adapter receives the existing document, parses it in whatever format it
owns, merges, and returns the final text plus the diagnostics the deploy report
prints. The engine writes: backup, atomic replace, report. That split is the
part that is genuinely agent-neutral; parsing never was.

`deploy/engine.py:deploy_hooks` hardcodes `settings.json` and merges with a
function shaped like Claude Code's `matcher` / `hooks[]` block. Codex wants a
separate `hooks.json` or TOML declarations in `config.toml`; Copilot wants JSON
under `$COPILOT_HOME/hooks/`; Codex's MCP block lives in TOML. A `dict` return
cannot express "N files in two formats", so `generate_hook_config` and
`generate_mcp_config` are replaced, not extended.

The existing repair logic — entries Claude Code would reject, backups, the
"preserved N entries not managed by the harness" report — moves behind the
Claude Code adapter's merge. It stays byte-identical for existing profiles;
that identity is the acceptance test.

**Ownership must be identity-based, not text-based**, for the reason decision 1
gives: `_is_harness_owned` currently tests the command string and is already
wrong. Each generated entry carries a stable harness identity — the canonical
hook name — that survives a change in how the command is spelled.

### 5. Codex hook trust cannot be deployed, and the adapter reports it instead

**The previous revision of this decision was factually wrong**, and it is worth
stating plainly because it is the clearest instance of the failure this revision
is about. It proposed writing `bypass_hook_trust = true` into `config.toml`.
That key is not readable from a config file, in the exact version cited:

```rust
// codex-rs/core/src/config/mod.rs:925-927 @ 6b9826e (rust-v0.154.0)
/// Whether enabled hooks should run without requiring persisted hook trust for this session.
///
/// This is a runtime-only knob populated from invocation overrides, not from config files.
pub bypass_hook_trust: bool,
```

It appears in exactly two places: `Config` (runtime) and `ConfigOverrides`
(invocation, `mod.rs:2601`), reached only from the `--dangerously-bypass-hook-trust`
flag, whose own startup warning says *"for this invocation"*. There is no TOML
deserialisation for it. The evidence the earlier draft relied on — the string
`"must be a boolean"` in the binary — belongs to the app-server's request-override
parser.

Two further corrections to what that decision asserted about trust:

**Trust does not hash the hook's content.** It hashes the *normalised
declaration*:

```rust
// codex-rs/hooks/src/engine/discovery.rs:775-791
fn hook_hash(event_name, matcher, group, normalized_handler) -> String {
    let identity = NormalizedHookIdentity { event_name: ..., group };
    version_for_toml(&TomlValue::try_from(identity)?)
}
```

Editing `pre_tool_use_security.py` does **not** invalidate trust. Editing the
generated declaration does. This inverts the risk: the dangerous case is not a
modified script running untrusted, it is a *redeploy* that changes a matcher and
silently untrusts all 18 hooks mid-flight.

**There is a bypass, and the harness cannot reach it.** `HookTrustStatus::Managed`
skips trust entirely, but only for `System`, `Mdm`, `EnterpriseManaged` and
legacy-managed config layers (`discovery.rs:823-838`). The `User` layer — where
`lh deploy` writes — is explicitly not managed.

So the real options are three, none of them "emit a config key":

| Option | Cost |
|---|---|
| **(a)** Compute `hook_hash` in Python and pre-write `[hooks.state.<key>].trusted_hash` | Reimplements Codex's TOML normalisation and version hash. Silently wrong on any upstream change to either, with no signal until hooks stop firing. |
| **(b)** Deploy untrusted; the user trusts once in the TUI; `lh doctor` reads back `trusted_hash` per hook and reports drift | One manual step per profile and after any declaration change. Nothing to keep in sync with upstream. |
| **(c)** Wrap the launch with `--dangerously-bypass-hook-trust` | The harness does not own how Codex is launched; a shell alias is outside the deploy model and invisible to `lh doctor`. |

**This design takes (b).** It is the only one whose failure mode is visible.
`lh doctor` compares each generated hook against the persisted
`[hooks.state]` and reports `trusted` / `modified` / `untrusted` per hook, and
`lh deploy` prints the re-trust instruction when it changes a declaration.
(a) is revisited only if the hash turns out to be stable across releases, which
is a measurement, not an assumption.

There is still no `post_deploy()`: the harness cannot complete trust
programmatically, so a lifecycle method would have nothing to do.

This still has to be observed, not inferred: deploy, start a session, confirm
the hooks are reported untrusted and do not fire; trust them; confirm they fire;
change one matcher, redeploy, confirm `lh doctor` reports it modified *before*
the next session silently drops it.

### 6. System docs become a list, without a scope field yet

```python
def system_docs(self) -> list[Path]:
    """Paths, relative to the profile's config dir, this agent actually loads."""
```

**These are destinations, not recognised filenames** — the distinction the first
two drafts collapsed, and the reason the per-agent table below changed in two
columns. Copilot recognises `AGENTS.md` and `CLAUDE.md`, but only in
repositories; its user-level destinations are `copilot-instructions.md` and
`instructions/**/*.instructions.md` under `$COPILOT_HOME`. Writing `CLAUDE.md`
into Copilot's config dir installs nothing at all. A method that answers "what
filenames does this agent know" cannot be the input to a deployer that writes
files.

The list is also not a stacking promise. Copilot combines every applicable
instruction file with no defined precedence; opencode takes the first match and
breaks. For a deployer with one global destination per agent the distinction
does not bite yet — but a list of two entries means two *files written*, and on
opencode the second would be dead weight the agent never reads. Each entry is a
path the harness will write and the agent will load; an adapter returning two
entries is asserting the agent loads both.

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
              [projects."<abs path>"].trust_level        per-directory trust (observed)
Copilot CLI   --allow-tool / settings.json allowedUrls   flags and lists
              permissions-config.json:
                locations."<abs path>".tool_approvals[]  per-directory approvals (observed)
opencode      permission: {bash: {"git *": "allow"}}     per-tool globs
```

These are not encodings of one model. Running both agents added a dimension the
previous revision did not have: Codex and Copilot both key permission state by
**absolute directory**, and both **write it themselves during a session** as the
user approves things. Claude Code's model has no such axis.

A unified model would be a lie in every direction, and the failure mode of a
lying permission abstraction is a permission that silently does not apply.

`[permissions]` is therefore declared per agent and serialised by each adapter,
with no cross-agent translation attempted. This is the one place where the
framework accepts duplication as the honest answer.

It also imposes a hard constraint on decision 4: these files are **jointly
owned**. A deploy that reserialises `permissions-config.json` or Codex's
`[projects.*]` erases decisions the user made interactively, and no test written
against a fixture would catch it.

### 9. Tools are normalised too, and hooks declare which operations they need

Normalising the *event* was the whole of the first two drafts' translation
story. It is not enough: a matcher can fire correctly and hand the hook a
payload whose field names its logic does not recognise, which fails open with
every test passing. Measured in this repo:

| Literal | Files containing it |
|---|---|
| `"Edit"`, `"Write"` | 6 each |
| `"file_path"` | 8 |
| `"Bash"`, `"Read"` | 3 each |
| `"command"` | 2 |
| `"old_string"`, `"new_string"` | 1 each |

```python
# hooks/loader.py:78
matcher="Bash|Read|Edit|Write|NotebookEdit"
# pre_tool_use_security.py:183-190
FILE_TOOLS = frozenset({"Read", "Edit", "Write", "NotebookEdit"})
COMMAND_TOOLS = frozenset({"Bash"})
FILE_PATH_KEYS = ("file_path", "notebook_path")
```

Rename `preToolUse` to `pre_tool_use` and `pre_tool_use_security` still asks
Copilot's payload for `tool_input["command"]` and gets `toolArgs`, typed
`unknown`. It finds nothing to block, exits 0, and reports success.

The fix is not a universal tool language. It is the smallest set of
*operations* the builtins actually need, normalised onto `HookEvent`:

```python
class Operation(StrEnum):
    RUN_COMMAND = "run_command"     # → command: str
    READ_FILE = "read_file"         # → paths: list[Path]
    MODIFY_FILE = "modify_file"     # → paths: list[Path], is_create: bool

@dataclass(frozen=True)
class ToolCall:
    native_name: str
    operation: Operation | None     # None = an operation no builtin reasons about
    command: str | None = None
    paths: tuple[Path, ...] = ()
    raw_input: dict | None = None   # adapters only
```

`paths` is plural because Codex's `apply_patch` and Copilot's `edit` can touch
several files in one call; a singular `file_path` is a Claude Code assumption
that `pre_tool_use_git_scope` would silently under-enforce elsewhere.

Each builtin declares the operations it reasons about. `lh doctor` then answers
the question that matters — *does this hook cover these operations on this
agent* — instead of the weaker *does this event exist*. Copilot's PascalCase
compatibility mode already maps its runtime names onto Claude's
(`view`→`Read`, `create`→`Write`, `apply_patch`→`Edit`), which the adapter can
lean on for names; it does not map argument fields, which is the half that
matters.

### 10. Profile assets are deployed per agent, not wholesale

`deploy/engine.py:52-58` symlinks every entry of the profile source directory
into the config dir, unfiltered:

```python
for item in src_dir.iterdir():
    target = target_dir / item.name
    status = ensure_symlink(item, target)
```

With one agent that is correct. With a profile that contains `CLAUDE.md`, an
`AGENTS.md`, Claude-shaped slash commands and Copilot `*.instructions.md`, it
deploys all of them to all agents. Decision 6 defines what the *system document*
assembles into; nothing defined which of the remaining assets belong to whom.

The profile source gains an explicit per-agent segment, mirroring how the system
document is already split by identity:

```
profiles/personal/
  shared/            # deployed to every agent
  claude-code/       # deployed only when the profile's agent is claude-code
  codex/
```

`deploy_profiles` links `shared/` plus the directory named by
`agent_for_profile(cfg, name)`, and nothing else. An asset that exists only
under `shared/` and is meaningless to one agent is a content problem, not a
deploy problem; an asset under an agent directory that never reaches that agent
is the bug this prevents.

### 11. Transcript dependence is a hook capability, declared before the reader exists

`TranscriptReader` is last in the sequence (below), and the first two drafts
paired that with a claim that hooks are portable once the runner lands. Both
cannot be true. Verified:

| Hook | Claude-specific structure it parses |
|---|---|
| `stop_verify_guard` | `entry["type"] == "attachment"` and `attachment["type"] == "goal_status"` — Claude Code's native `/goal` marker (`:49-52`) |
| `herdr_context_gauge` | `usage.input_tokens` / `cache_read_input_tokens` / `cache_creation_input_tokens` — the Anthropic API usage schema (`:44-52`) |
| `pre_compact` | `role == "assistant"`, `content` as a list of blocks, `block["type"] == "tool_use"` (`:63-77`) |
| `compound_loop`, `session_end` | resolve a path only; the `knowledge/compound_loop.py` they hand to parses the same Claude message schema (`:57-354`) |

So `Stop` existing on an agent, with `DENY` in its `verdicts`, does **not** mean
`stop_verify_guard` works there: it will never find a goal marker, will conclude
there is nothing to verify, and will pass. A hook that cannot fail is worse than
a hook that is absent, because `lh doctor` reports it green.

Each builtin therefore declares `requires_transcript: bool` in the same step
that migrates it — not when the reader is written. A profile whose agent has no
`TranscriptReader` does not deploy the transcript-dependent hooks, and
`lh doctor` reports them as unavailable rather than passing.


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
| `system_docs()` — **global destinations** | `CLAUDE.md` | `AGENTS.md` (source) | `copilot-instructions.md`, `instructions/**/*.instructions.md` (vendor docs) | `AGENTS.md` **or** `CLAUDE.md`, first match wins (source, pinned) |
| repo-discovered names (**not** deploy targets) | `CLAUDE.md`, `.claude/CLAUDE.md` | `AGENTS.md` | `.github/copilot-instructions.md`, `AGENTS.md`, `CLAUDE.md`, `.claude/CLAUDE.md`, `GEMINI.md` (vendor docs) | `AGENTS.md`, `CLAUDE.md` |
| hook events | 10 canonical | 12 incl. `Interrupt`, **PascalCase only** (source, pinned) | 12 camelCase incl. `errorOccurred` (binary, 1.0.40 bundle) + a PascalCase compat mode with `tool_result` (vendor docs); 4 seen firing (log, 1.0.40) | none (source) |
| verdicts honoured on pre-tool | `deny`, `allow`, `ask` | `deny` only; `allow`/`ask` fail open (source, pinned) | `deny`; command hooks fail **closed** on nonzero exit, **open** on timeout (vendor docs) | n/a |
| hook config | `settings.json:hooks` | `hooks.json` **or** `[hooks]` in `config.toml` (source, pinned) | `$COPILOT_HOME/hooks/*.json`, `.github/hooks/*.json` (vendor docs) | plugins in JS/TS (source) |
| hook trust | n/a | `[hooks.state.<k>].trusted_hash` in `config.toml`, hashing the **declaration**, not the script; `User` layer is never `Managed`; bypass is invocation-only (source, pinned) | n/a | n/a |
| MCP | `.claude.json` | `config.toml` `[mcp_servers.<id>]` (binary) | `mcp-config.json` (present on disk) | `opencode.json` `mcp` (source) |
| transcript | `projects/**/*.jsonl` | `sessions/YYYY/MM/DD/rollout-*.jsonl`, `{type, payload, ordinal}` envelope (**log, 0.154.0**); SQLite migration staged but not active (binary) | `session-state/<uuid>/events.jsonl`, `{type, data, id, parentId}` envelope (**log, 1.0.83**) plus `session-store.db` (disk) | SQLite + JSON, undocumented (source) |
| cost unit | tokens + cache tokens | `token_usage_record` (log, 0.154.0) | `totalNanoAiu`, `totalPremiumRequests` (log, 1.0.83) | unknown |
| native tool names | `Bash`, `Read`, `Edit`, `Write` | `apply_patch`, shell (source) | `bash`, `view`, `rg`, `glob`, `task`, `skill`, `web_fetch` (**log, 1.0.83**) | unknown |
| headless | `-p --output-format json` | `codex exec --json` (binary); `--oss` with ollama/lmstudio (binary) | `-p` (source) | `opencode run --format json`, `serve` (source) |

The 1.0.83 cask binary is a launcher: its strings contain no hook vocabulary,
and the application is `~/.copilot/pkg/universal/1.0.40/app.js`, which is where
every `binary` mark in that column comes from.

### What running both agents actually showed

The two review sessions that produced this revision were themselves the first
sessions either agent has run on this machine, which resolves the two largest
`source` / `none` caveats the previous revision carried.

**Codex 0.154.0 still writes rollout JSONL.** The "migration to SQLite in
flight" row was a claim about a moving target; the target has not moved yet.
`~/.codex/sessions/2026/09/13/rollout-<ISO>-<uuid>.jsonl`, `cli_version`
`0.154.0` in its own `session_meta`. The envelope shares nothing with Claude's:

```
{"timestamp": …, "ordinal": 0, "type": "session_meta",   "payload": {…}}
{"timestamp": …, "ordinal": 1, "type": "event_msg",      "payload": {"type": "task_started", …}}
                               "response_item"           payload.type ∈ {reasoning, message,
                                                           custom_tool_call, custom_tool_call_output}
                               "token_usage_record"
                               "turn_context", "world_state"
```

An outer `type` + `payload` envelope with ordinals, where Claude has flat
records. Token accounting is its own record type, not a `usage` object hanging
off an assistant message — which is precisely what `herdr_context_gauge` reads.

**Copilot 1.0.83 writes `session-state/<uuid>/events.jsonl`**, self-identifying
`"producer": "copilot-agent", "copilotVersion": "1.0.83"`. So the format did not
change between 1.0.40 and 1.0.83, and the previous revision's "nothing about
1.0.83 has been observed" is now closed. Envelope: `{type, data, id, parentId,
timestamp}`. Usage arrives as `session.usage_checkpoint` with `totalNanoAiu` and
`totalPremiumRequests` — a third cost unit, mapping onto neither Claude's tokens
nor Codex's.

**Copilot's native tool names are confirmed lowercase, from a real session:**
`bash` (28 calls), `view` (27), `web_fetch` (24), `rg` (7), `web_search` (3),
`task`, `skill`, `glob`. Arguments arrive as an `arguments` object —
`{"toolName": "bash", "arguments": {"command": …, "description": …}}`. Decision 9
is not hypothetical.

**Config is split across four files, and the agents write to them.** This is the
strongest argument for decision 4's merge-in-the-adapter:

| File | Shape observed |
|---|---|
| `~/.copilot/mcp-config.json` | `mcpServers.<id>.{type, command, args, tools}` — the converged shape, plus a `tools` allowlist Claude has no equivalent for |
| `~/.copilot/settings.json` | `allowedUrls[]` |
| `~/.copilot/permissions-config.json` | `locations.<absolute path>.tool_approvals[].{kind, commandIdentifiers}` — a **fifth** permission model, keyed by absolute path, written by the agent as the user approves things |
| `~/.codex/config.toml` | `[projects."<abs path>"].trust_level = "trusted"` — written by Codex itself during the session |

Both agents mutate their own config during a session. A deploy that reserialises
`config.toml` without preserving `[projects.*]` destroys the user's project
trust; one that rewrites `permissions-config.json` destroys every approval they
have granted. The engine cannot know that. The adapter can.

**Still unobserved:** `~/.copilot/hooks/` exists and remains empty, and
`~/.codex/skills/` is empty — so the "`~/.agents/skills` scanned by Codex and
opencode" row stays `source`. No hook has fired on either agent.

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

- **`format_hook_output -> tuple[dict | str | None, int]`** (the previous
  revision). Rejected: no stderr channel, and both exit-2 hooks put the refusal
  reason there. The justification given for it — that Claude ignores stdout on
  exit 2 — was also false.

- **`verdict: Verdict = Verdict.ALLOW`** (the previous revision). Rejected:
  converts `pre_tool_use_security`'s silent no-objection branch into an explicit
  prompt-skipping approval. Abstention gets its own state.

- **`can_block: bool`** (the previous revision). Rejected: Codex honours `deny`
  but fails open on `allow` and `ask`, so a boolean cannot say which decisions
  survive. Replaced by a `verdicts` set.

- **`bypass_hook_trust = true` as a deployed config key** (the previous
  revision). Rejected because it does not exist as a config key; see decision 5.

- **Normalising the event and leaving tool names alone.** Rejected: a matcher
  that fires while the payload field names do not match is a hook that silently
  passes. Decision 9.

- **One global system-doc filename list per agent.** Rejected: it conflated
  filenames an agent *recognises in a repository* with paths a deployer can
  *write*. Decision 6.

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
- This revision added three decisions (9, 10, 11) that the previous one did not
  have, all of them work the first two drafts had implicitly assumed away: tool
  and argument normalisation, per-agent asset deployment, and transcript
  dependence as a declared capability. The design is larger than it was. It is
  larger because the smaller version would have shipped hooks that install,
  fire, and enforce nothing.
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
- **Adoption check:** total sessions on a non-Claude profile over the trailing
  four weeks, from the metrics store's `profile` label. The previous revision
  measured this per week and thresholded it per four weeks; one unit, stated
  once.
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

The two external reviews disagreed on exactly one thing, and it is the ordering.
Codex argued for Claude-only first — runner plus goldens — so the contract
hardens without multiplying variables. Copilot argued the opposite: that
stabilising an abstraction against Claude and only then meeting a second
provider reproduces the mistake this design exists to fix.

Both are right about different risks, and the resolution is a gate rather than
an order. The runner lands first because it is a correctness fix for Claude Code
on its own merits — it is the step that survives even if the kill criteria fire.
But **the contract is not frozen, and the bulk migration does not start, until a
non-identity adapter has run against it.** Step 3 is that gate.

0. **Fix `_is_harness_owned`** to identify harness entries by canonical hook
   name rather than by command text, with a test that redeploys after a command
   format change and asserts no duplicate. This is a defect on `main` today
   (decision 1) and every later step compounds it.
1. `HookEvent`, `HookDecision`, `Verdict`, `HookOutput`, `HookSupport`,
   `ToolCall`, `Operation`, `ConfigArtifact`, `MergeResult` and the Protocol
   methods in `agents/base.py`. `ClaudeCodeAdapter` implements them with today's
   hardcoded values extracted; `parse_hook_input` and `format_hook_output` are
   identity. Type-check only.
2. **`lh hook <name> --profile <p>` becomes the runner**, with *three* builtins
   migrated, not eighteen: `pre_tool_use_security` (deny via stderr + exit 2),
   `stop_verify_guard` (block via stdout, and transcript-dependent) and
   `context_inject` (additional context, no verdict). Both entry points move —
   `hook_invoke` and `lh hooks run`. Golden test per hook on stdout, stderr and
   exit code, every branch.
3. **Contract gate: a throwaway `CodexAdapter` runs those three hooks.** Codex
   verified with `--oss` against a local model so no account is needed. Deploy,
   trust the hooks manually (decision 5), observe each fire, observe
   `pre_tool_use_security` actually refuse a command, observe `stop_verify_guard`
   find no goal marker and be reported unavailable rather than green. Anything
   the contract cannot express is fixed **here**, while three hooks depend on it
   instead of eighteen.
4. Migrate the remaining 15 builtins, each declaring its `Operation` set and
   `requires_transcript`. Delete `profile_name()`, `_TRANSCRIPT_KEYS` and the
   nine `get_agent("claude-code")` literals.
5. `agent` per profile, `agent_for_profile()`, `per_profile` on `Capability`,
   the 18 `cfg.agent.type` readers. Full save/load/save/load round trip on the
   new-document and merge-on-existing paths. `CapabilityRegistry.toggle()` walks
   with `getattr`/`setattr` only (`plugins/capabilities.py:246-248`) and cannot
   reach `[profiles.<name>].agent`; decide explicitly whether the registry
   *reports* per-profile state or also *writes* it, and implement the one chosen.
6. `hook_config()` / `mcp_config()` returning `MergeResult`; `deploy_hooks` and
   `deploy_mcp_servers` write artifacts. Existing `settings.json` and
   `.claude.json` byte-identical, and Codex's `[projects.*]` preserved across a
   redeploy.
7. `system_docs()` replaces `system_doc_name()`; update the four call sites.
   Per-agent profile asset segments (decision 10).
8. **`CodexAdapter` for real**, replacing the throwaway from step 3, with trust
   reporting in `lh doctor`.
9. `hook_events()` surfaced in `lh doctor` per profile: honoured verdicts per
   event, covered operations per hook, transcript availability.
10. **`CopilotAdapter`.** The 1.0.83 session format is now known (see above), so
    the remaining unknown is the hook payload, which no local hook has fired.
    The first agent where `system_docs()` returns something other than a
    repo-shaped filename.
11. `TranscriptReader`, Claude Code first, then Codex — whose rollout format is
    now observed rather than assumed — then the others.

## Verification gates

These are checks, not principles. Each one corresponds to a way this design can
ship broken while every test passes.

- **A name in a binary is evidence of a name, and of nothing else.** Every
  provider claim in this document states what it was read from and what that
  source can support. Before a claim about *behaviour* — persistence, semantics,
  destination, precedence — ships, it is confirmed against vendor source pinned
  to a commit, vendor docs, or an observed run. This gate exists because the
  previous revision asserted six such claims and all six were wrong: a config
  key that was runtime-only, response values that fail open, event aliases that
  nothing deserialises, stacking that is fallback, repo paths named as global
  destinations, and a trust hash over the wrong input.
- **The runner migration is proven by bytes, not by tests passing.** For each
  builtin, capture **stdout, stderr and exit code** on every branch before the
  migration; assert identity after. A hook whose golden file was never captured
  was never migrated safely, and a golden file without stderr does not cover the
  two hooks that refuse through it.
- **Abstention has its own test.** For every hook with a permission verdict,
  assert that the no-objection branch emits *no* `permissionDecision` — not an
  `allow`. Delete the `None` handling, watch that test fail.
- **A redeploy after a command-format change installs each hook once.** Deploy,
  change the generated command, redeploy, assert the hook count is unchanged and
  nothing was classified as foreign. This is the test `tests/unit/test_deploy_engine.py`
  does not have today, and its absence is why `_is_harness_owned` has been dead
  code without anyone noticing.
- **A config the agent writes to survives a redeploy.** Start a session, let the
  agent write its own state (`[projects.*]` for Codex, `permissions-config.json`
  for Copilot), redeploy, assert that state is still there. Both agents were
  observed mutating their own config during the sessions that produced this
  revision.
- **A hook that runs is not a hook that blocks.** For every (adapter, event)
  whose `verdicts` contains `DENY` or `BLOCK`, exercise that path against the
  real binary and assert the agent refused the action. Then remove the verdict
  from the adapter's set and assert `lh doctor` reports the hook unenforced.
- **A hook that blocks is not a hook that sees anything.** Separately from the
  block path, assert each hook's *input* is intelligible on each agent: that its
  declared `Operation`s resolve, and that a transcript-dependent hook on an
  agent without a `TranscriptReader` is reported unavailable rather than passing.
  `stop_verify_guard` on an agent with no `goal_status` marker passes every test
  while enforcing nothing.
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

Closed since the previous revision, by the runs described above: whether Codex
still writes rollout JSONL (it does, at 0.154.0), and whether Copilot 1.0.83
writes the same `events.jsonl` shape as 1.0.40 (it does, self-identifying its
version).

Still open:

- Whether `codex exec` lets the caller pin a new session id, or only resume an
  existing one. Determines whether `CodexAdapter` can implement
  `SessionPinningAgent` or must reconcile the id after the fact.
- Whether `hook_hash` is stable enough across Codex releases to compute in
  Python — the difference between option (a) and option (b) in decision 5. This
  is a measurement across two releases, not a judgement.
- The minimum Codex version carrying the hook system. The adapter should probe
  rather than assume; the previous revision's second half of this question
  (the `bypass_hook_trust` key) is void, as no such key exists.
- Where Codex's transcript lands once the staged SQLite migration activates, and
  whether `state_5` is stable enough to read.
- Copilot's actual `preToolUse` payload. The docs give two shapes, camelCase
  (`toolName`, `toolArgs: unknown`) and a PascalCase compat mode (`tool_name`,
  `tool_input`, and `tool_result` on post). No hook has fired locally;
  `~/.copilot/hooks/` is still empty.
- Whether Copilot honours `permissionDecision: "deny"` on `preToolUse` in
  practice. Docs say command hooks fail closed on nonzero exit and **open** on
  timeout — so a slow hook is a hook that does not protect.
- Whether `~/.agents/skills` is genuinely scanned by Codex. `~/.codex/skills/`
  is empty and the claim remains `source`-only.
- Whether opencode's session storage is stable enough to read at all, or whether
  its `serve` HTTP API is the only defensible source.

## What the review changed

Recorded because the *pattern* is more reusable than the corrections.

Two external agents reviewed the previous revision independently. Codex reviewed
architecture and found three contract holes — merge, output channels, asset
filtering. Copilot dispatched a research subagent against vendor source and
found that six factual claims about other agents were wrong, every one of them
by reading a name out of a binary and inferring behaviour.

The architecture survived: the runner, per-profile agent resolution, and the
refusal to unify permissions were all confirmed as correct. What did not survive
was the evidence standard. A document that carefully labelled each row `binary`,
`log`, `source` or `none` still drew behavioural conclusions from `binary` rows,
because the label recorded *where a string was found* and not *what a string can
prove*. The first gate above is the fix.

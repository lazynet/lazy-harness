# ADR-041: The multi-agent hook contract — a runner that knows its profile

**Status:** accepted
**Date:** 2026-09-13
**Supersedes:** —
**Superseded by:** —
**Related:** ADR-004 (agent adapter pattern), ADR-006 (hooks as subprocess + JSON), ADR-032 (agent adapter completeness), ADR-035 (capability registry)

## Context

ADR-004 promised that adding a second agent costs "one new file, one registry
entry, zero changes elsewhere". ADR-032 found seven places that broke the
promise and closed them. A survey ahead of actually adding a second agent found
that the promise still does not hold, for a reason ADR-032 could not have seen:
**the adapter is not on the path a hook takes.**

A hook today is a Python module that reads Claude Code's JSON from stdin, writes
Claude Code's JSON to stdout, and signals refusal through Claude Code's exit
code 2. The adapter is consulted when the hook is *deployed* and never when it
*runs*. Eighteen builtins each carry their own copy of one agent's wire format.

Three other agents — Codex, GitHub Copilot CLI, opencode — have converged on the
same *shape*: a subprocess, JSON on stdin, an event name, a verdict. They have
not converged on the semantics. Measured against installed binaries during the
design work behind this ADR:

- Codex 0.154.0 carries `hooks` as a stable feature and names ten events, two of
  which (`PermissionRequest`, `Interrupt`) have no Claude Code counterpart.
- Copilot 1.0.83 honours `permissionDecision: "deny"`, fails **closed** on a
  nonzero hook exit, and fails **open** on a hook timeout. A slow hook there
  protects nothing.
- Codex hooks must be trusted before they run, and the trust record is keyed on
  the normalised *declaration*, not the script. A redeploy that changes a
  matcher silently untrusts every hook.

So the same hook, deployed unchanged to three agents, would be enforced on one,
unenforced but green on another, and silently skipped on the third. A test suite
passing against Claude Code says nothing about any of that.

There was also a live defect at the seam, and it is what step 0 fixed.
`_is_harness_owned` identified harness entries by matching a builtins path in
the command text, while `hook_command` had moved to emitting `lh hook <name>`.
It matched nothing: every harness hook was classified as another tool's. A
second guard in the merge masked the duplicate only because the two command
strings were byte-identical — which stops being true the moment the command
format changes, as it does the moment the runner takes a `--profile` argument.
Ownership is now the canonical hook name inside a launcher invocation, and the
function moved with the merge it belongs to: it lives at
`agents/claude_code.py:191`, not in `deploy/engine.py`.

## Decision

**`lh hook <name> --profile <p>` becomes the runner**, and the adapter is on the
path. The hook's job shrinks to a decision about a typed event; translating that
decision into an agent's wire format belongs to the adapter, once, rather than
to each of eighteen builtins.

The contract is a small vocabulary — `HookEvent`, `HookDecision`, `Verdict`,
`HookOutput`, `HookSupport`, `ToolCall`, `FileEdit`, `Operation`, `Signal`,
`ConfigArtifact`, `WriteOp` — with `parse_hook_input` and `format_hook_output`
on the adapter Protocol. `ClaudeCodeAdapter` implements both as the identity
transform, which is what makes the first migration a refactor rather than a
rewrite.

Four properties matter more than the type list:

1. **Support is declared per event, not assumed.** An adapter says which events
   it delivers and which verdicts that event honours. A hook whose verdict the
   agent will not honour is reported unenforced by `lh doctor` rather than
   deployed and trusted to work.
2. **A hook declares the signals it needs.** `stop_verify_guard` needs a goal
   marker; on an agent that supplies none it must be reported as a missing
   signal, not deployed to pass every test while enforcing nothing.
3. **A profile is an (agent, identity) pair.** `[profiles.<name>].agent`
   declares which agent a profile runs, and `agent_for_profile` is the single
   place that resolves it. Deploy loops previously resolved the global agent
   once, above their own profile loop, so a per-profile agent could not take
   effect at all.

   *Known exception, now closed — the record of how it closed matters.* Two
   readers under `deploy/` resolved the global agent off `get_agent(cfg.agent.type)`
   — `deploy_claude_symlink` and `snapshot_targets` — reaching for
   `global_config_link()` and `mcp_config_file()`. Neither sat inside a
   per-profile loop, so neither reproduced the defect this point describes; both
   were instances of the wider `cfg.agent.type` sweep that step 6 of the
   implementation sequence owns, and this ADR deliberately deferred them. The
   deferral carried one condition: **they must move together**, because they
   answer one question — which agent's artifacts does this deploy own — and a
   snapshot resolving it differently from the deploy is a rollback that misses
   the link.

   That condition was broken and then repaired, in that order, and the invariant
   stands unamended because it was violated rather than made obsolete. #292 moved
   `deploy_claude_symlink` alone, ahead of step 6, because step 4's gate needed
   it: a Codex throwaway made the default profile repointed `~/.claude` — the
   daily profile's own link — at the throwaway's Codex home, which is the blast
   radius step 4 exists to avoid. For one release `snapshot_targets` was the last
   reader of `[agent].type` under `deploy/`, and the divergence was live: a
   default profile declaring `agent = "codex"` had `.claude.json` and `~/.claude`
   snapshotted although `CodexAdapter` answers `""` and `None` for them, while the
   `hooks.json` the deploy did write went uncaptured. #297 closed it — the
   snapshot now resolves `agent_for_profile` per profile for config documents and
   the default profile's adapter for the link, and an integration test invokes
   both readers under an override and asserts they agree.

   Step 6 still owns the sweep outside `deploy/`; what moved early is these two
   readers and nothing else.
4. **Permissions are not unified.** Each agent's permission model is expressed
   in its own terms. Attempting one cross-agent permission language would
   produce a translation that is wrong in exactly the cases that matter.

**The contract is not frozen until a non-identity adapter has run against it.**
The runner lands first because it is a correctness fix for Claude Code on its
own merits, but the bulk migration of the remaining builtins waits for a
throwaway `CodexAdapter` to run three hooks end to end against a throwaway
profile. Anything the contract cannot express is fixed while three hooks depend
on it rather than eighteen.

**That gate ran on 2026-09-15 and passed, against the installed 0.67.1 binary
rather than a worktree, which is why this ADR is now `accepted`.** It took three
runs to pass, and seven production defects came out of them. Six are of one
shape — an answer derived from the global agent where the profile's agent is
the source: three in #292, one more in #297 when the second of two readers that
had to move together was found still reading globally, and two in #300. The
seventh is of another shape and is the sharper one: `_planner_for` called
`agent.name()` where `name` is a `@property`, so the step-3 promise that an
adapter without a `ConfigPlanner` is rejected before the first write died on a
`TypeError` — with four tests asserting that rejection and all four passing,
because both doubles declared `name()` as a method (#294). What the gate
asserts is narrower than the sentence above, and the difference is the part
worth carrying forward:

- **Two builtins are asserted, not three.** `stop-verify-guard` is migrated but
  writes no `hooks.log`; its only sink is the metrics DB, scoped by
  `LH_DATA_DIR` rather than by the agent runtime dir. It has no site in scope
  and the gate prints the skip with its reason on every run.
- **The fifteen unmigrated builtins are counted, not failed.** They reach
  `main()` through `cli/hooks_cmd.py`'s unmigrated branch, which calls
  `main_fn()` with no arguments, so the `--profile` value is parsed and
  discarded. Seven of them leaked 28 lines in the passing run. That is the
  known gap, tracked to step 5 in `specs/backlog.md`, and a `PASS` does not
  mean nothing leaks — it means the *migrated* hooks are isolated.
- **The gate discriminates.** It exits 1 against 0.67.0, and it also exits 1
  against a shim that fixes only `pre-tool-use-security`, so a pass is not an
  artefact of a gate that cannot fail.

The contract is frozen on that evidence. Freezing it on a gate whose scope is
two hooks rather than three is a choice with a cost, and the cost is named: the
`--profile` value dying in the dispatch is a *contract* defect, not a hook
defect, and it stayed invisible to the gate because the hooks that carry it were
outside the assertion set.

## Consequences

**What gets better.** Eighteen builtins stop carrying a wire format each. A
second agent becomes a file and a registry entry, as ADR-004 said it should.
`lh doctor` can answer "is this hook actually enforced on this profile", which
no current surface can. Per-profile agent resolution makes a mixed-agent machine
expressible at all.

**What it costs.** Every builtin needs a golden test over stdout, stderr *and*
exit code before it moves, captured on every branch — a test suite passing is
not evidence a migration preserved behaviour. The config schema grows a
per-profile field, and every reader of `cfg.agent.type` has to be audited rather
than left to inherit.

**What stays uncertain.** The contract is designed against three agents, two of
which are mid-migration in their own storage formats. A transcript parser is
valid only for the version it was read from, and both non-Claude formats are
moving. Adapters are pinned to an agent version and re-verified on upgrade.

**Kill criteria.** This work is removed rather than maintained if, at its
horizon, no second agent is in real use. The measurement that decides it is the
subject of its own open question — the instrument does not exist yet, and the
horizon does not start until it does and has accumulated a window.

## Evidence standard

This ADR's design work established one rule that outlived its own conclusions:
**a name in a binary is evidence of a name, and of nothing else.** A `--help`
line, a docstring, a flag name and a config key prove that a thing exists, never
what it does. Six behavioural claims in an earlier revision were all wrong, each
one derived by reading a name and inferring behaviour.

Every provider claim in the design documents now states what it was read from
and what that source can support, and a claim about behaviour is confirmed by
running the path — recording the command, its exit code, and its output. Where a
probe could be satisfied by a name alone, a control is run to prove the probe
discriminates.

## References

- `specs/designs/2026-09-13-multi-agent-harness-design.md` — the contract, the
  per-agent reference, the implementation sequence and the verification gates.
- `specs/designs/2026-09-13-multi-agent-blast-radius-design.md` — the impact
  outside the adapter seam: metrics, system documents, shell aliases, `.envrc`,
  and the staging and rollback story.

# ADR-041: The multi-agent hook contract — a runner that knows its profile

**Status:** proposed
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

There is also a live defect at the seam. `_is_harness_owned` (`deploy/engine.py`)
identified harness entries by matching a builtins path in the command text,
while `hook_command` had moved to emitting `lh hook <name>`. It matched nothing:
every harness hook was classified as another tool's. A second guard in the merge
masked the duplicate only because the two command strings were byte-identical —
which stops being true the moment the command format changes, as it does the
moment the runner takes a `--profile` argument.

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
4. **Permissions are not unified.** Each agent's permission model is expressed
   in its own terms. Attempting one cross-agent permission language would
   produce a translation that is wrong in exactly the cases that matter.

**The contract is not frozen until a non-identity adapter has run against it.**
The runner lands first because it is a correctness fix for Claude Code on its
own merits, but the bulk migration of the remaining builtins waits for a
throwaway `CodexAdapter` to run three hooks end to end against a throwaway
profile. Anything the contract cannot express is fixed while three hooks depend
on it rather than eighteen. That gate is why this ADR is `proposed` and not
`accepted`.

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

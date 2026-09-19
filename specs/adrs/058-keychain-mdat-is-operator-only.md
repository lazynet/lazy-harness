# ADR-058: Keychain `mdat` remains operator-only evidence

**Status:** accepted
**Date:** 2026-09-19
**Supersedes:** —
**Superseded by:** —
**Related:** ADR-045 (credential boundary)

## Context

ADR-045 deliberately kept the session-start hook out of the macOS Keychain.
Running a credential helper from launchd's Background domain had deleted a
credential store twice, so a stale Claude Code mirror degrades to `unknown`
instead of being checked against the live store.

A later probe, run manually from an Aqua terminal and without `-w`, established
that `security find-generic-password` exposes a non-secret modification date.
The keychain item's `mdat` matched the day of a successful login while the
`.credentials.json` mirror remained older and claimed an expired refresh token.

That proves `mdat` is useful diagnostic evidence. It does not create a safe
execution context for an automatic hook. An agent pane is itself descended
from an Aqua terminal, so process ancestry, `isatty()`, or launchd domain alone
cannot distinguish an operator command from an agent-issued command. The guard
the proposal needs is therefore not enforceable by this package.

## Decision

Do not execute `security` from lazy-harness code, hooks, doctor checks,
schedulers, or agent-launched subprocesses.

`mdat` remains an operator-only diagnostic. The documented safe probe is run
manually from an Aqua terminal, names the expected item, omits `-w`, and records
only metadata. Its result may support a human diagnosis, but lazy-harness does
not persist, parse, or convert it into an auth verdict.

The macOS Claude Code preflight therefore keeps ADR-045's behaviour:

- a mirror-derived `pass` survives as a lower bound;
- a mirror-derived `warn` or `fail` becomes `unknown`;
- no Keychain access occurs while the agent is starting.

This decision can be reopened only when macOS or Claude Code exposes a
read-only liveness interface that is safe in the hook's real execution domain,
or when an external operator-owned process provides a signed, non-secret
snapshot without lazy-harness invoking credential tooling.

## Alternatives considered

### Read `mdat` directly in the hook

Rejected. It repeats the execution shape involved in the two credential-loss
incidents. Testing the happy path with a mocked `security` binary would prove
the parser, not the safety of the real Keychain call.

### Guard on Aqua, a TTY, or terminal ancestry

Rejected. Agent panes meet those tests. The check would certify the unsafe
case instead of excluding it.

### Cache `mdat` in a harness-owned file

Rejected for now. Something still has to produce the cache. A manual producer
makes the preflight's answer depend on an untracked ritual; an automatic
producer reopens the execution-context problem under another process name.

## Consequences

- Probe 9 closes the format question, while this ADR closes the automation
  question in the negative.
- The preflight retains an honest `unknown` on macOS instead of risking the
  credential store to manufacture a stronger status.
- No code change is required; the current file-only implementation already
  embodies the decision.


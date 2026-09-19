# ADR-057: Codex `last_refresh` is freshness evidence, not a credential verdict

**Status:** accepted
**Date:** 2026-09-19
**Supersedes:** —
**Superseded by:** —
**Related:** ADR-045 (credential boundary), ADR-049 (permission bypass intent)

## Context

The Codex auth probe recorded the complete key shape of `auth.json` without
recording secret values. It has `auth_mode`, `OPENAI_API_KEY`, `tokens`, and
`last_refresh`; the token object has no expiry field at any level.

That left an open proposal to choose an age threshold for `last_refresh`, call
an older credential stale, and use that result in the session-start preflight.
The proposal assumes that refresh recency and credential liveness are the same
fact. The file does not establish that contract.

Two live observations on 2026-09-19 make the gap concrete. The active
`lazy-codex` profile had refreshed about one day earlier, while the default
Codex profile's marker was about four days old. Neither observation identifies
the maximum age of a valid login, and the file contains no server-side expiry
or rejection state that could supply it.

## Decision

Do not derive an auth verdict from the age of `last_refresh`.

`CodexAdapter.credentials_file()` continues to return `None`, and the
session-start preflight continues to report `n/a` for Codex auth. There is no
age threshold: choosing seven, thirty, or ninety days would turn an operational
preference into a claim about credential validity that the measured format
does not support.

`last_refresh` may be displayed later as explicitly labelled telemetry — for
example, "credentials last refreshed four days ago" — but it must not map to
`pass`, `warn`, or `fail`, and it must not tell the user to log in. A future
Codex contract can reopen this decision only if a probe demonstrates one of:

- an expiry value with defined semantics;
- a read-only status command whose exit state distinguishes a live login from
  a dead one; or
- an observed rejection tied to a specific `last_refresh` age, with a control
  showing a credential of the same age still accepted or rejected as claimed.

## Alternatives considered

### Warn after seven days

Rejected. Four days was already observed without an associated failure, and
there is no evidence that seven is a boundary rather than a round number. A
warning that routinely describes healthy credentials trains the reader to
ignore the preflight.

### Fail after a longer horizon

Rejected more strongly. No local timestamp can prove that a server-side token
is dead, and a preflight `fail` is an instruction to interrupt work and repair
the login. The evidence does not justify that instruction at any age.

### Invoke a Codex login command from the hook

Rejected. The preflight's credential path is deliberately read-only. Credential
helpers belong in an interactive terminal, not inside an agent hook, and no
behavioural probe has established a safe non-mutating Codex status command.

## Consequences

- Codex auth remains a named coverage gap rather than a guessed green or red
  result.
- No code change is required: the current `None` / `n/a` path already embodies
  this decision.
- The backlog item asking for an age heuristic is closed by rejection, not
  deferred implementation.


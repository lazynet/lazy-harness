# ADR-045: The credential boundary — a refusal at launch, and a check that names the agent it cannot speak for

**Status:** accepted
**Date:** 2026-09-16
**Supersedes:** —
**Superseded by:** —
**Related:** ADR-004 (agent adapter pattern), ADR-032 (agent adapter completeness), ADR-041 (multi-agent hook contract), ADR-043 (system docs by role)

## Context

Two defects were recorded separately and are one question: **who is allowed to
answer "where are this profile's credentials, and are they alive?"** Today the
answer is written by hand in two places, for one agent and one platform.

### The launch preserves the inherited credential

`agents/launch.py` copies the whole ambient environment, points the adapter's
own variable at the profile's `config_dir`, and lays the profile's secrets file
over the result. `core/secrets.py:overlay_profile_secrets` is fail-open by
design: its docstring says every failure "degrades to no overlay with a message
on stderr rather than raising", because the caller is about to `exec` the agent
and a permissions problem is not a reason to emit a traceback.

The 2026-09-16 audit measured the consequence with a mocked probe and recorded
it as F2 in `specs/backlog.md`. A second profile whose secrets file exists but
cannot be read launches with the **first** profile's credential, inherited from
the ambient environment, with nothing on the channel that says the identity
changed. `tests/unit/core/test_secrets.py` pinned that as intended behaviour.

Availability was traded for account identity, and the trade was never stated —
it was inherited from an `except OSError` whose stated purpose was avoiding a
traceback, which is a much smaller claim.

The two failure shapes inside that one branch are not equivalent:

- **No file at all.** This is the default profile, which takes its values from
  the global environment and has never had a file. It is the ordinary case, on
  every machine, at every launch.
- **A file that exists and cannot be read or decoded.** Nobody provisions a
  file by accident. Its presence is somebody having said "this profile carries
  its own account", and a launch that inherits another account's credential
  anyway is doing the one thing the file exists to prevent.

### The preflight reads a Claude Code filename, and on macOS reads a mirror

`hooks/builtins/session_start_preflight.py:_credentials_path` builds
`<agent dir>/.credentials.json`. The directory half is already per-profile; the
**filename** is written into the builtin, and it is Claude Code's. The
function's own docstring says the location belongs on the adapter beside
`session_dirs()` and `global_config_link()`, and names the gap as open.

Two measured consequences:

1. **A non-Claude profile reports `unknown` — "could not read the credentials
   file".** That is the correct degradation for a corrupt file and exactly the
   wrong one for an agent that never had that file. The two are indistinguishable
   on the channel, and the second is not fixed by logging in again.

2. **On macOS the check reports a false `fail` for Claude Code itself.**
   Confirmed live on 2026-09-16: a profile with a successful login that day had
   a keychain entry (`Claude Code-credentials-<sha256(config_dir) prefix>`) with
   a fresh modification date, while `.credentials.json` still carried the
   2026-09-08 mtime and an expired `refreshTokenExpiresAt`. `check_auth` opens
   the file, parses it, finds a valid shape — so no degradation branch applies —
   and returns `fail`. The live credential was healthy the whole time. macOS
   keeps the credential in the keychain and leaves a file mirror that nothing
   re-synchronises.

The cost is the one `check_auth`'s own docstring anticipates: "reporting a
healthy login as dead trains the reader to skip the whole block." A preflight
that cries wolf every session on the platform this repository is developed on
is worse than no preflight.

## Decision

### D1 — A file inside the secrets directory is the declaration

A profile declares that it carries its own account by having a secrets file at
`<secrets dir>/<profile>.env`. Nothing else declares it: no config field, no
deploy-time snapshot. The declaration is the artefact the provisioner already
writes.

### D2 — An unreadable declared file refuses the launch

`overlay_profile_secrets` raises `SecretsError` when the file exists and cannot
be read or decoded. `resolve_launch` converts it to
`LaunchError("secrets-unreadable", …)` — the same traceback-free channel
`binary-not-found` and `unknown-profile` already use.

`FileNotFoundError` alone returns the environment unchanged, as before. The
branch is keyed on the errno rather than on `Path.is_file()` precisely because
`is_file()` answers `False` for a file whose *parent directory* cannot be
traversed, which would have re-opened the hole this closes under a different
name.

A secrets path resolving outside the directory keeps its warning and its
fail-open return: no file inside the directory was ever named, so by D1 the
profile declared nothing.

### D3 — `lh doctor` reports every profile that inherits

A profile other than the default with no secrets file is listed, with the path
that would be read and the statement that it inherits the ambient environment's
credentials. The line names no environment variable and prints no value.

Naming the variable would require the harness to enumerate which variables are
credentials, per agent — see A2, where that enumeration is rejected outright.
The honest statement is the one that needs no list.

### D4 — `AgentAdapter.credentials_file() -> str | None`

A new Protocol member beside `mcp_config_file()`, `session_dirs()` and
`system_docs()`: the filename, relative to the agent directory, of a
credentials file this harness can read and understand — or `None`.

- `ClaudeCodeAdapter` returns `".credentials.json"`.
- `CodexAdapter` returns `None`. `specs/designs/codex-evidence.md` records the
  *location* (`~/.codex/auth.json`, copied by all six probes) but not the
  **shape**. `check_auth` parses `claudeAiOauth.refreshTokenExpiresAt`, which is
  Claude Code's; routing Codex's file at it would produce `unknown — credentials
  file has an unexpected shape`, which is the same conflation this ADR exists to
  remove. See A4.
- `NullAdapter` returns `None`.

The name and the shape are equally agent-specific. This ADR moves the name and
deliberately leaves the parser where it is: half a seam that reports honestly
beats a whole one built on a shape nobody probed.

### D5 — `None` is its own status, not `unknown`

`Status` gains `"n/a"`, rendered `[n/a]`. The check emits it with a detail
naming the agent: the harness cannot speak for this agent's credentials. It is
noteworthy, so it gets its own line rather than joining the `Clear:` tail —
"clear" would assert a check that did not run.

One line per session for a profile whose auth coverage is a known blind spot is
the point, not noise. The line disappears when that agent's credential shape is
probed and `credentials_file()` starts returning a name.

### D6 — On macOS, a file-derived `fail` or `warn` for Claude Code degrades to `unknown`

When the file is a mirror of a live store the hook does not read — today,
`claude-code` on `darwin` — a `fail` or a `warn` derived from the file becomes
`unknown`, with a detail saying the credential lives in the keychain and the
file is a mirror the harness cannot verify.

`pass` survives unchanged. A mirror cannot claim more life than the store it
mirrors, so a file saying the refresh token is good is a lower bound on the
truth. `unknown` for an unreadable or unparseable file is unchanged: it was
already the weakest statement available.

This is the bias toward false negatives the repository requires of a
behavioural check. The check loses the ability to report a genuinely dead macOS
login through the file — which it never had, since the file is stale whether the
login is alive or not.

### D7 — The hook does not read the keychain, and neither does `lh doctor`

`security find-generic-password` from a launchd Background context is what
destroyed a credential store twice on this machine. No code shipped by this ADR
spawns a credential helper. Reading the keychain, if it is ever the right
answer, is a separate ADR with its own probes; the probe script for it is listed
in this change's report rather than run from an agent pane.

## Alternatives considered and rejected

### A1 — Keep fail-open everywhere and make it loud

Name the inherited variable and the profile on stderr at launch, and report it
in `lh doctor`, but launch anyway.

**Rejected as insufficient, kept in part.** The `lh doctor` half is D3. The
stderr-at-launch half fires on every launch of the default profile, which is the
ordinary case — a warning printed on every ordinary run is read once and
filtered forever. And for the case that actually motivated F2 it leaves the
wrong-identity launch happening: a line on stderr that scrolls past does not
stop work being written under the wrong account.

### A2 — Scrub the credential variables the adapter names

Add a second Protocol member enumerating which environment variables are
credentials, and delete them from the launch environment when the declared file
cannot be read.

**Rejected.** The enumeration cannot be verified from the code. Claude Code
reads at least `CLAUDE_CODE_OAUTH_TOKEN`, `ANTHROPIC_API_KEY` and
`ANTHROPIC_AUTH_TOKEN`; Codex reads its own set; a provider adds one in a minor
release and the harness does not find out. An incomplete denylist scrubs the
variable it knew and inherits the one it did not — **failing open, silently,
which is the exact defect being fixed**, now wearing a guard that makes it look
handled. A refusal cannot be wrong that way: it stops the whole launch and names
the file.

It also widens the Protocol twice in one change, and the second widening's
correctness is unfalsifiable by any test in this repository.

### A3 — A config field declaring that a profile carries its own account

`[profiles.<p>].secrets = "required"`, or a deploy-time snapshot recording the
file's existence.

**Rejected as a second source of truth.** Configuration and the filesystem
would then both answer "does this profile have its own credentials", and they
drift the first time a file is provisioned without the config being edited —
which is the normal order of operations, since the provisioner writes the file.
D1 uses the artefact that already exists. A config field would also have to be
added to every profile of every existing machine before the refusal could fire,
so the fix would ship dormant.

### A4 — Return `"auth.json"` from `CodexAdapter`

The evidence names the path.

**Rejected on the shape, not the path.** `check_auth`'s parser is Claude Code's
JSON envelope. A Codex profile would then get `unknown — credentials file has an
unexpected shape`, which reads as "your credentials are corrupt" for a file that
is perfectly fine. `n/a` is the true statement. The probe that would change this
is listed for the operator; until it runs, `None` is the answer supported by
evidence.

### A5 — Read the keychain

Resolve the live credential on macOS instead of a file, from the hook or from
`lh doctor`.

**Rejected for this change,** and not on principle — it is the long-term
correct answer. It is rejected on sequencing: the repository's rule for an
adapter over an external binary is that the probes come first and the observed
contract is recorded before the first test. No probe of
`security find-generic-password`'s output shape has been run, and the one place
it must never be run from is an agent pane, which is where this change was
written. D6 is the cheap correct answer available without it.

### A6 — Collapse `n/a` into `unknown` with a clearer detail

**Rejected.** `unknown` means "this check ran and could not tell"; the new state
means "this check does not apply to this agent". A reader triaging a preflight
acts differently on each: the first is worth investigating, the second is a
capability gap nothing they do today will fix. The backlog entry names the
collapse as the defect, so reintroducing it in the detail string would close the
entry without changing the outcome.

## Consequences

- A profile whose secrets file exists but is unreadable no longer launches. That
  is a new way for `lh run` and `lh exec` to fail, and the remedy is in the
  message: fix the file's mode or its content. The default profile, and any
  profile with no file, is unaffected.
- `AgentAdapter` gains a member, so every adapter, every test double and the
  Protocol-completeness sweep must declare it. That audit is part of this
  change.
- The preflight's auth line acquires a fourth marker, `[n/a]`, and on macOS the
  `fail` and `warn` markers become unreachable for Claude Code through the file.
  The byte goldens for this hook are therefore platform-keyed for the three
  cases whose verdict is derived from the file; both targets are exercised in
  CI, which runs Linux and macOS.
- The harness still cannot report a dead login on macOS. `lh doctor` and the
  preflight both say so rather than guessing, which is the whole of the
  improvement — a check that admits a blind spot is usable, and one that reports
  a false `FAIL` is not.

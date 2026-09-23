# ADR-042: Multi-file config planning — several targets, explicit deletes, and a refusal instead of a lock

**Status:** accepted
**Date:** 2026-09-16
**Supersedes:** —
**Superseded by:** —
**Related:** ADR-004 (agent adapter pattern), ADR-018 (no behaviour change on upgrade), ADR-032 (agent adapter completeness), ADR-041 (the multi-agent hook contract)

## Context

ADR-041 froze the hook contract and put the adapter on the path a hook takes.
`ConfigPlanner` came with it: `config_targets()` names the files an adapter may
read or write, `plan_config()` returns the complete set of `WriteOp`s, and the
engine does the I/O. The split is that **merging is an adapter operation because
parsing never was agent-neutral; writing is the engine's.**

Step 3 shipped that cycle. Three things it promised were not in it, and the
design document said so about only one of them.

**The engine never stats a target.** Decision 4 of the multi-agent design
describes the engine recording each target's mtime and size at read time and
aborting if either changed before apply. The paragraph is written in the present
tense and reads as current behaviour. It was not: `grep -n 'st_mtime\|st_size'`
over `src/lazy_harness/deploy/` and `src/lazy_harness/agents/` returned nothing.
A deploy concurrent with a running agent silently won the race.

**Deletes were reachable only from a fixture.** `WriteOp(artifact=None)` unlinks
the file, and the engine has done so since step 3, but no shipped adapter ever
emitted one. The two tests covering it each asserted one direction in isolation,
so neither discriminated against an engine that unlinked every path it was
handed.

**Codex shipped no MCP at all.** The throwaway `CodexAdapter` named one target,
`hooks.json`, and ignored `servers` entirely. Codex reads MCP servers from
`[mcp_servers.<id>]` in `config.toml` and from nowhere else — which is the file
decision 4 calls *jointly owned*, because Codex writes into it during a session:

```toml
[projects."/Users/someone/repos/one"]
trust_level = "trusted"

[hooks.state."/Users/someone/.codex/hooks.json:session_start:0:0"]
trusted_hash = "sha256:904128e4"
```

The first row is the user trusting a directory. The second is the user approving
a hook. A deploy that reserialises the file without carrying both destroys
decisions that cannot be reconstructed, and no test written against a fixture of
the harness's own shape would notice them going.

## Decision

**One plan, several targets, and the whole plan is refused rather than partly
applied.**

**Deletion is explicit and keyed on ownership, not on existence.** An adapter
that stops generating a file emits `WriteOp(artifact=None)` for it. Codex is the
first adapter to do so: a `hooks.json` carrying the harness's `description`
stamp is retired once no hooks are generated, and one without it is left alone.
Keying the delete on the file merely existing would eat a `hooks.json` the user
wrote by hand the first time a profile configured no harness hooks — and that
file is also where a Codex user declares hooks of their own.

**The race is refused, not resolved.** The engine records `(st_mtime_ns,
st_size)` for every target at read time, including the ones that do not exist,
and raises `ConfigTargetChangedError` if any of them moved before apply. It is
checked once, between plan and apply, over all targets at once.

**A file the agent writes to is merged into, never owned.** Codex's
`config.toml` is parsed with `tomlkit` and updated by key. Everything the
harness does not name comes back out unchanged, and `[projects.*]` is reported
in the deploy's `preserved` lines so the user sees their trust survived.

**Hook declarations do not cross into `config.toml`.** MCP does, because it has
no second home. The asymmetry is not inconsistency: Codex's trust state key is
`<declaring file>:<event>:<group index>:<handler index>` — path-scoped — so
moving a declaration between `hooks.json` and `config.toml` re-prompts for every
hook in the file even though the normalised hash is identical. That was measured
on 0.154.0 with a byte-identical handler: the `hooks.json` entry read `Trusted`
and the `config.toml` one read `new · review required`, both carrying
`sha256:904128e4…`.

## Alternatives considered

**A lock file, instead of the abort.** Rejected because the agents would have to
honour it and they do not know the harness exists. A lock the writer ignores is
a lock that reports safety it does not provide, which is worse than no lock: it
converts a refusal the operator can act on into a silence they cannot.

**Winning the race — write anyway, it is our file.** Rejected because it is not
our file. `config.toml` and `permissions-config.json` are where two of the three
agents record what the user approved by hand, and the loss is silent and
unrecoverable. Deploying while an agent is running is not a supported state, so
it is named as such.

**Comparing the read bytes instead of a stat pair.** Rejected as more I/O for no
more safety: re-reading every target to diff it still races the write that lands
after the read. The stat pair is the cheap conservative check, and the whole
point is to be conservative rather than correct-under-concurrency.

**Comparing `os.stat_result` wholesale.** Rejected: it carries `st_atime`, which
moves on every read, so the guard would abort on every second deploy. The two
fields are named because each catches what the other misses — size misses an
in-place edit of the same length, mtime misses a write inside one filesystem
timestamp tick. Both are pinned by a test that fails when its half is removed.

**`tomli_w` for the Codex merge.** Rejected. It emits semantically equivalent
TOML and rewrites the whole document doing it, dropping every comment. This file
is one the user opens by hand and one Codex appends to live, so each byte of
churn is a diff they have to read and a chance to lose something. `tomlkit`
keeps the trivia attached to every key it is not asked to rewrite; measured
against a real `~/.codex/config.toml`, the output's prefix is byte-identical and
everything outside `mcp_servers` parses identical through `tomllib`.

**Replacing an unparseable `config.toml`.** Rejected, and this is the one place
the harness refuses to make progress. `CodexConfigUnreadableError` leaves the
file alone: a missing `[mcp_servers]` block costs one redeploy, and a discarded
`[projects.*]` costs the user every trust decision they ever made.

## Consequences

**What gets better.** An adapter can retire a file it no longer generates, which
is what stops a document from an earlier release living forever. A deploy racing
a live agent fails loudly and writes nothing instead of silently winning. Codex
ships MCP without owning the file it lives in. `deploy/snapshot.py` picks the new
target up for free — it derives its rollback manifest from `config_targets()`
rather than listing paths of its own, so `--rollback` can restore the one file
here carrying state the user cannot retype.

**What it costs.** Every target is stat'd twice per deploy, which is two syscalls
per file and not worth optimising. A user editing their own `settings.json`
while `lh deploy` runs now gets a refusal where they previously got a silent
overwrite — correct, and still a behaviour change. The Codex merge pulls
`tomlkit` onto the deploy path; it was already a dependency for `core/config.py`.

**What stays uncertain.** The abort is conservative by construction and refuses
deploys that would have been harmless. Neither field is decided by content, so
an editor re-saving a byte-identical file is enough to trigger it — measured:
writing the same two bytes twice, a second apart, moved `st_mtime` and left
`st_size` alone. That is the intended bias and not a bug, but if it turns out to
be common the answer is a `--force` flag, not a narrower guard. In the other
direction the stamp is taken on the harness's side of a filesystem it does not
control: one with coarse mtime *and* a write that preserves size would defeat
both halves at once. No such deployment is known here.

**Kill criteria.** The abort is removed rather than tuned if it fires on a deploy
that was in fact safe more often than it catches a real concurrent write.
Measuring that needs the deploy to record both, which it does not yet; until it
does, the guard stays biased toward refusing — a false refusal costs a re-run and
a false pass costs the user's trust decisions.

## What is out of scope

**Dropping harness-generated MCP servers Codex no longer receives.** The merge
adds and updates; a server the harness stopped detecting stays in `config.toml`.
Retiring one needs a marker saying which entries the harness wrote, and
`[mcp_servers.<id>]` has no free key for it — Codex's own deserialiser decides
what that table may contain. `ClaudeCodeAdapter._plan_mcp` has the same gap for
the same reason, so this is a known limit of both, not a Codex quirk.

**`CodexAdapter` as a real adapter.** It is still step 4's throwaway. Trust
reporting in `lh doctor`, project-layer hook discovery, and the `[projects.*]`
read that `lh doctor` needs in order not to report a project hook as installed
that Codex will never load are step 9's.

> **Evolution (2026-09-16).** Closed by ADR-044, which replaced the throwaway with the real `CodexAdapter`.

**Per-agent profile asset segments and the `sync_agent_md.py` layout
agreement.** Decision 10's half of the same design step, and it touches
`core/sync_agent_md.py`, which this work does not.

**Copilot's `permissions-config.json`.** The third jointly-owned file, and there
is no `CopilotAdapter` yet.

> **Evolution (2026-09-16).** ADR-047 added `agents/copilot.py`; this out-of-scope note records the state when ADR-042 was written.

## Evidence standard

Every claim here about Codex was read from a running binary or from its source
at a named revision, per ADR-041's rule that a name is evidence of a name and
nothing else.

The `[projects.*]` round trip is asserted through `tomllib` — the parser Codex's
own deserialiser is built on — over the bytes the adapter produced, and over two
successive plans rather than one, because a merge can be correct reading a
hand-written file and lossy reading its own output.

One assertion in the existing suite turned out to be a fact about the developer's
`PATH` rather than about the code. `test_an_overridden_agent_keeps_snapshot_and_deploy_in_agreement`
carved `.claude.json` out of its reverse direction in prose, on the stated
grounds that the Codex profile had no MCP-dependent target of its own. Widening
`config_targets()` gave it one, and the test passed locally — where `qmd` is
installed, so the deploy did write `config.toml` — and failed on all four CI
runners, where it does not. The probe is now pinned by a fixture, which makes
the assertion mean the same thing everywhere instead of describing where it does
not hold. The fix was verified in both directions: with every real probe forced
to answer no, the test fails without the fixture and passes with it.

Each guard was verified by removing it by hand and watching the named test fail:
the unlink, the `artifact is None` condition, each half of the stat pair, and
the widened `config_targets()`. All four were restored by hand rather than from
git, which would have reverted the uncommitted implementation with them.

## Evolution — 2026-09-19: ownership is per hook group

The original deletion rule above treated Codex's `hooks.json` description stamp
as ownership of the whole document. That conclusion is superseded. Native
installers and users also place declarations in this file, so the adapter now
merges it and owns only matcher groups it can prove are lazy-harness builtins.

New documents carry a versioned provenance envelope in `description`, including
launcher history and the exact managed event/position/group records. The legacy
description remains a migration signal. Neither string is sufficient on its
own: every handler in a claimed group must also be a recognized `lh hook
<name>` command (or the legacy builtin-path form), and mixed, malformed or
unrecorded groups remain foreign. Recognition parses only the exact current
launcher grammar, its explicit no-profile migration, or a registered builtin's
exact legacy module path; wrappers, shell operators, extra arguments,
substrings and invented builtin names remain foreign. A valid envelope's
launcher list is editable history by design, so it may name a launcher no
current profile uses; that history grants nothing unless the recorded event,
position and group still match and the command is an exact registered-builtin
invocation. A launcher absent from both that history and the current/default
launcher set remains foreign. Attached operators, substitutions and redirects
are rejected by comparing the parsed command with the emitter's canonical
quoting, while an emitter-quoted profile remains valid. The legacy path form
requires the exact registered module basename plus `.py` in the executable
argument position.
Foreign groups, fields, duplicates and event order are preserved. Existing
managed slots are refilled, then surplus managed groups are appended after all
existing groups for the event so additions do not shift foreign positional
trust keys unnecessarily. Removing an earlier managed slot can still shift a
foreign key. A malformed shared document is refused rather than replaced.

A disposable `codex-cli 0.155.1` app-server probe established that changing
only `description` changes neither the native positional key, `currentHash` nor
`trustStatus`. `WriteOp.changed` nevertheless compares only the old and final
`hooks` arrays, so provenance-only migration never prints a false re-trust
instruction. File deletion now requires actual recognized managed groups to be
removed and no foreign group to remain; a stamp on an empty document grants no
deletion authority.

## References

- `specs/designs/2026-09-13-multi-agent-harness-design.md` — decision 4 and step 7
- `src/lazy_harness/deploy/engine.py` — `ConfigTargetChangedError`, `_stamp`, `_read_targets`, `_refuse_if_changed`
- `src/lazy_harness/agents/codex.py` — `CodexConfigUnreadableError`, `_plan_hooks`, `_plan_mcp`
- `src/lazy_harness/deploy/snapshot.py` — `snapshot_targets`, which derives the rollback manifest from `config_targets()`
- `tests/unit/test_deploy_config_concurrency.py`, `tests/unit/test_agent_codex.py`, `tests/unit/test_deploy_config_engine.py`

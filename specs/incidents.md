# Incident ledger

Every verification gate in `CLAUDE.md` came from a failure the compound loop recorded more than once. `CLAUDE.md` carries the check — the thing to run. This file carries the evidence: what actually broke, and how.

The short version is in `CLAUDE.md`; this file is the expanded "why this gate exists" reference. The two are kept in the same order, so a gate's heading here matches its bullet there.

A gate whose incident is listed here is not retired. Retiring one means deleting both halves in the same commit, with the reason recorded in an ADR.

## A tool's exit code is not proof of its effect

`uv tool install --force` returned 0 and reused a cached wheel, so the new code never shipped. A config generator wrote syntactically valid TOML that the loader then rejected at load time — again, exit 0.

Both failures share a shape: the command reported on *itself*, not on the state it was supposed to produce.

## Config schema changes are tested through a full load cycle

A null hook matcher parsed fine and made the agent discard the entire settings file. Nothing raised; the settings simply stopped existing as far as the agent was concerned.

The create path and the merge-on-existing path each skipped a required field the other supplied, which is why they get separate round trips. Create also dodged the mode-preserving `chmod` that merge applied.

## Hooks handle every exception explicitly and exit 0

An unhandled exception in a hook escapes to the subprocess and crashes the chain rather than degrading. The inverse holds for a *blocking* hook, where exit 0 is itself the failure.

Hook tests that covered only the happy path missed both the wrong-type input and the out-of-scope file. Valid JSON of the wrong type — null, int, or list where a dict was expected — broke `.get()` calls that malformed-JSON tests never reached.

## Prose that names a mechanism is grepped against the code, in both directions

`auto_rebuild_on_commit` shipped as a config field for months doing nothing at all.

One ingest docstring promised a deterministic rebuild and left 2,139 orphaned rows behind, also for months.

In the other direction: `loop_events.jsonl` and `CLAUDE_DATA_DIR` both appeared in documentation, both pattern-matched this repo's conventions perfectly, and neither ever existed.

## Every path deriving a project key uses `--git-common-dir`, never `--show-toplevel`

Using `--show-toplevel` fragmented `decisions.jsonl` into per-worktree directories nothing reads, and split one repo across as many project rows as it had branches.

The fix has to land everywhere at once and be tested from a main checkout *and* a worktree — a partial fix leaves the two halves disagreeing about where memory lives.

## Fixing a safeguard updates its documented examples and every diagnostic that reports on it

A memory-size hook capped lines while the actual cost was bytes, waving a 20KB file straight through.

Stale examples become a false source of truth, and a diagnostic still measuring the old dimension reports false green after the fix lands.

## Parallel work is not isolated by default

Two worktrees writing ADRs in parallel collided on the sequence number.

Subagent diffs reached cleanup unreviewed more than once.

## An implemented hook does not run until it is wired and its binaries are reachable

Registration in `_BUILTIN_HOOKS` without a `config.toml [hooks.*]` entry passes every test in the suite and never executes once in production.

A binary living in a peer project's virtualenv was invisible to a hook running from the installed tool. A bare command name resolved from ambient `PATH` instead of the `pyproject.toml` pin; the divergence was silent, surfacing later as deterministic reformatting on edits and a flaky docs gate.

**Read the absence before fixing it.** `stop-verify-guard` is registered and unwired *on purpose* — nothing emits the `verify_ran` event it reads, so wiring it produces a guaranteed nag rather than calibrated enforcement. The decision is recorded in `specs/backlog.md` and in the comment above `_DEFAULT_ON_HOOKS`. A missing `config.toml` entry is evidence of a question, not proof of an oversight.

## A static list that should mirror a directory is derived from it

`GUARDED_HOOKS`, hand-maintained beside `hooks/builtins/*.py`, drifted the moment a hook was added.

A completeness test against the glob is what puts a new file in scope with no code change.

## Behavioural automation ships with kill criteria

A documented practice without enforcement ran at roughly 60% non-compliance.

Kill criteria are declared *before* deployment: a measured baseline, an adoption check at a fixed horizon, and the threshold below which the automation is removed. The calibration a baseline is read against stays frozen until that baseline closes — widening a matcher mid-measurement invalidates the comparison, which is why a new matcher starts biased toward false negatives.

## A test that passes with and without the thing it claims to cover, covers nothing

With a type guard removed, four tests written specifically to prove that guard still passed. Broad `except` clauses were hiding the failure.

The same blindness shows up in an expected value reverse-calculated from the implementation, and in an assertion that mirrors the code's own predicate.

`pytest.raises(match=...)` anchored on a loose substring matched text a `tmp_path` or traceback also carried.

Two `Path.cwd()` bugs survived years of green suites because every CLI test injected the parameter explicitly and default resolution was never exercised.

Restoring the guard after the experiment is done by hand — `git checkout` reverts the uncommitted implementation along with it.

## Every reader and writer of a config-derived path resolves it the same way

Readers honour `[monitoring] db` before falling back to the data dir. A hook that skipped that lookup wrote its file somewhere nothing reads: zero rows forever, no error, no complaint.

## Widening a type means auditing every path that names it

`path: Path` widened to `Path | str` without coercion left `path.parent` raising on every string but one.

For a pluggable protocol the audit covers every path naming its type or its config, not just the `Protocol` methods: `AgentAdapter` gained Codex beside Claude, and every leak was outside the adapter file — deploy, config, hook wiring, monitoring.

## Deploying a hook is binary-first, never from a worktree

Repository and deployed state diverge the moment a release cuts.

Running `uv` against live profiles from a worktree bakes that venv into deployed hooks, because the generators embed the invoking interpreter's path. The same mistake has degraded `uv.lock`.

## An artifact is verified by the system that consumes it

This repo generates launchd plists, systemd units, cron lines and `index.yml` for four foreign parsers. Every one of them has accepted a syntactically valid file and then rejected it at load time.

A qmd template that passed every check in the suite indexed zero documents on Linux.

For a gate script the rule runs in both directions: a `set -e` interaction once made a checker evaluate 1 of 11 views and exit 0 — it needed a case it must fail, not only a case it must pass.

## A scheduled job is verified by running it through its scheduler

The metrics sink reported inactive for 96 consecutive launchd runs while the identical command worked fine from a terminal. Code inspection plus a file-existence check caught none of it.

Credentials belong in the job definition — plist `EnvironmentVariables`, systemd `EnvironmentFile` — never in shell init, which no scheduler reads. The macOS Background domain additionally denies Keychain access, so a helper that falls back to it fails there and nowhere else.

## A duck-typed attribute on an injected collaborator is tested with that attribute absent

Scheduler backends read `getattr(proc, "stdout", "")` and `getattr(proc, "returncode", 0)`. A fake omitting either one silently yields the default — and the default reads as success.

## A cost optimisation starts from a measurement of the suspect category

Two token-cost hypotheses in this repo — deferred tool schemas, and a disconnected connector — were both disproved the moment they were instrumented.

A token accounting report showing 18x subscription spend was independently recounted from raw JSONL and confirmed within 1%: the suspicion was reasonable, the estimate was not evidence either way.

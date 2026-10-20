# ADR-071: `lh doctor` fails on a graph error only in a repo present on this host

**Status:** accepted
**Date:** 2026-10-20
**Implemented:** 2026-10-20 — `collect_graph_health` reports an absent repo as
`skipped`, `has_errors` decides the exit code, and both the text and `--json`
forms of `lh doctor` read it.
**Supersedes:** —
**Superseded by:** —
**Related:** ADR-025 (doctor Features section), ADR-068 (profiles are identity ×
agent), `specs/designs/2026-10-09-graph-freshness-design.md` §2.4

## Context

The `Graph repos` section of `lh doctor` (graph freshness design §2.4) shipped
with the rule "nothing here fails `lh doctor`": every line, `error` included,
was informational and the run still ended with "All checks passed" and exit 0.
The backlog carried the open question of whether an `error` should change the
exit code.

Two different things printed the same `✗`:

- a repo present on the host whose graph cannot stay fresh — a hook missing
  from `<git-common-dir>/hooks` or not forwarded by `core.hooksPath`, a
  directory that is not a git repository, or a check that crashed;
- a repo listed in `[knowledge.structure].repos` whose path does not exist.

`config.toml` is shared across hosts, while the set of checked-out repos is
not. Measured on 2026-10-20 with 0.89.5: the agents host printed 11 `✗ repo:
path missing` lines for repos only the workstation carries, and exited 0; the
workstation printed none. A doctor that failed on those would be red on that
host forever, with no repair available short of forking the shared config.

Doctor already distinguishes absence from degradation elsewhere: the sink
freshness section prints an absent subsystem as a grey `·`, because "an absent
subsystem is not a degraded one".

## Decision

1. **An absent repo is `skipped`, not `error`.** `_repo_health` returns
   `skipped` with the check detail `not on this host: <path>`, and the text
   section renders it as one grey `· <repo> — not on this host` line. It never
   flips the exit code. This holds for registered and discovered repos alike.
2. **An `error` in a present repo fails doctor.** `graph_repos.has_errors`
   is the single answer; the text renderer and `_doctor_json` both set
   `ok = False` from it, so the run ends with "Some checks failed" and exit 1
   in either form.
3. **Warnings stay non-failing.** A stale graph, no graph yet, a `failed` or
   `skipped` last update (timeouts included), ignored paths still indexed and
   extension drift are repairs `lh knowledge graph update` or the next commit
   makes; they are named, not exit-worthy.
4. **A collector failure stays a warning line.** When `collect_graph_health`
   itself cannot run, the section says so without failing doctor, as before:
   it reports a defect of doctor, not of the repos.

## Alternatives considered

- **Keep "nothing here fails doctor".** Rejected: a hook the dispatcher does
  not forward leaves the graph silently stale, and a gate reading the exit
  code never learns about it.
- **Fail on every `error`, absent paths included.** Rejected: a shared config
  makes the agents host fail permanently for repos it was never meant to
  carry.
- **A per-host repo list in `config.toml`.** Rejected for now: it adds a
  schema field to answer what the filesystem already answers, and a repo the
  host should carry but lost is still visible as a `·` line.

## Consequences

- A repo that should exist on a host but was deleted reads as `· not on this
  host` and does not fail doctor; the line is the only signal.
- Hosts that today show a present repo with a hook `error` start exiting 1
  after this ships. Both hosts measured on 2026-10-20 had none.
- `lh doctor --json` consumers see `status: "skipped"` where they saw
  `status: "error"` for an absent repo.

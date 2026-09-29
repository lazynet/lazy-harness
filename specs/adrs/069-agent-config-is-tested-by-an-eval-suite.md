# ADR-069: The agent configuration is tested by an eval suite before it is deployed

**Status:** proposed
**Date:** 2026-09-29
**Supersedes:** —
**Superseded by:** —
**Related:** ADR-021 (async response grading), ADR-037 (metric event v2 —
`workload`), ADR-038 (the `lh exec` envelope), ADR-039 (role-routed inference),
ADR-041 (multi-agent hook contract), ADR-045 (credential boundary), ADR-048
(Codex rollout streams), ADR-060 (`AGENTS.md` is the portable contract),
ADR-068 (profiles are identity × agent)

## Context

The governance surface — the system docs and repository contracts, the skills
and the hooks a profile deploys — changes as often as the code, and it is the
only part of the harness with no test in front of it. pytest covers a hook's
logic against a fed payload; nothing covers whether a changed contract, a
reworded skill description or a re-wired hook still produces the behaviour it
was written for once a real agent loads it. The repository's own gates already
name the gap: a claim about behaviour is verified by running the path, and an
artifact is verified by the system that consumes it — for a contract, that
system is the agent.

The signal that the advisory layer is not holding is measured, not suspected.
`lh metrics loops` on 2026-09-29 reports a success criterion declared in 29% of
the sessions the goal check evaluated (163 of 560) and verification run 5 times against 4,680
closed sessions. The compound loop's `failures.jsonl` for this repository holds
1,182 rows; the most frequent prevention tags are variants of the same two
failures — a claim made without the tool invocation that would evidence it, and
work started without a declared criterion — renamed by the grader on each
recurrence (`TOOL-INVOCATION-GATE-MANDATORY`,
`CRITERION-GATE-BEFORE-WORK-MANDATORY`, `EVIDENCE-CHAIN-MANDATORY-TRANSCRIPT`,
…). A rule edited to fix one of them today ships with no way to tell whether it
moved the rate, or whether it broke a neighbour.

ADR-021 grades sessions after the fact; that is monitoring. What is missing is
the test phase before deployment: a small set of real tasks run against a
candidate configuration, with criteria that hold without ground truth.

## Decision

1. **Two case kinds with different authority.** A case is `kind = "gate"` or
   `kind = "signal"`. A `gate` case covers deterministic mechanics — the
   contract is loaded, a hook fires or blocks on the real operation, a skill is
   invoked on the prompt meant to trigger it — and a red `gate` fails the run.
   A `signal` case covers behaviour — a criterion declared before work,
   evidence before a claim — and is reported, never blocking, until the
   baseline in decision 9 closes.

2. **The runner is `lh exec` against an ephemeral profile.** `lh eval run`
   deploys the candidate configuration into a temporary config directory, then
   runs each case through `lh exec --agent <agent>` with
   `--workload eval:<case-id>`, so the envelope, cost provenance, timeout and
   typed `error.kind` of ADR-038 apply unchanged. A hook's logic stays covered
   by pytest; the suite covers only what pytest cannot see, the wiring through
   the real agent. The ephemeral profile carries its identity's secrets file
   (ADR-045 D1); a profile whose secrets cannot be overlaid is skipped as
   `skipped: credentials`, never run on the ambient account.

3. **A case is a TOML file.** Fields: `id`, `kind`, `prompt`, `agents`,
   `identities`, `fixture` (a minimal git repository copied to a temporary
   directory per run), `covers` (path globs, decision 5), `max_usd`, `source`
   (the `failures.jsonl` rows it was harvested from), and a list of `checks`.
   Cases live in the user's configuration, under a directory named by
   `[evals].cases_dir`; the framework ships the runner, the schema and its own
   test fixtures, not a user's cases.

4. **Checks are deterministic first; a judge is confined to `signal`.** The
   deterministic checks read the normalised transcript each adapter's
   `TranscriptReader` already produces: `tool_called(name, args)`,
   `tool_before_text(tool, pattern)` (the evidence precedes the claim),
   `hook_fired(name)`, `hook_blocked(name)`, `text_matches(pattern)` and
   `file_state(path, …)` over the fixture after the run. A `judge(rubric)` check
   calls `run_inference` under an `eval-judge` role with a clean context — the
   transcript and the rubric, nothing else — and is rejected by the loader on a
   `gate` case, naming the case and the check.

5. **Selection by path, full run before release.** `lh eval run` without
   arguments runs the cases whose `covers` globs match the paths changed
   against the merge base; `--all` runs every case and is part of the
   pre-release routine alongside the coherence audit. Changing a governance
   path without a recorded run is a process rule in `AGENTS.md`, not a
   technical block on `lh deploy`.

6. **Two cost ceilings.** Each case has `max_usd` (default USD 0.25); each run
   has `--budget-usd` (default USD 2 for a path selection, USD 10 for `--all`).
   `lh exec` prices a run only once it ends, so the per-case ceiling is applied
   after the fact — a case over it fails as `over-budget` — and `--timeout` is
   what stops a runaway live. A run that reaches its budget stops launching and
   reports every case not run as `skipped: budget`, never as passed.

7. **Coverage is identity × agent.** A case declares `agents` and `identities`;
   the runner expands the product over the configured profiles (ADR-068), so
   both adapters are exercised where their hook payloads and transcripts
   diverge (ADR-041, ADR-048).

8. **Cases are harvested semi-automatically, and must fail first.**
   `lh eval harvest` clusters `failures.jsonl` rows by summary similarity and
   normalised tags, reports each cluster's count, and writes a draft case —
   prompt and suggested checks — that a human edits and accepts. A case is
   accepted only after it fails against the configuration preceding the fix it
   covers, or against a mutation deleting the rule; one that passes both ways
   covers nothing.

9. **Kill criteria, declared now.**
   - *Baseline:* the first `--all` run against `main`, three repetitions per
     case. A case that passes one or two of its three repetitions is flaky
     and cannot be `gate`.
   - *Horizon:* six weeks from the first run.
   - *Adoption:* at least one recorded run for every merged change touching a
     governance path.
   - *Value:* at least one regression caught before deployment — a red `gate`
     that changed what shipped — or a measured drop in the covered
     `failures.jsonl` clusters against the six weeks before the first run.
   - *Removal:* at the horizon, no adoption, or neither value condition, retires
     the suite: the command is removed and the cases archived. If only the
     `signal` half shows no value, the judge is removed and the `gate` cases
     stay.
   - Thresholds, ceilings and rubrics are frozen until the baseline closes.

## Alternatives considered

Calling `claude -p` and `codex exec` directly would drop one layer and
re-implement the pricing, timeout and failure typing `lh exec` already owns,
once per agent. Replaying a captured hook payload through `lh hook` costs no
tokens but is what pytest already does, and cannot see the wiring — a hook
registered is not a hook that runs.

A judge on every behavioural case, or on `gate` cases, would make the most
common failure easy to express and would put a non-deterministic grader in
front of a deploy. Most of the recurring failures are expressible as ordering
over the transcript (`tool_before_text`), so the judge is kept for the
remainder and denied blocking authority.

Blocking `lh deploy` on a green run keyed by the configuration's hash is the
stronger enforcement, and is itself behavioural automation with no baseline;
it is the natural successor once decision 9 closes with value, not the
starting point. Generating cases automatically from every cluster above a
count would fill the suite with checks nobody saw fail.

## Consequences

- A governance change gains a pre-deploy test that runs the agent it
  configures; the evidence gates in `AGENTS.md` get a mechanism instead of a
  reminder.
- Every run spends real tokens. The `eval:` workload prefix keeps that spend
  separable in `lh metrics`, and the `flex` identity's cases draw on that
  identity's own account.
- The ephemeral deploy is only as faithful as the deploy it copies; a
  divergence between the temporary and the real config directory is a false
  green. The runner deploys through the same engine `lh deploy` uses rather
  than a parallel writer.
- The configuration a user deploys lives in their dotfiles, outside this
  repository. Path selection has to diff that source as well as this one; how
  the runner learns the dotfiles' merge base is left open for the design.
- The suite is advisory in its enforcement (decision 5) and may be deleted by
  its own criteria (decision 9); neither is a defect.

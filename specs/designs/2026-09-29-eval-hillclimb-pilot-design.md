# Evaluation and hillclimbing pilot for compound-loop proposals

**Status:** proposed\
**Date:** 2026-09-29\
**Decision:** pending; accept an ADR before implementation or paid experiments.

## Problem

The compound loop proposes durable workflow rules from session transcripts.
Changing its prompt needs evidence that useful proposals survive while redundant
or unsupported proposals decrease. Generating fewer proposals alone proves
nothing: an evaluator that always returns an empty list would win that metric.

The [backlog](../backlog.md) defers a multi-model evaluation framework until a
concrete use case exists. This design supplies one bounded use case and a way
to decide whether reusable infrastructure is worth maintaining.

## Existing integration points

- [`build_prompt`](../../src/lazy_harness/knowledge/compound_loop.py) accepts
  the session summary, existing knowledge, captured insights, rejected and
  pending proposals, and recent failures. Its output includes
  `claude_md_proposals` alongside other compound-loop fields.
- [`run_inference`](../../src/lazy_harness/llm/invoke.py) resolves an inference
  role and returns output, success, model, backend, duration, and an error.
  Its result does not contain token usage or billed cost. Its schema check
  covers only selected constraints; it is not full JSON Schema validation.
- [`resolve_role`](../../src/lazy_harness/llm/roles.py) resolves `distill` through
  existing configuration. The pilot should reuse that resolution in an isolated
  configuration rather than introduce another provider registry.

These are source-level integration points, not evidence that a replay runner
or the external skill has been exercised. This specification changes no runtime.

## Goals and non-goals

The pilot must produce a reproducible baseline, a bounded search over prompt
changes, and an independent final comparison. Its primary goal is fewer
unnecessary proposals without materially reducing useful-proposal recall.

The first experiment changes only proposal-related instruction text inside
`build_prompt`. It keeps the model, backend, input assembly, output schema,
remaining instructions, and runtime configuration fixed.

Out of scope: automatic rule adoption, scheduled optimization, hook deployment,
editing live profiles or knowledge stores, model routing, general harness
rewrites, and a new judge-model dependency. Jev is an optional future evaluator,
not a requirement of this pilot. No `lh eval` or `lh hillclimb` command ships yet.

## External workflow and compatibility gate

Use the `claude-api` skill's `build-eval` and `hillclimb` workflows described in
[Anthropic's article](https://claude.dev/blog/automating-eval-design-and-hillclimbing/).
The article is a design reference, not proof of the installed skill's behavior.

Before implementation, inspect and record the installed Claude Code version,
skill source and revision or content digest, command availability, generated
artifacts, approval points, and actual data access. Exercise a disposable
fixture and record observations in the experiment report before writing tests
for an adapter. Installation or a successful help command is insufficient.

The article's repeated use of a held-out "test" split is validation for this
pilot. Configure or explicitly steer the workflow to use development and
validation data only. A separate final test is never supplied to the optimizer.
If that boundary cannot be enforced, stop the native workflow; do not silently
downgrade the final test to another optimization signal.

## Corpus and labels

Start with reviewed, sanitized session inputs. Preserve the complete inputs
to `build_prompt`, including the knowledge and proposal lists that existed at
the time. Missing historical context is marked explicitly and excluded from
the primary analysis; do not substitute today's lists and call it a replay.

Sample ordinary sessions as well as known failures. Include sessions where no
proposal is warranted, paraphrases of rejected or pending rules, unsupported
generalizations, and recurring failures that justify a concrete new rule.
Synthetic adversarial cases are a separately reported diagnostic set.

Before baseline execution, a human reviewer labels expected useful concepts,
forbidden or redundant concepts, supporting evidence, and legitimate abstention.
Labels describe meaning rather than exact wording. Ambiguous cases are resolved
or quarantined before splitting, never removed because a candidate fails them.

Split by project or related-session cluster, with near-duplicates kept together:
50% development, 25% validation, 25% final test. Record the seed and assignments.
Choose the corpus size from calibration variance and the success thresholds
below; split ratios alone do not establish sufficient statistical power.

Private inputs, labels, and transcripts stay outside tracked repository files.
Record consent for provider transmission and a retention deadline before use.
Published reports contain sanitized aggregates and hashes, not raw sessions.

## Evaluator

Use code to validate the complete output structure and required field types.
Use reviewed semantic judgments to match proposals to expected concepts and
identify duplication, unsupported claims, or inappropriate scope. The evaluated
model must not be its own semantic judge.

Calibrate the judge against human labels on a separate calibration set. Present
baseline and candidate outputs without identity and randomize pair order. Repeat
judging identical outputs and record disagreement; freeze judge model, rubric,
and settings before the scored baseline. Any change starts a new experiment.

The evaluator must reject deliberately degraded outputs: all-empty proposals,
duplicates, unsupported rules, and malformed output. It must accept a reviewed
valid proposal and a justified empty response. If it cannot distinguish these
controls, optimization is blocked regardless of its aggregate score.

## Metrics and decision rule

Aggregate repeated runs within each session before computing intervals; repeated
calls are not independent new cases. Compare baseline and candidate on the same
inputs and repetition schedule, interleaving their execution. Use paired cluster
bootstrap intervals at 95%, resampling the independent corpus clusters.

| Metric | Definition | Required result on the final test |
|---|---|---|
| Unnecessary proposals | Unsupported, redundant, or out-of-scope proposals per session; each proposal counted once | At least 20% relative reduction, with the lower confidence bound of baseline minus candidate above zero |
| Useful-proposal recall | Expected useful concepts recovered / expected useful concepts; abstention-only sessions excluded | Lower confidence bound of candidate minus baseline at least -5 percentage points |
| Abstention accuracy | Fraction of no-proposal sessions producing no proposals | Lower confidence bound of candidate minus baseline at least -5 percentage points |
| Output validity | Fraction satisfying the complete output contract | No new schema failure in paired runs |
| Other compound-loop fields | Reviewed checks for decisions, failures, learnings, handoff, grade, goal declaration, and project update | No newly observed regression on the frozen control cases |
| Inference cost | Attributable cost per replay, with price provenance | Candidate mean no more than 10% above baseline |
| Latency | Per-call duration and p50/p95 distribution | Reported separately; no latency improvement claim without evidence |

These are proposed acceptance thresholds, not measurements. Freeze them before
baseline execution. A zero unnecessary-proposal baseline has no reduction
headroom; stop this objective. Insufficient positive examples or intervals too
wide for the recall margin produce an inconclusive result, not a pass.

Do not treat unavailable cost as zero. Obtain usage and pricing from a verified
provider record, or an attributable billing measurement, without widening the
production inference protocol for the pilot. Separate optimizer, judge, and
replay costs. If cost cannot be measured or conservatively bounded, the cost
gate remains unmet and the candidate cannot qualify for adoption.

## Search and isolation

1. Freeze a manifest with the corpus and split hashes, code revision, exact
   prompt, model/backend settings, judge, metrics, budget, and stopping rules.
2. Run baseline calibration and the development/validation baseline. Check that
   the detectable effect fits the declared thresholds before optimizing.
3. Let Claude inspect development failures and propose one hypothesis and patch
   per round. Evaluate each candidate on development and validation. Reject
   regressions or improvements confined to development; record every attempt.
4. Stop after six candidate rounds, two consecutive rounds without a qualifying
   validation improvement, or the budget limit, whichever occurs first.
5. Freeze one selected candidate and its hash. An independent runner evaluates
   baseline and candidate on the final test once, using the predeclared repeats.
6. Report success, failure, or inconclusive evidence. Final-test failures never
   feed another round in the same experiment.

The proposed cap is USD 25 of total inference spend and three hours of execution
per experiment, including calibration, judge calls, and final evaluation.
Reserve final-test budget before search. Record an operator-approved budget
before the first paid call; this document itself authorizes no expenditure.
Admission checks must bound the next batch's cost and set per-call timeouts.

Run candidates in disposable worktrees with disposable configuration and output
directories. Invoke prompt construction and inference without starting the live
worker or persistence path. Capture and validate responses through the real
consumer parser in an isolated fixture; a runner-only validator is insufficient.

The optimizer's filesystem and tools must exclude final-test inputs, labels,
outputs, and credentials for retrieving them. Keeping files out of its prompt
is insufficient. Use a separate restricted process or environment and test the
access denial. Credentials needed for approved inference stay out of artifacts.

Do not broaden edit permissions when a candidate proposes a change outside the
allowlist. Do not disable repository gates. Each production prompt patch needs
a failing behavioral regression test first and a mutation check showing that
removing the change makes that test fail. Existing commit gates still apply.

## Artifacts and implementation boundary

Each experiment retains a frozen manifest, reviewed labels and split map, the
baseline and candidate patches, per-call JSONL results and transcripts, evaluator
verdicts with evidence, failures and retries, cost records, and a comparison
report with confidence intervals and a decision. Record missing fields explicitly.

Infrastructure errors remain visible and never become a correct empty result.
Predeclare retry limits; retain original attempts and their cost. Contaminated
or materially incomplete runs cannot support adoption. Check artifact hashes
before comparing results and reject incompatible manifests.

Pilot runners and external-skill output live in scratch space or an experiment
branch, following [repository layout](../workflow/layout.md). They are not new
production modules. Keep only sanitized reports suitable for this public repo.
No release, merge, configuration deployment, or rule adoption is automatic.

After the pilot meets the promotion criteria, a separate design may propose a
portable runner under `src/lazy_harness/` and commands such as `lh eval run` and
`lh eval compare`. These names are illustrative and do not describe existing
commands. Reuse inference resolution; keep patch generation in agent workflows.

## Acceptance checks and removal criteria

Before accepting the pilot runner, demonstrate both directions of its gates:
valid and malformed artifacts; matching and mismatched manifests; allowed and
denied paths; useful and empty-all candidates; available and exhausted budget;
successful inference and infrastructure failure. Remove each safeguard in turn
and observe the corresponding test fail before restoring it.

Complete at most two experiments within 30 days of the first baseline. The
second may refine the approach, but must reserve fresh final-test clusters.
Two experiments are a maintenance checkpoint, not two chances to report the
better p-value; retain and report both outcomes.

Promote reusable infrastructure only if at least one experiment meets every
final-test gate and a second experiment reuses the workflow without redesigning
the runner. If neither yields a verified improvement, remove the experimental
integration and leave the generic framework deferred. An inconclusive result
does not extend the pilot automatically.

If a candidate is adopted through normal review and release, check adoption
after 30 days against the frozen baseline rubric on new reviewed sessions.
Revert the candidate if useful-proposal recall drops by more than five percentage
points or unnecessary-proposal reduction falls below 20%. If evidence remains
insufficient at that checkpoint, revert pending a new proposal. Keep calibration
fixed through this checkpoint and record the runtime version actually observed.

## Alternatives

| Option | Benefit | Cost or limitation |
|---|---|---|
| Native Claude skill plus bounded pilot | Tests value before maintaining a framework | Requires verifying external workflow behavior and enforcing data isolation |
| Build a generic `lh` optimizer immediately | Portable interface from the start | Commits to maintenance before a measured use case; remains deferred |
| Manual prompt edits with unit tests only | Lowest setup cost | Tests known examples without estimating production quality or uncertainty |
| Introduce a specialized judge first | May reduce evaluation cost and variance | Adds calibration and integration work before the objective is validated |

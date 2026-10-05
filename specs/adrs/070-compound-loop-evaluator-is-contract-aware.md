# ADR-070: The compound-loop evaluator sees the contracts in force

**Status:** proposed
**Date:** 2026-10-05
**Supersedes:** —
**Superseded by:** —
**Related:** ADR-008 (compound loop as async worker), ADR-019 (handoff
freshness and the reprocess growth gate), ADR-021 (async response grading),
ADR-039 (role-routed inference), ADR-060 (`AGENTS.md` is the portable
repository contract), ADR-069 (the agent configuration is tested by an eval
suite)

## Context

The compound-loop evaluator proposes `claude_md_proposals` without seeing the
contracts the session ran under: the profile's system document and the
repository's `AGENTS.md`. `build_prompt` in
`src/lazy_harness/knowledge/compound_loop.py` makes this worse by asking for
it: when the session's failures or the recorded failures show the same root
cause two or more times, it requests an `[EVITAR]` proposal, whether or not a
rule for that root cause already exists.

The damage is measured. Draining all 26 project queues on 2026-10-05 (54
pending, 99 held) accepted 12 and rejected 141. Of the 54 pending, 24 were
rejected because they restated a rule of the profile contract —
evidence-before-claims or first-action. The held entries were not classified
by reason. The immunity registry, `claude-md.rejected.md`, does not contain
this, because it is per project: rejecting a restatement in one repository
does not stop the same restatement in the next. A rule violated fourteen times
does not need a fifteenth copy. It is an enforcement gap, and the queue
currently hides it.

The design, `specs/designs/2026-10-05-evaluator-contract-dedupe-design.md`,
proposed an id-keyed rule index in the prompt, a `rule_violations` output
field, and an `lh doctor` report. Before any test, a probe ran the real
`distill` role once against a spliced prompt (recorded in
`specs/designs/claude-code-evidence.md`, "Distill role — rule_violations
schema probe (2026-10-05)"). It confirmed one claim and falsified two
premises:

- **Confirmed:** `rule_violations` survives the unchanged `parse_response` as a
  list. It came back empty, so neither citing a valid id nor inventing one was
  exercised.
- **Falsified, budget:** with the design's 6,000-character budget trimming the
  profile contract first, the repository contract alone filled 28 rules and
  5,791 characters and the profile contract got **zero** rules. Each contract
  yielded 43 extracted entries; repository bullets average about 200
  characters, several over 500. The rule behind the 24 restatements was
  outside the index.
- **Falsified, trigger:** a kept repository rule closely matched the fixture's
  failure and the model cited nothing. The new instruction hung off the
  `[EVITAR]` trigger, which needs the root cause two or more times, so a
  single-session violation never reaches it.

A follow-up measurement for this ADR, with the probe's extractor, shows two
more things. The profile's evidence-before-claims rule is a prose paragraph
under its heading, not a bullet, so a bullet extractor reaches it only as a
bare heading. And the first-action rule is not in either contract at all: a
hook injects it at prompt time. No contract index can suppress restatements of
a rule that lives in a hook.

## Decision

This ADR adopts the design with the corrections the probe forces. Where the
two differ, this ADR governs.

1. **A rule index enters the prompt.** A new module,
   `knowledge/contract_index.py` (new), builds `ContractRule` entries (new) —
   `id`, `source`, `text` — from the profile contract
   (`agent_dir / adapter.system_docs()[0]`) and the repository contract, the
   instruction file at the root derived from
   `git rev-parse --path-format=absolute --git-common-dir` and `.parent`.
   Paths are deduplicated by `realpath`. The id is
   `<source>:<hash16>`, the first 16 hex digits of the SHA-256 of the
   whitespace-collapsed, lower-cased rule text, so reflowing a paragraph keeps
   the id. When the index is non-empty, `build_prompt` gains a section
   `## Rules already in force (id — rule)`. When it is empty, the prompt is
   byte-identical to today's.

2. **The indexed unit is a rule's lead-in, not its body.** A bullet or
   numbered item is indexed as its bold lead-in, or its first sentence when it
   has none, capped at 160 characters. Headings are not rules and are not
   indexed on their own. A section whose body is prose with no list is indexed
   once, as its heading joined to the first sentence of its first paragraph —
   this is what reaches the profile's evidence-before-claims rule. Code
   fences, tables and nested items are skipped. Measured on the probe's two
   contracts, lead-ins take 4,002 characters for 36 repository rules and
   2,752 for 29 profile rules, against 11,281 and 6,044 for the full text with
   headings.

3. **The budget is split by source, not trimmed in order.** The default
   budget stays at 6,000 characters. Each source gets half; a source that uses
   less than its half releases the remainder to the other. Within a source,
   rules are kept in document order and the tail is trimmed. Lead-ins alone
   would not have been enough: 6,754 characters still exceed 6,000, and a
   profile-first trim would again cut the profile. The quota guarantees both
   contracts appear whatever their sizes. On the measured pair, the profile's
   2,752 fit whole and the repository keeps about 3,250 characters of its
   4,002. The quota is the allocation this ADR decides; the alternatives are
   listed below.

4. **`rule_violations` is emitted per session, not on recurrence.** The output
   schema gains
   `"rule_violations": [{"rule_id": "...", "evidence": "one sentence from the transcript"}]`,
   requested whenever the transcript shows the session violating a listed
   rule, independent of the `[EVITAR]` trigger. Recurrence is what `lh doctor`
   aggregates across sessions and projects (decision 6); asking the grader to
   detect it as well hides first occurrences and, as the probe showed, leaves
   the branch unreachable. Separately, the `[EVITAR]` instruction gains one
   clause, only when the section is present: a recurring root cause covered by
   a listed rule produces a violation citing its id instead of a proposal.
   Suppression still happens only through an explicitly cited id.

5. **Ids are validated before anything is written.** The worker checks each
   entry against the index built for that run. An unknown id is dropped and
   logged, never persisted, so an invented id earns nothing. A
   `rule_violations` value of the wrong type — null, int, dict, entries
   missing a key or carrying a non-string — is dropped with a log note and
   never fails the task. Valid entries are appended under `memory_dir_lock` to
   `memory_dir/rule_violations.jsonl` (new) with `ts`, `session_id`,
   `rule_id`, `source`, `rule_text` and `evidence`. `rule_text` is a snapshot,
   so a violation of a rule since edited stays readable as an orphan.

6. **`lh doctor` reports the most-violated rules.** A new section walks
   `all_memory_dirs` and lists, over 30 days, the count per rule, the projects
   affected, and orphaned ids labelled as changed since. It warns and never
   fails. A rule that keeps topping it is a candidate for a hook, not for more
   prose.

7. **Degradation falls back to today, never to something new.** A missing,
   unreadable or undecodable contract (`OSError`, `UnicodeError`) is skipped.
   With no readable contract the section is omitted. A worker with no resolved
   profile indexes the repository contract only.

8. **Sequencing: this lands before the hillclimbing pilot.** The pilot
   (`specs/designs/2026-09-29-eval-hillclimb-pilot-design.md`) freezes input
   assembly and the output schema while it varies proposal instruction text,
   and this change alters both, so the two cannot run at once. The maintainer
   decided on 2026-10-05 that this change goes first. The pilot then runs
   against the contract-aware evaluator as its baseline, and may reuse this
   change's hand classification of restatements as its "unnecessary proposal"
   labels.

9. **Acceptance and merge preconditions.** This ADR moves to `accepted`, and
   the implementation merges, only when all of the following hold:
   - The B and C kill-criteria readings are recorded in `specs/backlog.md` at
     their 2026-10-13 horizon. The B re-reading, over proposals dated on or
     after the v0.83.2 deploy, is this change's baseline.
   - A **second probe** of the real `distill` role is recorded in
     `specs/designs/claude-code-evidence.md`, with the index built as in
     decisions 2 and 3. Its fixture shows a clear violation of a rule that is
     inside the index and visible in the evaluator's extracted transcript, and
     the probe must observe a cited id. It also includes a canary that invites
     an id not in the index, and records whether the role invents one, so the
     drop path in decision 5 has been seen against the real role and not only
     in a unit test.

10. **Kill criteria, copied from the design.**
    - *Baseline:* the B re-reading at its horizon, over proposals dated on or
      after the v0.83.2 deploy: the acceptance rate and the share of proposals
      that restate a rule in force, classified by hand.
    - *Horizon:* 14 days from the release being installed on the primary
      machine (`uv tool install --reinstall` plus a site-packages grep), not
      from the merge.
    - *Success:* restatements ≤ 10% of proposals, an acceptance rate at or
      above baseline, and rule violations recorded in at least three
      projects.
    - *Removed if:* the acceptance rate falls, newly accepted rules per week
      drop by more than 50% (the grader is over-suppressing), or evaluator cost
      per evaluated session rises by more than 15%.
    - *Calibration:* start biased toward false negatives. Suppression happens
      only through an explicitly cited id. Budget, quota, cap and wording stay
      frozen until the horizon.

## Alternatives considered

| Option | Benefit | Cost or limitation |
|---|---|---|
| Index of lead-ins with a per-source quota (chosen) | Both contracts present by construction; one inference call; ids make violations countable | About +6 KB of prompt per run; lead-ins lose detail from long rules |
| Profile-first trim of full bullets (the design) | Simplest | Measured: the profile got zero rules, losing the motivating case |
| Lead-ins with a profile-first trim | Fits most of both contracts | Measured at 6,754 characters, still over 6,000; the profile is cut first again |
| Per-source quota over full bullets | No extraction heuristic | The profile keeps about half its rules and the repository about a quarter |
| Larger budget, full bullets | Maximum fidelity per rule | About 11 KB for the repository contract alone, inflating the cost C measures |
| Dropping headings as the only fix | Removes noise entries | Saves about 1 KB across both contracts; loses the prose-only evidence rule entirely |
| Full contract text in the prompt | Maximum fidelity | Up to about 24 KB per run, mostly non-rule text |
| Second classifier call after the grader | Main prompt untouched | Doubles calls, the metric C tracks |
| Cross-project rejected registry as immunity | No contract reading | Learns only after a human rejects; no ids for violations |
| Embedding similarity | Wording-independent matching | New infrastructure for a judgement the grader already makes by reading |
| `rule_violations` only on the `[EVITAR]` recurrence trigger | Fewer false positives | Measured unreachable on a single-session violation; duplicates the aggregation `lh doctor` does |

## Consequences

- The evaluator stops being asked for rules it cannot know exist, and a
  violated rule becomes a count with an id instead of another proposal.
- Rules injected by hooks or plugins, such as the first-action rule, are
  outside both contracts and outside the index. Their restatements will keep
  arriving; the hand classification behind the baseline and the success
  threshold has to report them separately, or the ≤ 10% target measures
  something the change cannot move.
- `extract_messages` carries no tool calls. A violation that is only visible
  as a missing tool invocation, such as a claim made without evidence, can be
  reported by the grader as a view artifact. Per-session emission makes these
  counts noisier; the `evidence` field is what lets a reader audit them, and
  the second probe's fixture is chosen to avoid the blind spot rather than to
  rely on it.
- `process_task` receives only the task file, the config and the learnings
  directory today, while the worker resolves the adapter and runtime directory
  in `main`. Indexing the profile contract needs that pair plumbed into
  `process_task`.
- The pilot's baseline moves: anything it measures is relative to the
  contract-aware prompt and schema, not to today's.
- Every evaluated session pays for the index. Decision 10's cost trigger is
  what keeps that honest.

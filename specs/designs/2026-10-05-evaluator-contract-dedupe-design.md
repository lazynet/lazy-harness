# Contract-aware compound-loop evaluator

**Status:** proposed\
**Date:** 2026-10-05\
**Decision:** pending; accept an ADR before implementation. Do not merge before
the kill-criteria horizon of B and C closes (2026-10-13) and both readings are
recorded in the [backlog](../backlog.md).

## Problem

The compound-loop evaluator proposes `claude_md_proposals` without ever seeing
the contracts already in force: the profile's system document and the
repository's `AGENTS.md`. A failure whose root cause an existing rule already
covers is therefore proposed again as a new `[EVITAR]` rule, and
[`build_prompt`](../../src/lazy_harness/knowledge/compound_loop.py) actively
asks for it: two or more occurrences of the same root cause trigger an
`[EVITAR]` proposal, whether or not a rule for it exists.

The immunity registry (`claude-md.rejected.md`) does not contain the damage,
because it is per project: rejecting a restatement in one repository does not
stop the same restatement in the next.

Measured on 2026-10-05, draining all 26 project queues (54 pending, 99 held)
accepted 12 and rejected 141. Of the 54 pending, 24 were rejected as
restatements of the profile contract's evidence-before-claims or first-action
rules. The held entries were not classified by reason, but read the same way.

A rule violated fourteen times does not need a fifteenth copy. It is an
enforcement problem, and today that signal is lost in the noise of the queue.

## Goals and non-goals

Goals:

- The evaluator stops proposing rules equivalent to one already in force in
  the profile or repository contract.
- A recurring failure that an existing rule covers becomes a **rule violation**
  record, attributed to that rule and countable across projects.
- `lh doctor` reports the most-violated rules, so enforcement gaps (candidates
  for a hook, not for more prose) become visible.

Non-goals: automatic rule adoption, editing any contract, a judge model or
embeddings, changing the inference role or model, and cross-project immunity
through the rejected registries.

## Existing integration points

- `process_task` assembles the prompt from the task's `cwd` and `memory_dir`
  and routes it through `run_inference(role="distill")`.
- The worker already resolves the profile's adapter and runtime directory
  (`_agent_dir_for_profile` in
  [`compound_loop_worker.py`](../../src/lazy_harness/knowledge/compound_loop_worker.py)).
  The profile contract is `agent_dir / adapter.system_docs()[0]`.
- The repository contract is the instruction file at the repository root,
  derived with `git rev-parse --path-format=absolute --git-common-dir` and
  `.parent`, never `--show-toplevel` (the project-key verification gate).
- `core/proposals.rule_lines` and `_tail_within_budget` already parse and budget
  rule text for the rejected and pending sections.
- `lh doctor` already walks `all_memory_dirs` for halted proposal queues.

## Design

### Contract index

A new pure module, `knowledge/contract_index.py`:

```python
@dataclass(frozen=True)
class ContractRule:
    id: str        # "<source>:<hash16>", source in {"profile", "repo"}
    source: str
    text: str

def build_contract_index(contracts: list[tuple[str, Path]], max_chars: int) -> list[ContractRule]: ...
```

- It extracts bullets and headings, not code blocks, tables or layout prose.
- `hash16` is the SHA-256 prefix of the whitespace- and case-normalized rule
  text, so reflowing a paragraph does not change an id.
- Paths are deduplicated by `realpath`, because some repositories keep
  `CLAUDE.md` as a symlink to `AGENTS.md`.
- The budget (default 6,000 characters) trims the profile contract first: it is
  the most generic, and the repository contract is what this session ran under.

### Prompt and schema

When the index is non-empty, `build_prompt` gains a section
`## Rules already in force (id — rule)` and the output schema gains:

```json
"rule_violations": [{"rule_id": "repo:3f2a…", "evidence": "one sentence from the transcript"}]
```

The `[EVITAR]` instruction changes only when the section is present: if a
recurring root cause is covered by a rule in force, emit a `rule_violations`
entry citing its id instead of a proposal. When the index is empty, the
prompt is byte-identical to today's.

### Persistence

The worker validates each entry against the index built for that run. An id
that is not in the index is dropped and logged, never persisted. A model that
invents an id gets no credit for it. Valid entries are appended to
`memory_dir/rule_violations.jsonl` under `memory_dir_lock`:

```json
{"ts": "...", "session_id": "...", "rule_id": "...", "source": "repo", "rule_text": "...", "evidence": "..."}
```

`rule_text` is a snapshot. When a contract edit changes a rule's hash, earlier
violations become orphans that are still readable.

### Reporting

`lh doctor` adds a **Most-violated rules** section across `all_memory_dirs`:
the count per rule over 30 days, the projects affected, and orphaned ids
labelled "rule since changed". It is a warning, never a failure.

## Error handling

- **A missing, unreadable or undecodable contract** (`OSError`, `UnicodeError`)
  is skipped. With no readable contract, the section is omitted and behaviour
  equals today's. Degradation falls back to the current behaviour, never to a
  new one.
- **`rule_violations` of the wrong type** (null, int, dict, entries missing
  keys or with non-string values) is dropped with a log note, and the task
  never fails on it. Every `.get()` is guarded by a type check.
- **A worker with no resolved profile** indexes the repository contract only.

## Testing

Strict TDD, each guard removed by hand to watch its test fail, never with
`git checkout`.

- **Parser:** fixtures copied from real contracts. Ids are stable across
  reflow, the budget trims the profile first, and symlinked duplicates are
  indexed once.
- **`build_prompt`:** the section appears with rules and is absent without
  them. The `[EVITAR]` wording changes only with the section, and the prompt is
  byte-identical to the current one on an empty index.
- **Worker:** an invented id is not persisted; this test must fail with
  validation removed. Plus wrong-type payloads for every field.
- **Repository contract resolution** from a main checkout *and* from a
  worktree.
- **`lh doctor`:** an integration test over two projects, asserted against a
  hand count.
- **Consumer probe first:** run the real `distill` role once against a
  fixture session with the new schema, record the raw response in
  `claude-code-evidence.md`, and confirm that `rule_violations` parses. Only
  then write the first test.

## Kill criteria

Declare these in the backlog before deploy:

- **Baseline:** taken from the B re-reading at its horizon, over proposals
  dated on or after the v0.83.2 deploy. It covers the acceptance rate and the
  share of proposals that restate a rule in force, classified by hand.
- **Horizon:** 14 days from the release being installed on the primary
  machine (`uv tool install --reinstall` plus a site-packages grep), not from
  the merge.
- **Success:** restatements ≤ 10% of proposals, an acceptance rate at or above
  baseline, and rule violations recorded in at least three projects.
- **Removed if:** the acceptance rate falls, newly accepted rules per week drop
  by more than 50% (the grader is over-suppressing), or evaluator cost per
  evaluated session rises by more than 15%.
- **Calibration:** start biased toward false negatives. Suppression happens
  only through an explicitly cited id. Keep it frozen until the horizon.

## Sequencing with the evaluation pilot

The [hillclimbing pilot](2026-09-29-eval-hillclimb-pilot-design.md) freezes
input assembly and the output schema while it varies proposal instruction
text. This design changes both, so the two must not run at the same time.
Whichever lands first sets the baseline the other measures against. The
pilot's "unnecessary proposal" labels can serve as this design's
restatement classification.

## Alternatives

| Option | Benefit | Cost or limitation |
|---|---|---|
| Contract index in the prompt plus `rule_violations` (chosen) | One inference call; the grader decides with the rules in view; ids make violations countable | Prompt grows by up to the index budget |
| Full contract text in the prompt | Maximum fidelity | Up to ~24 KB per run, mostly non-rule text, which inflates the cost C measures |
| Second classifier call after the grader | Keeps the main prompt untouched | Doubles calls, the very metric C tracks |
| Cross-project rejected registry as immunity | No contract reading | Learns only after a human rejects; no ids for violations |
| Embedding similarity | Wording-independent matching | New infrastructure for a judgement the grader already makes by reading |

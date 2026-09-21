# ADR-064: The planned config document is validated by the agent's own detector

**Status:** accepted
**Date:** 2026-09-20
**Supersedes:** —
**Superseded by:** —
**Related:** ADR-042 (multi-file config planning), ADR-052 (profile assets per
agent), ADR-063 (the hook ownership ledger)

## Context

ADR-063's ledger was one way to write a `settings.json` that Claude Code 2.1.278
discards whole. It is not the only one. The document is *merged*: everything the
harness does not generate is copied out of what was on disk and back in, so a key
another tool wrote — or a key the harness adds later for an unrelated reason —
reaches the same detector through the same path.

ADR-042 already refuses a write, but only for concurrency: the engine compares
each target's `(st_mtime_ns, st_size)` between read and apply. Nothing anywhere
asked whether the bytes about to be written are bytes the consumer will accept.
`_plan_settings` produced them, `_apply` wrote them, and the deploy exited 0.

The detector itself already existed after ADR-063 — ported from the shipped
binary as a test-suite regression gate over the goldens. A gate that only runs in
CI covers the documents the repo generates, not the one a particular machine's
merge produces.

## Decision

**The detector moves onto the shipping path.** It leaves the test tree for
`src/lazy_harness/agents/_settings_shape.py`, and `_plan_settings` calls
`fatal_hook_shape` on the finished document, raising `SettingsShapeError` with
the offending JSON path (`$.lh_hook_ownership.managed[0].group`, for the original
case) in the message. The goldens gate keeps running; it is now the same function.

**Gate the output, not the input.** The check runs on the document about to be
written, not on `existing_raw`. Two reasons, and the second is the binding one. An
input that passes says nothing about an output the merge assembled from it. And an
input that *fails* may be one this very merge repairs — a profile still carrying
the pre-fix embedded ledger has a fatal input, and `_plan_settings` pops that key
before writing. Gating the input would have refused exactly the profiles that were
mid-migration, which is every profile the fix existed for.

**Raise, do not repair.** Every key in the artifact is either generated here or
copied verbatim from what was already on disk, so an offender the harness did not
generate belongs to something else. Repairing means deleting a document the
harness does not own and cannot reconstruct. Refusing loses nothing measurable: a
file that trips the detector is a file the agent is *already* discarding whole,
so the state the refusal preserves is state that is not being read anyway. The
counterfactual is the one that cost nine hours — the deploy would have written it
and exited 0.

## Alternatives considered

**Strip the offending key and write the rest.** Rejected as above: silent data
loss from a shared document, to produce a file that is now missing whatever the
other tool needed.

**Warn and write.** Rejected. The failure mode being fixed is a deploy that
reports success while disarming the profile; a warning on a deploy whose other
lines all read `✓` reproduces it with extra steps.

**Validate by invoking the agent binary.** Rejected. It makes a deploy depend on
a working agent install and on a diagnostic surface the binary does not commit to
— Claude Code reports a discarded settings file by behaving as if it has none.
The decompiled function is version-pinned evidence that can be re-derived when it
moves; a scraped console line is not.

**Leave it a test-suite gate.** Rejected. The goldens are documents the repo
authors. The dangerous document is the merge of a golden with whatever a
particular machine already had, which no fixture enumerates.

## Consequences

- A deploy that would disarm a profile now fails loudly and writes nothing,
  naming the path to remove.
- The detector is a copy of decompiled behaviour from one named version. It is
  ADR-041's rule applied to a reader instead of a writer: it is evidence about
  2.1.278 and nothing else, and a later version narrowing or widening the scan
  will make it wrong in one of two directions — a false refusal, which costs a
  re-run, or a false pass, which is where this started.
- The refusal is per-profile and raised during planning, so it aborts that
  profile's plan before any of its targets are touched, consistent with ADR-042's
  whole-plan-or-nothing rule.
- The check generalises to any adapter whose config document a merge assembles.
  Only Claude Code has one today; Codex's `config.toml` is merged under ADR-042
  with no equivalent detector, because none has been measured.

# reports/

Point-in-time reports, as `specs/workflow/doc-short-path.md` classifies them:
analysis, verification and rollout evidence for a single lane. They are
intermediates, not contract. The contract lives in `specs/adrs/`,
`specs/backlog.md`, `docs/` and the code.

Keep a report only while it holds something no other surface does: a raw
measurement against a pinned external version that nobody has re-run, or a
finding not yet recorded in the backlog, an ADR or a `failures.jsonl` entry.

Delete it once its conclusion lands somewhere durable. Review gates, GO/NO-GO
rounds, implementation logs, release cuts and handoff prompts for a finished
iteration are absorbed the moment the work merges — they go. Git keeps the
history, so deletion is recoverable and precaution is not a reason to hoard.

Prune when a lane closes, and again at every release cut.

# External hook ownership implementation

Date: 2026-09-19
Status: implemented and verified in the worktree; no commit, release or deploy

## Outcome

Hook ownership is now explicit and generic. The engine marks builtins as
harness-managed and `[hooks.*].external` entries as external ensure-present
declarations. Claude Code and Codex preserve foreign declarations; omission of
an external declaration does not authorize deletion.

Codex no longer replaces `hooks.json` wholesale. It refuses unreadable shared
documents, preserves foreign event/group order and native fields, fills proven
managed positions, drops only proven managed groups, retains foreign
duplicates, and de-duplicates a generated external only against the same native
event/matcher/handler-type/command identity. An equivalent richer installed
group wins.

## TDD evidence

The first production edit followed an observed failing test:

- RED: `test_the_plan_preserves_foreign_groups_on_modelled_and_unknown_events`
  failed because the planner replaced the existing description with `Managed
  by lazy-harness...`; the then-current whole-file plan also removed both
  foreign groups.
- RED: the expanded focused suite failed collection because `HookOwnership`
  did not yet exist, proving the engine/adapters carried no ownership
  provenance.
- GREEN: 17 new ownership-focused cases passed after the first implementation
  slice.
- A later integration RED exposed an obsolete assumption: changing an
  `external` matcher was expected to replace index 0. The corrected contract
  preserves index 0 and ensures the new declaration at index 1; the tests now
  assert no false stale claim for the preserved group.

Coverage added for malformed JSON and wrong types, modeled and unknown events,
valid richer native metadata, foreign duplicates, matcher-sensitive external
identity, legacy migration, mixed groups, unmarked builtin-shaped groups,
non-command handlers, managed removal, foreign-only retention, positional
replacement, launcher transitions, description-only trust diagnostics, shifted
trust keys, engine provenance, and byte-stable second deploys.

## Provenance and trust decisions

The behavioral probe in
`reports/2026-09-19-codex-hook-trust-probe.md` observed `codex-cli 0.155.1`
through its local app-server with a disposable `CODEX_HOME`. A description-only
change preserved the native key, `currentHash` and `trustStatus`.

The implementation therefore uses a versioned `description` envelope instead
of a sidecar. The envelope records launcher history and exact managed
event/position/group values. It is non-authoritative metadata: a group is owned
only when the recorded value still matches and every handler is a recognized
`lh hook` command from a recorded launcher. The legacy description is accepted
only for conservative migration. Mixed, edited, malformed or unrecorded groups
remain foreign. `WriteOp.changed` compares hook arrays only, so provenance-only
changes do not request re-trust.

## Other changes

- Claude Code's external de-duplication now uses native declaration identity
  and retains richer installed metadata instead of replacing it with the
  narrower shared model.
- The config reference documents `external` as optional ensure-present state,
  including the non-deletion rule.
- ADR-042 records the move from file ownership to group ownership and the
  description probe. ADR-054 records the clarified external lifecycle.
- Product code, tests, docs and current ADRs use generic fixtures and contain no
  integration-specific vendor knowledge.
- Graphify was queried before `rg`; the worktree had no local graph, so the
  successful query used the repository's existing `graphify-out/graph.json`.

## Verification

- Focused ownership/config/docs suite: `289 passed`.
- Related engine/snapshot/retrust/protocol integrations: `84 passed`.
- Full test suite: `5161 passed in 367.90s`.
- `ruff check src tests`: passed.
- `ruff format --check src tests`: `502 files already formatted`.
- `mkdocs build --strict`: passed; Material emitted its upstream MkDocs 2.0
  advisory, with no content, navigation or link warning.
- `git diff --check`: passed.
- No commit, push, release, dotfiles operation, deploy or real-home mutation was
  performed.

## Review remediation — 2026-09-19

The independent review's NO-GO is remediated in this worktree. The original
implementation remains uncommitted; no release, deploy, dotfiles operation or
real-home mutation was performed.

Strict TDD began with one focused RED run covering F1–F8 and the F9 guard:
**20 failed, 249 passed**. The failures reproduced permissive builtin
classification, Codex user-script duplication, Claude duplicate/metadata and
prompt/mixed loss, Copilot external retirement, avoidable Codex index shifts,
ignored native trust events, unhashable Claude identities and the untested
provenance equality guard.

Two later boundary cases each ran RED before their corresponding production
change: an external-only Claude builtin-shaped declaration was incorrectly
retired after omission, and a real builtin on native `SubagentStart` was
incorrectly claimed even though the harness cannot emit that event. Both now
remain foreign.

The remediation makes builtin recognition an exact registry-backed grammar.
It accepts the current launcher form, the explicitly shipped no-profile
migration and an exact registered legacy module path; invented names or
launchers, wrappers, operators, extra arguments and path substrings remain
foreign. Provenance still requires an exact recorded group at its recorded
position, and a real-builtin-to-real-builtin edit proves that equality check is
independently load-bearing.

User scripts resolved from `[hooks.*].scripts` now carry ensure-present
ownership. Codex therefore converges across repeated deploys and preserves the
script after omission without widening builtin classification. Claude records
only generated managed groups, preserves prompt-only and mixed groups, keeps
all equivalent foreign duplicates and metadata, and safely preserves malformed
identity fields instead of raising `TypeError`. This also closes the inherited
last-builtin retirement case.

Copilot uses its measured native hook-file glob as a generic ownership
boundary: `hooks/lazy-harness.json` remains replaceable, while
`hooks/lazy-harness-external.json` is merged and omission-preserving. The new
target is derived through `config_targets()` and covered by the real snapshot
contract. Codex now appends surplus managed groups after all existing groups,
and trust recognizes all twelve native Codex event names while retaining
canonical harness labels where one exists.

The first GREEN after production changes was **269 passed** across the focused
Codex, trust, Claude planner, Copilot, deploy-engine and snapshot suites.

### Remediation verification

- Expanded focused suite: **574 passed** across Codex, trust, Claude planner,
  Copilot, adapter contracts, config, loader, deploy engine, snapshot/rollback,
  retrust and docs tests.
- F9 mutation equivalent: removing only
  `hooks[event][index] == recorded_group` made the real-builtin command-edit
  case fail while the matcher, metadata and position cases remained
  conservatively foreign (**1 failed, 3 passed**). The equality guard was
  restored by patch; all four cases then passed in the focused suite.
- `uv run --frozen --no-sync ruff check src tests`: passed.
- `uv run --frozen --no-sync ruff format --check src tests`: passed; 502 files
  already formatted.
- `uv run --frozen --no-sync --group docs mkdocs build --strict`: passed. The
  only advisory was Material's upstream MkDocs 2.0 notice; there were no build,
  navigation or link warnings.
- `git diff --check` and no-index checks for the three untracked reports:
  passed after removing two trailing Markdown spaces.
- The full pytest suite was deliberately not rerun during this remediation, as
  requested. The 5161-pass full-suite result above belongs to the pre-review
  implementation state and is not claimed as remediation evidence.

## Rereview remediation — R1–R4

The four P2 findings in the independent rereview are remediated without
expanding scope beyond ownership reconciliation:

- R1 compares launcher commands with the exact canonical form emitted by
  `hook_command`, so attached operators, substitutions and redirects remain
  foreign while quoted profiles still match. Legacy recognition requires the
  registered module's full `.py` basename in the interpreter's script
  position. Provenance tests now distinguish an invented builtin from a
  recorded historical launcher; editable launcher history is explicitly a
  compatibility mechanism, not independent authority.
- R2 de-duplicates only generated Claude external candidates by native
  identity before merge. One installed foreign group satisfies every matching
  desired candidate, while all installed foreign duplicates and metadata are
  preserved. The loader-to-engine reproduction converges at `[1, 1, 1]` and
  omission retains one installed group.
- R3 migrates the former Copilot combined artifact in the same plan that writes
  the split artifacts. Exact managed builtins stay managed; unknown, external
  and user-script groups move intact, with duplicates and metadata. Desired
  declarations do not duplicate migrated groups, invalid legacy input refuses
  the plan, and the real snapshot replayer restores both pre-migration paths.
- R4 distinguishes an absent Claude ownership key from a present invalid value.
  Only absence enables legacy classification; null, wrong dicts, lists and
  integers grant zero ownership. The external-to-null-to-omission sequence now
  preserves the installed declaration.

The initial reproduction run was **18 failed, 12 passed**. The first focused
GREEN after the four fixes was **309 passed** across the Codex, Claude planner,
deploy-engine, Copilot, loader and snapshot suites. Final verification follows
below.

### R1–R4 verification

- Reproductions: **31 passed**. This includes every attached-operator,
  substitution, redirect and legacy-extension case; the emitted quoted-profile
  control; separated launcher/builtin provenance controls; the real
  loader-to-engine duplicate sequence; Copilot HEAD-equivalent migration
  states and refusal; snapshot rollback; and Claude absent/null/malformed
  ownership states.
- Expanded focused suite: **530 passed** across Codex, trust, Claude planner,
  Copilot, adapter contracts, config, loader, deploy engine,
  snapshot/rollback, retrust and docs coherence tests.
- `uv run --frozen ruff check src tests`: passed.
- `uv run --frozen ruff format --check src tests`: passed after formatting the
  seven files changed by this remediation.
- `uv run --frozen --group docs mkdocs build --strict`: passed. Material's
  upstream MkDocs 2.0 advisory was the only notice.
- `git diff --check`: passed; the updated untracked implementation report was
  also checked directly for trailing whitespace.
- The full pytest suite was not run, as requested. No commit, push, deploy
  command, dotfiles operation or real-home mutation was performed; deploy
  application was exercised only inside isolated test fixtures.

## Final-review remediation — strict Claude version and Copilot reconciliation

The two remaining P2 findings from the final scoped review are closed:

- Claude accepts an ownership envelope only when `version` has exact Python
  type `int` and value `1`. Exact recorded groups under `true`, `1.0`, `false`,
  `null`, `2` and `"1"` grant no deletion authority. An absent ownership key
  remains the sole legacy-migration sentinel.
- Copilot reconciles the migrated and installed external artifact before
  emitting its managed artifact. A foreign group with the same native
  `(event, matcher, command)` identity satisfies the managed candidate without
  transferring ownership: richer metadata and all pre-existing foreign
  duplicates remain intact, while only the additional generated declaration
  is suppressed. The behavior holds during the legacy transition and on
  subsequent redeploys.

Strict TDD began with the two requested regressions. The RED run was **3
failed**: Claude removed the exact recorded group for both `true` and `1.0`,
and Copilot produced declaration counts `[2, 2, 2]`. After the production
changes, those three cases passed.

### Final-review verification

- Direct regression controls: **11 passed**, including the strict-version
  matrix, absent-key legacy migration, three Copilot plans, foreign duplicate
  preservation and the existing migration/metadata controls.
- Focused planner, Copilot, deploy-config, deploy-engine and snapshot suites:
  **195 passed**.
- `uv run --frozen ruff check src tests`: passed.
- `uv run --frozen ruff format --check src tests`: passed; 502 files already
  formatted.
- `uv run --frozen --group docs mkdocs build --strict`: passed. Material's
  upstream MkDocs 2.0 advisory was the only notice.
- `git diff --check`: passed. The no-index check of this untracked report
  produced no whitespace diagnostics (its expected exit 1 only reports that
  the file differs from `/dev/null`).
- The full pytest suite was not run, as requested. No commit, push, deploy,
  release, dotfiles operation or real-home mutation was performed.

**DONE**

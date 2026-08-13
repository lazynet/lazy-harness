# Unused skill triage — 2026-08-13

Bucket assignment for every skill in the `UNUSED_SKILLS` column of
[`2026-08-13-agent-surface-audit.txt`](2026-08-13-agent-surface-audit.txt), re-measured against
a fresh run of [`2026-08-13-agent-surface-audit.sh`](2026-08-13-agent-surface-audit.sh) on
2026-08-13. Rationale for the four buckets: `specs/designs/2026-08-13-agent-surface-adoption-design.md`
(W5). Bucket definitions below are the ones actually applied; they win over the design doc where
the two differ in wording.

**Write boundary.** This report is the only artifact produced by this triage. `lazy-ansible` is
the only `~/repos/lazy/` repo in scope; every other repo below — `ai-adoption-mgmt`, `flex-mgmt`,
`supervielle-mgmt`, `tb-ydi-delivery`, `ydi-mgmt`, `supervielle-backstage-poc`, `ydi-data-layer` —
is FlexibilitySRL-owned with versioned `.claude/` configuration. All recommendations for those
seven are proposals to raise with whoever owns that repo, not actions taken. No commits, no
file changes were made in any of them.

## Count discrepancy

The design doc's W5 section states 49 unused skills. The literal current count, verified skill
by skill against both `.claude/skills/*/SKILL.md` on disk and the transcript grep, is **48**:
42 explicit names in the `UNUSED_SKILLS` column (repos with `SESSIONS > 0`) plus 6 more that the
column hides. The audit script special-cases zero-session repos — it prints `-` for
`UNUSED_SKILLS` without running the `comm` diff at all (`agent-surface-audit.sh:33-36`) — so
`tb-ydi-delivery`'s 6 skills never appear in the column even though all 6 are unused. This
report includes them under bucket 2. No skill count changed between the committed audit and the
2026-08-13 re-run; only `SESSIONS`/`INVOCS` drifted (expected, per Step 1). The 49→48 gap is most
likely stale arithmetic in an earlier design-doc draft, not a measurement regression — but it is
recorded here rather than silently absorbed.

No name in the `UNUSED_SKILLS` column turned out to be a non-skill (a directory without
`SKILL.md`). The one known trap — `supervielle-backstage-poc/_shared/`, which holds convention
docs and no `SKILL.md` — is already excluded by the audit script itself (confirmed: 19 dirs
with `SKILL.md` vs 20 total subdirectories under `.claude/skills/`).

## A second measurement trap found during this triage

The audit's `SESSIONS` count is a raw count of `.jsonl` transcript files. A material fraction of
those files are not organic work sessions:

- **Compound-loop learning-evaluation sidecars** — sessions whose first user message is
  `"You are evaluating a Claude Code session for learnings..."`. These are the compound-loop
  hook grading a *previous* session, not new usage.
- **Automated CI bot sessions** — in `ydi-data-layer`, most of the remainder are
  `security-review` invocations whose first message is `"Review this change for security
  vulnerabilities..."`, triggered by CI on PR diffs, not by a person typing a prompt.

Measured directly (`grep -l "evaluating a Claude Code session for learnings"` across each repo's
transcript directories, plus a manual classification pass on `ydi-data-layer`):

| Repo | Raw SESSIONS | Meta-eval sessions | CI-bot sessions | Organic sessions |
|---|---:|---:|---:|---:|
| `ydi-mgmt` | 22 | 13 | 0 | **9** |
| `ydi-data-layer` | 82 | 69 | ~9 of the remaining 13 | **~1** |
| `lazy-ansible` | 404 | 201 | 0 (no CI bot) | 205 |
| `flex-mgmt` | 65 | 11 | 0 | 55 |
| `supervielle-mgmt` | 337 | 220 | not classified | 118 |
| `supervielle-backstage-poc` | 588 | 245 | not classified | 346 |

For `lazy-ansible`, `flex-mgmt`, `supervielle-mgmt`, and `supervielle-backstage-poc` the organic
count still clears the 20-session threshold by a wide margin, so this correction does not change
any bucket assignment there. For `ydi-mgmt` and `ydi-data-layer` it does — both nominally clear
the `SESSIONS ≥ 20` line in the raw column (22 and 82) but have an organic sample far below it (9
and ~1). Both are triaged as bucket 3 below using the corrected number, not the raw one, because
the raw number does not measure what the bucket-3 threshold is meant to measure: genuine
opportunities for a human prompt to have matched the skill.

## Bucket definitions (verbatim from the task brief)

1. **Superseded** — a competing surface already does this job, with invocation counts to prove
   it.
2. **Repo never opened** — the repo's `SESSIONS` column is 0. No verdict is possible.
3. **Sample too small** — `SESSIONS` under 20. No verdict is possible.
4. **Wanted but untriggered** — the work happens by hand, or sibling stages of the same flow
   fire while this one does not.

## Summary

| Bucket | Count | Repos involved |
|---|---:|---|
| 1 — Superseded | 3 | `flex-mgmt`, `supervielle-mgmt` |
| 2 — Repo never opened | 6 | `tb-ydi-delivery` |
| 3 — Sample too small | 16 | `ai-adoption-mgmt`, `ydi-mgmt`, `ydi-data-layer` |
| 4 — Wanted but untriggered | 23 | `lazy-ansible`, `flex-mgmt`, `supervielle-mgmt`, `supervielle-backstage-poc` |
| **Total** | **48** | 7 repos |

---

## Bucket 1 — Superseded (prune candidates)

Only assigned where the competing surface's invocation count was actually measured in the same
repo's transcripts — not assumed from the estate-wide `gws` pattern described in the design doc.

| Repo | Skill | Evidence | Recommendation |
|---|---|---|---|
| `flex-mgmt` | `ctoflex-sheets` | Description: "creating or operating Google Sheets for tracking TC documents." Repo transcripts show 6 direct `gws sheets` Bash calls and 0 `ctoflex-sheets` invocations across 65 sessions. | Propose removal to the `flex-mgmt` owner; the need is met by direct `gws` CLI use per the global `CLAUDE.md` instruction. |
| `flex-mgmt` | `ctoflex-docs` | Description: "creating or updating Google Docs... syncing TC deliverables to Drive." Repo transcripts show 5 direct `gws drive` Bash calls, 4 `gws gmail`, and 0 `ctoflex-docs` invocations. | Same as above. |
| `supervielle-mgmt` | `qmd-knowledge` | Description: "searching project documentation... querying the knowledge base." Repo transcripts show 19 direct `qmd` MCP calls (`query`×13, `multi_get`×3, `get`×2, `status`×1) and 0 `qmd-knowledge` invocations across 337 sessions. | Propose removal; this is the exact `qmd-knowledge` vs `qmd` MCP pattern the design doc names as "the same shape appears once more." |

`ydi-mgmt` also declares a `qmd-knowledge` skill with an identical description, and the design
doc groups it with the `supervielle-mgmt` instance. It is **not** placed in bucket 1 here: no
direct `qmd` MCP calls were found in `ydi-mgmt`'s transcripts, and the repo's organic sample (9
sessions, see above) is too small to distinguish "superseded" from "never came up." It is
triaged under bucket 3 instead, alongside the repo's other six skills.

## Bucket 2 — Repo never opened (no verdict)

`tb-ydi-delivery`: `SESSIONS = 0` in both the committed audit and the 2026-08-13 re-run. No
project transcript directory exists under either `~/.claude-lazy/projects/` or
`~/.claude-flex/projects/` for this repo — confirmed directly, not inferred from the audit
script's shortcut. Zero invocations measures the repo, not the skills.

| Repo | Skill | Evidence | Recommendation |
|---|---|---|---|
| `tb-ydi-delivery` | `tb-confluence-sync` | 0 sessions | Leave intact. Re-measure if the repo is ever opened. |
| `tb-ydi-delivery` | `tb-graph` | 0 sessions | Same. |
| `tb-ydi-delivery` | `ydi-docs` | 0 sessions | Same. |
| `tb-ydi-delivery` | `ydi-scorecard` | 0 sessions | Same. |
| `tb-ydi-delivery` | `ydi-sheets` | 0 sessions | Same. |
| `tb-ydi-delivery` | `ydi-sync` | 0 sessions | Same. |

## Bucket 3 — Sample too small (no verdict)

| Repo | Skill | Evidence | Recommendation |
|---|---|---|---|
| `ai-adoption-mgmt` | `gws-admin-reports` | `SESSIONS = 3` (raw and organic — no meta-eval contamination found). | Leave intact. Re-measure once the repo accumulates more real usage. |
| `ydi-mgmt` | `contract-iterate` | Repo `SESSIONS = 22` raw, **9 organic** (13 of 22 are compound-loop meta-eval sessions). `INVOCS = 0` for the whole repo — no skill of any kind fired, not just this one. | No verdict. Re-measure once organic session count clears ~20. |
| `ydi-mgmt` | `qmd-knowledge` | Same repo-level correction. No `qmd` MCP calls found either, unlike the `supervielle-mgmt` instance — but 9 organic sessions is too thin to call that supersession vs. "never came up." | Same. |
| `ydi-mgmt` | `repo-audit` | Same repo-level correction. | Same. |
| `ydi-mgmt` | `ydi-docs` | Same repo-level correction. | Same. |
| `ydi-mgmt` | `ydi-scorecard` | Same repo-level correction. | Same. |
| `ydi-mgmt` | `ydi-sheets` | Same repo-level correction. | Same. |
| `ydi-mgmt` | `ydi-sync` | Same repo-level correction. | Same. |
| `ydi-data-layer` | `data-contracts` | Repo `SESSIONS = 82` raw. Classified all 13 non-meta transcripts by opening message: ~9 are automated `security-review` CI-bot invocations (`"Review this change for security vulnerabilities..."`), 1 is organic (`"Hay nos pr en el repo que quiero revisar..."`), remainder unclassified. Organic sample ≈ **1**. | No verdict — the sample is not "small," it is close to absent. Do not attempt W3's lexical-overlap diagnosis on this repo as currently measured; it would be drawing a conclusion from n≈1. |
| `ydi-data-layer` | `data-controls` | Same repo-level correction. | Same. |
| `ydi-data-layer` | `data-lake-dms-cdc` | Same repo-level correction. | Same. |
| `ydi-data-layer` | `data-lake-etl-jobs` | Same repo-level correction. | Same. |
| `ydi-data-layer` | `data-lake-monitoring` | Same repo-level correction. | Same. |
| `ydi-data-layer` | `data-lake-troubleshoot` | Same repo-level correction. | Same. |
| `ydi-data-layer` | `iceberg-best-practices` | Same repo-level correction. | Same. |
| `ydi-data-layer` | `medallion-architecture` | Same repo-level correction. | Same. |

**On the Step 3 lexical-overlap test for `ydi-data-layer`.** The brief calls for reading each
skill's description against the opening prompts of several sessions in the repo. That test was
run against the one organic session found: the prompt ("Hay nos PR en el repo que quiero
revisar antes de llevar a producción. ¿Generan impactos en la infraestructura existente?
Recordame el proceso...") names a *task* ("review these PRs before shipping", "remind me the
process"). The skill descriptions name *artifacts* ("Reference for the YDI data-layer data
contracts", "Apache Iceberg best practices", "Medallion architecture pattern for Data Lakes").
That single data point is consistent with the design doc's description-mismatch hypothesis — but
it is one data point. Concluding "the fix is a reworded description" from n=1 would be the exact
mistake this task's method notes warn against. The honest reading is bucket 3, with the
mismatch noted as a lead for whoever revisits this once the repo has real usage to measure.

## Bucket 4 — Wanted but untriggered (attach a mechanism)

Evidence quality varies within this bucket; each row states what was actually found rather than
asserting a uniform level of confidence.

### `lazy-ansible` (2 skills, 205 organic sessions — the only `~/repos/lazy/` repo in scope)

| Skill | Evidence | Recommendation |
|---|---|---|
| `ansible-lint` | Sibling skills fire: `opnsense-admin` ×7, `tailscale-admin` ×2, `ansible-role-scaffold` ×1, `ansible-automation` ×1. `ansible-lint` and `ansible-security-audit` are the only two of six local skills at zero. | Matches W2 in the design doc exactly: move to a `PostToolUse` hook scoped to `roles/**` and playbook edits. This repo is `lazy`-owned but this task's write boundary excludes it — the fix is W2's own task, not this one. |
| `ansible-security-audit` | Same sibling evidence. | Same — W2. |

### `flex-mgmt` (6 skills; 55 organic of 65 raw sessions)

Only 1 of 9 local skills (`ctoflex-slides`) ever fired in this window. `gws` CLI usage is heavy
(20 direct calls: `sheets`×6, `slides`×5, `drive`×5, `gmail`×4), consistent with the estate-wide
pattern, but that alone would put the `gws`-shaped skills in bucket 1 — those two (`ctoflex-sheets`,
`ctoflex-docs`) are filed there. The remaining six either show direct evidence of the work
happening by hand at the exact target artifact, or show no evidence either way.

| Skill | Evidence | Recommendation |
|---|---|---|
| `ctoflex-tech-costs` | Description: "close, review, or report monthly tech costs... updates the Finance sheet." Direct `Edit`/`Write` calls found targeting `knowledge/tech-costs/reports/2026-05.md`, `2026-06.md` (×2), `2026-07.md` — the exact artifact this skill owns. | Work happens by hand at the target file. Propose a hook or a reworded description keyed to "monthly close" vocabulary, to the `flex-mgmt` owner. |
| `ctoflex-project-sync` | Description: "check the health of management repos... consolidated view of the mgmt repo ecosystem." `knowledge/projects.md` edited directly 7 times. | Same — direct-edit evidence, weaker link to this specific skill's full scope than `ctoflex-tech-costs` but the target file matches. |
| `ctoflex-commercial-sync` | No direct-edit or sibling-invocation evidence found for this skill's specific artifact in this window. | Weak evidence — default classification from the repo-wide pattern (8 of 9 skills never fire despite 55 organic sessions), not from skill-specific proof. Flag as such if raised with the owner; the underlying need may simply not have arisen. |
| `ctoflex-cto-scorecard` | Same — no direct evidence found. | Same weak-evidence caveat. |
| `ctoflex-finance-sync` | Same — no direct evidence found. | Same weak-evidence caveat. |
| `ctoflex-okr-tracker` | Same — no direct evidence found. | Same weak-evidence caveat. |

### `supervielle-mgmt` (7 skills; 118 organic of 337 raw sessions)

Sibling skills fire heavily: `work-session` ×17, `supervielle-issues` ×13, `supervielle-docs`
×5, `weekly-status` ×3, `supervielle-sheets` ×1, `meeting-prep` ×1.

| Skill | Evidence | Recommendation |
|---|---|---|
| `assessment-sync` | Description: "Runs `sync_assessment_tabs.py` to push each section file as a separate tab." That exact script name appears in 47 transcript files — the work happens, repeatedly, via direct script execution rather than the skill wrapper. | Strongest evidence in this repo. Propose a hook that fires on edits to the assessment section files, or a slash command wrapping the script, to the `supervielle-mgmt` owner. |
| `u04-deliverable` | Description: "Orchestrates claim of the GitHub Project card... dispatches the right sub-agent (mesh-architect / mesh-engineer / mesh-operations)." `supervielle-issues` (13 invocations) already covers the card claim/release step this skill was meant to gate. 268 transcript mentions of `mesh-architect`/`mesh-engineer`/`mesh-operations`, but none appear as an actual `Task` `subagent_type` dispatch (only `general-purpose` and `Explore` appear there) — the sub-agent names are discussed, not invoked through this flow. | Partial overlap with a sibling skill for the claim step; the dispatch step appears to happen by other means. Flag both observations to the owner rather than asserting full supersession. |
| `consistency-check` | No direct competing-tool or by-hand evidence found; keyword "consistencia" appears in 71 transcript files but that measures topic frequency, not mechanism. | Weak evidence — default classification from repo-wide pattern (only 6 of 14 skills ever fire). |
| `deliverable-review` | "revisar entregable" appears in 42 transcript files; no stronger mechanism evidence found. | Same weak-evidence caveat. |
| `milestone-prep` | "milestone" appears in 292 transcript files (a common word, weak signal); no stronger mechanism evidence found. | Same weak-evidence caveat. |
| `supervielle-slides` | No `gws slides`/`presentations` Bash calls found in this repo's transcripts, unlike `supervielle-sheets` and `supervielle-docs` which both show usage and both fire as skills. | No competing mechanism proven — genuinely weak evidence either for bucket 1 or bucket 4. Kept in bucket 4 on the repo-wide default; flag the absence of a smoking gun to the owner. |
| `supervielle-sync` | Description: "propagating changes from the Maestro spreadsheet to BTR... exporting BTR as xlsx." No direct script/CLI evidence found (searched for `sync_maestro`, `BTR.xlsx`, both zero hits). | Same weak-evidence caveat. |

### `supervielle-backstage-poc` (8 skills; 346 organic of 588 raw sessions)

| Skill | Evidence | Recommendation |
|---|---|---|
| `sdd-apply` | All of `sdd-spec`×2, `sdd-tasks`×2, `sdd-propose`×2, `sdd-explore`×2, `sdd-design`×2, `sdd-verify`×1 fire; `sdd-apply`, `sdd-archive`, `sdd-init` do not. Each `SKILL.md`'s `description:` reads "Trigger: When the orchestrator launches you to..." — these are sub-agent-dispatched stages of one SDD flow, not independently model-routed skills. | Matches the design doc's read exactly: a workflow whose later stages are never reached. This is a process question for whoever owns the SDD flow in this repo, not a dead-skill question — flag, don't delete. |
| `sdd-archive` | Same. | Same. |
| `sdd-init` | Same. | Same. |
| `smart-commit` | Description: "Generate conventional commit messages... commits on approval." 13 direct `git commit` Bash calls found in this repo's transcripts. | Work happens by hand via direct `git commit`. Propose the owner either wire this into a `PreToolUse`/prompt hook or drop it. |
| `changelog-pr` | Description: "creates/updates a PR via GitHub MCP." 0 GitHub MCP tool calls found in this repo's transcripts; 7 direct `gh pr create` Bash calls found instead. | Work happens by hand via the `gh` CLI rather than the GitHub MCP path this skill was written against. |
| `admin-auth-providers` | Sibling skills fire: `admin-catalog`×3, `admin-integrations`×3, `admin-rbac`×5. Auth/SSO-related terms appear in 274 transcript files (topic is clearly live) but the skill itself never fires. | Sibling-firing evidence is solid; flag to the owner as a probable description/vocabulary mismatch against the other `admin-*` skills that do match. |
| `backstage-setup` | Sibling skills `backstage-add-plugin`×1 and `backstage-help`×1 fire. No direct `make <target>` Bash calls found (searched, zero hits) to confirm by-hand setup. | Weaker evidence than the sibling-skill argument alone provides — flag, don't assert a specific alternative mechanism. |
| `skill-creator` | No invocation of any skill named `skill-creator` (local or otherwise) found anywhere in this repo's transcripts. 19 `SKILL.md` files have been added to this repo over its git history, but that reflects the original bulk setup of the skill tree, not evidence of ongoing ad hoc authoring without the skill. | Weakest evidence in this bucket — the task this skill covers (authoring a new skill) may simply not have recurred in the measurement window. Included in bucket 4 by the repo-wide default rather than specific proof; flag that caveat explicitly if raised with the owner. |

---

## Method notes for whoever re-runs this

- Re-running `2026-08-13-agent-surface-audit.sh` reproduces the `UNUSED_SKILLS` column exactly;
  only `SESSIONS`/`INVOCS` drift session-to-session, as expected.
- The meta-session contamination (compound-loop learning-eval sidecars, and in
  `ydi-data-layer`'s case automated `security-review` CI runs) is not something the audit script
  currently filters. Any repo sitting near the `SESSIONS ≥ 20` line is worth re-checking with
  `grep -L "evaluating a Claude Code session for learnings"` before trusting the raw count — this
  is what moved `ydi-mgmt` and `ydi-data-layer` from "has a sample" to "no verdict" in this
  triage.

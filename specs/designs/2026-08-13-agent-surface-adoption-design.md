# Agent surface adoption — design

**Date:** 2026-08-13
**Status:** Proposed
**Scope:** `~/.claude-lazy/skills`, `~/.claude-flex/skills`, graphify MCP, and 18 repositories
(`lazy-*`, `flex/mngt/*`, the supervielle repos, `ydi-data-layer`)

## Problem

The original request assumed three repos were missing agent surface — MCP servers and
skills that had not been configured yet. Measurement contradicts that premise. The
surface exists; it does not fire.

Evidence gathered from 2,624 session transcripts across both profiles (2026-07-20 →
2026-08-13):

| Surface | Declared | Invocations in window |
|---------|----------|-----------------------|
| `ydi-data-layer` domain skills (8, incl. `data-lake-monitoring`) | versioned in repo | 0 across 81 sessions |
| `ansible-lint`, `ansible-security-audit` | `lazy-ansible/.claude/skills/` | 0 across 396 sessions |
| `graphify` MCP | both profiles | 0 |
| `grafana` MCP | flex profile | 0 across 1,217 sessions |
| `gws-*`, `persona-*`, `recipe-*` skills (36) | symlinked into lazy profile | 0 |

Widening the audit to 18 repositories confirms the pattern is systemic, not local to
three repos:

| Repo | Skills | MCPs | Sessions | Never invoked |
|------|--------|------|----------|---------------|
| supervielle-backstage-poc | 19 | 0 | 587 | 8 |
| supervielle-mgmt | 14 | 0 | 331 | 8 |
| flex-mgmt | 9 | 0 | 63 | 8 |
| ydi-mgmt | 7 | 3 | 22 | 7 |
| ydi-data-layer | 8 | 3 | 81 | 8 |
| lazy-ansible | 6 | 0 | 396 | 2 |
| tb-ydi-delivery | 6 | 3 | 0 | 6 (never opened) |
| ai-adoption-mgmt | 2 | 0 | 3 | 2 (sample too small) |
| lazy-desktop-manager, lazy-hermes | 1 each | 0 | 252 / 74 | 0 |

**73 local skills declared across the estate; 49 have never been invoked once.**
Restricting to repos with a sample large enough to conclude from (≥20 sessions), 41 are
dead with solid evidence.

The defect is uniform: **declaring a capability is not the same as adopting it.**
Availability is passive; invocation requires a trigger — a hook, a slash command, or a
description that matches the vocabulary actually used in prompts.

### The dominant cause: a CLI already won

The largest single cluster of dead skills is Google Workspace wrappers — the 36 global
`gws-*`/`persona-*`/`recipe-*` skills, plus `ctoflex-sheets`, `ydi-sheets`,
`supervielle-slides`, `gws-shared`, `gws-admin-reports` and their siblings in the mgmt
repos. Every one sits at zero.

They are not unwanted. The work happens — via 40 direct `gws` CLI calls through Bash. The
global `CLAUDE.md` instructs exactly that:

> Para acceder a artefactos de Google (Drive, Gmail, Calendar, Docs, Sheets, etc.) usá
> `gws` vía Bash

An always-loaded instruction competes with a router-matched skill, and the instruction
wins every time. These skills are redundant against a mechanism that already works —
which makes them the clearest prune candidates in the estate.

The same shape appears once more: `qmd-knowledge` (declared in both `supervielle-mgmt`
and `ydi-mgmt`) sits at zero while the `qmd` MCP records 38 direct calls. Superseded by
a competing surface, not unused for lack of need.

This restates a failure already recorded in project memory (`tool_adoption_gate`): a
rule written in `CLAUDE.md` is not an adoption mechanism. The ydi numbers are the
empirical confirmation — 81 sessions, 8 skills, 0% adoption.

## Measurement method

The audit script lives at `specs/analyses/` alongside its output. Four traps were
checked and cleared before trusting the numbers; anyone re-running this must clear them
again.

**Slash commands are logged as skill invocations.** A command in `.claude/commands/`
appears in transcripts as `"skill":"<name>"`, identical to a skill. Verified against
`new-worktree` (6), `tdd-check` (1), `cleanup-worktree` (1) — all commands, all counted.
A metric that greps only for skills is therefore complete, not half-blind.

**Transcript directories must include worktrees.** The project key encodes the absolute
path with `/` replaced by `-`, and each worktree gets its own sibling directory. Matching
the exact encoded name alone silently drops every worktree session — the same class of
defect that lost 22% of the corpus in the 2026-08-10 audit. Match the encoded prefix plus
`-*`.

**`.claude/skills` may be a symlink to the real tree.** In `supervielle-backstage-poc` it
points at `../.agents/skills`. Counting the link target is correct; assuming duplication
between `.claude/` and `.agents/` is not.

**Not every directory under `skills/` is a skill.** `_shared/` in `supervielle-backstage-poc`
holds convention documents and has no `SKILL.md`. It was counted as a dead skill on the
first pass and removed on verification — hence 19 skills there, not 20.

## Non-goals

- Adding new MCP servers or skills to any repo in scope.
- Deleting anything from the skill source tree at `~/.agents/skills/`.
- Modifying versioned team configuration in `FlexibilitySRL/ydi-data-layer`.
- Standing up monitoring infrastructure. `PRJ-HomeLab` Phase 6 has phase 2 (OPNsense)
  outstanding; a monitoring MCP has nothing to query until that lands.

## Cost model

An unused skill is not free. Its `description` is injected into the system prompt of
every session. The skill listing is budgeted at roughly 1% of the context window; once
the summed descriptions exceed it, entries are truncated and skill routing degrades.

A dead skill therefore does not merely occupy space — it degrades the matching accuracy
of live ones. The 36-skill dead cluster costs ~3.3 KB of descriptions per session.

The inverse also holds: zero invocations does not prove uselessness. A skill may sit at
zero because its case never arose. The decision criterion is therefore
**usage × cost × replaceability**, not usage alone.

## Workstreams

### W1 — Prune global skills

Unlink, do not delete. The source tree at `~/.agents/skills/` (managed by
`.skill-lock.json`, not chezmoi) stays intact; recovering a skill is one `ln -s`.

| Profile | Action | Expected end state |
|---------|--------|--------------------|
| lazy | Remove 36 symlinks (`gws-*`, `persona-*`, `recipe-*`) from `~/.claude-lazy/skills/` | 45 → 9 entries |
| flex | Remove two stray `.zip` files from `~/.claude-flex/skills/`; audit the 7 real entries against measured usage | 9 → 7 entries |

The dead cluster exists only in lazy. Flex carries different residue.

**A third option exists between keep and prune.** The `grill-me` skill is symlinked into
the lazy profile yet absent from the model's skill listing, because its frontmatter sets
`disable-model-invocation: true`. It stays reachable as a user-typed slash command while
costing nothing in the listing the router reads.

Any skill that is genuinely wanted but only ever invoked deliberately — rather than
matched by the router — belongs in this category instead of being unlinked. Applying it
requires editing the source frontmatter, which is a heavier change than removing a
symlink, so it is reserved for skills with a demonstrated manual-invocation case.

**Verification:** entry count before and after, plus confirmation that a subsequent
session's skill listing no longer includes the pruned names. Directory listing alone is
not proof the listing changed.

### W2 — lazy-ansible: triggers, not new skills

`ansible-lint` and `ansible-security-audit` are the only two local skills at zero. The
four that carry domain knowledge (`opnsense-admin` 7, `tailscale-admin` 2,
`ansible-role-scaffold` 1, `ansible-automation` 1) all fire. The pattern is not that
lint and audit are unwanted — it is that nothing calls them.

Both move to a `PostToolUse` hook scoped to edits under `roles/**` and playbook files.
This relocates them from "the model must remember" to "the harness executes", which is
the only mechanism in this setup with a demonstrated invocation record.

Per the repo's hook contract: the hook handles every exception explicitly and exits 0.
An unhandled error escapes to the subprocess and crashes the chain rather than degrading.

No `.mcp.json` is added to `lazy-ansible`.

### W3 — ydi-data-layer: diagnosis only

Work happens in a dedicated Herdr **tab**, not a split pane.

Hypothesis to test: the 8 skills' `description` fields do not match the vocabulary used
in the 81 recorded sessions, so the router never selects them.

Method: extract each skill's description, extract the opening user prompt of each
session, and check for lexical overlap. A skill whose description describes the
*artifact* ("Iceberg table best practices") while prompts describe the *task* ("why is
this job failing") will never match.

Write scope is bounded to `.claude/settings.local.json`, which is not versioned.
`.mcp.json` and the team's skills are read-only here; any recommended change ships as a
written proposal for Martin to carry to the team.

### W4 — graphify: attach a trigger

`graphify-out/` exists in `lazy-harness`, `lazy-ansible`, and `ydi-data-layer`, and
`CLAUDE.md` instructs the agent to prefer the graph over grep for structural questions.
The MCP recorded zero calls in both profiles.

A `SessionStart` hook detects whether the cwd contains `graphify-out/` and whether it is
older than the last commit, then injects that state. The instruction stops depending on
recall.

Note that zero MCP calls does not rule out CLI usage (`graphify query`). The hook design
does not depend on which surface wins — it makes the graph's freshness visible either way.

### W5 — Estate-wide triage of the 49 unused skills

A single verdict for all 41 would be wrong. Each falls into one of four buckets, and only
the first is a prune candidate.

**1. Superseded by a competing surface — prune.** Workspace wrappers beaten by the `gws`
CLI, and `qmd-knowledge` beaten by the `qmd` MCP. The need is real and already met; the
skill only costs listing budget. This is the largest bucket.

**2. Repo never opened — no verdict.** `tb-ydi-delivery` has 6 skills and 3 MCP servers
across 0 sessions. Zero invocations here measures the repo, not the skills. Leave intact;
re-measure if it ever gets used.

**3. Sample too small — no verdict.** `ai-adoption-mgmt` at 3 sessions cannot support a
conclusion either way. Same treatment as bucket 2.

**4. Wanted but untriggered — attach a mechanism.** `ansible-lint` and
`ansible-security-audit` (W2), and the unreached stages of the `sdd-*` flow in
`supervielle-backstage-poc`, where `sdd-spec`, `sdd-tasks`, `sdd-propose`, `sdd-explore`,
`sdd-design` and `sdd-verify` all fire while `sdd-apply`, `sdd-init` and `sdd-archive`
never do. That is a workflow whose later stages are never reached — a process question,
not a dead-skill question, and it should be raised with whoever owns that flow rather
than resolved by deletion.

**Write boundary.** Every repo in buckets 1–4 outside `~/repos/lazy/` belongs to
FlexibilitySRL and carries versioned `.claude/` configuration. The same rule as W3
applies: measurement and written recommendations only; no commits to team repos from this
work. Only `lazy-*` repos are edited directly.

## Testing

Every code change in W2 and W4 follows the repo's strict TDD rule: a failing test that
exercises the behaviour precedes the implementation, with no exception for hooks.

Hook tests must cover the exception path explicitly, with an intentional failure, and
assert exit code 0. A hook that silently swallows an error and a hook that handles it
correctly are indistinguishable without that test.

`pytest.raises(match=...)` anchors on literal config keys or enum names, never on a
substring that could also appear in a `tmp_path` — the temp directory carries the test
name and produces false positives.

Pre-commit gate for both workstreams is `/tdd-check`: `uv run pytest`,
`uv run ruff check src tests`, and `uv run --group docs mkdocs build --strict`.

## Sequencing

W1 is independent and lands first — it is reversible and its effect is immediately
observable in the next session's listing.

W2 and W4 both add hooks and both require worktrees per the repo's non-negotiable #1.
They are independent of each other and may proceed in either order.

W3 is read-mostly and independent of all three.

W5 subsumes W3: the ydi diagnosis is one instance of the estate-wide triage. Run W5's
bucket assignment first, then apply W3's lexical-overlap method to whichever skills land
in bucket 4. Buckets 2 and 3 produce no work at all — recording "no verdict, and why" is
the deliverable for those.

## Open risks

- **W1 verification is the weak point.** A removed symlink is easy to confirm on disk
  and hard to confirm in the prompt. The check must inspect an actual subsequent
  session's listing, not the filesystem.
- **W2 hook scope.** A `PostToolUse` hook firing on every playbook edit can become
  noise. If lint runs on partial edits mid-task it will report failures that are not
  real. Scope to write completion, and measure invocation count after one week to
  confirm the trigger produces signal rather than fatigue.
- **W3 may find the skills are simply unnecessary.** If the diagnosis shows the
  descriptions match fine and the tasks never arose, the honest conclusion is that ydi
  does not need those 8 skills — not that they need better triggers.

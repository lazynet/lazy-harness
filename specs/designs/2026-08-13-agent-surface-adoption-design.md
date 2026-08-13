# Agent surface adoption — design

**Date:** 2026-08-13
**Status:** Proposed
**Scope:** `~/.claude-lazy/skills`, `~/.claude-flex/skills`, `lazy-ansible`, `ydi-data-layer`, graphify MCP

## Problem

The original request assumed three repos were missing agent surface — MCP servers and
skills that had not been configured yet. Measurement contradicts that premise. The
surface exists; it does not fire.

Evidence gathered from 2,624 session transcripts across both profiles (2026-07-20 →
2026-08-13):

| Surface | Declared | Invocations in window |
|---------|----------|-----------------------|
| `ydi-data-layer` domain skills (8, incl. `data-lake-monitoring`) | versioned in repo | 0 across 65 sessions |
| `ansible-lint`, `ansible-security-audit` | `lazy-ansible/.claude/skills/` | 0 across 395 sessions |
| `graphify` MCP | both profiles | 0 |
| `grafana` MCP | flex profile | 0 across 1,217 sessions |
| `gws-*`, `persona-*`, `recipe-*` skills (36) | symlinked into lazy profile | 0 |

The defect is uniform: **declaring a capability is not the same as adopting it.**
Availability is passive; invocation requires a trigger — a hook, a slash command, or a
description that matches the vocabulary actually used in prompts.

This restates a failure already recorded in project memory (`tool_adoption_gate`): a
rule written in `CLAUDE.md` is not an adoption mechanism. The ydi numbers are the
empirical confirmation — 65 sessions, 8 skills, 0% adoption.

## Non-goals

- Adding new MCP servers or skills to any of the three repos.
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
in the 65 recorded sessions, so the router never selects them.

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

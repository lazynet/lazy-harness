# Claude Code 2.1.270–2.1.278: impact on lazy-harness

Read-only research. Every claim below is tagged `[verified-on-this-machine]` or
`[inferred-from-changelog]`. Source: `raw.githubusercontent.com/anthropics/claude-code/main/CHANGELOG.md`,
fetched fresh for this report. Installed build: `2.1.278`
(`~/.local/share/claude/versions/`) `[verified-on-this-machine]`.

## Correction: my first pass was wrong on both premise checks

My first draft ran the changelog fetch through `WebFetch`, whose summarizing
step silently reshuffled bullets between versions and dropped one entirely. I
re-verified directly against the raw file
(`scratchpad/CHANGELOG.md`, 7158 lines, `grep`/`sed`, no summarization layer)
`[verified-on-this-machine]` and both of the brief's claims are correct; mine
were not:

- **AGENTS.md support shipped in 2.1.277, not 2.1.278.** Line 10, under `##
  2.1.277` (line 8): *"Added AGENTS.md support: in a project with no
  CLAUDE.md, Claude Code reads AGENTS.md instead; change it under 'Project
  instructions' in `/config` (not yet on Bedrock, Vertex or Foundry)."*
  2.1.278 (lines 3–7) has exactly two bullets, both about the auto-mode
  server-side classifier — nothing about CLAUDE.md/AGENTS.md. This doesn't
  change the ADR-060 analysis below (the probed binary was 2.1.278, which
  obviously includes what 2.1.277 shipped), but two things are worth carrying
  forward that my first pass missed entirely: the feature is **not yet
  available on Bedrock/Vertex/Foundry**, and it's **user-configurable** —
  `/config` → "Project instructions" can be set away from the AGENTS.md
  fallback. That setting is per-machine, not per-repo (the ADR-060 evidence
  doc already found this and rejected relying on it — see below) — but it
  means the fallback isn't unconditional even where it is available.
- **The saturated-macOS settings-watcher item is real.** Line 406, under `##
  2.1.271`: *"Fixed settings file changes made outside the session going
  unnoticed on macOS machines whose system file-event service is saturated;
  the watcher now falls back to polling."* This is squarely aimed at what
  `lh deploy` does to every running session on this machine — evaluated
  properly in §2 below instead of dismissed.

Lesson for next time: don't fetch a changelog through a summarizing tool when
the task is "get every bullet for these exact versions" — `grep`/`sed` on the
raw file is what actually keeps every line intact.

## 1. AGENTS.md fallback (2.1.278) — the one you asked about

**This already happened, on purpose, and the harness has already reacted.**

- `lazy-harness`'s own repo root carries `AGENTS.md` (75 lines) and **no**
  `CLAUDE.md` `[verified-on-this-machine: ls CLAUDE.md AGENTS.md in repo root]`.
  Before 2.1.278, a Claude Code session (lazy/flex profile) working in this
  exact repo read nothing project-specific. On the installed 2.1.278 build, it
  now reads `AGENTS.md` directly, walking the parent chain the same way Codex
  always has.
- This is deliberate: **ADR-060** (`specs/adrs/060-agents-md-is-the-portable-repository-contract.md`,
  accepted 2026-09-19) declares AGENTS.md the sole repository instruction
  surface and rejects any `CLAUDE.md` that would shadow it
  `[verified-on-this-machine: read the ADR]`. It's backed by
  `specs/designs/repo-instruction-discovery-evidence.md`, ten probe runs
  against the real `2.1.278` binary and `codex-cli 0.155.0` dated 2026-09-19
  on this host `[verified-on-this-machine: read the evidence doc; I did not
  re-run the ten probes myself this session — that work and its dated,
  reproducible method belong to a prior session]`. Key results from that doc:
  - Direct `AGENTS.md` reading (no `CLAUDE.md` present) walks the parent chain
    correctly from any subdirectory (run 8).
  - A `CLAUDE.md`'s `@AGENTS.md` import only expands in the CWD's own
    `CLAUDE.md` — one directory down, the import silently fails to expand
    (runs 3–6). So "redirect AGENTS.md's content via a CLAUDE.md import" is
    not a safe converge path.
  - Codex is unaffected either way (runs 9–10).
- **Rollout status**: lazy-harness has migrated. `lazy-ai-tools` and
  `dotfiles` — the other two ADR-060 pilots — still carry only `CLAUDE.md`, no
  `AGENTS.md` `[verified-on-this-machine: ls in both repo roots]`. They are
  unaffected by the 2.1.278 change today (no `AGENTS.md` exists there to fall
  back to) and are exactly where the harness's own rollout says they should be
  next.
- **`lh repo instructions .`** is the static gate ADR-060 names. It passes on
  lazy-harness right now `[verified-on-this-machine: ran it]`. It is **not**
  wired into CI, a pre-commit hook, or `coherence-audit`
  `[verified-on-this-machine: grepped .github/workflows, .claude/commands,
  specs/workflow for references — none]` — nothing currently stops someone
  from reintroducing a shadowing `CLAUDE.md` in this repo.
- **`omitClaudeMd` (2.1.271) is not relevant.** Zero occurrences anywhere in
  `lazy_harness` source `[verified-on-this-machine: grep]`. It's a per-subagent
  frontmatter opt-out (skip loading user/project CLAUDE.md for one specific
  subagent definition) — a different axis from ADR-060, which governs the
  main session's own repo-instruction discovery. The harness doesn't generate
  subagent frontmatter that would use it.

**Answering the brief's three questions directly**: CLAUDE.md wins when both
are present (it shadows AGENTS.md for the session that loaded it), but its
`@import` of AGENTS.md doesn't survive one directory down — so "both present"
is not actually a safe convergence state, full replacement is. Yes, the
current layout already produces exactly this in lazy-harness itself. Yes,
there's a path to converge (already executed once); what breaks is nested
`@import` expansion, which is why ADR-060 rejects CLAUDE.md outright rather
than trying to make it a redirect.

## 2. 2.1.271 settings-watcher fix — evaluated for real, top priority

**This is not hypothetical.** You reported that today, two profiles ran ~9h
with `settings.json` changed underneath them without either session noticing
`[your report — I did not independently observe the 9h window itself]`. What
I can independently confirm around it:

- `lh deploy` genuinely rewrites `settings.json` for a profile while sessions
  on that profile may be running — there's no session-liveness check before
  the write, only a same-run staleness guard (`_refuse_if_changed` in
  `deploy/engine.py` aborts the *deploy* if a target changed since it was
  read mid-plan; it says nothing about sessions already running against the
  old content) `[verified-on-this-machine: read deploy/engine.py]`.
- Both profiles' `settings.json` were rewritten very recently — `20:00:34`
  (lazy) and `20:00:51` (flex) — against a `now` of `20:12:41`
  `[verified-on-this-machine: stat]`, consistent with a corrective redeploy
  around the time you were investigating this.
- Long-lived processes exist on this machine right now, including ones
  running continuously since Friday `[verified-on-this-machine: ps aux
  shows processes with start times back to "Fri03AM"]` — the shape a 9h
  stale-settings window needs (a session old enough to predate the
  out-of-band write) is present in general on this machine, though I can't
  attribute the specific 9h incident to a specific process from `ps` alone.
- The installed build (2.1.278) **includes** the 2.1.271 fix per the
  changelog — the polling fallback should already be active. Your report of
  it still failing today is the actually important data point here: either
  the fix doesn't fully close the gap, the incident predates whatever
  triggered today's `~20:00` redeploy, or there's a second mechanism at
  play. I can't resolve which from static inspection — this needs a
  deliberate repro (edit `settings.json` out-of-band on a live session,
  time how long the session takes to notice) rather than more reading.

This changes the ranking: this is the top backlog item, not a dismissed one.

## 3. Also assessed

| Item | Verdict | Basis |
|---|---|---|
| 2.1.275 sandboxed Bash can't write `hooks/`/`config/`; `/update-config` bad `Write(path)` rules | Not currently exposed | `lh hook` runs as an external process Claude Code spawns from `settings.json`, not through the agent's own sandboxed-Bash path; no `sandbox` key is set on the lazy profile `[verified-on-this-machine]`. The harness's generated `permissions` block is `allow`-only (112 entries), empty `deny`/`ask` — no generated `Write(<path>)` rules exist to be malformed `[verified-on-this-machine: read settings.json]`. |
| 2.1.274 Read/Edit deny rules not applying to symlinked dirs | Not currently exposed, and already fixed upstream | Profile layout genuinely is symlinks (`deploy/symlinks.py`, `deploy/ledger.py` explicitly owns them) `[verified-on-this-machine]`. But the lazy profile's `permissions.deny` is empty — the harness doesn't use deny rules at all today, so this had no bite even before the fix. The fix itself is listed under 2.1.274, so it's already in the installed 2.1.278 build `[inferred-from-changelog]`. |
| 2.1.275 `SubagentStop` firing for empty agent types | Not affected | The lazy profile's `settings.json` hooks block has no `SubagentStop` entry at all (registered: SessionStart, Stop, SessionEnd, PreCompact, PreToolUse, PostToolUse, UserPromptSubmit, Notification, PermissionRequest) `[verified-on-this-machine]`. |
| 2.1.275 claude.ai skill/plugin sync; 2.1.271 synced skills staying indefinitely | **Live gap, no opt-out set** | No skill/plugin-sync opt-out key appears anywhere in the deployed `settings.json` `[verified-on-this-machine]`, so the native default (sync on, per the 2.1.275 entry) applies un-overridden. The harness's own skill ledger (`deploy/skills.py`) does defend against a second writer: a native-root entry present but absent from `.lazy-harness/skill-links.json` raises `SkillCollisionError` and aborts the whole deploy with nothing written `[verified-on-this-machine: read skills.py:208-220]` — so collision fails loud, not silent, but it would still block `lh deploy` the first time a synced skill's name collides. |
| 2.1.271 `/hooks` menu crash on object-property-named matchers | Not affected | Every `"matcher"` value the harness emits is a tool name or hook-event name (checked every `"matcher":` occurrence in source) — none collide with JS object properties like `constructor`/`toString` `[verified-on-this-machine: grep]`. |
| 2.1.278 missing first message after `/clear` with heavy SessionStart hook output | Precondition confirmed true; exact repro not reproduced | This very session's own SessionStart hook output was flagged "Output too large (13.3KB)" and separately truncated to fit a "12000-char budget" `[verified-on-this-machine: this session's own transcript]` — `session-context`/`context_inject.py` genuinely emits that much on every session start on this profile. Whether the specific post-`/clear` repro triggers is `[inferred-from-changelog]` — I did not run an actual `/clear` to confirm — but the precondition the bug needs is real and present on every session here, so the fix is not moot. |

## Backlog (ranked, ≤6)

1. Reproduce the settings-watcher gap deliberately (edit a live profile's
   `settings.json` out-of-band, time how long a running session takes to
   notice) — today's ~9h incident happened on a build that's supposed to
   already carry the 2.1.271 polling-fallback fix, so either the fix doesn't
   fully close it or something else is going on; static reading can't settle
   which.
2. Wire `lh repo instructions` into CI or `coherence-audit` so the ADR-060
   AGENTS.md-only contract can't silently regress in lazy-harness — right now
   nothing enforces it outside a manual run.
3. Continue the ADR-060 rollout to `lazy-ai-tools` and `dotfiles` (both still
   CLAUDE.md-only) using the same root+nested probe method the evidence doc
   used, since that's the harness's own stated next step, not a new finding.
4. Decide whether to set an explicit skill/plugin-sync opt-out in
   `settings.json` now that 2.1.275 syncs claude.ai skills/plugins by default
   with no override currently set — a same-named synced skill will hard-fail
   `lh deploy` via `SkillCollisionError` until this is addressed.

# ADR-043: System docs by role — a set of destinations, and segments that lose their stem

**Status:** accepted
**Date:** 2026-09-16
**Supersedes:** —
**Superseded by:** —
**Related:** ADR-004 (agent adapter pattern), ADR-009 (profile symlink deploy), ADR-032 (agent adapter completeness — deferred exactly this), ADR-041 (the multi-agent hook contract), ADR-042 (multi-file config planning)

## Context

`AgentAdapter.system_doc_name() -> str` answered one question: *what is this
agent's system-instruction filename?* It has been the key to the whole
system-document tree since ADR-032, and ADR-032 named the deferral in its own
alternatives section — "make `system_doc_name()` return a list to handle agents
that load multiple files" — on the grounds that no shipped adapter needed one.

Two things have changed since.

**A single name cannot express a real agent's destinations.** Copilot CLI
recognises `AGENTS.md` and `CLAUDE.md`, but only inside repositories. Its
*user-level* destinations are `copilot-instructions.md` and
`instructions/**/*.instructions.md` under `$COPILOT_HOME`. Writing `CLAUDE.md`
into Copilot's config dir installs nothing at all. One of those two destinations
is not even a bare filename — it carries a directory component that every reader
of a `str` would have to agree how to split, which is a second answer to one
question.

**The tree was keyed by Claude Code's filename across three repositories.**
`sync_agent_md.py` derived every path from the name the adapter returned:

```python
stem = doc_name.removesuffix(".md")                             # "CLAUDE"
common_path = profiles_dir / "_common" / f"{stem}.common.md"
head = entry / f"{stem}.head.md"
tail = entry / f"{stem}.tail.md"
```

So a profile running a second agent needed a *duplicate segment tree* for
identical content — the parent design measured 193 of 199 lines identical
across the deployed tree — and a destination like
`instructions/lh.instructions.md` yields no segment name at all.

Measured at `7585c7c` with
`grep -rn 'system_doc_name' src/lazy_harness/ --include='*.py'`: four call
sites, four definitions, four docstrings. The brief for this work said "four
call sites" with line numbers that steps 6 and 7 had already moved; the count
held, the lines did not.

## Decision

### 1. `system_docs() -> list[Path]` replaces `system_doc_name() -> str`

```python
def system_docs(self) -> list[Path]:
    """Paths, relative to the profile's config dir, this agent actually loads."""
```

**Destinations, not recognised filenames.** Each entry is a path the harness
writes and the agent loads, so an adapter returning two entries is asserting the
agent loads both. It is not a stacking promise: Copilot combines every
applicable instruction file with no defined precedence, opencode takes the first
match and breaks, and Claude Code reads only `CLAUDE.md`. That difference is a
per-agent property and belongs to the adapter, not to the deployer.

The old method is **removed**, not kept alongside. Two methods answering one
question is the failure mode this repo's own gate names — *one answer lives in
one importable place; every path naming it is derived from it or audited against
it* — and the segmented `<name>.head.md` lookup was exactly such a reader.
`bool(system_docs())` is the gate the empty string used to be.

### 2. Segments are named by role, not by the destination filename

```
<profile>/head.md      identity
_common/common.md      shared rules
_common/<agent>.md     agent-specific rules            (new, optional)
<profile>/tail.md      per-profile context
```

`render_agent_md` composes `head + common + agent + tail`, and the **identical
rendered bytes** are written to every path `system_docs()` returns. A
destination is where an agent looks, not a variant of the content.

**The agent segment is shared across profiles, not per profile.** That is a
measurement, not a preference. Re-measured on the deployed tree on 2026-09-16,
because the parent design's numbers had moved: `_common/CLAUDE.common.md` is 133
lines and holds every agent-specific line (`TaskCreate`/`TodoWrite`, subagent
model routing, `/rewind` / `/compact` / `/clear`); `lazy/CLAUDE.head.md` (4
lines), `lazy/CLAUDE.tail.md` (29), `flex/CLAUDE.head.md` (5) and
`flex/CLAUDE.tail.md` (26) hold none —
`grep -c 'TaskCreate\|TodoWrite\|/rewind\|/compact\|/clear\|subagent'`
returns 2 for the shared segment and 0 for all four identity segments. The
content is identity-independent in practice, so `<profile>/<agent>.md` would
split a file that lives in one place into one copy per profile, to serve no
observed need. That override is additive to this layout and costs nothing to add
when a second profile actually needs to say something different about the same
agent. One agent and zero divergent profiles is not a pattern.

An agent with no segment renders without one. That is the common case, not an
error.

### 3. The legacy stem-keyed layout still renders, and says so

A profile carrying no `head.md` falls back to `<stem>.head.md`,
`_common/<stem>.common.md` and `<stem>.tail.md`, where the stem is its first
destination's. The `SyncResult` carries `legacy segment layout — rename to
head.md / common.md / tail.md`, and `lh profile sync-claude-md` prints it.

This is deliberate and scoped. The deployed segment tree is **chezmoi source in
another repository**, symlinked into each profile dir per ADR-009; renaming its
eight plain files is a `chezmoi` source rename plus a redeploy, and it is that
change's job, not this one's. Shipping the rename without the fallback would
mean the next `uv tool install --reinstall` silently stops regenerating the
user's contract file on both machines — a failure whose only symptom is a
document that stops changing.

A tree carrying both layouts uses the role names. Reading the legacy files when
the role-named ones are present would make the rename a no-op that reports
success.

The fallback is a migration window, not a second permanent answer. It comes out
with the chezmoi rename.

**Evolution, 2026-09-19.** The rename and kill criterion closed on 2026-09-18;
the fallback was retired as recorded in [ADR-055's Evolution](055-segment-rename-and-the-agent-segment.md#evolution).
The same retirement removed the legacy spellings from `segment_filenames()`:
they are no longer inputs, so editing one no longer triggers a resync.

### 4. The sync hook's trigger set is derived from the roles

`post_tool_use_sync_claude.SEGMENT_FILES` was a literal
`{"CLAUDE.head.md", "CLAUDE.tail.md", "CLAUDE.common.md"}`. It is now
`segment_filenames()`, computed from the role constants plus the registry: the
three role basenames and one agent segment per registered agent. Legacy
spellings are not part of the current trigger set.

This is the half of the blast-radius design's decision 5 that had to move with
the rename. A static list mirroring a set of files is how renaming the segments
stops firing the hook that regenerates the document *from* those segments — the
rename lands, the hook keeps watching three filenames nobody edits any more, and
the deployed contract file goes stale with nothing on any channel to say so. The
repo's gate on static lists that mirror a directory is the general form.

## The widening audit

The gate: *widening a type audits every path naming that type **or its config**,
not just the `Protocol` methods.*

| Path | Names the type or its config | Changed |
|---|---|---|
| `agents/base.py:AgentAdapter` | Protocol declaration | ✅ `system_docs()` |
| `agents/claude_code.py`, `agents/codex.py`, `agents/registry.py:NullAdapter` | implementations | ✅ |
| `core/sync_agent_md.py` | the generator, sole reader of the segment layout | ✅ destinations + roles |
| `core/artifact_version.py` | version stamp per deployed artifact | ✅ one report per destination |
| `plugins/capabilities.py:_agent_has_system_doc` | `requires_system_doc` gate | ✅ |
| `deploy/defaults.py:merge_with_defaults` | `_SYSTEM_DOC_HOOKS` gate | ✅ |
| `hooks/builtins/post_tool_use_sync_claude.py` | trigger set + docstrings | ✅ derived |
| `cli/profile_cmd.py:sync-claude-md` | prints one line per result | ✅ names the destination |
| `docs/how/hooks.md` | prose naming the mechanism | ✅ |
| `plugins/capabilities.py:Capability.requires_system_doc` | **config field** | audited, unchanged — it is a boolean about *whether* a doc is loaded, and widening one to N does not change its question |
| `plugins/builtins.py:_SYSTEM_DOC_HOOKS` | **config**, the hook names the gate filters | audited, unchanged — a set of hook names, independent of how many docs there are |
| `config.toml` schema (`core/config.py`) | — | audited: `grep -rn 'system_doc\|CLAUDE\.md' src/lazy_harness/core/config.py` returns nothing. No config key names a system doc; the answer has only ever come from the adapter |

The two audited-unchanged config surfaces are the ones the `Protocol`-only
reading of the gate would have missed. Both are questions of *kind*, not of
*cardinality*, which is why widening the cardinality leaves them correct.

## What is out of scope

**Decision 10's per-agent profile asset segments.** The design assigns four
things to this step besides the rename: per-agent asset segments, file-level
linking, stale-link removal, and `sync_agent_md.py` agreeing with the resulting
layout. The first three are `deploy/engine.py:deploy_profiles`, which this work
does not own.

The fourth cannot ship alone, and that is a measurement rather than a
preference. `deploy/engine.py:188` links **every entry** of the profile source
dir as one symlink, directories included — which is how `skills/` and
`commands/` are deployed today. So an assembler that wrote the rendered document
into `<profile>/<agent>/CLAUDE.md`, against a deployer that has not learned to
walk segments and link at the file level, would produce
`~/.claude-<profile>/<agent>/CLAUDE.md`: a correct file in a directory the agent
never reads. Half of this agreement is worse than none of it.

**The sync hook's rename.** `post_tool_use_sync_claude` →
`post_tool_use_sync_system_doc` and `lh profile sync-claude-md` →
`lh profile sync-system-doc` are the other half of decision 5. Only the hook's
*name* is still Claude Code-specific — its trigger set no longer is. The rename
travels with the chezmoi source rename and the paragraph in the deployed system
document that documents this hook's trigger, because the gate requires the prose
and the mechanism move together and that paragraph is read by a person who acts
on it.

> **Evolution (2026-09-16).** This half of decision 5 shipped with #366 (`4309633`, 2026-09-16):
> the builtin is `hooks/builtins/post_tool_use_sync_system_doc.py`, and
> `lh profile sync-system-doc` is the command, with `sync-claude-md` kept as a
> hidden alias.

**Retiring MCP entries the harness stopped generating.** Named here only because
ADR-042 records it against the same design step; it needs an ownership marker in
`[mcp_servers.<id>]`, which has no free key, and it is `deploy/engine.py`'s.

## Kill criteria

This work is registered in `specs/backlog.md` under *Multi-agente — items
declarados, deliberadamente no cableados*, with the start condition:

> **Condición de arranque:** con el step 8 del spec padre, en el mismo release
> que el rename del hook de sync (decisión 5). Tampoco sobrevive a los kill
> criteria.

So it is, by its own registration, work that is thrown away if the multi-agent
effort dies. It ships anyway because it was asked for, and this section is the
honest accounting rather than a silent completion.

**The criteria have not fired, and could not have.** The instrument is the
`launches` table of the derived design's decision 1, and the clock starts at
parent step 9 — a real `CodexAdapter`. Measured today:

- `grep -rn 'launches' src/lazy_harness/ --include='*.py'` finds one hit, the
  first line of `agents/launch.py`'s module docstring. The table does not exist.
- `agents/codex.py:1` still reads "the throwaway that runs step 4's contract
  gate". Step 9 has not happened.

> **Evolution (2026-09-23).** The measurement above is the state on the date
> of writing. The instrument now exists — `monitoring/launches.py` records
> launches and `monitoring/db.py` creates the `launches` table — and step 9
> happened: ADR-044 replaced the throwaway with the real `CodexAdapter`. The
> clock has started; the horizon opens on 2026-11-11 (`docs/roadmap.md`).

There is therefore no evidence either way, which is a different statement from
"the criteria are satisfied". The honest reading is that this step was taken
before the horizon it is meant to survive has opened.

What survives regardless of that horizon: the hook trigger set stops being a
static list, `lh doctor` gains a per-destination version report, and the
segment tree stops being keyed by one vendor's filename. Those are correctness
improvements for a single-agent Claude Code installation on their own. What does
not survive: the `system_docs()` list having more than one element, and
`_common/<agent>.md` having more than one file in it.

## Alternatives considered

**Keep `system_doc_name()` and add `system_docs()` beside it.** Rejected by the
repo's own gate. The stem lookup in `sync_agent_md.py` was a second reader of
the same answer, and leaving both would have let a call site keep the narrow one
indefinitely — which is exactly what the audit above found in the two adapters
that inherit from `NullAdapter` in tests: a fake overriding only `system_docs()`
silently reported "no system doc" through the inherited `system_doc_name()`.
That failure is what the capability registry's red test caught.

**Return `list[str]` rather than `list[Path]`.** A `str` cannot carry a nested
destination without every reader agreeing how to split it. `Path` also makes
`out.parent.mkdir(parents=True, exist_ok=True)` the obvious write, rather than a
directory the deployer has to infer.

**Attach `scope: Literal["global", "repo"]` to each entry.** The parent design's
first draft had it. No consumer exists for `"repo"`: the harness writes system
docs into the profile's config dir and nowhere else. A field with no reader is a
config promise with no implementation. It returns when `lh deploy` learns to
write into a repository, as its own decision.

**Rename the segments with no fallback, per decision 4 as written.** Decision 4
describes the migration as a chezmoi source rename plus `chezmoi apply` plus
`lh deploy`. That is correct for a coordinated change across both repositories;
it is not correct for a release of the Python package alone, which is what this
is. The fallback is the price of shipping the two halves in two changes, and it
is bounded by a diagnostic that names itself.

**Per-profile agent segments (`<profile>/<agent>.md`).** Deferred, with the
measurement above.

## Consequences

**Positive**

- A second destination becomes expressible, and each is separately version-
  stamped, so a stale `instructions/*.instructions.md` beside a current
  `copilot-instructions.md` can no longer read as clean.
- The segment tree stops multiplying by destination filename: one rendered
  document, N destinations, one agent segment per agent rather than a duplicated
  tree per profile.
- The sync hook's trigger set can no longer drift from the segments it watches.
- `lh profile sync-claude-md` names the file it wrote, which it had to start
  doing once one profile could produce several lines.

**Negative**

- **Historical — closed by #403 and ADR-055.** Two segment layouts were readable
  during the migration window, which temporarily gave two answers to "where do
  segments live". The role-named layout is now the only readable one.
- `render_agent_md`'s signature changed, and its `names` argument exists only so
  the generated header can spell the layout actually read. Three test call sites
  moved with it.
- **Historical — closed by #403 and ADR-055.** The deployed tree carried the
  legacy names, so generated headers named `CLAUDE.head.md` until the rename
  landed. All deployed profiles now use the role names.
- Decision 10's half of this design step is deferred with a named blocker rather
  than done, so the design's "the assembler and the deployer must agree on one
  layout" is still an open item — now with the reason recorded.

## Evidence standard

Every guard in this change was verified by removing it **by hand**, watching the
named test fail, and restoring it by hand — never with `git checkout`, which
would have reverted the uncommitted implementation with it. Eight guards, each
with its own test:

| Guard removed | Test that went red |
|---|---|
| `capabilities.py` reading `system_docs()` | `test_a_multi_destination_agent_reports_its_system_doc_hook_on` |
| `defaults.py` reading `system_docs()` | `test_an_agent_with_two_destinations_keeps_the_doc_hook` |
| `artifact_version` iterating every destination | `test_a_multi_destination_agent_is_reported_once_per_destination` |
| `sync_profiles` writing every destination | `test_one_rendered_document_lands_at_every_destination` |
| the role layout winning over legacy | `test_the_role_layout_wins_over_a_legacy_layout_left_beside_it` |
| the agent segment being composed in | `test_the_agent_segment_is_shared_across_profiles_and_lands_after_common` |
| the derived trigger set | `test_an_edit_to_a_role_named_segment_regenerates_the_tree` |
| the legacy diagnostic | `test_the_legacy_stem_keyed_layout_is_named_in_the_result` |

The Protocol widening itself is asserted the only way `runtime_checkable`
permits: an adapter that implements `system_docs()` and *not* `system_doc_name()`
is an `AgentAdapter`, which was false before the change and is the widening
stated as an assertion.

Suite: 3948 passed at `7585c7c`, 3970 after. The brief for this work quoted
3904; that number was stale by 44 before the work started.

## References

- [`specs/designs/2026-09-13-multi-agent-harness-design.md`](../designs/2026-09-13-multi-agent-harness-design.md) — decision 6, decision 10, step 8
- [`specs/designs/2026-09-13-multi-agent-blast-radius-design.md`](../designs/2026-09-13-multi-agent-blast-radius-design.md) — findings 4 and 5, decisions 1, 4 and 5
- [`specs/adrs/032-agent-adapter-completeness.md`](./032-agent-adapter-completeness.md) — the deferral this closes
- [`specs/backlog.md`](../backlog.md) — *Segmentos de perfil nombrados por rol, no por filename destino*

# ADR-044: Codex's native edit path — three fixes, and the half that cannot be gated

**Status:** accepted
**Date:** 2026-09-16
**Supersedes:** —
**Superseded by:** —
**Related:** ADR-004 (agent adapter pattern), ADR-041 (multi-agent hook contract), ADR-042 (multi-file config planning), ADR-043 (system docs by role)

## Context

ADR-041 shipped a throwaway `CodexAdapter` to run the hook contract's freezing
gate against a real binary. Its own docstring said what it was: "the smallest
thing that can carry three builtins to a real Codex session". It mapped exactly
one native tool name — `Bash -> RUN_COMMAND` — and populated neither
`ToolCall.edits` nor `ToolCall.reads` for any tool at all.

The F8 translation gate (`specs/gates/f8/translation-gate.sh`) measured the
consequence and named five builtins inert under Codex: `post-tool-use-format`,
`post-tool-use-sync-claude`, `post-tool-use-ansible-lint`,
`pre-tool-use-memory-size` and `pre-tool-use-read-size`. Inert, not absent —
they deploy, they are wired, they run, they exit 0, and they enforce nothing.

That gate wrote its payloads in **Claude Code's dialect**
(`{"tool_name":"Edit","tool_input":{"file_path":…}}`) and said so in its own
header. It measured "what happens if Codex sent Claude's tool name", never
"what Codex actually sends". `specs/designs/codex-evidence.md` closed that gap
on 2026-09-16 with six probes against `codex-cli 0.154.0`, and the answer
changes what the fix has to be.

**Codex takes two edit paths and picks between them non-deterministically.**

1. `Bash` running a python heredoc — most runs. `tool_input` is
   `{"command": "<arbitrary shell script>"}`.
2. `apply_patch`, its own tool — confirmed by probe 4c, which forced a native
   edit and used a *validated* deny envelope to prove the hook saw it.
   `tool_input` is **also** `{"command": …}` — the same key — carrying a raw
   patch blob: `*** Begin Patch\n*** Update File: <abs path>\n@@\n-old\n+new\n*** End Patch`.
   There is no structured path field; the touched path is a line inside the text.

The first round of probes read the native path as *unhooked*. It was not: that
round's deny verdict was built with a hand-escaped `echo`, and a malformed
envelope is an unsupported `permissionDecision`, which ADR-041 already records
as **failing open**. The edit going through said nothing about whether the hook
fired. Probe 4c, with a `json.dumps`-built envelope, blocked the edit and logged
`tool_name: "apply_patch"`. The reading is withdrawn; the correction is why this
ADR exists in the shape it does.

## Decision

### 1. Three fixes, and each is necessary

The prevailing account — in `specs/backlog.md` and in the F8 gate's own control
fixture `fake-translate-operations-only.sh` — was that widening
`_TOOL_OPERATIONS` is a no-op. That fixture was written expecting the gate to
fail it and the gate passed it, which is the stronger result: the mapping alone
revives nothing. Three independent gaps stack, and the parser is the one the
earlier account missed.

| Fix | Without it |
|---|---|
| `_TOOL_OPERATIONS["apply_patch"] = MODIFY_FILE` | `post-tool-use-format` returns at `operation is not MODIFY_FILE`. |
| `"apply_patch"` in the edit builtins' `INSPECTED_TOOLS` | Three builtins return at the tool-name gate. |
| `_parse_patch` turning the blob into `FileEdit`s | All five return one line lower, iterating an empty `tool.edits`. |

A fourth was found while shipping them, and it is in one builtin only:
`pre_tool_use_memory_size._projected_text` branches on the *tool name* —
`"Write"` takes `content`, `"Edit"` replays `replacements`, anything else
returns `None` and the hook goes quiet. So that builtin stayed silent on
`apply_patch` with all three fixes above in place. `apply_patch` carries both
shapes in one blob, so it is the one tool whose branch is chosen by the
`FileEdit` rather than by the name.

### 2. `INSPECTED_TOOLS` becomes one importable answer

Four builtins each carried their own `frozenset({"Edit", "Write"})`. They now
read `_shared.EDIT_TOOLS`, and a test asserts identity rather than equality: a
retyped equal set drifts on the next name, which is exactly how a widening
reaches three of four.

`NotebookEdit` stays **out** of that set, which is the whole reason it is a
tool-name set and not `Operation.MODIFY_FILE`. The adapters map `NotebookEdit`
to `MODIFY_FILE`, and every one of these builtins re-checks the path by *name*
(`CLAUDE.md`, `MEMORY.md`, `.yml`), never by suffix — so a notebook whose
normalised path is named `CLAUDE.md` clears the second gate. Switching to the
operation would widen four hooks onto notebooks for the first time with nothing
on any channel to say so.

`pre-tool-use-read-size` is deliberately **not** widened: it gates on
`Operation.READ_FILE` and iterates `tool.reads`. `apply_patch` is an edit;
Codex's read dialect has never been probed. It stays inert, and the F8 gate
still asserts it.

### 3. `ToolCall.command` stays unset for `apply_patch`

A patch blob is not a shell command, and two builtins read `tool.command` as
one — `pre_tool_use_security.py:362` and `pre_tool_use_git_scope.py:402` both
scan it for shell syntax. Setting it would put the *content of an edit* in front
of a command denylist, matching on lines the model is writing into a file rather
than on anything being executed. The blob stays reachable through `raw_input`,
which is adapters-only by its own docstring.

### 4. `lh doctor` reports Codex hook trust, and no more than it can establish

Decision 5 of the harness design takes option (b): deploy untrusted, the user
trusts once in the TUI, and `lh doctor` reads `[hooks.state.<key>].trusted_hash`
back. Codex decides the status by *comparing* the persisted hash with a freshly
computed one, and computing that second hash is what (b) declines to
reimplement. So reading a `trusted_hash` establishes that a hash was stored and
nothing about whether it still matches.

`lh doctor` therefore reports two states and not three: `untrusted` (no entry
for this hook's key) and `trust unknown` (an entry exists). It never says
`trusted`. It also names **orphaned** state entries — keys `[hooks.state]`
carries for this `hooks.json` that the file no longer declares — because the
trust key is `<declaring file>:<snake_case event>:<group index>:<handler index>`
and is therefore position-scoped: a redeploy that reorders a group re-prompts
for every hook below it.

## Consequences

**Only half of Codex's edits are gateable, and that is a property of the agent.**
The `Bash` path is structurally ungateable as an edit, not merely unmapped:
`tool_input` is `{"command": "<arbitrary shell script>"}` with no reliable path
to extract, because the model constructs that script however it likes. Mapping
`Bash` to `MODIFY_FILE` when its command *happens* to write a file would be
wrong for the same reason `RUN_COMMAND` is right for it today — from the hook's
point of view a `Bash` call is a command whatever it goes on to do. So a
fully-fixed adapter gates the `apply_patch` half and is blind to the other,
which the model chooses at random. **These fixes are a real improvement with a
measured ceiling, not a closed gap**, and nothing downstream should treat a
Codex profile's edit guards as complete.

**A `*** Delete File:` section produces no `FileEdit`.** `FileEdit` carries
`is_create` and no counterpart, so a delete emitted as an edit would tell every
reader the path is still there — `post_tool_use_format` would run a formatter
over a file that is gone. Widening `FileEdit` is the honest fix and it is not
taken here: the delete spelling is the patch format's, not one any probe has
seen Codex emit. `post-tool-use-sync-claude` consequently misses a deleted
system-doc segment.

**Multi-file blobs parse but were never observed.** No probe forced a multi-file
`apply_patch`, so whether Codex concatenates `*** Update File:` sections into one
`command` or splits them across hook calls is open. The parser is generic over
sections either way; the tests say which shape is evidence and which is the
format.

**The F8 gate now consumes the real dialect and its control table changed.**
`fake-translate-operations-only.sh` used to pass — the finding that a mapping
fix revives nothing. With the parser shipped it fails, which is the
discrimination proof the gate needed: remove the blob parsing and four builtins
fall back into the inert set.

**`global_config_link()` stays `None` for Codex, now for a measured reason.**
`ensure_symlink` renames an existing target to `<name>.bak` before linking
(`deploy/symlinks.py:16-21`), and `~/.codex` holds `auth.json` plus the
`config.toml` carrying `[hooks.state]` approvals and `[projects.*]` trust —
none of it reconstructible. The step-4 docstring justified `None` as throwaway
blast-radius shrinking; `core/paths.py:162-171` already records that the
justification did not hold, because the last-resort fallback is `~/.<agent
name>` — the very directory `None` was protecting. The answer is unchanged and
the reason is now the right one.

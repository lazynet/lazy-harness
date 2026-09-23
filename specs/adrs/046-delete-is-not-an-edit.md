# ADR-046: A delete is not an edit — `ToolCall.deletes`, and the readers that must not see it

**Status:** accepted
**Date:** 2026-09-16
**Supersedes:** —
**Superseded by:** —
**Related:** ADR-041 (multi-agent hook contract), ADR-043 (system docs by role), ADR-044 (Codex's native edit path)

## Context

`FileEdit` (`agents/base.py:60`) carries `is_create` and no counterpart, so the
contract has no way to say that a tool call removed a file. `_parse_patch`
(`agents/codex.py:201`) therefore drops a `*** Delete File:` section on purpose,
and its docstring says why: emitting one as a `FileEdit` "tells every reader the
path is still there — `post_tool_use_format` would run a formatter over a file
that is gone."

ADR-044 left the widening undecided on an evidence argument, not a design one:
"the delete spelling is the patch format's, not one any probe has seen Codex
emit."

**That reason expired on 2026-09-16.** Probe 6 (`specs/designs/codex-evidence.md:60`,
`:379-387`, `codex-cli 0.154.0`, model `gpt-5.6-sol`) recorded one `PreToolUse`
with `tool_name: apply_patch` and a single-section blob whose header is the
literal `*** Delete File: <abs path>` with **no diff body** under it. The target
file was removed from disk. The spelling is measured; what remains is the shape
the contract gives it.

### What the audit found before the type was touched

Five modules in `src/` consume `ToolCall.edits`, and one consumes
`ToolCall.paths`. Their behaviour on a delete is not uniform, and that
asymmetry is the whole decision:

| Reader | What it does with an edit | What it must do with a delete |
|---|---|---|
| `post_tool_use_format.py:41` | `ruff format` on every `.py` path | nothing — the file is gone |
| `post_tool_use_ansible_lint.py:127` | `ansible-lint` on every `.yml`/`.yaml` path | nothing — same reason |
| `pre_tool_use_memory_size.py:258` | project the post-edit size and warn | nothing — a delete projects to no file, and every budget it could breach is now zero |
| `post_tool_use_sync_claude.py:87` | regenerate the profile tree of an edited segment | **regenerate**, which is the one thing a delete gains |
| `pre_tool_use_security.py:425` | gate `tool.paths` against the secret globs | **gate** — deleting a protected file is worse than editing it |

Three readers must not see a delete, one must, and one must see it through a
different door. A representation whose default is "the delete looks like an
edit" gets three of those five wrong by omission, and gets them wrong *silently*:
`ruff format /gone.py` exits non-zero into a `check=False` subprocess and the
hook returns `HookDecision()` either way.

`sync_profiles` was read before deciding a delete may reach it. It degrades
without raising: a missing `head.md` or `tail.md` yields
`SyncResult(action="skipped", reason="missing ...")` and leaves the deployed
document alone, a missing `_common/<name>` raises `SyncError`, and the hook
wraps the whole call in `except Exception: pass`. The interesting case is the
agent segment: deleting `_common/<agent>.md` makes `_agent_segment` return
`None` and the document re-renders without that section, which is exactly the
regeneration the backlog entry asked for.

### A second gap the audit surfaced

`pre_tool_use_security.main` reads `subject = str(paths[0]) if paths else ""`.
Under Claude Code that is complete — `reads` and `edits` are never both
populated and `edits` never holds more than one entry. Under Codex it is not:
probe 5 measured a two-section `apply_patch` blob arriving as one call, so since
#348 every path after the first in a multi-file patch has been ungated. This
ADR inherits that defect the moment a delete path joins `paths`, because a
delete lands after the edits in the tuple and would be the path most likely to
go unchecked.

## Decision

### D1 — The delete gets its own field on `ToolCall`, not a flag on `FileEdit`

```python
@dataclass(frozen=True)
class ToolCall:
    ...
    edits: tuple[FileEdit, ...] = ()
    deletes: tuple[Path, ...] = ()
```

`edits` keeps the meaning every reader already assumes: *the file is still
there, and here is what the tool disclosed about how it changed*. Nothing about
the four existing edit readers changes, and none of them can format, lint or
size a ghost, because a delete never enters the collection they iterate.

The failure mode this picks is the one that is visible. A reader that wants
deletes and does not ask for them under-reacts, which is what
`post-tool-use-sync-claude` did before this ADR and what it is fixed to stop
doing. A reader that gets a delete inside `edits` and forgets to check a flag
over-reacts on a path that does not exist, and no channel says so.

A bare `tuple[Path, ...]` rather than a `FileDelete` record: the measured shape
carries nothing but a path — no body, no mode, no `replacements` — and a record
with one field is a record inventing the second.

### D2 — `ToolCall.paths` includes the deletes

```python
@property
def paths(self) -> tuple[Path, ...]:
    return self.reads + tuple(edit.path for edit in self.edits) + self.deletes
```

`paths` is the question "which files does this tool call touch", and a delete
touches one. This is what keeps the path guard gating a delete without knowing
the field exists, and it is the reason D1 is safe rather than merely tidy: the
one reader that must *not* miss a delete is the one that already reads the
union.

### D3 — `_parse_patch` returns both halves, named

```python
class _Patch(NamedTuple):
    edits: tuple[FileEdit, ...]
    deletes: tuple[Path, ...]
```

A bare 2-tuple would put the discipline in the call site's unpacking order. The
parser already delimits all three section headers — it has to, or a header it
did not know would swallow the next file's body into the previous file's hunks —
so `delete` stops being a section it skips and becomes one it collects.

Section order is preserved within each half. It is not preserved across them,
and nothing reads it: `apply_patch` applies every section in one call, so the
interleaving of two different files carries no semantics, and no consumer of
either collection orders work by it.

### D4 — `post-tool-use-sync-claude` is the one reader that opts in

`_trees_touched` is fed `tool.paths`-style input already; it now receives the
edit paths **and** the deletes. A deleted segment regenerates its tree exactly
as an edited one does. This is the concrete loss the backlog entry named, and
it is the only reader whose behaviour this ADR deliberately widens.

### D5 — The path guard judges every path, not the first

`pre_tool_use_security.main` walks `tool.paths` and blocks on the first path
that matches a secret glob, instead of testing `paths[0]` alone. The denylist,
`SECRET_PATH_EXCEPTIONS` and `should_block_path` are untouched; only the number
of subjects handed to them changes.

Recorded rather than deferred because D2 creates the exposure: without D5 a
blob reading `*** Update File: /w/notes.md` followed by
`*** Delete File: ~/.ssh/id_rsa` would present `/w/notes.md` to the guard and
delete the key unexamined.

## Alternatives considered and rejected

### A1 — `FileEdit.is_delete: bool = False`, mirroring `is_create`

The smallest diff, and the one the backlog entry's phrasing ("ensanchar el
tipo") most naturally suggests. Rejected on the shape of its failure: two
independent booleans make `is_create and is_delete` representable and
meaningless, and — the heavier cost — every present and future reader of
`tool.edits` must remember a negative check. Three of the five readers audited
above would have needed one, and a fourth reader written next year needs one
too, with nothing in the type to ask for it.

The asymmetry matters: forgetting `is_create` degrades a projection to a
replay, which is wrong but bounded. Forgetting `is_delete` runs a subprocess
over a path the tool just removed.

### A2 — An `EditKind` enum (`CREATE` / `UPDATE` / `DELETE`) replacing `is_create`

Fixes A1's representable-nonsense — a section is exactly one kind — and is the
more honest model of the patch format, which is itself a three-header
vocabulary. Rejected for the same omission hazard as A1 plus a wider blast
radius: `is_create` is read in `pre_tool_use_memory_size.py:155` and written in
`claude_code.py:457` and `codex.py:235`, and the migration touches every
constructor and the goldens over them, all to arrive at a representation whose
default behaviour for a forgetful reader is still "treat the delete as an edit".

Worth revisiting if a second agent ever discloses a delete with structure a
path cannot hold — a trashed-file destination, a rename disclosed as
delete-plus-create. Until then it is a larger change that buys a taxonomy, not
a guarantee.

### A3 — A delete inferred from `FileEdit` field emptiness

`is_create=False`, `content=None`, `replacements=()` as the delete signal, with
no new field at all. Rejected outright: that combination already occurs for an
`Edit` whose payload carries no `old_string`, and
`pre_tool_use_memory_size._projected_text`'s docstring records that exact shape
as a live one it deliberately projects the current file for. Overloading it
would turn a documented quirk into a silent data loss.

### A4 — Keep dropping the delete and record the gap

The status quo, now that the evidence exists. Rejected because the loss is no
longer hypothetical: probe 6 removed a file, and any Codex profile whose system
doc is assembled from segments can lose one with the deployed contract file
left stale and nothing on any channel saying so.

## Consequences

- **Every existing constructor and reader keeps working unchanged.** `deletes`
  defaults to `()`; `ClaudeCodeAdapter` never sets it, because Claude Code has
  no delete tool — its removals go through `Bash`, which carries no path to
  extract and stays under the structural ceiling ADR-044 records.
- **A reader that wants deletes must name them.** That is the point, and it is
  also the cost: `deletes` is invisible to a hook author who greps only for
  `edits`. `ToolCall`'s own docstring is where that is said.
- **The choice is reversible in the cheap direction.** Folding `deletes` back
  into `edits` behind an `EditKind` (A2) later is a mechanical change, and until
  it happens every reader already ignores deletes, so no intermediate state is
  unsafe. The reverse — retracting `is_delete` from `FileEdit` after readers
  have started branching on it — is not.
- **`pre-tool-use-security` gates strictly more than it did.** A multi-file
  patch whose second section names a secret is now blocked where it was not.
  That is a widening of a deny rule; it changes no pattern, and the
  first-match-wins reporting keeps one block message per call.
- **The F8 translation gate is unaffected.** Its `modify_file` leg feeds a
  single `*** Update File:` section, `edits` stays length 1, and no builtin's
  inert/live verdict moves. The gate's stale note about `read_file` being "the
  one synthetic leg left" is corrected in this change for a different reason:
  probe 7 found Codex 0.154.0 has no native read tool at all, so
  `pre-tool-use-read-size`'s inert verdict rests on a measured absence rather
  than on weaker evidence.
- **A delete still does not reach `pre-tool-use-memory-size`.** A removed
  `MEMORY.md` breaches nothing, and the hook's tool-name-keyed projection
  (`_projected_text`, the fourth fix ADR-044 records) is left exactly as it is —
  the delete never reaches it, so no branch was added there to forget.

## Evolution

**2026-09-16 — the one reader that opts in was renamed.** D4's
`post-tool-use-sync-claude` (`post_tool_use_sync_claude.py`) is
`post-tool-use-sync-system-doc` (`hooks/builtins/post_tool_use_sync_system_doc.py`)
since #366 (`4309633`, 2026-09-16); the decision is unchanged and the old name survives as an alias in
`hooks/loader.py`.

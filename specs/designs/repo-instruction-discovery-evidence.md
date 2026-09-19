# Repository instruction discovery evidence — root and nested, two binaries

**Status:** probes run 2026-09-19, ten runs, all read-only. §1 and §2 are closed
against the real binaries. §3 is the correction they force on
[the design](2026-09-19-portable-repository-instructions-design.md) and
[ADR-060](../adrs/060-agents-md-is-the-portable-repository-contract.md).
**Binaries:** `2.1.278 (Claude Code)` and `codex-cli 0.155.0`, both confirmed
with `--version` on the same host, 2026-09-19.
**Scope:** one question only — does each agent receive the content of
`AGENTS.md` when it starts in a repository root, and when it starts in a
subdirectory? Nothing here is evidence about hooks, tools or cost.

## Method

Four scratch fixtures, each a `git init` repository outside the worktree, each
carrying a unique sentinel token in the file under test. Every run asked for the
sentinel and nothing else, with file tools removed so the answer could only come
from loaded context: `claude -p '<prompt>' --disallowedTools Read Bash Grep Glob
Task WebFetch Edit Write` and `codex exec -C <dir> --sandbox read-only
'<prompt>'`. A run that reports `NONE` is a run where the content never arrived.

The prompt is the whole probe: a sentinel invented for the fixture cannot be
recovered from training data or from the repository, so a correct answer is
proof of loading and `NONE` is proof of absence.

## §1 Observed

| # | Fixture | cwd | Binary | Asked for | Observed |
|---|---------|-----|--------|-----------|----------|
| 1 | root pair: `AGENTS.md` + `CLAUDE.md` with `@AGENTS.md` | root | Claude Code | root sentinel | root sentinel |
| 2 | same, plus nested pair in `pkg/` | `pkg/` | Claude Code | every sentinel | nested sentinel only |
| 3 | root pair, empty `sub/` | `sub/` | Claude Code | sentinel or `NONE` | **`NONE`**, while the `CLAUDE.md` appendix line was quoted back |
| 4 | root pair, import written `@./AGENTS.md` | `sub/` | Claude Code | sentinel or `NONE` | **`NONE`** |
| 5 | root pair, import written as an absolute path | `sub/` | Claude Code | sentinel or `NONE` | **`NONE`** |
| 6 | root `CLAUDE.md` importing `@SHARED.md` (no `AGENTS.md` anywhere) | `sub/` | Claude Code | sentinel or `NONE` | **`NONE`** |
| 7 | same as 6 | root | Claude Code | sentinel or `NONE` | sentinel |
| 8 | `AGENTS.md` alone, no `CLAUDE.md` | `sub/` | Claude Code | sentinel or `NONE` | sentinel |
| 9 | root pair | `sub/` | Codex | sentinel or `NONE` | sentinel |
| 10 | this repository, post-migration | `src/lazy_harness/` | Codex | non-negotiable 5 | quoted verbatim |

Two runs against this repository's own pair frame the table: Claude Code quoted
non-negotiable 5 verbatim from the worktree root, and from
`src/lazy_harness/` answered that `AGENTS.md` "está referenciado desde
`CLAUDE.md` con `@AGENTS.md`, pero su contenido no entró en mi contexto".

## §2 What the runs establish

1. **The import resolves only for the `CLAUDE.md` in the working directory.**
   Runs 1 and 7 pass; runs 3, 4, 5 and 6 fail from one directory down. Run 3
   separates the two halves: the parent `CLAUDE.md` *is* loaded — its appendix
   line comes back — and its `@` line is not expanded.
2. **It is not specific to `AGENTS.md` or to a spelling.** Run 6 fails with a
   differently named target, and runs 4 and 5 fail with the relative-marked and
   absolute spellings. So this is parent-chain import expansion, not path
   resolution.
3. **Direct `AGENTS.md` reading does walk the parent chain.** Run 8 passes from
   a subdirectory with no `CLAUDE.md` in the repository at all.
4. **Codex is unaffected.** Runs 9 and 10 pass from a subdirectory.

Observed against spec: the memory documentation says imported files "are
expanded and loaded into context at launch alongside the `CLAUDE.md` that
references them", and that a session in `foo/bar/` loads `foo/bar/CLAUDE.md`
and `foo/CLAUDE.md`. It states no exception for the parent copies, so runs 3–6
contradict it on `2.1.278`. The same page also documents direct `AGENTS.md`
reading from v2.1.277, which run 8 confirms.

## §3 Correction this forces

The import mechanism fails one directory down for Claude Code. Run 8 supplies
the correction: without `CLAUDE.md`, Claude Code reads `AGENTS.md` directly
through the parent chain, the same contract Codex uses.

The pilot therefore ships one `AGENTS.md`, with Claude-only notes in a labelled
conditional section, and rejects every repository `CLAUDE.md`. This preserves
one source and makes the root/nested guarantee true for both measured binaries.

Rejected alternatives:

| Option | Cost |
|--------|------|
| Move the Claude-only appendix into `.claude/rules/` | Direct reading applies, but the extra discovery surface was not needed; a conditional `AGENTS.md` section is portable and explicit. |
| Set project instructions to `claude-md-and-agents-md` | Claude Code ignores that setting in project and local settings files, so it cannot ship with a repository — per machine, not per repo |
| Accept a root-only guarantee | Rejected: worktrees and scoped commands routinely start below repository root. |

`lh repo instructions` enforces the measured shape: one root `AGENTS.md` and no
`CLAUDE.md` that can shadow it.

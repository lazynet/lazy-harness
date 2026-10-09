# Graph freshness — plan

Design: `specs/designs/2026-10-09-graph-freshness-design.md` (read it first; §
numbers below refer to it). Every unit: strict TDD, the four-check gate in
`.claude/commands/tdd-check.md`, conventional commits, no AI trailers.

Run the gate with `TMPDIR=/tmp` in agent sessions: the repo-local TMPDIR from
#504 breaks ~126 tests (backlog, 2026-10-08).

## Unit 1 — freshness rule (`fix/graph-freshness`)

Files: new `src/lazy_harness/knowledge/graph_freshness.py`;
`hooks/builtins/pre_tool_use_graph_assist.py`; `hooks/builtins/context_inject.py`;
`.gitignore`; tests under `tests/` mirroring each module.

1. `CODE_EXTENSIONS: frozenset[str]` copied verbatim from
   `graphify/detect.py` of the installed graphify (0.9.72, site-packages under
   `~/.local/share/uv/tools/graphifyy/`). Comment names the source version.
2. `last_code_commit_ts(root: Path) -> float | None` (None = no code commit or
   git error), `is_fresh(root: Path) -> bool | None` (None = unknown), and the
   HEAD-sha cache in `graphify-out/cache/lh-freshness.json` (§2.1). One git
   process for the log; one for `rev-parse HEAD`.
3. Tests with real temporary git repos: docs-only commit after the graph →
   fresh (fails against today's rule — prove it); code commit after the graph →
   stale; no code commits → fresh; cache hit does not spawn `git log` (patch
   `subprocess.run` and count); corrupted cache → recompute; git missing → None.
   Uppercase extensions (`.F90`) and nested paths are matched.
4. Both consumers call `graph_freshness.is_fresh`; delete their inline `%ct`
   logic. Existing staleness tests keep passing or are updated to the new rule
   with a docs-only case added. The banner names the last code commit date.
5. `/tmp/` in `.gitignore`.

## Unit 2 — self-repair and scope (`feat/graph-repos-repair`)

Files: new `src/lazy_harness/knowledge/graph_repos.py`;
`src/lazy_harness/cli/knowledge_cmd.py` (graph `add`, `list`, `update` only);
`docs/reference/cli.md` (graph commands only); tests.

1. `ensure_repo(root: Path) -> RepoRepair` with three actions per §2.2:
   post-merge marked block, graphify hooks (`graphify hook install` via
   subprocess, cwd=root), global-only ignored dirs into a marked block of
   `<common-dir>/info/exclude`. Each returns `installed | already | failed`.
   Use `git rev-parse --path-format=absolute --git-common-dir` (AGENTS.md gate),
   tested from a main checkout and a worktree.
2. post-merge block: exits 0 in a linked worktree; otherwise runs
   `lh knowledge graph update --repo "<root>"` detached (`nohup … &`), appending
   to `<log dir>/graphify-post-merge.log`; preserves foreign content; idempotent
   (second run → `already`, file byte-identical). Test the generated script by
   executing it with `sh` in a temp repo with `lh` replaced by a stub on PATH.
3. Ignored dirs: feed a temp repo a fake global excludes file through
   `GIT_CONFIG_GLOBAL` / `core.excludesfile`; assert only global-sourced entries
   land in the block, repo `.gitignore` entries do not, the block is rewritten
   (not appended) on a second run.
4. Scope: registered ∪ discovered (`<data dir>/graph-repos.json`), discovery
   from every profile's `graph_assist_metrics.jsonl` `repo` field where
   `graphify-out/graph.json` exists. Malformed lines and wrong JSON types are
   skipped (test null/int/list).
5. CLI: `update` gains `--repo PATH`; without it iterates the scope and calls
   `ensure_repo` before each graphify run; prints one line per repair action
   that is not `already`. `add` calls `ensure_repo`. `list` marks discovered
   repos. Pair each `--repo` test with a parameter-less smoke test.
6. Out: doctor (unit 3).

## Unit 3 — doctor section (`feat/graph-doctor`), after units 1 and 2

Branch from unit 2's branch with unit 1 merged in. Files:
`knowledge/graph_repos.py` (`collect_graph_health`), `cli/doctor_cmd.py`
(`_render_graph_repos` + JSON), `docs/reference/cli.md` (doctor), tests.
Checks per §2.4, each with a passing and a failing fixture.

## Unit 4 — report denominator (`feat/graph-assist-denominator`)

Files: `src/lazy_harness/knowledge/graph_assist_report.py` and its tests only.
Per §2.5. Do not touch `cli/knowledge_cmd.py`; if rendering lives there, report
it instead of editing. Fixture: sessions with no evaluation must not move (a').

## Unit 5 — dispatcher (dotfiles repo, `fix/git-dispatch-post-merge`)

`home/dot_config/git/hooks/`: add `symlink_post-merge` and `symlink_post-checkout`
with the same target as `symlink_post-commit`. Run the repo's own test suite.

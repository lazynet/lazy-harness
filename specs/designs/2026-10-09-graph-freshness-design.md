# Graph freshness — design

Status: approved 2026-10-09. Plan: `specs/plans/2026-10-09-graph-freshness-plan.md`.

## 1. Problem

The graph-assist kill read on 2026-10-09 (`lh knowledge graph-assist report
--since 2026-09-25`) tripped one criterion: graph touch 89/742 = 12.0% < 20%.
The other two passed with margin (hit precision 91.2%, p95 latency 47 ms), and
deflection was 97.7%. The hook works when it fires; it rarely fires.

`graph_assist_metrics.jsonl` (claude-lazy + claude-flex, since day 0) shows why:

| Best outcome in the session | Sessions |
| --- | --- |
| every evaluation `stale`, no fresh search | **178** |
| ≥ 1 hit | 74 |
| misses only | 57 |
| fresh graph, no identifier-shaped search | 55 |
| outside a repo / no graph only | 39 |

`stale` means `graph.json` mtime < `%ct` of main's HEAD. Four causes, each
observed:

1. **False stale on non-code commits.** graphify's post-commit hook rebuilds
   from the changed files only, and on a change set with no code it leaves the
   outputs untouched (`No tracked code files in change set - skipping rebuild`,
   210 times in `~/.cache/graphify-rebuild.log`). The graph is correct; its
   mtime falls behind HEAD.
2. **HEAD moves without post-commit.** `git pull` and fast-forward merges of
   worktree branches fire `post-merge`, not `post-commit`. graphify installs no
   `post-merge` (0.9.72: `hook install` writes post-commit and post-checkout
   only), and its post-commit exits early in a worktree.
3. **Hooks not reachable.** The global `core.hooksPath` dispatcher forwards only
   the hook names it has symlinks for (`commit-msg`, `post-commit`, `pre-push`):
   graphify's `post-checkout` never runs. One registered repo (dotfiles) has no
   graphify hook at all.
4. **Bloated graph.** lazy-harness's `graph.json` is 417 MB: 239 376 of 258 581
   nodes come from `tmp/`, the repo-local TMPDIR introduced in #504. `tmp/` is
   ignored only by `~/.config/git/ignore`. Probe (scratch repo, graphify 0.9.72):
   graphify honours `.gitignore`, `.git/info/exclude` and `.graphifyignore`, and
   **not** the global excludes file. Every `lh knowledge graph update` run times
   out on it after 600 s, so the graph is stale permanently.

Refuted on the way: a full `graphify update <path>` *does* rewrite `graph.json`
on a docs-only commit. Only the incremental post-commit path leaves it.

The report itself over-counts the denominator: 742 sessions, of which ~340 made
no Bash/Grep call the hook could see.

## 2. Decisions

### 2.1 Freshness rule (one place, two consumers)

A new module `knowledge/graph_freshness.py` owns the answer. A graph is fresh
when `graph.json` mtime ≥ the committer time of the last commit on the main
checkout's HEAD that touched a file graphify treats as code:

```
git log -1 --format=%ct -- <one ':(glob)**/*<ext>' pathspec per extension>
```

- `CODE_EXTENSIONS` is a vendored copy of `graphify.detect.CODE_EXTENSIONS` at
  the installed version (graphify's venv is not importable from `lh`). Doctor
  compares it against the installed graphify and reports drift (§2.4).
- No code commit in history → fresh if `graph.json` exists.
- Result cached per repo keyed on the HEAD sha (`git rev-parse HEAD`), in
  `graphify-out/cache/lh-freshness.json`, so the hook pays the `git log` once
  per HEAD. The cache is advisory: unreadable or mismatched → recompute.
- Consumers: `pre_tool_use_graph_assist._evaluate` and
  `context_inject.graphify_section`. Both drop their inline `%ct` check. The
  banner text keeps its shape, with the date of the last code commit.
- Fail-soft: a git error yields "unknown", which both consumers treat as fresh —
  today's behaviour on a failed `git log`.

### 2.2 Self-repair (the harness fixes what it can, every run)

`lazy_harness/knowledge/graph_repos.py` exposes `ensure_repo(path) -> RepoRepair`
and is called by `lh knowledge graph add` and at the start of every
`lh knowledge graph update`, for every repo in scope. Idempotent; each action
reports `installed | already | failed: <why>`.

- **post-merge hook.** Marked block (`# lazy-harness graph-begin` /
  `# lazy-harness graph-end`) appended to `<git-common-dir>/hooks/post-merge`
  (created executable with a `#!/bin/sh` line if missing; another tool's content
  is preserved). The block exits 0 in a linked worktree (git-dir ≠ common-dir)
  and otherwise launches `lh knowledge graph update --repo <root>` detached,
  output appended to `<log dir>/graphify-post-merge.log`. It never fails the merge.
- **graphify hooks.** If `<common-dir>/hooks/post-commit` lacks
  `# graphify-hook-start`, run `graphify hook install` with cwd = repo root.
- **Ignored paths.** Directories git ignores **only** through the global excludes
  file are written into a marked block of `<common-dir>/info/exclude`. Source:
  `git ls-files --others --ignored --exclude-standard --directory`, filtered with
  `git check-ignore -v --no-index` to entries whose source is the global file
  (`git config --path core.excludesfile`, default `$XDG_CONFIG_HOME/git/ignore`).
  Git behaviour does not change (those paths are already ignored); graphify stops
  indexing them. The block is rewritten each run.
- `lh knowledge graph update --repo <path>` updates one repo (registered or not);
  without `--repo` it updates the scope below.

**Scope** = registered repos (`[knowledge.structure].repos`) ∪ discovered repos.
Discovered repos are repos with `graphify-out/graph.json` that appear as `repo`
in any profile's `graph_assist_metrics.jsonl`; they are persisted in
`<data dir>/graph-repos.json` (`{"discovered": [...]}`), never in `config.toml`,
which is rendered from a chezmoi template. `lh knowledge graph list` shows both,
marked.

### 2.3 Lazy-harness itself

`/tmp/` goes into the versioned `.gitignore`: since #504 `tmp/` is a repository
convention, not a personal preference. The graph is rebuilt from scratch after
merge (operational step, not code).

### 2.4 Doctor: what the harness could not fix

A `Graph repos` section in `lh doctor`, one line per repo in scope, from a
collector in `knowledge/graph_repos.py` (`collect_graph_health`):

- hooks: post-commit (graphify), post-checkout (graphify), post-merge (harness)
  present **and reachable**: when `core.hooksPath` is set for the repo, each
  name must exist in that directory, else `error: <name> not forwarded by
  core.hooksPath (<dir>)`;
- freshness by §2.1, with the age of the gap when stale;
- last `lh knowledge graph update` result for the repo, from
  `graphify-update.log` (`failed:` / timeout → warning with the line);
- ignored paths in the graph: top-level directories of node `source_file`s that
  `git check-ignore` matches → warning with the node count;
- `CODE_EXTENSIONS` drift against the installed graphify (one line, not per
  repo): run graphify's interpreter (`graphify-out/.graphify_python` or the
  shebang of `graphify` on PATH) with `-c` to print the set.

Healthy is one `ok` line per repo. The JSON output (`lh doctor --json`) carries
the same records.

### 2.5 Report denominator

`graph_assist_report` counts (a') and (a) over sessions with ≥ 1 hook evaluation
(any line in `graph_assist_metrics.jsonl` for the session), and adds a line
`stale share` = stale evaluations / evaluations in repos with a graph. The old
denominator stays as an informational line (`sessions (all)`). Kill thresholds
are unchanged.

### 2.6 Outside the harness

The dotfiles dispatcher gets `post-merge` and `post-checkout` symlinks to
`_dispatch` (separate PR in the dotfiles repo). Doctor (§2.4) is what proves it
landed on each machine.

## 3. Measurement

The 2026-10-09 read is recorded as **suspended, not killed**. Day 0 of a new
14-day window is the day this ships on the Mac and the agents CT (binary first:
merge, release, `uv tool install --reinstall`, grep site-packages, deploy).
Same §6 kill criteria of the graph-assist design, new denominator; calibration
frozen in the window. If a criterion trips with the graph fresh, the removal
goes ahead without a new investigation.

## 4. Out of scope

- graphify 0.9.72 installed against a 0.9.67 pin (ADR-023) — backlog.
- Codex control drop (74% → 7%) — backlog, read separately.
- Changing graphify's own post-commit.

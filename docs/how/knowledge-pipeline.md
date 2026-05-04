# How the knowledge pipeline works

The knowledge pipeline is the path from "a session just happened" to "six months from now I can ask a semantic question about it and get the right answer". It is the long-term arm of the memory model.

Four moving parts feed it:

- **`session-export`** — writes clean markdown sessions into `<knowledge.path>/sessions/`.
- **`compound-loop`** — writes distilled learnings into `<knowledge.path>/<compound_loop.learnings_subdir>/`.
- **QMD** (optional external tool) — indexes the knowledge tree semantically and exposes a `qmd query` interface.
- **The knowledge directory itself** — a plain filesystem tree the user can backup, grep, and open in any editor.

See [ADR-011](https://github.com/lazynet/lazy-harness/blob/main/specs/adrs/011-session-export-and-classification.md), [ADR-016](https://github.com/lazynet/lazy-harness/blob/main/specs/adrs/016-knowledge-dir-qmd-optional.md) for the design decisions. This page explains the mechanics.

## Directory shape

```
<knowledge.path>/               # from config.toml [knowledge].path
├── sessions/                   # written by session-export hook
│   ├── 2026-03/
│   │   ├── 2026-03-01-a1b2c3d4.md
│   │   ├── 2026-03-02-f5e6d7c8.md
│   │   └── ...
│   └── 2026-04/
│       └── 2026-04-13-9a8b7c6d.md
└── learnings/                  # written by compound-loop worker
    ├── 2026-03/
    │   └── 2026-03-15-file-based-queue-is-enough.md
    └── 2026-04/
        └── 2026-04-13-symlinks-vs-copies-for-profile-deploy.md
```

Every file is plain markdown with YAML frontmatter. No database, no lock files, no hidden index. You can `rsync -a` the whole directory to backup, and `rg` it directly if you do not have QMD.

## Session export in detail

Module: `src/lazy_harness/knowledge/session_export.py`. Called from the `session-export` built-in hook on every `Stop` event.

### What gets parsed from the JSONL

Claude Code stores each session as a JSON-per-line file:

```
{"type":"permission-mode", ...}         # line 1 — interactive marker
{"type":"system","cwd":"...", ...}      # system message with metadata
{"type":"user","message":{"content":"..."}, ...}
{"type":"assistant","message":{"content":[{"type":"text","text":"..."}]}, ...}
...
```

`_parse_session_jsonl` walks this and produces:

- `meta`: `{cwd, version, branch, timestamp}` from the first `system` record.
- `messages`: a list of `{role, text, timestamp}` dicts. Content extraction handles both string content (`"hello"`) and structured content (`[{"type":"text","text":"..."}]`).
- Sessions without a `permission-mode` first line return an empty message list — headless `claude -p` invocations are filtered at this gate.

### The interactive + length filter

A session is only exported if it has at least `min_messages` (default 4) messages after the interactive filter. Below that threshold, the export function returns `None` and the hook logs a skip.

### Classification rules

`_classify(cwd, rules)` returns `(profile, session_type)` based on the first rule whose pattern is a case-insensitive substring of `cwd`. Rules come from `[[knowledge.classify_rules]]` in `config.toml`; if the section is omitted, a built-in default list applies. See [ADR-028](https://github.com/lazynet/lazy-harness/blob/main/specs/adrs/028-classify-rules-configurable.md).

Default rules (used when nothing is declared):

```toml
[[knowledge.classify_rules]]
pattern = "lazymind"
profile = "personal"
session_type = "vault"

[[knowledge.classify_rules]]
pattern = "obsidian"
profile = "personal"
session_type = "vault"

[[knowledge.classify_rules]]
pattern = "/repos/lazy/"
profile = "personal"
session_type = "personal"

[[knowledge.classify_rules]]
pattern = "/repos/flex/"
profile = "work"
session_type = "work"
```

Override entirely by declaring your own block — for example, a consultant juggling client work:

```toml
[[knowledge.classify_rules]]
pattern = "/srv/clients/acme/"
profile = "client"
session_type = "acme"

[[knowledge.classify_rules]]
pattern = "/opt/research/"
profile = "research"
session_type = "experiment"
```

Order matters: the first matching pattern wins. Anything that matches no rule is classified as `("other", "other")`. Setting `classify_rules = []` opts out completely. The `profile` value also drives the `profile:` frontmatter field, so `context-inject` and other downstream filters can discriminate without scanning bodies.

### Project name extraction

`_extract_project` walks from `cwd` upward looking for the first `.git` directory and returns that directory's basename. If no git root is found, it falls back to `basename(cwd)`. This is how a session in `/Users/me/repos/lazy-harness/src/lazy_harness/hooks/` correctly identifies `lazy-harness` as the project.

There is a separate decoder, `_decode_project_dir`, that reverses Claude Code's directory-name mangling (`/` replaced with `-`). Because hyphens appear inside real directory names (`lazy-harness`, `lazy-claudecode`), naive `replace("-", "/")` is wrong — the decoder tries candidate splits against the real filesystem and picks the one that exists.

### The written file

Output path: `<knowledge.path>/sessions/YYYY-MM/YYYY-MM-DD-<short_id>.md` (`short_id` = first 8 chars of `session_id`).

Frontmatter:

```yaml
---
type: claude-session
session_id: 9a8b7c6d-1234-5678-90ab-cdef12345678
date: 2026-04-13 18:32
cwd: /Users/me/code/lazy-harness
project: lazy-harness
profile: personal
session_type: personal
branch: docs/restructure
claude_version: 1.2.3
messages: 47
---
```

Body: a sequence of `## User` and `## Claude` blocks with the extracted text, separated by blank lines. Tool-use blocks are intentionally not included — they would explode file size and are already captured by `pre-compact` for the sessions where file-touch history matters.

### Idempotence

`_existing_message_count` reads the frontmatter of any pre-existing export at the same path. If the on-disk copy already contains at least as many messages as the current JSONL, the export is skipped. This makes the hook safe to re-run — for instance after a resume, or during a `lh migrate` replay.

### Atomic writes

Every write goes through `_atomic_write`: write to `<dir>/.filename.tmp`, then `os.replace` to the target. A sync observer (iCloud, Dropbox) sees a single rename event rather than a window during which the file is partially written. Required whenever the knowledge directory lives under a synced folder — and it usually does.

## Learnings via compound loop

The compound-loop worker writes one markdown file per learning into `<knowledge.path>/<compound_loop.learnings_subdir>/` (default `<knowledge.path>/learnings/`). The structure is identical in spirit to session exports: year-month subdirectories, dated filenames, YAML frontmatter.

For the full flow, see [how the memory compound loop works](memory-compound.md). The key points for the pipeline:

- Learnings are **write-once**. Existing files are not overwritten. This is intentional — a learning is a snapshot of a specific session's insight, and editing it later changes the historical record.
- Deduplication happens in the LLM prompt, not in the filesystem. The worker passes the titles of the last 50 learnings into the prompt with explicit "do not generate semantic duplicates" instructions.
- Learnings carry a `scope` field (`universal | backend | infra | consulting`) that lets future queries slice by applicability.
- Weekly learnings review is a separate scheduled job that reads the learnings directory, surfaces near-duplicates, and prompts a human (or agent) to merge them. It is not part of the session-close pipeline.

## QMD integration

QMD is an external semantic search tool the framework integrates with but does not require. Module: `src/lazy_harness/knowledge/qmd.py`.

### How the framework calls QMD

One entry point: `run_qmd(action, collection, timeout)` — a thin wrapper around `subprocess.run(["qmd", action, "--collection", collection])`. Three convenience functions:

- `sync(collection)` — calls `qmd update`, which re-parses markdown files and updates indices.
- `embed(collection)` — calls `qmd embed`, which computes embeddings for newly synced files.
- `status()` — calls `qmd status`, which reports index health.

The `session-export` hook triggers `qmd update` automatically at the end of every exported session. Embedding is left to scheduled jobs — it is more expensive and does not need to happen synchronously.

### QMD availability and graceful degradation

Every call site starts with `shutil.which("qmd")`. If QMD is not installed, the framework **silently skips** the indexing step. All other parts of the pipeline still work: sessions are still exported to markdown, compound loop still writes learnings, `context-inject` still reads files directly. What you lose is cross-session semantic recall — `qmd query "circular imports python"` is the feature that is unavailable.

QMD can be installed later without re-running any framework command. The next `session-export` invocation will pick up the binary and start triggering `qmd update`.

### Collection configuration

QMD treats each indexed directory as a named collection. The framework's convention is that the knowledge directory is one collection, and the collection name is configured externally in QMD itself (not in `lazy-harness`). This keeps the framework unopinionated about QMD's config model — we call `qmd` the same way you would call it by hand.

## Querying the knowledge tree

With QMD:

```bash
qmd query "when did I last deal with symlinks on macOS"
# returns matching session/learning files with scores
```

Without QMD:

```bash
rg -l "symlink" ~/Documents/lazy-harness-knowledge/
# or
find ~/Documents/lazy-harness-knowledge -name '*.md' | xargs rg 'symlink'
```

Both work. One is faster and semantic; the other is always available and a good fallback.

Inside a session, Claude Code itself can also read these files as regular markdown — which means an agent with filesystem access can answer "what did we learn about X last quarter" by reading the learnings directory directly, without needing QMD as a tool.

## Backup and portability

Because the entire knowledge pipeline outputs to a single directory of markdown files:

```bash
# Backup
rsync -a ~/Documents/lazy-harness-knowledge /backup/location/

# Restore
rsync -a /backup/location/lazy-harness-knowledge ~/Documents/

# Git-version it
cd ~/Documents/lazy-harness-knowledge && git init
```

Moving to a new machine is "point `config.toml`'s `[knowledge].path` at the same directory and run `qmd update`". Nothing inside the framework holds state that can diverge from the directory contents.

## Other consumers of the same pipeline

QMD is the headline consumer of the knowledge tree, but it is not the only one. Two more pieces plug into the same on-disk artifacts and are worth understanding alongside the main pipeline.

### Engram persistence loop — JSONL mirrored into a per-project store

Module: `src/lazy_harness/knowledge/engram_persist.py`. Wired as a `Stop` hook (`engram-persist`) that runs **after** `compound-loop` writes its new entries. Design rationale: [ADR-029](https://github.com/lazynet/lazy-harness/blob/main/specs/adrs/029-engram-persist-deterministic-mirror.md).

While the JSONL pair (`decisions.jsonl` / `failures.jsonl`) is the file-of-record, [Engram](https://github.com/Gentleman-Programming/engram) is the agent's MCP-queryable view of the same data. The mirror keeps both views in sync without dual-writing from `compound-loop` itself — `compound-loop` only writes to JSONL, and `engram-persist` reads what is new and ships it to `engram save`.

Determinism comes from a **per-file byte cursor** stored alongside each project's memory dir, in `<memory_dir>/engram_cursor.json`:

```json
{
  "version": 1,
  "decisions_offset": 18234,
  "failures_offset": 5120,
  "updated_at": "2026-04-13T18:33:01Z"
}
```

Each run, for each kind:

1. Open the JSONL, seek to the stored offset.
2. Read whole lines until EOF. Partial lines are deferred (the writer might still be flushing the entry).
3. Decode each line as JSON; malformed lines advance the cursor and are counted as `skipped_malformed` — they are not retried.
4. Call `engram save <title> <json> --type <kind> --project <project_key> --scope project`. The project key is `git rev-parse --git-common-dir`'s basename, so worktrees collapse onto the parent repo.
5. **On success**, advance the cursor (atomic tempfile + `os.replace`).
6. **On failure**, leave the cursor untouched and stop processing this kind. The next run picks up from the same offset → at-least-once delivery, ordering preserved.

This produces three things on disk besides the Engram DB itself:

- `<memory_dir>/engram_cursor.json` — offsets per kind, atomically updated.
- `~/.claude/logs/engram_persist.log` — append-only error log (subprocess failures, missing binary).
- `~/.claude/logs/engram_persist_metrics.jsonl` — one record per run (run summary) plus one per slow `engram save` (≥ 500 ms). `lh doctor` reads this to classify the loop's health as `ok` / `warn` / `fail` based on age, failure rate, and cursor lag.

If `engram` is not on `PATH`, the loop logs a no-op and exits cleanly. Like every other external integration in the framework, this layer is opt-in: install `engram`, declare `[memory.engram].enabled = true`, the rest of the pipeline keeps working unchanged.

### Structural layer — Graphify

Module: `src/lazy_harness/knowledge/graphify.py`. Pinned to a specific Graphify version (see [ADR-023](https://github.com/lazynet/lazy-harness/blob/main/specs/adrs/023-graphify-code-structure.md)) so that an upgrade is an explicit decision rather than a transparent behaviour change.

[Graphify](https://github.com/safishamsi/graphify) is a tree-sitter–based code-structure indexer covering 25 languages. Where QMD answers "where did we discuss X across all my notes?", Graphify answers "what calls this function?", "explain this module", or "show me the dependency neighbourhood of this symbol". Its output is a JSON graph plus an interactive HTML report under `graphify-out/` **inside each repo**, not in the knowledge directory.

The harness's job is integration, not re-implementation:

- `is_graphify_available()` probes `shutil.which("graphify")`. If absent, every other piece of the framework keeps working — the structural layer is simply missing.
- `check_version()` parses `graphify --version` and compares against `PINNED_VERSION`. `lh doctor` surfaces a row when the installed version drifts from the pin.
- `run_graphify(action, target, timeout)` is a thin wrapper around `subprocess.run(["graphify", action, target])`, used by the `/graphify` skill in interactive sessions. The framework never invokes Graphify automatically — building the graph is up to the user (or a scheduled job, or a post-commit hook).

Configuration lives under `[knowledge.structure]` in `config.toml`:

```toml
[knowledge.structure]
engine = "graphify"
enabled = true
auto_rebuild_on_commit = false
version = "0.6.9"
```

`enabled = true` is what `lh deploy` reads to wire the Graphify MCP entry into each profile's `settings.json`. With `auto_rebuild_on_commit = true`, `lh deploy` also installs a `post-commit` git hook that triggers a graph rebuild on every commit — useful in actively-edited repos where stale graph data would mislead the agent.

Because `graphify-out/` is checked into the repo by convention, teammates and future sessions reuse the index without rebuilding. Adding it to `.gitignore` is a deliberate (if rare) choice for repos where build cost dominates over reuse.

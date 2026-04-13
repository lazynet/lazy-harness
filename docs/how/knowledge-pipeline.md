# How the knowledge pipeline works

The knowledge pipeline is the path from "a session just happened" to "six months from now I can ask a semantic question about it and get the right answer". It is the long-term arm of the memory model.

Four moving parts feed it:

- **`session-export`** — writes clean markdown sessions into `<knowledge.path>/sessions/`.
- **`compound-loop`** — writes distilled learnings into `<knowledge.path>/<compound_loop.learnings_subdir>/`.
- **QMD** (optional external tool) — indexes the knowledge tree semantically and exposes a `qmd query` interface.
- **The knowledge directory itself** — a plain filesystem tree the user can backup, grep, and open in any editor.

See [ADR-011](../architecture/adrs/011-session-export-and-classification.md), [ADR-016](../architecture/adrs/016-knowledge-dir-qmd-optional.md) for the design decisions. This page explains the mechanics.

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

### Classification heuristics

`_classify(cwd)` returns `(profile, session_type)`:

```
LazyMind, obsidian in path  →  ("personal", "vault")
/repos/lazy/ in path         →  ("personal", "personal")
/repos/flex/ in path         →  ("work", "work")
anything else                →  ("other", "other")
```

These are path heuristics, not config lookups. They are ported verbatim from the predecessor and preserve the calibration that proved useful across real-world projects. The assignment also drives `profile` frontmatter, so the context-inject hook can filter "last session for this project" without scanning bodies.

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
cwd: /Users/me/repos/lazy/lazy-harness
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

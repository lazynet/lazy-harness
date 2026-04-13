# ADR-016: Knowledge directory is a plain filesystem tree; QMD is an optional semantic index

**Status:** accepted
**Date:** 2026-04-13

## Context

Long-term memory across projects ([memory model](../../why/memory-model.md)) lives in a "knowledge directory" that the user points the framework at. The questions are:

- What is the shape of that directory? A database? A git repo? Just a folder?
- How does semantic search happen — which is where long-term memory earns its keep, because exact-grep is not enough to find "when did I last deal with circular imports"?
- Can a user run the framework without installing extra tooling, and still get most of the benefit?

Locking the answer to a specific index (Postgres + pgvector, Chroma, a vector DB service) would couple the framework to that tool forever. Declining to index anything would cut the most valuable feature.

## Decision

**The knowledge directory is a plain filesystem directory of markdown files. QMD is the preferred semantic indexer, but it is strictly optional and lives behind `shutil.which("qmd")` checks.**

Shape of the directory (`<knowledge.path>`):

```
<knowledge.path>/
├── sessions/                     # Session exports — see ADR-011
│   └── YYYY-MM/
│       └── YYYY-MM-DD-<id>.md
├── learnings/                    # Distilled learnings — written by compound loop
│   └── YYYY-MM/
│       └── YYYY-MM-DD-<slug>.md
└── (anything else the user drops in)
```

Every file is plain markdown with YAML frontmatter. There is no index file, no database, no lock file. The directory is trivially backupable, version-controllable, and openable in any text editor.

Wiring to QMD (`src/lazy_harness/knowledge/qmd.py`):

- `is_qmd_available()` — probe via `shutil.which("qmd")`.
- `run_qmd(action, collection=None, timeout=300)` — generic wrapper around `subprocess.run(["qmd", action, ...])`.
- `sync`, `embed`, `status` — thin convenience wrappers.
- Every caller of QMD in the framework checks availability first and degrades to a no-op log line if QMD is missing. The `session_export` hook only triggers `qmd update` after a successful export and only if `qmd` is on PATH.

Config (`[knowledge]` section):

```toml
[knowledge]
path = "~/Documents/lazy-harness-knowledge"

[knowledge.sessions]
enabled = true
subdir  = "sessions"

[knowledge.learnings]
enabled = true
subdir  = "learnings"

[knowledge.search]
engine = "qmd"         # Placeholder for future alternatives
```

## Alternatives considered

- **Built-in vector index inside the framework.** Would lock us to an embedding model, ship it with the package, and force every user to re-index on upgrade. Rejected on maintenance grounds.
- **SQLite + FTS5 for full-text only.** Works without QMD but misses semantic recall (the whole point of long-term memory is "find the thing I do not remember the keyword for"). Kept as a future fallback option — nothing in the framework prevents adding an `engine = "sqlite-fts"` branch later.
- **Store sessions as JSONL or structured data instead of markdown.** Forces a custom viewer and breaks the "open it in anything" property that makes this directory useful outside of `lh`. Rejected.
- **Require QMD as a hard dependency.** Makes a trivially-installable framework hard to install. The user who only wants profiles + hooks should not have to install a search tool to get started.
- **Pipe sessions to a hosted service (OpenAI embeddings, Pinecone, etc.).** Hard no on privacy. Personal agent history is exactly the data you do not want leaving the machine by default.

## Consequences

- The framework works fully without QMD. Sessions still export, compound loop still runs, memory still accumulates. What QMD adds is cross-session semantic recall via `qmd query`, and the lack of it downgrades that one feature while leaving everything else intact.
- QMD can be installed or removed at any time. The next `session_export` invocation will trigger `qmd update` if the binary appeared; if it disappeared the export proceeds and logs the missing binary. No state inside the framework tracks "QMD is enabled" — the filesystem probe is the source of truth.
- The `[knowledge.search]` config field exists specifically to allow a second engine later. Today the only value is `qmd`; the framework code does not branch on it yet, but the seam is reserved.
- Atomic writes via tempfile + `os.replace` are used everywhere the knowledge directory is written to. This is the same constraint that matters for iCloud/Dropbox sync paths — the knowledge directory often lives under one of them.
- Backup is trivial: `rsync -a <knowledge.path>` captures everything. Restore is `rsync` in the other direction. No database dump, no schema migration.
- The cost of optionality is one extra config field (`[knowledge.search].engine`) and one `is_qmd_available` check at each QMD call site. Cheap insurance.

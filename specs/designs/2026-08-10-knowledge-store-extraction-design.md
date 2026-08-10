# Knowledge store extraction: agent output leaves the vault

**Status:** proposed
**Date:** 2026-08-10
**Related:** `lazy-ai-tools` (`lazy-vault`, `lazy-shared-config`), `lazy-hermes` (Marge's soul), `~/.config/qmd/index.yml`

Extract agent-generated sessions and learnings out of the Obsidian vault into a
dedicated multi-writer git repository, with a self-describing contract owned by
the harness.

## Problem

Opening the vault on mobile is slow. The cause was isolated empirically:
disabling the Dataview plugin makes startup near-instant, so the cost is
Dataview's index over every `.md` file, not iCloud sync.

Measured on 2026-08-10:

| Scope             | Files |
|-------------------|-------|
| Vault total       | 3753  |
| `Meta/sessions`   |  833  |
| `Meta/learnings`  | 2325  |
| Curated remainder |  595  |

84% of the indexed corpus is agent output that no human curates and that
Obsidian never needs to render.

These counts are a moving snapshot — the two agent directories grew by 13 files
during the hour this design was written. Every number in this document is
illustrative of proportion, not a checksum. Verification must take its own
baseline at migration time (see "Verification").

Two mitigations were evaluated and rejected:

- **`userIgnoreFilters`** — already configured for `Meta/sessions` and
  ineffective. It is a presentation-layer filter; Dataview still reads from the
  metadata cache.
- **Dotfolder rename** — Obsidian honours it, but iCloud keeps replicating the
  transcripts to every device.

### Secondary effect: the corpus is not searchable

QMD indexes `LazyMind/Meta` as a single collection, `lazy-lazymind-meta`, at
3181 documents. Marge's soul file (`lazy-hermes/souls/marge.md:123`) documents
the consequence: that collection is 82% of the entire corpus and almost all of
it is session residue, so an unscoped query returns transcripts and little
else. Distilled learnings and raw session logs are corpora of very different
value that currently cannot be queried apart.

### What this design does not fix

The vault is itself a git repository (`lazynet/LazyMind`, auto-committed every
30 minutes) living inside iCloud. Of its 121M on disk, 51M is `.git`.

Removing `Meta` drops the working tree from ~70M to ~29M, but total on-disk
size only falls to ~80M. The `.git` directory does not shrink without
rewriting history, and `git filter-repo` is explicitly out of scope. Vault
size in iCloud is a separate problem whose target is `.git`, not `Meta`.

## Decision

A dedicated repository, `lazy-knowledge`, at `~/repos/lazy/lazy-knowledge`,
with a clean history cut: fresh `git init`, old history stays in the LazyMind
repository. No `filter-repo`.

### Two roots, explicitly separated

```
VAULT_ROOT      ~/…/LazyMind/                   curated knowledge, Obsidian, iCloud
KNOWLEDGE_ROOT  ~/repos/lazy/lazy-knowledge/    agent output, git, multi-writer
```

`~/repos/lazy` is a `[profiles.lazy]` root. Profile roots only drive
cwd-based profile resolution and `.envrc` deployment
(`core/profiles.py:58`, `core/envrc.py`), so placing the repo there is benign
and yields the correct profile for any session opened inside it.

### The repository describes itself

`knowledge.toml` at the repository root:

```toml
[knowledge]
version   = 1
sessions  = "sessions"
learnings = "learnings"
```

Layout:

```
lazy-knowledge/
├── knowledge.toml
├── .gitignore
├── README.md
├── sessions/YYYY-MM/YYYY-MM-DD-<session_id[:8]>.md
└── learnings/YYYY-MM/YYYY-MM-DD-<slug>-<host>.md
```

Consumers resolve exactly one thing — the root — with this precedence:

1. `LAZY_KNOWLEDGE_ROOT` environment variable
2. the consumer's own configuration
3. default `~/repos/lazy/lazy-knowledge`

Structure is never declared in configuration; it always comes from the marker.

This split is the core of the design. *Where the root lives* is environmental
and differs per machine. *How it is structured inside* is global and must be
identical everywhere. Conflating them is what allowed the case bug below to
exist.

`version` is validated on read. An unknown version is a hard failure with a
clear message, never a silent fallback — a missing field read as `""` would
land files at the repository root.

### Rejected alternatives for the contract

**CLI as the contract** (`lh knowledge path --kind learnings` via subprocess).
Rejected: it makes `lazy-ai-tools` depend on `lh` being installed and on
`PATH`. The headless Linux instance would need the whole harness just to run
`learnings-review`, and hooks in this harness have already failed by not
inheriting the interactive shell's `PATH` — the reason
`binary = "/opt/homebrew/bin/engram"` is pinned in `config.toml`.

**Derived contract file** (harness generates `~/.config/lazy-knowledge/contract.toml`
from its own config). Rejected: a derived artifact goes stale whenever
`config.toml` changes without regeneration — precisely the silent drift this
migration exists to eliminate.

`lh knowledge path` is still added, as a convenience for humans and shell
scripts. It is not the mechanism by which `lazy-ai-tools` resolves paths.

### The case bug

The real directory is `Meta/learnings` (lowercase); configuration declares
`Learnings` in three places. This works only because APFS is case-insensitive
and breaks on Linux, which is the target platform for the headless instance.

The marker declares the case once, and it is the only declaration. The
duplicated declarations are deleted rather than corrected.

## Harness ownership

| Command | Behaviour |
|---|---|
| `lh knowledge init` | create the repository, write `knowledge.toml`, `git init` |
| `lh knowledge path --kind sessions\|learnings\|root` | print the absolute path |
| `lh knowledge push` | commit, `pull --rebase`, push — also the scheduler job |

`[knowledge]` configuration changes:

| Before | After |
|---|---|
| `path = ".../LazyMind/Meta"` | `root = "~/repos/lazy/lazy-knowledge"` |
| `sessions.subdir = "sessions"` | deleted — the marker declares it |
| `learnings.subdir = "Learnings"` | deleted — kills the case bug |
| `compound_loop.learnings_subdir = "Learnings"` | deleted |
| `compound_loop.lazymind_dir = ".../LazyMind"` | **unchanged** |

`lazymind_dir` stays pointed at the vault because `resolve_prj_md()`
(`knowledge/compound_loop.py:988`) reads `1-Projects/` to annotate `PRJ-*.md`
files. It is the proof that both roots genuinely coexist: the compound loop
reads from the vault and writes to the knowledge store.

## Data flow

Three producers. None of them touches git.

```
Mac ─┬─ Stop hook → session-export ─────────► sessions/YYYY-MM/
     └─ Stop hook → compound-loop (bg, flock)
                       └─ worker ───────────► learnings/YYYY-MM/

Linux ── its own hooks ─────────────────────► both directories

scheduler (every 15 min, per machine)
     └─ lh knowledge push ──► add · commit · pull --rebase · push
```

Keeping git out of the producers means writes survive a broken transport: with
no network, no credentials, or a dead remote, files still land and the next
cycle picks them up. No Stop hook ever blocks on a network syscall.

The push is a scheduler job rather than a hook step for a second reason: the
compound-loop worker is decoupled via `fcntl.flock`
(`knowledge/compound_loop_worker.py:119`) and may write its learning minutes
after the hook returned. A hook-time push would systematically miss it.

`lh knowledge push` remains available manually for pushing immediately before
switching machines.

### Why concurrency converges

Every write creates a new file; nothing is ever modified. A `pull --rebase`
over commits that only add files at distinct paths cannot conflict.

The knowledge store is a degenerate CRDT: a set of immutable files with unique
keys. The union of two replicas is always well-defined and order-independent.
This is why git suffices as transport and no coordination is needed.

The only possible conflict is add/add — two machines creating the same path.

### Filename collision

`knowledge/compound_loop.py:878`:

```python
filepath = learnings_subdir / f"{date_str}-{_slugify(title)}.md"
if filepath.exists():
    continue          # local dedup
```

A learning's name is date plus title slug. Two machines working the same day on
similar topics produce the same path with different content, and the `exists()`
guard does not protect against it — each machine sees only its local copy until
it pulls.

**Fix:** append the origin host, `YYYY-MM-DD-<slug>-<host>.md`. This eliminates
add/add by construction and preserves intra-machine dedup exactly, since the
host is constant within a machine. It is what guarantees key uniqueness, and
therefore the CRDT property above.

`<host>` is `platform.node()` reduced to its first dot-separated label, slugified
to `[a-z0-9-]` — `Some-Laptop.local` becomes `some-laptop`. It is
resolved once per process. If it resolves empty, writing fails loudly rather than
falling back to an unsuffixed name, since an unsuffixed name is exactly the
collision this prevents.

Sessions do not need it: `session_id[:8]` is already a UUID.

### One push cycle

1. `flock` on `.push.lock` in the repository. Held → exit 0 silently.
2. Validate `knowledge.toml`. Unknown `version` → non-zero exit, clear message,
   nothing touched.
3. No changes and no pending commits → exit 0.
4. `add -A`, then `commit -m "knowledge: <n> sessions, <m> learnings (<host>)"`.
5. `pull --rebase`. On conflict: `rebase --abort`, log, non-zero exit.
   **Never auto-resolve.**
6. `push`. On failure the commits stay local and the next cycle retries.

Output goes to `~/.config/lazy-harness/logs/knowledge-push.log` through the
existing `core/logfile.py`, as `knowledge sync` and `context-gen` already do.

### Failure modes

| Failure | Consequence | Data loss |
|---|---|---|
| No network at push | local commits accumulate | no |
| Rebase conflicts | job stops, stays pending, logged | no |
| Lock held | cycle skipped | no |
| Invalid marker | loud failure, no write | no |
| Linux never pulls | stale reads | no |

### QMD

Each machine indexes its own local clone. Two new collections replace the
`Meta` half of `lazy-lazymind-meta`:

| Collection | Path | Docs |
|---|---|---|
| `lazy-knowledge-sessions` | `~/repos/lazy/lazy-knowledge/sessions` | 833 |
| `lazy-knowledge-learnings` | `~/repos/lazy/lazy-knowledge/learnings` | 2325 |
| `lazy-lazymind-meta` | unchanged path, now Findings + Weekly-Reviews | 93 |

A single `lazy-knowledge` collection was rejected: it reproduces the exact
scoping problem Marge documents, only at a different path. Splitting makes the
distilled corpus reachable without the raw one, which is impossible today.

The existing `qmd-sync` scheduler job needs no change; only `index.yml` does.

## Consumer inventory

Verified by grep across `lazy-harness`, `lazy-ai-tools`, `lazy-hermes`, the
deployed profiles, and the vault.

### Breaks at runtime

| Reference | Change |
|---|---|
| `lazy-ai-tools/shared/lazy-shared-config/.../loader.py:48` | delete `VaultSchema.learnings`; add `KnowledgeConfig(root, sessions, learnings)` |
| `lazy-ai-tools/.../learnings_review.py:349` | `knowledge.root / knowledge.learnings` |
| `lazy-ai-tools/.../learnings_review.py:131,140` | `relative_to(knowledge_root)` |
| `lazy-ai-tools/.../learnings_review.py:366` | `_scan_learnings` signature |

The `relative_to` pair is the deepest coupling and was not in the original
inventory. `_scan_learnings(learnings_dir, vault_root, ref_date)` computes
`f.relative_to(vault_root)` to identify each learning. `relative_to` is only
defined when one path descends from the other, so the moment learnings stop
living under the vault it raises `ValueError: not in the subpath` and the
command dies. Introducing `KnowledgeConfig` without fixing this leaves a crash
in place.

`VaultSchema.learnings` is deleted rather than repointed. Leaving it aimed at
anything recreates the two-declarations problem this design exists to remove.

That `rel_path` is also injected into prompts as a learning's identifier
(`"new_learning": "relative/path/to/new.md"`) and persisted into
`LR-YYYY-Www.md` reports. Historical reports carry `Meta/learnings/…` prefixes
while new ones carry `learnings/…`. Non-blocking, but a documented
discontinuity.

### Breaks silently (configuration)

- `~/.config/lazy-harness/config.toml` — `[knowledge] path`, both `subdir`
  keys, `compound_loop.learnings_subdir`
- `~/.config/qmd/index.yml` — the `lazy-lazymind-meta` collection

### Goes stale (prose)

- `lazy-hermes/souls/marge.md:108-134` and `lazy-hermes/marge/SOUL.md` — the
  collection table with per-collection counts, and the paragraph asserting
  `lazy-lazymind-meta` is 82% session residue. After the migration the advice
  inverts: `lazy-knowledge-learnings` for distilled knowledge,
  `lazy-knowledge-sessions` for raw transcripts.
- `LazyMind/CLAUDE.md:45,83`
- `lazy-harness/specs/backlog.md:15`
- `lazy-ai-tools` docstrings: `cli.py:206`, `learnings_review.py:1,343`

### Deliberately untouched

- `lazy-harness/specs/archive/**` (3 files) — frozen by repository rule
- `lazy-hermes/docs/superpowers/{specs,plans}/2026-08-10-*` — historical
  artifacts of a different design
- `~/.claude-lazy/projects/**/*.jsonl` — session transcripts
- `lazy-ai-tools/tools/model-eval/results/*.json` — historical evaluation
  results
- No wikilinks point at `Meta/Learnings` or `Meta/sessions` anywhere in the
  vault; `Meta/Weekly-Reviews` references are inside backticks, so they are
  text and not links. There are no broken links to repair.

### Prompts stay in the vault

The four `learnings_review*.md` prompts in `.lazy-vault/prompts/` receive
`$learnings_path` by injection and hard-code nothing. They are vault
maintenance prompts with no technical coupling to the data location. Only the
injected value changes.

## Migration

```
Phase 0  create repo · cp -a the data · verify counts      vault untouched
Phase 1  harness: code + configuration                     writes go to the new repo
Phase 2  lazy-ai-tools: read from the contract
Phase 3  qmd collections · marge · CLAUDE.md
Phase 4  full verification
Phase 5  delete from the vault                             point of no return
```

Two rules:

**`cp -a`, never `mv`.** Through phase 4 the data exists in both places.
Rolling back phases 0-4 means reverting configuration without touching a single
data file.

**Phase 5 runs last and alone,** only with phase 4 green.

Between phases 1 and 2 there is a window where the harness writes to the new
repo while `lazy-ai-tools` still reads the vault. `learnings-review` does not
crash but sees frozen data. The review is weekly, so a window under a week is
invisible; the phases should still run back to back.

## Rollback

| Phase | Undo | Cost |
|---|---|---|
| 0 | `rm -rf` the repository | none |
| 1 | revert `config.toml`; `cp -a` new files back to the vault | minutes |
| 2 | revert the `lazy-ai-tools` commit | none |
| 3 | revert `index.yml`, re-run `qmd sync` | one reindex |
| 4 | nothing to undo — verification is read-only | — |
| 5 | `git revert` in LazyMind | minutes |

Phase 5 is recoverable precisely because there is no `filter-repo`: the
deletion is an ordinary commit and the content remains in the vault's history.
That is the upside of the 51M `.git` that does not shrink.

## Verification

### QMD — the arithmetic must balance

On-disk composition of `Meta` at design time:

```
lazy-knowledge-sessions     833
lazy-knowledge-learnings   2325
lazy-lazymind-meta           93   (58 Findings + 32 Weekly-Reviews + 3 loose)
                           ────
                           3251
```

`index.yml` reports a cached 3181 for `lazy-lazymind-meta` — 70 short of disk,
because the index lags the corpus. Do not migrate against that number. Run a
baseline `qmd sync` **first**, record the three post-sync counts, and assert
that `sessions + learnings + meta` after the split equals the pre-split `meta`
total. The invariant is that no document is lost in the split; the specific
integers will have moved by then.

### Harness — one real end-to-end session

1. Run a short session in any repository, then close it.
2. `sessions/2026-08/*.md` appears in the new repository.
3. Wait for the worker; `learnings/2026-08/*-<host>.md` appears.
4. `git log` in `lazy-knowledge` shows the scheduler's commit.
5. **Nothing new** under `LazyMind/Meta/`.

Step 5 is what proves no writer is still attached to the old path.

### lazy-vault

Run `learnings-review` in dry-run against the new root. Its total must match
the file count in `lazy-knowledge/learnings` (2325 at design time). It emits
`LR-YYYY-Www.md` into `Meta/Weekly-Reviews/` — which stays in the vault — and
the `rel_path` values inside begin with `learnings/` rather than
`Meta/learnings/`.

### Obsidian

`find … -name '*.md' | wc -l` over the vault must equal the pre-migration total
minus the two agent directories — **595** at design time. Then open the vault on
the iPhone with Dataview **enabled**. The original diagnosis was empirical, so
its verification must be too: a file count that drops without a startup that
improves means the diagnosis was wrong, not that the migration failed.

Expect ~80M on disk, not 30M. See "What this design does not fix".

## Testing

TDD is non-negotiable in this repository; tests come first.

- `contract.py` — valid parse, unknown version, missing marker, missing field.
  All four fail loudly; none returns `""`.
- `git_push.py` — lock held → no-op; no changes → no-op; rebase conflict →
  `abort` plus non-zero exit; push failure → commits remain local.
- Host-suffixed naming — two hosts, same title, same day → two distinct paths.
- `config.toml` migration — old shape with `path` and `subdir` keys produces
  the new shape with `root`.
- **lazy-ai-tools** — a test with `learnings_dir` outside the vault. It fails
  today with `ValueError` and is the test that justifies the `KnowledgeConfig`
  refactor.

# ADR-034: OKF producer — export curated knowledge as an Open Knowledge Format bundle

**Status:** proposed
**Date:** 2026-06-29
**Supersedes:** —
**Superseded by:** —
**Related:** ADR-016 (knowledge-dir-qmd-optional), ADR-021 (async-response-grading),
ADR-027 (memory-stack-overview), ADR-032 (agent-adapter-completeness),
ADR-033 (llm-backend-abstraction)

## Context

The framework's curated long-term memory ([memory model](../../why/memory-model.md))
is already a tree of markdown files with YAML frontmatter — one concept per file,
written by the compound loop (ADR-021) into `<knowledge.path>/learnings/`. This is
the same pattern that Google Cloud published in June 2026 as the **Open Knowledge
Format (OKF) v0.1**: a vendor-neutral spec where a *bundle* is a directory of
markdown files, each file is one *concept*, every file carries YAML frontmatter
whose only required field is `type`, and concepts link to each other with plain
markdown links to form a relationship graph. OKF has no runtime, no SDK, and no
compression — "just files, just markdown, just YAML frontmatter."

Two facts make this worth acting on:

1. **Convergent format.** The harness invented the LLM-wiki pattern for its own
   memory; OKF standardises the same pattern. Our `learnings/` files are roughly
   90% of an OKF bundle already — they differ in field names and lack the explicit
   `type` field and the cross-concept link graph.

2. **Directional fit.** ADR-032 and ADR-033 are deliberately decoupling the
   framework from any single agent CLI or inference provider. Curated memory that
   only a Claude-Code-shaped reader understands is a gap in that story. An OKF
   bundle is readable by *any* agent — it renders on GitHub, mounts on any
   filesystem, and needs no bespoke tooling. Speaking OKF makes the harness's
   accumulated knowledge portable and publishable.

The scope question — should the harness *produce* OKF, *consume* it, or both —
was decided as **producer**. Consuming external OKF bundles as injectable context
is a separate, later decision and is explicitly out of scope here.

The open design questions this ADR resolves: which layer is exported, how the
field mapping works, how cross-concept links are materialised, and whether OKF is
adopted natively or as an export transform.

## Decision

**Add an OKF *export* path that transforms the curated `learnings/` layer into a
conformant OKF v0.1 bundle. Export-only, non-invasive: the compound loop's write
path is unchanged. The episodic layer is never exported.**

A new module `src/lazy_harness/knowledge/okf.py` and a CLI command
`lh knowledge export-okf <dest>` produce the bundle on demand.

### What is exported, and what is not

| Source artifact | Exported? | Reason |
|---|---|---|
| `learnings/**/*.md` | **Yes** | Atomic, durable, curated concepts with rich frontmatter. The natural OKF concept set. |
| `MEMORY.md` + per-project `memory/` | Deferred to v2 | Per-project ⇒ many bundles. Global `learnings/` is one publishable bundle; start there. |
| `decisions.jsonl` / `failures.jsonl` / `grades.jsonl` | **No** | OKF is *semantic/conceptual* knowledge. Append-only episodic logs are a different kind; projecting them as concepts would corrupt the bundle's meaning. |
| `handoff.md`, `insights/` | **No** | Ephemeral session-scoped state, not durable knowledge. |
| `sessions/` exports | **No** | Raw transcripts, not curated concepts. |

### Field mapping (`learnings/` → OKF frontmatter)

| OKF field | Source | Rule |
|---|---|---|
| `type` *(required)* | `scope` | `universal` / `backend` / `infra` / `consulting` become the `type`. Gives OKF consumers a real routing axis. Falls back to `type: learning` if `scope` is absent. |
| `title` | `title` | Verbatim. |
| `description` | first sentence of the `## Learning` section | Generated; `learnings/` has no `description` field today. |
| `tags` | `tags` | Verbatim. |
| `timestamp` | `origin_session` | Already ISO-8601-ish; normalised to a full ISO-8601 datetime. |
| `resource` | — | Omitted in v1. Candidate later: a URI to the originating session export. |
| *(extension fields)* | `status`, `origin`, `origin_session`, `deprecated_by`, `deprecated_on`, `deprecated_reason` | Preserved verbatim. OKF requires consumers to keep unknown fields, so provenance and deprecation survive the round-trip. |

### Concept IDs

OKF defines a concept's ID as its bundle-relative path minus `.md`. Today
`learnings/` is laid out by date (`YYYY-MM/YYYY-MM-DD-<slug>.md`), which makes for
ugly, unstable IDs. The export flattens to `<slug>.md` at the bundle root, so the
concept ID is the human-meaningful `<slug>`. Slug collisions (same slug in two
months) are resolved deterministically by appending the origin date.

### Cross-concept links (in v1)

Links are the one genuinely new capability OKF brings that the harness does not
have today — the audit confirmed `learnings/` files are independent artifacts with
no parsing or validation of inter-file relationships. v1 materialises links from
two best-effort sources, both optional:

1. **Body wikilinks.** A `[[slug]]` token in a learning's markdown body is
   rewritten to a bundle-relative OKF link `[<title>](/<slug>)`. This lets the
   compound loop (or a human curating `learnings/`) assert relationships inline
   using a syntax the harness already documents elsewhere.

2. **Frontmatter `related`.** An optional `related: [slug, slug]` list is emitted
   as a trailing `## Related` section of bundle-relative links in the concept body.

Unresolved targets (a `[[slug]]` or `related` entry with no matching concept) are
**not fatal** — OKF requires consumers to tolerate broken links — but the export
logs each one so the curator can fix dangling references. Because relationships are
opt-in, early bundles will have few links; the graph densifies as the compound
loop starts emitting `related`/wikilinks. v1 ships the *machinery*; populating it
richly is incremental.

### Reserved files

- `index.md` (reserved by OKF) is generated: concepts grouped by `type`, each a
  bundle-relative link. This replaces the harness-specific `MEMORY.md` index, which
  is not part of the `learnings/` layer anyway.
- `log.md` (reserved) is omitted in v1.

### Conformance

The export validates its own output before writing the bundle: every emitted file
must have parseable frontmatter and a non-empty `type`. A `--check` flag runs the
validator against an existing bundle without rewriting it. Writes are atomic
(tempfile + `os.replace`), consistent with ADR-016, because the destination may
live under a synced directory.

### Trigger

v1 is **on-demand only**: `lh knowledge export-okf <dest>`. A Stop/SessionEnd hook
that refreshes the bundle automatically is a later refinement (it has the same
staleness trade-off as any snapshot and is not needed to prove the format).

## Alternatives considered

- **Adopt OKF natively — make the compound loop write OKF directly instead of the
  current `learnings/` format.** Deferred, not rejected. It is the cleaner end
  state (one format, no snapshot drift), but it touches the compound loop's write
  path, the `learnings/` frontmatter schema, and every reader of that layer. The
  export transform proves the mapping and produces a real artifact with zero risk
  to the existing pipeline. Native adoption becomes a follow-up ADR once the export
  mapping is validated in practice.

- **Export the per-project `memory/` layer too (or instead).** Deferred to v2.
  Per-project memory yields one bundle per project, raising questions about bundle
  identity and aggregation that the global `learnings/` layer does not. Global
  first; per-project once the single-bundle path is proven.

- **Project the episodic JSONL logs as OKF concepts (`type: decision`,
  `type: failure`).** Rejected. OKF concepts are durable, curated knowledge; the
  JSONL logs are an append-only temporal record. Materialising every log line as a
  concept would flood the bundle with low-value, redundant nodes and blur the line
  OKF draws between a knowledge bundle and an event log (which OKF parks in the
  reserved `log.md`, not in concepts).

- **Use OKF as the format for session exports (ADR-011).** Rejected. Session
  exports are raw transcripts, not concepts. Forcing them into a concept-per-file
  shape misrepresents what they are.

- **Wait for OKF to stabilise past v0.1 before producing it.** Rejected. The spec's
  conformance surface is tiny (parseable frontmatter + non-empty `type`) and
  explicitly designed to tolerate unknown fields and broken links. The cost of
  tracking a v0.x change is low, and producing a bundle now is the cheapest way to
  discover whether the format actually serves the harness's knowledge.

## Consequences

**Positive**

- The harness's curated knowledge becomes portable: any agent or human reads the
  bundle with no harness-specific tooling. This closes the agent-coupling gap that
  ADR-032/033 leave open at the data layer.
- The relationship graph between learnings becomes explicit and machine-consumable
  for the first time — today those relationships are not represented at all.
- Non-invasive: the compound loop, the JSONL logs, and every existing reader are
  untouched. Pure additive surface (`okf.py` + one CLI command).
- The bundle is publishable (renders on GitHub, ships as a tarball) and trivially
  diff-able and backupable, inheriting ADR-016's "just files" properties.

**Negative**

- Snapshot drift: an on-demand export can go stale relative to `learnings/`. A
  refresh hook (deferred) closes this, at the cost of a staleness trade-off.
- Two representations of the same knowledge coexist (`learnings/` + the exported
  bundle) until/unless native adoption lands. This is the explicit price of the
  non-invasive transform.
- Link density is low initially: relationships only exist where a curator or the
  compound loop has written wikilinks/`related`. The graph is opt-in and grows over
  time rather than arriving full.
- A `type` vocabulary derived from `scope` is a v1 choice that may need revisiting
  if the scope set changes or proves too coarse for useful routing.
- OKF v0.1 may evolve; the producer may need adjustment to track spec changes.
  Mitigated by the spec's deliberately minimal conformance surface.

## Implementation

Recommended sequence (each step independently testable; follows strict TDD per
ADR-015):

1. `okf.py`: pure helpers — `concept_id_from_path()` (flatten + collision rule)
   and `map_frontmatter()` (`learnings/` frontmatter → OKF frontmatter). Pure
   functions, table-driven tests.
2. `okf.py`: `rewrite_wikilinks()` — `[[slug]]` → `[title](/slug)`, plus the
   `related` → `## Related` section builder. Unresolved-target logging.
3. `export_okf(learnings_dir, dest)` orchestrator: read concepts, map, resolve
   links, validate conformance, atomic-write each concept, generate `index.md`.
4. `--check` conformance validator over an existing bundle.
5. CLI `lh knowledge export-okf <dest> [--check]` wired into the `knowledge`
   command group, degrading cleanly when `learnings/` is empty or absent.
6. (Later) `lh doctor` surface + docs page; (later) refresh hook; (later) native
   adoption ADR and per-project `memory/` bundle.

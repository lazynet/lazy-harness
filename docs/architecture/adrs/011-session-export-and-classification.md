# ADR-011: Session export produces typed markdown with project/profile classification

**Status:** accepted
**Date:** 2026-04-13

## Context

Claude Code stores every session as a JSONL transcript under `~/.claude/projects/<encoded-cwd>/<session-id>.jsonl`. That format is fine for the agent — it is a linear event log, not a human artefact — but it is useless for:

- Semantic search across months of history
- Weekly reviews that scan multiple projects
- Grepping for "when did I work on X?"
- Feeding the knowledge directory into QMD for vector indexing

What we want is a clean markdown export per session, with frontmatter the indexer can query, landing in a single knowledge tree that spans every project and every profile.

## Decision

Built-in `Stop` hook at `src/lazy_harness/hooks/builtins/session_export.py`, backed by a pure export function at `src/lazy_harness/knowledge/session_export.py`. The hook locates the most recent session JSONL for the current `cwd`, calls `export_session`, triggers a QMD re-index, and always exits 0.

The `export_session` function is the load-bearing piece:

1. **Parse the JSONL.** `_parse_session_jsonl` walks lines, separating metadata (first `system` record) from messages (`user` / `assistant` events). It extracts text from both string-valued and structured (`[{"type": "text", "text": ...}]`) content. Sessions without a `permission-mode` record are treated as non-interactive and produce zero messages.
2. **Interactive filter.** Only sessions that have at least `min_messages` (default 4) interactive messages are exported. Headless `claude -p` invocations, subagent dispatches, and trivial prompts are skipped at this gate.
3. **Classify the session.** `_classify(cwd)` returns `(profile, session_type)` using path heuristics:
   - `LazyMind` / `obsidian` in the path → `(personal, vault)`
   - `/repos/lazy/` → `(personal, personal)`
   - `/repos/flex/` → `(work, work)`
   - otherwise → `(other, other)`
4. **Extract the project name.** `_extract_project` walks parents looking for a `.git` directory; the repo root's basename is the project. Falls back to the `cwd` basename if no git root is found.
5. **Decode the Claude Code project dir name.** `_decode_project_dir` reverses Claude Code's `/` → `-` mangling, trying candidate splits against the filesystem (so `lazy-claudecode` is recovered correctly instead of becoming `lazy/claudecode`).
6. **Write the file.** Output path is `<knowledge>/sessions/YYYY-MM/YYYY-MM-DD-<short-id>.md`, with frontmatter:
   ```yaml
   type: claude-session
   session_id: <full-id>
   date: YYYY-MM-DD HH:MM
   cwd: <absolute path>
   project: <repo name>
   profile: <personal|work|other>
   session_type: <personal|work|vault|other>
   branch: <git branch at session time>
   claude_version: <agent version>
   messages: <count>
   ```
   Body is a sequence of `## User` / `## Claude` headings with the extracted text blocks.
7. **Idempotence.** `_existing_message_count` reads the frontmatter of a possibly-pre-existing export and compares message counts. If the on-disk copy already contains at least as many messages as the current JSONL, the export is skipped. This makes the hook safe to run multiple times on the same session (e.g. after a resume).
8. **Atomic write.** `_atomic_write` writes via tempfile + `os.replace`, same as the compound-loop persistence. Required for iCloud / Dropbox sync paths where an observer sees a single rename instead of a partial file.
9. **QMD re-index.** After a successful export, if `qmd` is on PATH, `subprocess.run(["qmd", "update"])` is invoked so the new session is indexed immediately. See [ADR-016](016-knowledge-dir-qmd-optional.md).

## Alternatives considered

- **Export everything, no filtering.** Floods the knowledge directory with 3-message scratch sessions. Rejected; `min_messages` is the cheap, tunable filter.
- **Store sessions as JSONL in the knowledge directory.** Usable by humans only via `jq`. Rejected — markdown is the lingua franca of note-taking tools, and QMD already understands it.
- **Classify profiles by reading `config.toml` and matching `cwd` against profile roots.** More principled than hardcoded heuristics, but the heuristics were ported from the predecessor's bash implementation and preserve calibration. Moving classification to `core/profiles.resolve_profile` is tracked for a later iteration and will land when we prove the heuristic stops matching a real user setup.
- **Include tool use blocks in the markdown output.** Tempting for "what did Claude actually do", but blows up file size and pollutes the text. The `pre-compact` hook already captures the touched-files list for the use cases that need it ([ADR-010](010-pre-compact-preservation.md)).
- **Push exports to an external database (Postgres, Elasticsearch).** Overkill. Markdown in a plain directory is trivially backup-friendly, greppable with `rg`, and indexable by QMD on demand.

## Consequences

- The knowledge directory becomes a uniform, indexable timeline spanning every project and every profile. A single `qmd query` can surface "the last time I touched circular imports" across years of sessions.
- Profile and session-type frontmatter let the `context-inject` hook filter by project (see `last_session_context` in `context_inject.py`) — it only surfaces prior sessions with a matching `project:` marker.
- Re-exports are safe. A user running the hook twice on the same session never corrupts the existing file; the idempotence check is by message count, so a resumed session that adds real content does get the updated export.
- Because classification lives inside the exporter and not inside the config loader, adding a new profile today does not automatically give it its own `session_type` — the heuristics need to be extended. This is a known trade-off between "ship the calibration" and "derive from config". Tracked.
- The export runs on every `Stop`, adding tens of milliseconds (JSONL parse + one file write). Below the user-perceptible threshold, well under Claude Code's hook budget.

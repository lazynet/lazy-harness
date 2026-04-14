# specs/

Internal design artifacts for `lazy-harness`. This tree is tracked in git but **not published** to the public docs site (`docs/`, served on GitHub Pages via MkDocs).

The rule of thumb: if a document explains *what* a user of the framework should do or see, it belongs in `docs/`. If it explains *how* we decided to build something, or captures an in-progress design, it belongs here.

## Subdirectories

- **`adrs/`** — Active Architecture Decision Records. Short, focused, past-tense documents capturing a decision and its consequences. Each ADR is numbered sequentially. New decisions get new ADRs; existing ones are annotated or superseded, never rewritten.
- **`designs/`** — Long-form design specs produced during brainstorming for non-trivial features. Named `YYYY-MM-DD-<topic>-design.md`. Each spec is the input to an implementation plan.
- **`archive/`** — Frozen historical material from before or during the rename to `lazy-harness`. Preserved as-is for provenance. **Do not edit files under `archive/` to fix references, typos, or stale paths** — the historical record is the point. See `archive/README.md`.

## Relationship to `docs/`

The `docs/` tree is the public, user-facing documentation served at the project's GitHub Pages site. It covers *install*, *use*, *how things work*, and narrative architecture overview. Internal decision artifacts used to live under `docs/architecture/` but were moved here to keep the published site focused on user needs.

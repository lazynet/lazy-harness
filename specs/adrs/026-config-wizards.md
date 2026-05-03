# ADR-026: `lh config <feature> --init` wizards (Fase 3b)

**Status:** accepted
**Date:** 2026-05-03

## Context

ADR-018 specified two surfaces: `lh doctor` for discoverability (implemented in ADR-025) and `lh config <feature> --init` for interactive opt-in (deferred). With the triple stack (QMD/Engram/Graphify) wired through ADR-024 and surfaced via ADR-025, the remaining piece is the wizard surface that lets a user enable a feature without hand-editing TOML.

## Decision

**Add a `lh config` Click command group with two subcommands today: `memory` and `knowledge`. Each subcommand takes a `--init` flag and delegates to a wizard function in a separate `wizards/` package. Wizards inject their IO callables (`prompt_confirm`, `echo`) so they are testable without monkeypatching Click globally.**

The wizards always:
1. Probe whether the underlying tool is installed (`is_<tool>_available`); if not, print the install hint with the pinned version and ask for confirmation to continue setup anyway.
2. Walk the user through the relevant options with `click.confirm` defaults that match the safest path (cloud sync defaults to `false`, auto-rebuild defaults to `false`).
3. Print the proposed TOML block before writing.
4. Ask for explicit confirmation before merging into `config.toml`.
5. Use the shared `wizards/_toml_merge.py` helper to do an atomic deep-merge that preserves all other sections.

ADR-018 is flipped from `accepted-deferred` to `accepted` in the same PR.

## Alternatives considered

- **`click.prompt` chain without IO injection.** Rejected. Tests would have to monkeypatch `click.confirm` globally, which is fragile and leaks across tests. Injecting the callables makes wizard tests deterministic.
- **One wizard per tool (`lh config engram --init`, `lh config graphify --init`).** ADR-018's example output named features by section (`knowledge_backend`, `metrics_sink`), so per-section is the documented pattern. Per-tool would explode the surface as the tool count grows.
- **Auto-install missing tools.** Out of scope. Per the user-confirmed plan, the wizard prints the install command but does not run it. The user retains control of when network/package-manager calls happen.
- **Skip the TOML preview.** Rejected. ADR-018 requires "they always preview the TOML they are about to add and ask for confirmation". Surprise-free is the whole point of the discoverability split.

## Consequences

- New optional features that need an interactive wizard ship as `lh config <feature> --init` plus a function in `wizards/<feature>.py`. The contract is uniform; adding a new wizard is a checklist, not a design exercise.
- The `wizards/` package is intentionally separate from `cli/`. Wizards are pure functions of `(config_path, prompt_confirm, echo)`; the CLI subcommand is a thin adapter that injects the real Click callables. This keeps tests fast and predictable.
- The TOML merge helper is atomic (`tempfile + os.replace`), matching the precedent set by other `config.toml` writes in the repo (ADR-016 mentioned this as the pattern for the knowledge directory tree).
- ADR-018 flips to `accepted`. The doctor + wizards combination is the full implementation of the discoverability decision. Future extension points add a doctor row plus a wizard subcommand and they are done.
- `--show` and `--reset` remain out of scope until a concrete need surfaces. The wizard is enough for the current opt-in flow; inspection is covered by reading the file or running `lh doctor`.

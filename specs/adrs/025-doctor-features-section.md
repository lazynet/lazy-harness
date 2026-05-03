# ADR-025: `lh doctor` Features section — implementation for the triple stack

**Status:** accepted
**Date:** 2026-05-03

## Context

ADR-018 locked the discoverability approach in April 2026 but left implementation deferred until a concrete extension point needed it. With QMD (ADR-016), Engram (ADR-022), and Graphify (ADR-023) now wired through the MCP deploy seam (ADR-024), the harness has three optional tools the user can opt into. Each one needs a way for the user to ask "is this installed, is it active, what version do I have, and what is the canonical pin".

Before this ADR, `lh doctor` carried a single hard-coded QMD line that did not generalize. Engram and Graphify shipped without any `lh doctor` representation — the only way to know whether the deploy step had picked them up was to read `~/.claude-<profile>/settings.json` by hand.

## Decision

**Add a `Features` section to `lh doctor`, populated by a new `lazy_harness.features` helper module. The helper exposes a `FeatureStatus` dataclass and a `collect_feature_statuses(cfg)` function that probes the three tools (qmd, engram, graphify) and returns a normalized status list. `doctor_cmd.py` renders the list with state icons, version comparison against the pin, and actionable install/enable hints.**

State semantics:

| State | Meaning | Doctor icon | Sets ok=False |
|-------|---------|-------------|---------------|
| `active` | Installed AND enabled (or auto-on like QMD) | `✓` green | no |
| `dormant` | Installed but disabled in config | `·` yellow | no |
| `missing` | Not installed | `·` grey | no |
| `broken` | Enabled in config but binary not in PATH | `✗` red | yes |

QMD has no opt-in flag (per ADR-016) — it is `active` when installed, `missing` otherwise. Engram and Graphify use both gates.

The helper lives at `src/lazy_harness/features.py` (top-level, not under `cli/`) because the `lh config <feature> --init` wizards (Fase 3b, deferred) will reuse it for the same probing logic.

## Alternatives considered

- **Inline the per-tool probing in `doctor_cmd.py`.** Rejected. Three tools today, more in the future. The helper is one extraction that pays back at the second tool.
- **Read the version from a constant rather than probing the binary.** Rejected. The harness pins a version; the user might have a different one installed. The doctor's job is to surface that mismatch.
- **Treat `broken` as an info-level row, not an error.** Rejected. `enabled = true` plus `binary not in PATH` is a configuration error — the user explicitly asked for the tool but the next `lh deploy` will produce a settings file with an MCP entry that fails to start. That deserves `ok = False`.
- **Expose the helper under `cli/`.** Rejected. The helper has no CLI dependencies; placing it at `src/lazy_harness/features.py` keeps the import graph clean and makes it reusable from non-CLI contexts (the future `lh config` wizards, possibly the upgrade-notice machinery).

## Consequences

- New optional tools need three things to surface in the doctor: a `is_<tool>_available()` probe, a `PINNED_VERSION` constant, and a status function added to `collect_feature_statuses`. The contract is uniform across qmd, engram, graphify and any future addition.
- ADR-018 stays `accepted-deferred` for now. It flips to `accepted` when the `lh config <feature> --init` wizards (Fase 3b) ship in a follow-up PR. The doctor side is now done.
- Version drift surfaces at doctor time without needing a separate `lh version-check` command. Pin mismatches are visible inline next to each tool.
- The standalone QMD line that lived in `doctor_cmd.py` is removed — the Features section subsumes it. There is no behaviour difference for QMD users; the message just moves into the new section.
- The `broken` state guarantees that a misconfigured profile (e.g. user enabled engram in config but uninstalled the binary) fails `lh doctor` instead of silently producing a broken `settings.json` on the next `lh deploy`. This is the same defensive posture as the existing "profile dir missing" check.

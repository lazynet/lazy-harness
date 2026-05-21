# `lh deploy` — default hooks merge layer

**Date:** 2026-05-21
**Status:** Accepted — ready to implement
**Related backlog:** `lh deploy — merge hook defaults instead of total overwrite` (Open Prioridad MEDIA in `specs/backlog.md`)
**Related ADR:** ADR-031 (new, to be drafted as part of this work)

## Problem

`src/lazy_harness/deploy/engine.py:79` does `settings["hooks"] = agent_hooks`, where `agent_hooks` is generated from the events explicitly declared under `[hooks.<event>]` in `config.toml`. Events not declared in `config.toml` produce no entries, so the assignment silently strips every hook that previously lived in `settings.json`.

Two failure modes follow:

1. **Drift on partial config.** A user who only writes `[hooks.pre_tool_use]` + `[hooks.post_tool_use]` to opt into the security cluster wipes their previously-deployed `SessionStart` (`context-inject`), `Stop` (`session-export` + `compound-loop`), and `PreCompact` (`pre-compact`) entries. The real incident from 2026-04-17 in `specs/backlog.md` captures this exact case.

2. **No batteries-included default.** A fresh `lh init` produces a `config.toml` (from `templates/config.toml.default`) that declares zero hooks. The framework's built-in hooks — context-inject, compound-loop, the security cluster — are off until the user copies their declarations out of the docs by hand. The README promises "session-start context injection, pre-compact summaries, session export and compound-loop enforcement"; today none of that actually fires on a fresh install.

The two failures share one root cause: the deploy engine treats `cfg.hooks` as the complete set of hooks the framework wants, when in fact `cfg.hooks` only represents *user overrides* on top of an implicit framework-provided set.

## Goal

Make the framework's built-in hooks deploy automatically on a fresh `lh init` and stop silently disappearing when a user declares only a subset of events in `config.toml`. User overrides in `config.toml` win per-event. The hook block in `settings.json` becomes wholly framework-owned, with a backup + warning when manual entries are clobbered.

## Non-goals

- Per-script override granularity (e.g. "I want defaults for `session_stop` minus just `engram-persist`"). The override unit is one event. Listing `scripts = ["session-export", "compound-loop"]` is how you exclude `engram-persist`.
- Programmatic editing of `settings.json` by anything other than `lh deploy`. Hand-edits remain possible but lose at the next deploy (with backup).
- Preserving unknown hooks across deploys. The framework owns the block; idempotency wins over hand-edit preservation.
- Configurable default sets per-profile. Defaults are framework-wide; per-profile differences go through `config.toml` overrides.
- Changing `templates/config.toml.default` to declare hooks explicitly. The point of defaults is that the user does not need to declare them.

## Design

### 1. The default set lives in code

New module `src/lazy_harness/deploy/defaults.py`:

```python
"""Framework-provided default hook set.

This is the implicit hook configuration every profile starts with. User
overrides in `config.toml` replace per-event values; events not declared
in user config fall through to the defaults below.
"""

from __future__ import annotations

# event name (lazy-harness convention) → ordered list of built-in hook names.
# All entries must be names registered in `lazy_harness.hooks.loader._BUILTIN_HOOKS`.
DEFAULT_HOOKS: dict[str, list[str]] = {
    "session_start": ["context-inject"],
    "session_stop":  ["session-export", "compound-loop", "engram-persist"],
    "session_end":   ["session-end"],
    "pre_compact":   ["pre-compact"],
    "post_compact":  ["post-compact"],
    "pre_tool_use":  ["pre-tool-use-security", "pre-tool-use-memory-size"],
    "post_tool_use": ["post-tool-use-format", "post-tool-use-sync-claude"],
}
```

Properties:

- Plain Python literal — no TOML parsing, no I/O, importable from tests.
- The list is ordered. Hook order matters (e.g. `session-export` runs before `compound-loop` on Stop so the JSONL is dated before the queue picks it up).
- Every entry must be a `_BUILTIN_HOOKS` key. A contract test (#1 below) enforces this so a typo or rename surfaces in CI rather than at deploy time.
- All built-ins listed are already fail-soft: `engram-persist` no-ops when engram is not installed; `post-tool-use-sync-claude` no-ops outside profile-segment edits; `pre-tool-use-memory-size` only warns. Shipping them by default is safe.

### 2. Pure merge function

In the same module:

```python
def merge_with_defaults(user_hooks: dict[str, HooksConfig]) -> dict[str, list[str]]:
    """Produce the effective hook event → script-names mapping.

    Rules:
    - For each event in DEFAULT_HOOKS: if user_hooks declares it (even with
      an empty list), use user_hooks[event].scripts. Otherwise use the
      default.
    - For each event in user_hooks but NOT in DEFAULT_HOOKS (custom event
      like `notification`): include verbatim.
    - Events that end up with an empty script list are kept in the result
      so callers can distinguish "explicit opt-out" from "not configured";
      consumer code (engine) drops empty events before writing settings.

    The function is pure: no I/O, no logging, deterministic on its input.
    """
```

Pure-function placement (in `defaults.py`, not in `engine.py`) keeps the merge logic unit-testable without spinning up a temp `lh deploy` invocation.

### 3. Engine integration

`deploy/engine.py:deploy_hooks` changes its iteration source from `cfg.hooks` to the merged effective set:

```python
from lazy_harness.deploy.defaults import merge_with_defaults

effective = merge_with_defaults(cfg.hooks)
hook_entries: dict[str, list[str | HookEntry]] = {}
for event_name, script_names in effective.items():
    if not script_names:           # explicit opt-out
        continue
    hooks = resolve_script_names(script_names, user_hooks_dir=user_hooks_dir)
    if hooks:
        # existing HookEntry-vs-string handling stays the same
        hook_entries[event_name] = entries
```

To make this call shape work without synthesizing a fake `HooksConfig`, `resolve_hooks_for_event` (in `hooks/loader.py`) is refactored: a new `resolve_script_names(names: list[str], user_hooks_dir: Path | None = None) -> list[HookInfo]` takes the list directly, and the old function becomes a one-line wrapper that pulls `scripts` off a `HooksConfig` and delegates. External callers of `resolve_hooks_for_event` keep working.

### 4. Backup and warning for manual entries

Before writing `settings.json`, the engine compares the existing `hooks` block (if any) with the new `agent_hooks`. Claude Code's hook entries have the shape `{"matcher": ..., "hooks": [{"type": "command", "command": ...}]}`. The comparison key is the **command string** alone — `matcher` is ignored. Rationale: when the same command is repeated under a different matcher we consider it the same managed entry (the matcher is a framework-side detail driven by `claude_code.py:matcher_map`, not user intent); when a command disappears entirely we consider it unknown.

The diff is computed across every Claude Code event in the existing block. Any command present in the existing block but absent from the new block — for any event — is an "unknown removal". When unknowns are found:

```python
backup = settings_file.with_suffix(".json.bak")
backup.write_text(settings_file.read_text())   # raw pre-deploy snapshot
click.echo(
    f"  ⚠  {profile}/settings.json had {len(unknowns)} hook entries not "
    f"managed by lazy-harness. Backup saved to {backup.name}."
)
for cmd in unknowns:
    click.echo(f"      removed: {_truncate(cmd, 80)}")
```

The backup is overwritten on every deploy that finds unknowns. We do not keep a chain of `.bak.1`, `.bak.2`. Two reasons: (a) the cost of doing it is real (clutter, race with the user), (b) the user can git-version their `~/.config/lazy-harness/` if they care.

When no unknowns are found, no backup is written and no warning is logged — the deploy is silent and idempotent in the normal case.

### 5. Per-event opt-out

A user who wants no hooks on a given event writes:

```toml
[hooks.session_stop]
scripts = []
```

`merge_with_defaults` keeps this in the result as `"session_stop": []`. The engine drops it in step 3 (`if not script_names: continue`), so `Stop` does not appear in `settings.json`. The user has opted the entire event out of the default set.

This is the only opt-out granularity. There is no per-script disable. The lever is intentionally coarse — fine-grained overrides invite version churn (the next time a default is added or renamed, who is affected and how?). One event is the smallest unit that stays stable across releases.

### 6. New-default adoption on release upgrade

If v0.21 adds `new-hook` to `DEFAULT_HOOKS["session_stop"]`, a user upgrading from v0.20 sees:

- If their `config.toml` declared `[hooks.session_stop]`: their list wins. The new default is **not** applied. They opted out of automatic defaults for that event.
- If their `config.toml` did not declare `[hooks.session_stop]`: the next `lh deploy` writes the new list. Their `settings.json` gets `new-hook`. The backup logic fires only if `new-hook`'s command differs from what was there — for users on v0.20 defaults this means the backup fires once on the upgrade deploy (their stored block has the old default, the new block has the new default; the diff is the addition).

This is intentionally opt-in-by-default. The framework's stance: "if you didn't override, you trust us to keep the defaults useful." Users who want change-control on default set updates get it by *declaring* the events explicitly (which freezes their list to what they wrote).

### 7. Logging and observability

`deploy_hooks` already logs `✓ {name}/settings.json (hooks updated)`. The new behavior adds:

- The warning + per-removed-command lines from §4.
- A debug-level line per event showing the effective script names — only when `LH_DEBUG` is set, since it would be noisy on normal runs.

`lh status profiles` (existing) shows per-profile hook count, so users can verify the effective state without reading JSON.

## Files to touch

- **NEW** `src/lazy_harness/deploy/defaults.py` — `DEFAULT_HOOKS` literal + `merge_with_defaults`.
- **NEW** `tests/unit/deploy/test_defaults.py` — tests 1–5 (pure merge logic).
- **MOD** `src/lazy_harness/hooks/loader.py` — extract `resolve_script_names(list[str], user_hooks_dir)` from `resolve_hooks_for_event`; keep the old function as a wrapper.
- **MOD** `src/lazy_harness/deploy/engine.py` — call `merge_with_defaults`, iterate effective events, add backup-on-unknown logic.
- **MOD** `tests/unit/deploy/test_engine.py` — tests 6–11 (engine integration).
- **NEW** `specs/adrs/031-default-hooks-merge.md` — ADR drafted alongside the implementation, lands in the same PR.
- **MOD** `docs/how/hooks.md` — new section "Default hooks" after the event glossary table.
- **MOD** `specs/backlog.md` — move the item from Open Prioridad MEDIA to Done.

`templates/config.toml.default` is **not** touched. Defaults coming through code, not template.

## Test plan (TDD — red first)

Each test is watched to fail before the code that makes it pass.

1. `test_default_hooks_only_references_registered_builtins` — every value in `DEFAULT_HOOKS` resolves through `_BUILTIN_HOOKS`. Contract test; catches typos and renames.
2. `test_merge_empty_user_returns_defaults_verbatim` — `merge_with_defaults({})` returns a dict identical to `DEFAULT_HOOKS` (by value, not aliased).
3. `test_merge_user_overrides_one_event` — user declares `session_stop=["my-hook"]`; result has `my-hook` on `session_stop` and defaults everywhere else.
4. `test_merge_user_empty_list_is_explicit_opt_out` — user declares `session_stop=[]`; result has `session_stop=[]` (kept, not replaced by default).
5. `test_merge_preserves_user_custom_event` — user declares `notification=["my-notify"]`; result has `notification=["my-notify"]` alongside all defaults.
6. `test_deploy_hooks_fresh_profile_writes_all_defaults` — a profile with no pre-existing `settings.json` and empty `cfg.hooks` ends up with every default event in `settings.json["hooks"]`.
7. `test_deploy_hooks_idempotent_on_clean_managed_state` — second run on a profile already in framework-managed state writes the same bytes; no backup created.
8. `test_deploy_hooks_backs_up_and_removes_unknown_entries` — pre-existing `settings.json` contains a hook command not in the effective set; `.json.bak` is written, warning logged, removed entry no longer in new `settings.json`.
9. `test_deploy_hooks_empty_existing_hooks_block` — pre-existing `settings.json["hooks"] == {}` triggers no backup; defaults are written.
10. `test_deploy_hooks_honors_per_event_opt_out` — user declares `[hooks.pre_compact] scripts = []`; result `settings.json` contains no `PreCompact` key (event dropped).
11. `test_deploy_hooks_regression_2026_04_17` — partial user config with only `[hooks.pre_tool_use]` + `[hooks.post_tool_use]` declared; result `settings.json` contains the full default set for `SessionStart`/`Stop`/`SessionEnd`/`PreCompact`/`PostCompact` plus the user overrides for the two declared events.

Estimated effort: one focused session. Tests 1–5 are minutes of work each. Tests 6–11 require a temp profile config and exercising the engine end-to-end; the existing `tests/unit/deploy/test_engine.py` already has the scaffolding.

## Open questions

- **`lh config show-defaults`?** Out of scope for this PR. Once `DEFAULT_HOOKS` lives in `defaults.py`, a `lh config show-defaults` (or `lh hooks list --include-defaults`) becomes a thin one-screen reader. Backlog candidate, not a blocker.
- **Templates/`config.toml.default` documentation.** The template stays empty of hook declarations, but a comment block should mention that defaults are applied automatically and how to override. Will land in the same PR as a one-block addition to the template.
- **ADR-031 status.** Drafted alongside this work, lands in the same PR. Status `accepted` at merge (per `specs/adrs/README.md`: "Decision taken and embodied in code, config, or tests").

## Implementation sequencing

1. **Tests 1–5** (pure logic). Implement `DEFAULT_HOOKS` + `merge_with_defaults`. No engine changes yet.
2. **Refactor `hooks/loader.py`** — extract `resolve_script_names`. Update one call site (`resolve_hooks_for_event`). Run full suite.
3. **Tests 6–11** (engine integration). Modify `deploy_hooks`, add backup logic. Run full suite.
4. **ADR-031** — write the decision record.
5. **Docs**: `docs/how/hooks.md` new section + `templates/config.toml.default` comment.
6. **Backlog**: move item to Done in `specs/backlog.md`.
7. **`/tdd-check`**: pytest + ruff + mkdocs build, all green.
8. **Commit + PR**: single `feat:` commit, push, `gh pr create`.
9. **Merge**: squash + delete-branch + worktree cleanup.

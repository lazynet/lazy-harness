# Config TUI: one interactive surface for observing and changing harness state

**Status:** proposed
**Date:** 2026-08-17
**Depends on:** [capability registry design](2026-08-17-capability-registry-design.md) / [ADR-035](../adrs/035-capability-registry.md)
**Relates to:** [ADR-012](../adrs/012-sqlite-monitoring.md) (SQLite monitoring), [ADR-017](../adrs/017-selftest-as-health-check.md), [ADR-026](../adrs/026-config-wizards.md) (config wizards)

## Problem

Two surfaces exist and neither answers the question a user actually has.

**Observability is fragmented across nine subcommands.** `lh status` has `overview`, `profiles`, `projects`, `sessions`, `tokens`, `hooks`, `cron`, `queue`, `memory`. Each is a separate invocation with its own start-up cost, and correlating two of them — "the queue is deep, which hook last fired?" — means running both and holding the output in your head. There is no drill-down: `lh status hooks` reports an error count for a log file it will not show you.

**Configuration is hand-edited TOML.** `config.toml` on this machine has 11 top-level sections and roughly 60 keys. `lh config <feature> --init` (ADR-026) covers exactly two of them, `[memory]` and `[knowledge]`, and only in one direction — an init wizard, not an editor. Everything else is opened in `$EDITOR`, changed, and then `lh deploy` is run from memory, with no feedback about whether the change landed.

The gap between those two is where the real failure lives: **nothing connects "this is on" to "this is working"**. A hook can be enabled in `config.toml`, absent from a profile's `settings.json`, and reported nowhere. That divergence has bitten this repo before and is why the deployment gate in `CLAUDE.md` insists on grepping the installed artefact rather than trusting the checkout.

Secondary, but it constrains the design: the nine views print imperatively. Every one takes a `Console` and interleaves `console.print` with logic — `views/hooks.py` prints inside a loop at lines 71–91. Of the nine, only `profiles` has a dedicated unit test. They are hard to test for exactly the reason they are impossible to reuse.

## Scope

Confirmed in the scoping conversation: **observability plus configuration toggles.** Not a replacement for `lh status`.

The subcommands stay. They are the non-interactive, scriptable, hook-and-CI-safe surface, and `lh status tokens --json` in particular is a data interface. The TUI is an additional entry point, `lh tui`, for the interactive case.

## Non-goals

- **Replacing `lh status`.** Explicitly rejected during scoping. The subcommands are not deprecated, not hidden, and not reimplemented.
- **Editing arbitrary TOML.** Only registry-declared capabilities and their declared options are editable. A generic TOML editor is `$EDITOR`, and it is better at it.
- **Remote or multi-machine views.** One machine, one config, one metrics DB.
- **Writing to `settings.json` directly.** The TUI writes `config.toml` and invokes the existing deploy path. There is one seam that generates agent config and it stays the only one.
- **A daemon or background refresh service.** Refresh is polling inside the running process, like every other read in this framework.

## Design

### D1 — Views return renderables instead of printing

```python
# before
def render(ctx: StatusContext, console: Console) -> None: ...

# after
def render(ctx: StatusContext) -> RenderableType: ...
```

Each view builds a Rich renderable — usually a `Group` of tables and panels — and returns it. The CLI keeps its current behaviour with a one-line adapter (`console.print(view.render(ctx))`), so `lh status hooks` output is unchanged.

Two things fall out of this that are worth more than the TUI itself:

- **The views become unit-testable.** Today eight of nine have no dedicated test because asserting on captured console output is unpleasant. Returning a renderable means asserting on structure.
- **Textual hosts Rich renderables natively**, so the observe half of the TUI is composition rather than reimplementation.

`views/overview.py` and `views/sessions.py` take a `MetricsDB`, and `views/tokens.py` takes an `Aggregation`; those signatures keep their extra parameters. Only the `Console` argument changes.

This refactor is behaviour-preserving and independently valuable. It ships first, on its own, with the output-identity test as its gate.

### D2 — `lh tui` with two panes

```
┌ lazy-harness ──────────────────────────────── q quit ─┐
│  [o]bserve   [c]onfigure                              │
├───────────────────────────────────────────────────────┤
│  ▸ overview   profiles   projects   sessions   tokens │
│    hooks      cron       queue      memory            │
├───────────────────────────────────────────────────────┤
│                                                       │
│              (selected view's renderable)             │
│                                                       │
└───────────────────────────────────────────────────────┘
```

**Observe** hosts the nine views, keyboard-switchable, with a detail region below the table. Selecting a hook row tails the relevant `hooks.log` lines; selecting a job row shows its unit file or plist. This is the drill-down the subcommands cannot offer.

Refresh is a timer that rebuilds the active view's renderable. Default 5 s, paused when the pane is not focused, and never faster than the underlying probe cost — `views/cron.py` shells out per job, so a 1 s refresh would spawn subprocesses continuously.

**Configure** is driven entirely by `registry.capabilities()`, which is the whole reason ADR-035 comes first:

| Cardinality | Widget |
|---|---|
| `MANY` | checkbox list — hooks, metrics sinks, external tools |
| `ONE` | radio group — agent adapter, scheduler backend, LLM backend |
| external dependency present | checkbox plus a probe indicator and, when missing, the capability's `install_hint` |

The pane has no knowledge of hooks, sinks, or adapters. It dispatches on cardinality. Adding a seventh capability kind changes nothing here.

### D3 — Save is a four-step transaction that verifies its own effect

This is the part that matters. A configuration UI that flips a switch and reports "saved" without confirming the switch reached the agent is the exact failure the repo's gates were written from: *a tool's exit code is not proof of its effect*, and *an implemented hook does not run until it is wired*.

Changes stage in memory. Nothing touches disk until `s`. Then, in order:

1. **Back up.** Copy `config.toml` to `config.toml.bak`. This mirrors what `deploy/engine.py` already does before repairing a `settings.json`.
2. **Write atomically.** Serialise through the fixed read-modify-write `save_config` (prerequisite D5 of the registry design), into a temp file in the same directory, then `os.replace`. Same-directory-then-rename is already the pattern in `knowledge/session_export.py:141` and `knowledge/compound_loop.py:813`, chosen so a syncing filesystem observes one rename rather than a partial write.
3. **Deploy.** Invoke the existing `deploy_hooks` / `deploy_mcp_servers` path in-process. Not a shelled-out `lh deploy` — the installed binary may be a different version than the running one, which is the divergence the repo's binary-first gate warns about.
4. **Verify, per toggle.** Re-read each affected profile's `settings.json` from disk and confirm each toggled hook is present or absent as intended. Report per-capability in the TUI:

```
  ✓ engram-persist      enabled  → present in lazy/settings.json, flex/settings.json
  ✓ ansible-lint        disabled → absent from both profiles
  ✗ post-tool-use-format enabled → NOT found in flex/settings.json
```

A failed verification is displayed as a failure and the backup path is offered. It is never rounded up to success.

Step 4 is non-negotiable. Without it this is a TOML editor with extra rendering.

### D4 — Read-only mode is a first-class state

The Configure pane renders with toggles disabled, and a reason, when any of:

- `--read-only` is passed
- `config.toml` is not writable by the current user
- the config file is managed by chezmoi **and** the source is ahead of the destination

The chezmoi case deserves the check rather than a blanket refusal. The user's own rule is to edit the destination and close with `chezmoi re-add`; editing while the source is already ahead is what loses work. So: after a successful save, if `chezmoi managed` reports the file, print the `chezmoi re-add <path>` reminder. **Do not run it.** Running someone's dotfile manager as a side effect of a checkbox is a hidden action, and the reminder is what the user's own workflow asks for.

### D5 — Headless and ssh constraints

Both named Linux targets include ssh-only servers, and the macOS use is often inside tmux. Therefore:

- Every action is keyboard-bound. Mouse support is accepted where Textual provides it free but is never the only path to any function.
- Layout is correct at 80×24. Wide tables scroll horizontally inside their own region; the frame never depends on terminal width.
- No truecolor requirement. `NO_COLOR` is honoured, and the palette degrades to 16 colours without losing meaning — state is carried by glyph and text, never by colour alone.
- `lh tui` in a non-TTY exits with a clear message pointing at the `lh status` subcommands, rather than emitting escape codes into a pipe.

### D6 — Textual as an optional extra

```toml
[project.optional-dependencies]
tui = ["textual>=0.80"]
```

Installed with `uv tool install 'lazy-harness[tui]'`. `lh tui` without it prints the install command and exits non-zero.

Textual is the right choice: same author and same rendering stack as Rich, which is already a hard dependency, so the nine views compose in rather than being rewritten. The alternative — hand-rolling with `rich.live` plus raw terminal input — means implementing focus, key dispatch, and layout by hand for no gain.

Making it an extra rather than a core dependency keeps the install lean for the environment that dominates: hooks and cron jobs, which run headless and will never open a TUI. The cost is a one-line install hint; the benefit is that a scheduled `lh metrics drain` on a container does not carry a terminal UI framework.

### D7 — Phasing, write path last

| Phase | Content | Risk |
|---|---|---|
| **P0** | Views return renderables; CLI adapter; per-view unit tests | none — behaviour-preserving, ships value alone |
| **P1** | `lh tui` observe pane only, with drill-down. No write path exists | read-only |
| **P2** | Configure pane rendering capability state, toggles **disabled** | read-only |
| **P3** | Enable toggles, save transaction, verification step | first write |

The write path is the last thing added, on top of a read path that has been in use. P2 in particular is worth shipping on its own: a pane that shows every capability and its state is already better than what exists, with zero write risk.

P3 cannot start before the registry design's step 0 — the config round-trip fix — has landed and its key-loss test is green.

## Verification

- **P0's gate is output identity.** Capture every `lh status <sub>` output before the refactor into fixtures; assert byte-identical after. The refactor is only safe if it is invisible.
- **Prove the verification step catches a real divergence.** Deliberately break deploy for one profile — make its config dir unwritable — toggle a hook on, save, and confirm the TUI reports `✗` for that profile rather than a global success. A verification step that has never been observed failing has not been tested.
- **Prove the save transaction preserves unmodelled config.** Toggle one hook on a config containing all 11 sections; diff the raw TOML before and after; assert the only change is the intended one. This is the regression net for the 51-key loss.
- **Verify at 80×24 over ssh on a headless target**, in tmux, with `TERM=xterm-256color` and again with `NO_COLOR=1`. The assumption that a Textual app is legible over ssh is exactly the kind that the repo's gate requires be verified in the target context rather than reasoned about.

## Kill criteria

The repo requires behavioural automation to declare kill criteria before deployment. A user-invoked TUI is not behavioural automation — it fires on request, injects nothing, and consumes no context — so the full baseline-and-threshold apparatus does not apply. What does apply is the underlying rule: a mechanism nobody adopts is debt wearing the costume of a feature.

Therefore, one review at **four weeks after P3 ships**, against invocation counts already available from the shell history and the monitoring DB:

- If `lh tui` is invoked and the Configure pane is used to change something at least a few times, it has earned its place.
- If it is invoked but only the Observe pane is used, **P3 is removed** and the TUI stays read-only. The nine subcommands plus a viewer is a coherent product; a write path nobody uses is a liability that can corrupt config.
- If it is not invoked at all, the whole thing is removed and P0 is kept — the renderable refactor is worth having regardless, because it is what made the views testable.

The measurement parameters are frozen for those four weeks. Widening what counts as adoption mid-window invalidates the comparison the window exists to enable.

## Consequences

- Eight views gain their first unit tests as a side effect of P0.
- `lh status` behaviour is unchanged; the subcommands remain the interface for scripts, hooks and CI.
- One optional dependency is added. Core install weight is unchanged.
- The Configure pane is generic over capabilities, so every future capability appears in it without the TUI being modified — which is the payoff that justified ADR-035.
- `docs/reference/cli.md` gains an `lh tui` section, and `docs/getting-started/install.md` gains the `[tui]` extra. Both are in scope for the implementing change, not deferred.
- The save-and-verify transaction gives the framework its first surface where "configured" and "actually deployed" are checked against each other and reported together. That check is reusable by `lh selftest` and arguably belongs there too, but that is a follow-up, not part of this design.

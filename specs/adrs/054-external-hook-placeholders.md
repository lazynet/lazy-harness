# ADR-054: `[hooks.*].external` gains `{profile}` / `{config_dir}` placeholders

**Status:** accepted
**Date:** 2026-09-17
**Supersedes:** —
**Superseded by:** —
**Related:** ADR-041 (the multi-agent hook contract — the runner and `hook_command` this ADR reuses the shape of), ADR-004 (agent adapter pattern)

## Context

`specs/backlog.md` ("`[hooks.*].external` no puede expresar un comando por
perfil") measured the gap on 2026-09-14: `external` is a global list of
`ExternalHookConfig` entries in `config.toml`, and
`deploy/engine.py:172 _hook_entries_for` copies `ext.command` **verbatim** to
every profile it deploys —

```python
for event_name, event_cfg in cfg.hooks.items():
    for ext in event_cfg.external:
        entries.setdefault(event_name, []).append(
            HookEntry(command=ext.command, matcher=ext.matcher)
        )
```

The harness's own builtins do not have this problem: `hook_command(hook,
profile=profile, binary=binary)` resolves `--profile <name>` per profile
inside the per-profile loop `_hook_entries_for` already runs. `external` is
the one hook source that skips that resolution entirely, so a command whose
text needs to differ per profile — one that names a profile's own config
directory — has no way to say so. A single entry is either wrong on every
profile but one, or the config author hand-maintains one near-duplicate entry
per profile and keeps them in sync by hand.

This is not hypothetical: the herdr `SessionStart` hook (`bash
~/.claude-<profile>/hooks/herdr-agent-state.sh session`) fell out of version
control exactly here. Per `specs/backlog.md`'s own account, it lived hardcoded
per profile in the `settings.json` snapshot chezmoi maintained until `lh
deploy` became the sole writer of the `hooks` block; deleting that snapshot
left nowhere to declare a command that names its own profile, and the
workaround today is running `herdr integration install claude` by hand, once
per profile, immediately after every deploy.

### Alternatives

**A — `profiles = [...]` on each `external` entry, or a
`[profiles.<name>.hooks.<event>].external` table that merges over the global
one.** Expresses the general case (a command that is not just per-profile text
substitution but genuinely different logic on different profiles), but nothing
measured needs that generality: every case in the backlog entry is the same
command shape with one substring — a path — changed. This shape also
multiplies the config surface `_parse_profiles` and the coherence tests
already have to validate (a nested `[profiles.<name>.hooks.*]` table is a
second place `external` can appear, needing its own unknown-key and matcher
validation) for a generality nothing on this backlog asks for. Rejected for
now; revisit if a real case ever needs a command that is not expressible as
one template plus placeholders.

**B — expand `{config_dir}` / `{profile}` placeholders in `ext.command` at
plan time**, inside `_hook_entries_for`'s existing per-profile loop. Small: one
`str.format`-shaped substitution, no new config table, no new validation
surface beyond naming a placeholder the deploy does not recognise. Covers the
herdr case and every other command that needs to know its own profile's
directory or name. Chosen.

**C — document the limit and close the backlog entry.** Cheaper than either
code change, but leaves the herdr hook's workaround (`herdr integration
install claude` run by hand after every deploy) as the permanent state, which
is the failure this entry exists to fix in the first place. Rejected: the
backlog entry was opened *because* that workaround is silent and machine-
specific, not because no fix was wanted.

## Decision

`ExternalHookConfig.command` may contain `{profile}` and/or `{config_dir}`.
`_hook_entries_for` expands them per profile, in the same loop that already
resolves `hook_command` for the harness's own scripts — one place decides "the
command this profile's hooks run," not two:

```python
def _expand_external_command(command: str, *, profile: str, config_dir: str) -> str:
    try:
        return command.format(profile=profile, config_dir=config_dir)
    except (KeyError, IndexError) as exc:
        raise ExternalHookPlaceholderError(command, exc) from exc
```

`{config_dir}` expands to the profile's **raw, undexpanded** `config_dir`
field (`"~/.claude-lazy"`, not `/Users/<home>/.claude-lazy`) — the same string
`config.toml` declares. Two reasons: it reproduces the backlog's own
motivating example (`bash ~/.claude-<profile>/hooks/herdr-agent-state.sh`)
exactly, tilde and all, and it keeps a chezmoi-managed `settings.json`
converging across machines with different home directories — the same
portability property `hook_command`'s own docstring states for the harness's
built-in commands ("the command carries no path at all... so a chezmoi-managed
settings file could never converge across two machines"). An `external` command
is declared as a shell command string, the same shape the herdr example and
every measured Codex hook fixture in `specs/designs/codex-evidence.md` use
(`/bin/sh -c '...'`), so `~` is expected to expand the same way it would if the
user had typed the literal path by hand — not independently verified against a
running agent for this specific case, which a probe should close before this
decision is leaned on for a command whose tilde expansion matters.

A command naming a placeholder outside `{profile, config_dir}` is refused with
a diagnostic naming the unknown field — `str.format`'s own `KeyError` /
`IndexError`, wrapped in `ExternalHookPlaceholderError` so the message says
which placeholder and which command, rather than a bare Python traceback
reaching the user through `lh deploy`. A plain command with no `{...}` in it
is returned unchanged: `str.format` is a no-op on a string with no fields, so
every `external` entry declared before this ADR keeps working with no
migration.

This is deliberately the same shape `hook_command` already uses for the
harness's own scripts — a string template resolved once per profile inside
the existing loop — rather than a second, parallel resolution mechanism for
third-party commands.

## Consequences

`specs/backlog.md`'s `[hooks.*].external` entry closes: the herdr
`SessionStart` hook becomes expressible again —

```toml
[hooks.session_start]
external = [
  { command = "bash {config_dir}/hooks/herdr-agent-state.sh session" },
]
```

— one entry, every profile, each resolving its own directory.

`docs/reference/config.md`'s `[hooks.<event>]` / `external` field documents
the two placeholders and the unknown-placeholder refusal.

Alternative A (per-profile `external` lists or tables) stays available if a
future case needs more than text substitution — a command that must run on
some profiles and not others, or with genuinely different logic per profile —
but nothing measured today asks for it, and adding the surface speculatively
is exactly the premature abstraction this repo's own rules forbid.

The refusal happens at deploy/plan time (inside `_hook_entries_for`, per
profile), not at config load: a config that never deploys a bad profile never
hits it, matching how `ConfigTargetChangedError` and
`ConfigPlannerRequiredError` already surface mid-deploy rather than at parse
time. A future ADR could move it earlier if a case shows a config-load-time
check is worth the added validation surface; nothing measured needs that yet.

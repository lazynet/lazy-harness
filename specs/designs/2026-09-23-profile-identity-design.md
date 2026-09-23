# Profiles are identity × agent — design

**Status:** accepted\
**Date:** 2026-09-23\
**Decision:** [ADR-068](../adrs/068-profiles-are-identity-times-agent.md)

## Problem

A profile name carries two facts the model does not separate: *whose* context
it is (personal, work) and *which agent* runs it. The deployed fleet shows the
seam:

- Config dirs already follow `{agent}-{identity}` — `~/.claude-lazy`,
  `~/.claude-flex`, `~/.codex-lazy` — but the profile names are `lazy`, `flex`
  and `lazy-codex`: two conventions for one thing.
- The Codex profile shares the personal identity by symlink:
  `profiles/lazy-codex/tail.md -> ../lazy/tail.md`. The sharing is real; the
  model cannot see it.
- `init/wizard.py` derives `config_dir = ~/.{agent_prefix}-{profile_name}`, so
  a profile named after its agent would get `~/.claude-claude-lazy`.
- A second subscription of the same agent for the same identity (two Codex
  accounts) has no place to go but another copy of the source tree.
- `lh run` resolves the profile from the cwd, but a Codex profile has no
  `roots`, so it is only reachable with `--profile`, and the single launch alias
  (`lcca`) is Claude-only.

## Goals

- One naming convention: profile name = config dir basename =
  `{agent_prefix}-{identity}[-{suffix}]`.
- Identity is a declared field, and the source tree is organised by it, so every
  profile of one identity shares head, tail and docs without symlinks.
- Several profiles per (agent, identity) pair are legal.
- `lh run` can resolve "this agent, for this cwd" when profiles of different
  agents share a root.
- Launch aliases per agent and per profile, in dotfiles, on every host.

## Non-goals

- Backwards compatibility for the old names. The cutover is a coordinated
  big-bang (decision below); no `previous_names`, no alias resolution.
- Generating aliases from `config.toml` at shell start-up.
- Changing what a profile *is* at runtime (config dir, env var, adapter).

## Decisions taken during brainstorming

| # | Question | Decision |
|---|---|---|
| 1 | Plain rename vs identity × agent | Identity × agent |
| 2 | Name derived vs explicit | Explicit TOML key, validated against `{prefix}-{identity}[-{suffix}]` |
| 2b | `identity` required vs optional | Optional; declaring it opts the profile into the new model (decided during planning: a required field breaks every existing user of the public package and 102 test fixtures, for no behaviour the optional form lacks) |
| 3 | Old names during transition | None — big-bang cutover across all consumers |
| 4 | Metrics history | Rewritten to the new names, locally and in the sink |
| 5 | Default Codex launch | `activate` (`--approve-for-me`) |

## Design

### 1. Config schema

`ProfileEntry` gains `identity: str = ""`, **optional**. One helper,
`profile_identity(name, entry) -> str`, returns `entry.identity or name`, so a
profile without `identity` keeps today's behaviour exactly: its identity is its
name, its source is `profiles/<name>/`, and its name is not validated. The
fleet's `config.toml` declares `identity` on every profile; `lh doctor` warns
when a config mixes profiles with and without it.

```toml
[profiles]
default = "claude-lazy"

[profiles.claude-lazy]
identity = "lazy"
agent = "claude-code"
config_dir = "~/.claude-lazy"
roots = ["~/repos/lazy"]
root_default = true

[profiles.claude-flex]
identity = "flex"
agent = "claude-code"
config_dir = "~/.claude-flex"
roots = ["~/repos/flex"]

[profiles.codex-lazy]
identity = "lazy"
agent = "codex"
config_dir = "~/.codex-lazy"
roots = ["~/repos/lazy"]
```

Loader validation, each diagnostic naming the profile key and the offending
field:

- `identity` present but not a kebab-case token (`[a-z0-9]+(-[a-z0-9]+)*`), or starting with
  `_` → error. `_` is reserved for `profiles/_common`.
- When `identity` is present: profile name not equal to `{prefix}-{identity}` and not starting with
  `{prefix}-{identity}-` followed by a non-empty kebab suffix → error that
  shows the expected form.
- When `identity` is present and the agent has no declared prefix → error
  naming the agent.

`config_dir` stays explicit. The wizard proposes `~/.{profile_name}` and stops
concatenating the agent itself.

### 2. Agent prefix — one place

`agents/registry.py` declares `PROFILE_PREFIXES` beside `_AGENTS`
(`claude-code` → `claude`, `codex` → `codex`, `copilot` → `copilot`) and
exposes `profile_prefix(agent_name) -> str`. The loader, the wizard and
`lh run --agent` read it there; nothing else spells the mapping. A registry map
rather than a Protocol attribute, because widening `AgentAdapter` would touch
`NullAdapter` and every test fake for one string. A test asserts
`PROFILE_PREFIXES.keys() == _AGENTS.keys()` and that the values are unique.

### 3. Source tree by identity

```
profiles/
  _common/                 unchanged
  lazy/                    identity
    head.md  tail.md
    shared/                agent-neutral assets
    claude-code/           agent-specific assets (already exists)
    codex/                 agent-specific assets, when needed
    CLAUDE.md              generated for claude-code profiles of this identity
    AGENTS.md              generated for codex profiles of this identity
  flex/
```

One function, `profile_source_dir(cfg, name) -> Path`, returns
`config_dir() / "profiles" / profile_identity(name, entry)`. Every path that builds
`profiles / <name>` today goes through it:

- `deploy/engine.py` (link plan), `deploy/snapshot.py` (backup targets),
- `core/artifact_version.py` (doc version reports),
- `cli/profile_cmd.py` (add/remove/migrate),
- `core/sync_agent_md.py` and `hooks/builtins/post_tool_use_sync_system_doc.py`.

A test greps `src/` for `"profiles" /` followed by a profile variable and fails
on any hit outside the helper, so a seventh call site cannot reappear.

**`sync_profiles` becomes profile-driven.** Today it iterates *directories* and
assumes one directory = one profile = one agent. It now iterates configured
profiles, resolves each to `(identity dir, adapter)`, and writes each distinct
`(identity dir, system doc)` pair once. Two profiles that share identity and
agent (`codex-lazy`, `codex-lazy-alt`) produce byte-identical input and one
write. `only=<profile>` selects that profile's pair. A directory under
`profiles/` that no configured profile names is reported as orphaned and never
written — but only once at least one profile in the config declares
`identity`: until then (decision 1's "nothing changes"), an unnamed directory
keeps the old fallback of being synced with the caller's adapter, and
`only=<undeclared dir>` still syncs it the same way. The orphan report exists
for a tree that outlived its config: with identities the directory no longer
tells which agents it serves, but an identity-less config has no way to draw
that distinction in the first place.

**Generated docs never name a concrete profile.** The Codex head today says
"you are running in profile `lazy-codex`". Agent-specific prose moves to
`_common/<agent>.md` or `<identity>/<agent>/`; identity-level prose stays in
`head.md`. This is what makes the one-write rule above sound.

**The deploy ledger.** `deploy/ledger.py` treats a link as harness-owned when it
resolves inside the profile source. With identity dirs, the source a config
dir is compared against becomes `profiles/<identity>/`. Two profiles sharing an
identity own disjoint link sets because each ledger is per config dir. Links
pointing into a *removed* source dir (`profiles/lazy-codex/`) are no longer
recognised as owned; the cutover removes them explicitly (runbook step 6)
instead of relying on the deploy.

### 4. `lh run --agent <prefix>`

`--agent` filters candidate profiles by adapter prefix **before** root
resolution. With it:

- one candidate for the cwd → that profile;
- several → `root_default` among them, else the existing ambiguity error;
- no root match → `profiles.default` if it runs that agent, else the only
  profile of that agent if there is exactly one, else exit 1 naming the agent
  and the cwd. It never falls back to a profile of another agent.

Without `--agent`, resolution is unchanged (`root_default` decides a shared
root). `--agent` and `--profile` together: `--profile` wins if its agent
matches, else exit 1. `lh exec` takes the same flag through the same resolver.

### 5. Metrics rename

`lh metrics rename-profile <old> <new>` updates `profile` in `session_stats`,
`loop_events` and `launches` of the local store in one transaction, prints the
row count per table, and is idempotent (a second run reports 0). It refuses when
`<new>` is not a configured profile. Rows already carrying `<new>` are left
alone, so the command is safe after a partial run.

The Postgres sink is rewritten by the infrastructure repository with the
equivalent `UPDATE` and the dashboard `CASE` mappings are reduced to the new
names only.

### 6. Launch aliases (dotfiles, all hosts)

`dot_config/zsh/20-aliases-common.zsh` replaces `lcca`:

```zsh
# Resolved from cwd, filtered by agent
alias lc="lh run --agent claude --bypass=enable"
alias lcy="lh run --agent claude --bypass=activate"
alias lx="lh run --agent codex --bypass=activate"
alias lxn="lh run --agent codex --bypass=no-sandbox"

# Forced profile — the alias is the profile name
alias claude-lazy="lh run --profile claude-lazy --bypass=enable"
alias claude-flex="lh run --profile claude-flex --bypass=enable"
alias codex-lazy="lh run --profile codex-lazy --bypass=activate"
```

Overriding the level on a forced alias (`claude-flex --bypass=activate`)
depends on how click treats a repeated option; the plan probes it first and,
if the last value does not win, forced aliases drop `--bypass` instead.

## Cutover runbook

Strict order; each step verified before the next.

1. **lazy-harness.** Sections 1–5 under TDD, one PR. Merge, release-please cut,
   `uv tool install --reinstall` on Mac and agent station, grep site-packages
   for `profile_source_dir` and `rename-profile`.
2. **Freeze the agent station.** Stop the `lh exec` timers (vault passes, tidy,
   workloads) for the duration.
3. **dotfiles**, one commit: `config.toml.tmpl` with new names and `identity`;
   `profiles/lazy-codex/` merged into `profiles/lazy/` (head prose split per
   section 3, symlink deleted); prose and skills naming profiles
   (`restrictions.md`, `audit-harness`, `recall-cowork`, `governance.md`,
   `common.md`, `chezmoi.md`, both `modify_settings.json.tmpl`);
   `lazy-vault.toml.tmpl`; the aliases; `lcca` mentions in `docs/tools/`.
4. **lazy-ai-tools.** `--profile lazy` → `--profile claude-lazy` in defaults,
   docs and tests; release.
5. **lazy-ansible.** Workload templates, `scripts/test_lhexec.sh`, sink
   `UPDATE`, dashboard `CASE`.
6. **Per host, Mac first:** `chezmoi apply`; `lh deploy`; `lh metrics
   rename-profile` for the three pairs; `find ~/.claude-* ~/.codex-* -xtype l`
   and remove the dangling links into the removed source dir; re-add to chezmoi.
7. Resume the agent station timers.

## Testing

- Loader: no `identity` keeps today's behaviour (name unvalidated, source by
  name); invalid identity token; name not matching the
  prefix; valid suffix (`codex-lazy-alt`); agent without prefix. Each asserts
  the diagnostic names the key (`pytest.raises(match=...)` anchored on the
  literal key).
- Config round-trip — save, load, save, load — for a new document and a merge
  onto an existing one.
- Prefix registry: every adapter declares one, all unique.
- `profile_source_dir`: the grep test for stray `profiles /` joins; each former
  call site exercised with two profiles sharing an identity.
- `sync_profiles`: two agents on one identity write `CLAUDE.md` and `AGENTS.md`
  in the same dir; two profiles with the same agent and identity produce one
  write; an orphan dir is reported and untouched; `only=` selects one pair.
- `--agent`: shared root, zero candidates, several with and without
  `root_default`, conflict with `--profile`; a parameter-less smoke test beside
  the explicit-parameter ones.
- `rename-profile`: all three tables, idempotence, unknown target refused,
  pre-existing target rows untouched.

## Success criteria

Verified on both hosts after step 7:

- `lh run --list` shows exactly `claude-lazy`, `claude-flex`, `codex-lazy`.
- `lc`, `lx`, `claude-flex`, `codex-lazy` with `--dry-run` from `~/repos/lazy`
  resolve the expected profile, env var and bypass flag.
- `grep -rE "profile[= ](lazy|flex|lazy-codex)\b"` over the four repositories
  and the deployed config dirs returns nothing outside `specs/archive/`.
- `SELECT DISTINCT profile` on the local store and on the sink returns only new
  names (or empty).
- `lh doctor` clean; one real `lh exec` workload fired through `systemctl
  start` on the agent station exits 0.
- `find ~/.claude-* ~/.codex-* -xtype l` is empty.

## Risks

- **Missed consumer.** A scheduled job still passing `--profile lazy` fails
  after the cutover. Mitigated by the freeze, the grep criterion, and firing a
  real workload before unfreezing.
- **Ledger orphans.** Links into the removed source dir are invisible to the
  deploy. Mitigated by the explicit `-xtype l` sweep.
- **Doc drift between profiles of one identity.** Removed by construction: the
  generated doc is keyed by `(identity, agent)`, never by profile.

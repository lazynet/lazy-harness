# How profiles and deploy work

A profile is the complete agent configuration for one isolated context — typically "personal", "work", a specific client, or an experimental sandbox. The framework ships profile management and a deploy engine that gets that configuration into the exact directory the agent reads from.

This page explains how the pieces fit. For the reasoning, see [ADR-001](https://github.com/lazynet/lazy-harness/blob/main/specs/adrs/001-hybrid-architecture.md) and [ADR-009](https://github.com/lazynet/lazy-harness/blob/main/specs/adrs/009-profile-symlink-deploy.md).

## Three directories, two roles

Profiles involve three directories per profile, and it is worth seeing them side by side before anything else.

```
Role           Path                                                 Owner
─────────────  ──────────────────────────────────────────────────── ──────────
source         ~/.config/lazy-harness/profiles/<name>/              user
target         ~/.claude-<name>/                                    agent
default link   ~/.claude                → target of default profile agent
```

- **Source.** The user owns this. It lives in their dotfile-managed config dir. It is where `CLAUDE.md`, `skills/`, and any other profile content live. The framework reads from here but does not write to it outside of `lh init` / `lh profile add`.
- **Target.** This is the directory Claude Code reads from when `CLAUDE_CONFIG_DIR` is set to it (or when it is `~/.claude` for the default profile). The framework writes symlinks into this directory during deploy, plus a generated `settings.json` for hooks. Claude Code itself also writes into this directory during normal use (session JSONLs, `projects/` state, memory files).
- **Default link.** A single top-level symlink `~/.claude → <default profile's target>`. This is what makes plain `claude` work without an env var.

The source and target are deliberately separated. Source is read-only from the agent's perspective — the framework controls the symlinks into it. Target is write-active — Claude Code drops session data, project state, and memory files there.

## How profiles are declared

In `~/.config/lazy-harness/config.toml`:

```toml
[profiles]
default = "personal"

[profiles.personal]
config_dir    = "~/.claude-personal"
roots         = ["~/code/personal", "~/notes"]
lazynorth_doc = "LazyNorth-personal.md"

[profiles.work]
config_dir    = "~/.claude-work"
roots         = ["~/code/work"]
lazynorth_doc = "LazyNorth-work.md"
```

Fields:

- **`default`** — which profile `~/.claude` symlinks to, and which profile is used when the cwd does not match any profile's roots.
- **`config_dir`** — the target directory for the profile. Can be anything, but the `~/.claude-<name>` convention is what the deploy and selftest assume.
- **`roots`** — list of directories; any cwd below one of these resolves to this profile. Longest-prefix match wins, so `~/code/work` beats `~/code` if both are declared.
- **`lazynorth_doc`** — optional. The filename inside the LazyNorth directory (if enabled in `[lazynorth]`) to pull strategic context from for this profile.

Profile management commands:

```bash
lh profile list                                           # show all with status
lh profile add work --config-dir ~/.claude-work \
                    --roots ~/code/work
lh profile remove experimental                            # cannot remove default
```

`list_profiles()` in `core/profiles.py` is the reader; `add_profile` / `remove_profile` are the writers. Removing the current default is refused — you must change the default first.

## Profile resolution — which profile am I in?

`resolve_profile(cfg, cwd=None)` in `core/profiles.py`:

```python
def resolve_profile(cfg: Config, cwd: Path | None = None) -> str:
    if cwd is None:
        cwd = Path.cwd()
    cwd_str = str(cwd.resolve())
    best_match = ""
    best_len = 0
    for name, entry in cfg.profiles.items.items():
        for root in entry.roots:
            root_str = str(expand_path(root))
            if cwd_str.startswith(root_str) and len(root_str) > best_len:
                best_match = name
                best_len = len(root_str)
    return best_match if best_match else cfg.profiles.default
```

Longest-matching-root wins. This is the rule that decides which `CLAUDE_CONFIG_DIR` a newly launched session points at — either via `lh run` (which wraps `claude` and sets the env var) or via a shell wrapper the user installs.

The rule matters when profiles overlap: if one profile says `roots = ["~/code"]` and another says `roots = ["~/code/work"]`, a session in `~/code/work/project` picks the second because its matching root is longer.

## Deploy flow — what `lh deploy` actually does

Module: `src/lazy_harness/deploy/engine.py`. Four functions, called in this order by `cli/deploy_cmd.py` — preceded by a snapshot.

### 0. The snapshot — taken before anything is written

Every deploy snapshots first. Not on a version change, not when the plan differs from disk: unconditionally, because each of those conditions can be wrong in the direction of *no snapshot when one was needed*, and the operation is cheap enough that guarding it costs more than running it. The managed artifacts total roughly 135 KB, so the ten kept snapshots are about 1.35 MB.

`deploy/snapshot.py` writes a **manifest** rather than a directory of loose files. One entry per artifact, carrying:

- its absolute destination path;
- its kind — `file`, `symlink`, or `absent` for something that does not exist yet and that a rollback must therefore **delete** rather than restore;
- the symlink target, where that applies;
- for a file, a content path unique **per destination**, not per basename. `~/.claude-lazy/settings.json` and `~/.claude-flex/settings.json` are two different files with one basename, so a basename-keyed backup would restore the second over the first.

Snapshots land in `~/.config/lazy-harness/backups/deploy/<ts>/`, pruned to the newest ten. That namespace is separate from `backups/migrate/<ts>/` on purpose: sharing a newest-wins parent would let `lh migrate --rollback` replay a deploy's log, and let a deploy's prune delete a migration's history.

`lh deploy --snapshot` records one and exits without deploying. `lh deploy --rollback` replays the newest: it restores file contents, repoints symlinks that still exist, and removes the artifacts the deploy created. The repoint is unconditional — under [ADR-009](https://github.com/lazynet/lazy-harness/blob/main/specs/adrs/009-profile-symlink-deploy.md) every profile artifact is an existing symlink, so a rollback that only recreated *missing* links would report success and change nothing.

### 1. `deploy_profiles(cfg)` — symlink profile content

For each profile in config:

1. Look under `~/.config/lazy-harness/profiles/<name>/`. If it does not exist, log "has no content dir" and skip.
2. Resolve the target via `expand_path(entry.config_dir)` and `mkdir -p` it.
3. Resolve **which** assets belong to this profile's agent (see the segments below), then call `ensure_symlink(source, target_dir/relative)` for each.

#### Segments — which assets reach which agent

The profile source is read as three layers, lowest precedence first:

```
~/.config/lazy-harness/profiles/personal/
├── CLAUDE.md        # root — deployed to every agent
├── head.md          # root — a system-doc segment, read by sync-system-doc
├── shared/          # deployed to every agent
│   └── skills/
├── claude-code/     # deployed only when this profile runs Claude Code
│   └── settings.json
└── codex/           # deployed only when this profile runs Codex
    └── hooks.json
```

The agent directories are named by the agent registry (`claude-code`, `codex`
and `copilot` today), never by a list typed into the deployer, so a new adapter
brings its segment name with it. A profile that has neither `shared/` nor an agent
directory is **entirely shared** — its root is deployed to whatever agent it
runs, which is the behaviour that predates segments. Nobody has to migrate to
keep a working profile.

A name carried by only one layer is linked whole, so `shared/skills/` arrives as
a single `skills/` symlink. A name carried by **more than one** layer is walked
and linked file by file, so `shared/skills/` and `codex/skills/` merge instead
of one replacing the other. On a same-name file the agent's segment wins and the
deploy prints a line naming both sources — a collision is reported, never
resolved in silence.

`lh profile migrate <name>` moves an existing flat profile into this layout; see
the [CLI reference](../reference/cli.md#lh-profile). The assembled system docs
and the segments they are built from stay at the root, because that is where
`lh profile sync-system-doc` writes them.

#### The ownership ledger

`ensure_symlink` reports an existing link and moves on, which means a link the
harness stopped generating would otherwise survive forever. Deploy therefore
records the links it created in `<config_dir>/.lazy-harness/links.json` and, on
the next run, removes the ones it owns and no longer generates.

Two things it never touches: a link the ledger does not name (that one is
yours), and a link it does name that you have since repointed somewhere outside
the profile source. The first deploy after upgrading has no ledger to read, so
it **adopts** every symlink in the config dir that resolves under that profile's
source — those are the harness's by construction — and says so once. Deleting
the ledger by hand is recoverable: the next deploy re-adopts.

`ensure_symlink` is idempotent: if the target already exists as a symlink pointing at the correct source, it reports `"exists"` and does nothing. If the target exists but points elsewhere (a stale link from a previous setup), it unlinks and relinks.

**A real file or directory at the target is not refused — it is moved aside.** `ensure_symlink` renames it to `<name>.bak` next to itself and writes the symlink in its place. That is a single slot, not a chain: if a later deploy finds another real file at the same target, the rename overwrites the previous `.bak`. Deploying over a target directory that holds hand-written content you care about is therefore a one-shot backup. `lh deploy` still has no dry-run mode, so there is nothing to *preview* with — but the deploy snapshot above is taken before any of this runs, so `lh deploy --rollback` undoes it. The `.bak` slot and the snapshot are separate mechanisms: the snapshot restores what the harness manages, the `.bak` is what `ensure_symlink` did with a real file it found in the way.

The linking is **per item**, not per directory. The target ends up with a mix of:

- Symlinks into the source (the user's versioned profile content)
- A `settings.json` written by `deploy_config` (see below)
- Runtime state Claude Code writes itself during sessions

All three coexist in the target without stepping on each other.

### 2. `deploy_config(cfg)` — plan and write the agent's own config documents

Hooks and MCP servers are one step, because an adapter is free to keep both in one file. Merging belongs to the adapter — parsing a native config format never was agent-neutral — and writing belongs to the engine. The cycle is:

1. **Discover.** Ask the profile's adapter for `config_targets()`: every file it may read or write, relative to the profile's config dir. Claude Code names `settings.json` and `.claude.json`.
2. **Read.** Read each target that exists and pass them as a mapping. A target that is not on disk is absent from the mapping, which is not the same as present and empty.
3. **Plan.** Call `plan_config(hooks, servers, existing, binary=...)` **once**, with the hook entries resolved for that profile and the MCP servers probed for this run — QMD (present on `PATH`), Engram (`[memory.engram].enabled` **and** present) and Graphify (`[knowledge.structure].enabled` **and** a `graphify-mcp` binary present; the CLI alone is not enough, older installs shipped no MCP entry point). One call, so an adapter whose hooks and MCP servers share a file emits a single write for it and cannot overwrite its own earlier result.
4. **Apply.** Write each returned document's text verbatim, delete the paths the plan retires (`artifact is None`, which is how an adapter stops generating a file it used to write), and print the diagnostics the plan carries: entries **preserved** because another tool owns them, entries **dropped** because the harness no longer generates them, and entries **repaired** because the agent would have rejected the file over them. A repair also leaves a `.bak` of the pre-merge bytes.

An adapter that has not been taught to plan its own config is refused before the first profile is written, rather than discovered halfway through a deploy.

Two consequences worth knowing. If no MCP tool is detected, no MCP document is written at all, rather than an empty block. And the MCP merge is additive: an entry for a tool you have since uninstalled is **not** pruned by a later deploy — remove it from `.claude.json` by hand.

Re-running `lh deploy` is safe and converges: the same config produces the same bytes, so a chezmoi-managed profile sees no diff on a redeploy.

Design: [ADR-024](https://github.com/lazynet/lazy-harness/blob/main/specs/adrs/024-mcp-server-orchestration.md) for the MCP half; the adapter/engine split is decision 4 of the 2026-09-13 multi-agent design.

### 3. `deploy_claude_symlink(cfg)` — the default shortcut

Creates `~/.claude → <default profile's target>`. This is the fallback that lets `claude` work without any env var. If the default is `personal`, running plain `claude` in a directory outside of any profile root still gets the personal profile.

## What the target directory looks like after deploy

Starting from an empty target:

```
~/.claude-personal/                          # (was empty)
├── CLAUDE.md              → ~/.config/lazy-harness/profiles/personal/CLAUDE.md
├── skills/                → ~/.config/lazy-harness/profiles/personal/shared/skills/
├── agents/                → ~/.config/lazy-harness/profiles/personal/shared/agents/
├── commands/              → ~/.config/lazy-harness/profiles/personal/shared/commands/
├── settings.json          (generated by deploy_config)
├── .lazy-harness/
│   └── links.json         (the ownership ledger — which links deploy created)
└── ...
```

The sources shown are the segmented layout; on an unmigrated profile the same
links point at the profile root instead.

After a few sessions, Claude Code itself adds:

```
~/.claude-personal/
├── ... (the above)
├── projects/                               # added by Claude Code
│   └── -Users-me-repos-lazy-lazy-harness/
│       └── 9a8b7c6d-...-....jsonl          # session JSONL
└── logs/
    ├── hooks.log
    └── compound-loop.log
```

The agent-written content lives under `projects/` and `logs/`. None of it is symlinked. None of it touches the source directory — the source stays read-only from Claude Code's perspective, which is the whole point of the separation.

Distilled memory (`MEMORY.md`, `decisions.jsonl`, `failures.jsonl`, `handoff.md`, `pre-compact-summary.md`) is **not** here. It lives in the knowledge store, under `<store root>/memory/<host>/<owner>/<repo>/`, keyed by the repository's git remote rather than by the path of the checkout — see the [architecture overview](../architecture/overview.md#data-model-three-persistent-stores). A `projects/<encoded-cwd>/memory/` directory in a target dir is either the legacy fallback (no store, or a checkout with no remote) or a leftover; `lh memory legacy-check` tells you which.

## Launching with a specific profile

Three ways, from explicit to implicit:

### 1. `lh run` (recommended)

```bash
lh run                       # uses resolved profile for cwd
lh run --profile work        # forces a specific profile
```

`lh run` sets `CLAUDE_CONFIG_DIR` based on `resolve_profile(cfg, cwd)` (or the `--profile` override) and `exec`s into the real `claude` binary. It uses `ClaudeCodeAdapter.resolve_binary()` to find `claude` while avoiding recursion into the `lh` wrapper — the resolver prefers the version-manager directory (`~/.local/share/claude/versions/`) and falls back to `shutil.which("claude")` with a filter to skip the `lh` entrypoint dir.

### 2. Manual env var

```bash
CLAUDE_CONFIG_DIR=~/.claude-work claude
```

Works without `lh run` at all. Useful if you want to wire profile selection into your own shell functions or direnv setup.

### 3. Plain `claude`

```bash
claude                       # uses ~/.claude → default profile
```

Works because of `deploy_claude_symlink`. Always points at the default profile regardless of cwd.

## Observability

```bash
lh profile list              # table: name, config_dir, roots, default?, exists?
lh selftest                  # runs profile_check + hooks_check + knowledge_check
```

`lh profile list` reads the config and walks each profile's `config_dir` to confirm the target exists. `profile_check` inside selftest goes further: it verifies every symlink inside each target dir resolves to a real file, and flags stale links left over from source moves.

## Common operations

**Add a new profile:**
```bash
mkdir -p ~/.config/lazy-harness/profiles/client-x
# Populate CLAUDE.md, skills/, etc. in that directory.
lh profile add client-x \
  --config-dir ~/.claude-client-x \
  --roots ~/repos/clients/x
lh deploy
```

**Move a profile's source:**
1. `mv ~/.config/lazy-harness/profiles/old ~/.config/lazy-harness/profiles/new`
2. Edit `config.toml` to match the new name.
3. `lh deploy` — stale symlinks in the target get relinked.

**Swap the default profile:**
Edit `[profiles].default` in config, then `lh deploy`. `~/.claude` is relinked to the new default's target.

**Delete a profile entirely:**
1. `lh profile remove <name>` (refuses if it is the default).
2. `rm -rf <config_dir>` if you want to wipe Claude Code's write-side state too. The source directory is untouched.

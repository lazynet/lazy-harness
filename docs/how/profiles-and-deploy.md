# How profiles and deploy work

A profile is the complete agent configuration for one isolated context — typically "personal", "work", a specific client, or an experimental sandbox. The framework ships profile management and a deploy engine that gets that configuration into the exact directory the agent reads from.

This page explains how the pieces fit. For the reasoning, see [ADR-001](../architecture/adrs/001-hybrid-architecture.md) and [ADR-009](../architecture/adrs/009-profile-symlink-deploy.md).

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
roots         = ["~/repos/lazy", "~/Documents"]
lazynorth_doc = "LazyNorth-personal.md"

[profiles.work]
config_dir    = "~/.claude-work"
roots         = ["~/repos/flex"]
lazynorth_doc = "LazyNorth-work.md"
```

Fields:

- **`default`** — which profile `~/.claude` symlinks to, and which profile is used when the cwd does not match any profile's roots.
- **`config_dir`** — the target directory for the profile. Can be anything, but the `~/.claude-<name>` convention is what the deploy and selftest assume.
- **`roots`** — list of directories; any cwd below one of these resolves to this profile. Longest-prefix match wins, so `~/repos/flex` beats `~/repos` if both are declared.
- **`lazynorth_doc`** — optional. The filename inside the LazyNorth directory (if enabled in `[lazynorth]`) to pull strategic context from for this profile.

Profile management commands:

```bash
lh profile list                                           # show all with status
lh profile add work --config-dir ~/.claude-work \
                    --roots ~/repos/flex
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

The rule matters when profiles overlap: if one profile says `roots = ["~/repos"]` and another says `roots = ["~/repos/flex"]`, a session in `~/repos/flex/project` picks the second because its matching root is longer.

## Deploy flow — what `lh deploy` actually does

Module: `src/lazy_harness/deploy/engine.py`. Three functions, called in this order by `cli/deploy_cmd.py`:

### 1. `deploy_profiles(cfg)` — symlink profile content

For each profile in config:

1. Look under `~/.config/lazy-harness/profiles/<name>/`. If it does not exist, log "has no content dir" and skip.
2. Resolve the target via `expand_path(entry.config_dir)` and `mkdir -p` it.
3. For every item directly inside the source dir (`CLAUDE.md`, `skills/`, `agents/`, etc.), call `ensure_symlink(source_item, target_dir/item_name)`.

`ensure_symlink` is idempotent: if the target already exists as a symlink pointing at the correct source, it reports `"exists"` and does nothing. If the target exists but points elsewhere (a stale link from a previous setup), it relinks. If the target exists as a real file or directory, it refuses — the deploy engine will not silently clobber real content.

The linking is **per item**, not per directory. The target ends up with a mix of:

- Symlinks into the source (the user's versioned profile content)
- A `settings.json` written by `deploy_hooks` (see below)
- Runtime state Claude Code writes itself during sessions

All three coexist in the target without stepping on each other.

### 2. `deploy_hooks(cfg)` — generate agent-native hook config

1. Look up the agent adapter via `get_agent(cfg.agent.type)`.
2. For each event declared in `cfg.hooks` (e.g. `session_start`, `session_stop`, `pre_compact`), call `resolve_hooks_for_event(cfg, event)` — this returns the resolved builtin or user-hook paths for that event.
3. Build a `hook_commands` dict mapping event name to a list of `"<python> <hook-path>"` command strings.
4. Call `agent.generate_hook_config(hook_commands)`. For Claude Code (`ClaudeCodeAdapter`), this returns a dict in the shape Claude Code's `settings.json` expects:
   ```json
   {
     "SessionStart": [
       {"matcher": "", "hooks": [{"type": "command", "command": "/path/to/python /path/to/hook.py"}]}
     ],
     "Stop": [
       {"matcher": "", "hooks": [{"type": "command", "command": "..."}]}
     ]
   }
   ```
5. For each profile, read its existing `settings.json` (if present — parsed leniently, corruption falls back to `{}`), replace the `hooks` key with the generated dict, and write it back to `<target_dir>/settings.json`.

The result is that every profile has its own `settings.json` with the exact hook wiring derived from config. Re-running `lh deploy` is safe — the generated block is always rewritten from config, so a user who changes `config.toml` and runs deploy gets a consistent update.

### 3. `deploy_claude_symlink(cfg)` — the default shortcut

Creates `~/.claude → <default profile's target>`. This is the fallback that lets `claude` work without any env var. If the default is `personal`, running plain `claude` in a directory outside of any profile root still gets the personal profile.

## What the target directory looks like after deploy

Starting from an empty target:

```
~/.claude-personal/                          # (was empty)
├── CLAUDE.md              → ~/.config/lazy-harness/profiles/personal/CLAUDE.md
├── skills/                → ~/.config/lazy-harness/profiles/personal/skills/
├── agents/                → ~/.config/lazy-harness/profiles/personal/agents/
├── commands/              → ~/.config/lazy-harness/profiles/personal/commands/
├── settings.json          (generated by deploy_hooks)
└── ...
```

After a few sessions, Claude Code itself adds:

```
~/.claude-personal/
├── ... (the above)
├── projects/                               # added by Claude Code
│   └── -Users-me-repos-lazy-lazy-harness/
│       ├── 9a8b7c6d-...-....jsonl          # session JSONL
│       └── memory/
│           ├── MEMORY.md                   # written by the agent
│           ├── decisions.jsonl             # compound loop
│           ├── failures.jsonl              # compound loop
│           ├── handoff.md                  # compound loop
│           └── pre-compact-summary.md      # pre-compact hook
└── logs/
    └── hooks.log
```

The agent-written content lives under `projects/` and `logs/`. None of it is symlinked. None of it touches the source directory — the source stays read-only from Claude Code's perspective, which is the whole point of the separation.

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
lh deploy --dry-run          # preview what would be linked
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

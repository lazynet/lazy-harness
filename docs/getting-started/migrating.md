# Migrating an existing setup

If you already have a Claude Code setup — vanilla (`~/.claude/`) or customized — `lh migrate` upgrades it to a lazy-harness installation without losing data.

## What gets detected

The migration detector scans for:

| Target | Location | What happens |
|---|---|---|
| Vanilla Claude Code | `~/.claude/` | Profile created, settings translated |
| Custom profile dirs | `~/.claude-<name>/` | Each becomes a lazy-harness profile |
| Symlinks into other repos | `~/.claude-<name>/*` | Flattened into real files in the profile dir |
| Deployed scripts | `~/.local/bin/lcc-*`, etc. | Removed (superseded by `lh`) |
| LaunchAgents | `~/Library/LaunchAgents/com.*` | Cataloged; optionally replaced with `lh scheduler` jobs |
| Knowledge directories | Paths referenced in existing configs | Cataloged; pointed at, not moved |
| QMD collections | `qmd status` | Reconfigured to point at the new knowledge path |

Detection is read-only and idempotent. You can run it as many times as you want without side effects.

## The dry-run gate

`lh migrate` without `--dry-run` refuses to execute unless there is a dry-run marker less than one hour old in the backup directory. This is a safety rail: you must review the plan before running it.

```bash
lh migrate --dry-run
```

Output is a human-readable plan like:

```
Detected:
  - 2 profile dirs: ~/.claude-personal, ~/.claude-work
  - 8 deployed scripts in ~/.local/bin/
  - 3 LaunchAgents (com.example.*)
  - QMD with 5 collections

Plan:
  1. Backup → ~/.config/lazy-harness/backups/<ts>/
  2. Generate config.toml with 2 profiles
  3. Relocate profiles to ~/.config/lazy-harness/profiles/
  4. Translate hooks from settings.json
  5. Replace 3 LaunchAgents with lh scheduler jobs
  6. Remove 8 script symlinks
  7. Point knowledge at ~/Documents/existing-knowledge
  8. Reconfigure 5 QMD collections
  9. Run lh selftest

Run `lh migrate` to execute this plan (within 1 hour).
```

## Executing

```bash
lh migrate
```

Each step logs what it is about to do. The executor takes a backup snapshot first and writes a rollback log as it goes.

## Rolling back

If something feels wrong after migration:

```bash
lh migrate --rollback
```

This reads the most recent rollback log and reverses every step in order. Rollback is idempotent — you can run it multiple times safely.

For an automatic rollback (if a step fails mid-execution), no action is needed — the executor does it for you and exits non-zero.

## Post-migration checklist

1. Run `lh selftest`. Every check should pass.
2. Start an agent session with your first profile. Verify context injection works: the first message should include a banner like `Session context loaded: on main | Last session: ...`.
3. If you had recurring jobs (cron / launchd), verify they still run. `lh scheduler ls` should list everything.
4. Version your profiles. Example with chezmoi:

```bash
cd ~/.config/lazy-harness
chezmoi add profiles/
```

5. Keep the backup directory until you have used the migrated setup for at least a week without issues.

## Known limitations

- **Windows** is not supported. The migration will refuse to run.
- **Arbitrary custom hooks** are best-effort translated. Complex hook chains may need manual review post-migration. Run `lh doctor` to see hook warnings.
- **Profiles containing broken symlinks** abort the migration with a clear error. Fix the underlying symlinks first, then retry.

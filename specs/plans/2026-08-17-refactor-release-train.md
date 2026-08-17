# Refactor release train — ordering, branches, and availability gates

**Date:** 2026-08-17
**Governs:** the four plans below. Read this before starting any of them.

| Plan | Waves | Spec |
|---|---|---|
| [`2026-08-17-config-persistence-plan.md`](2026-08-17-config-persistence-plan.md) | 1 | [capability registry design](../designs/2026-08-17-capability-registry-design.md) D5 |
| [`2026-08-17-linux-parity-plan.md`](2026-08-17-linux-parity-plan.md) | 2, 3, 4 | [linux parity design](../designs/2026-08-17-linux-parity-design.md) |
| [`2026-08-17-capability-registry-plan.md`](2026-08-17-capability-registry-plan.md) | 6 | [capability registry design](../designs/2026-08-17-capability-registry-design.md) |
| [`2026-08-17-config-tui-plan.md`](2026-08-17-config-tui-plan.md) | 5, 7, 8, 9 | [config TUI design](../designs/2026-08-17-config-tui-design.md) |

## The constraint that sets the order

`refactor:`, `chore:`, `test:`, `ci:` and `docs:` produce **no version bump** (`specs/workflow/release-flow.md`). A branch whose PR title carries one of those types never cuts a release, so `uv tool install --reinstall` has nothing to pull and the change cannot be deployed or verified against an installed binary in isolation.

Combined with the repo's binary-first gate — *repository state and deployed state diverge the moment a release is cut; verify the binary, never the checkout* — this yields two rules:

1. **A wave that must be deployed and verified on its own gets a `fix:` or `feat:` PR title.** Anything else rides along with the next release that does.
2. **A wave titled `refactor:` must be behaviour-preserving, and must prove it with an identity fixture** — captured output before, asserted byte-identical after. If a change needs independent deployment to be verified safely, it is not behaviour-preserving and must not be titled `refactor:`.

Under squash merge the PR title is the only message release-please sees. Title each PR after the **largest** change it carries. v0.36.1 shipped a feature as a patch by getting this wrong.

## Order

Ranked by impact, then by dependency. Waves 1 and 2 are live bugs; 3 and 4 deliver the Linux target; 5 through 9 build toward the TUI.

| # | Branch | PR type | Release | Blocks | Blocked by |
|---|---|---|---|---|---|
| 1 | `fix/config-round-trip` | `fix:` | 0.39.1 | 6, 9 | — |
| 2 | `fix/scheduler-schedule-translation` | `fix:` | 0.39.2 | 4 | — |
| 3 | `fix/scheduler-job-state` | `fix:` | 0.39.3 | 4, 5 | 2 |
| 4 | `feat/systemd-cron-backends` | `feat:` | 0.40.0 | — | 3 |
| 5 | `refactor/view-renderables` | `refactor:` | none — rides wave 7 | 7 | 3 |
| 6 | `refactor/capability-registry` | `refactor:` | none — rides wave 7 | 8 | 1 |
| 7 | `feat/tui-observe` | `feat:` | 0.41.0 | 8 | 5 |
| 8 | `feat/tui-configure` | `feat:` | 0.42.0 | 9 | 6, 7 |
| 9 | `feat/tui-write` | `feat:` | 0.43.0 | — | 1, 8 |

### Why this order

- **Wave 1 first** because it is active data loss (51 keys per `save_config` call) and because waves 6 and 9 both write config. Nothing else may land before a config write is safe.
- **Wave 2 second** because six declared jobs are over-executing right now, between 6× and 168×. It is independent of everything, so it costs nothing to ship early.
- **Wave 3 before 4** because `SystemdBackend` needs the runner seam to be testable and the `JobState` vocabulary to report honestly. Building it first would mean writing it twice.
- **Wave 5 after 3** — they collide. Wave 3 rewires `views/cron.py` and `views/overview.py` to drop `launchctl_loaded`; wave 5 changes every view's signature. Same files, same lines.
- **Wave 6 after 1** because its selftest check asserts that every capability's config path survives a round trip, which is exactly what wave 1 fixes.
- **Wave 9 last** because it is the only wave that writes config from an interactive surface.

### What can run in parallel

Wave 6 touches `plugins/`, `features.py`, `hooks/loader.py`, `deploy/defaults.py`. Waves 2–4 touch `scheduler/` and `monitoring/views/`. Disjoint — **wave 6 may run in its own worktree concurrently with 2, 3 and 4**, once wave 1 has merged.

Everything else is sequential. Two worktrees is the practical ceiling here; more than that and the merge order stops being obvious.

## Deploy procedure — run this after every releasing wave

From `CLAUDE.md`: *deploying a hook is binary-first.* Wiring new config against an old binary runs the new config against the old code.

```bash
# 1. Merge the feature PR. Wait for release-please to open `chore(main): release X.Y.Z`.
# 2. Merge the release PR. Confirm the tag exists.
gh release view vX.Y.Z --repo lazynet/lazy-harness

# 3. Reinstall from the ROOT CHECKOUT, never from a worktree, never editable.
cd ~/repos/lazy/lazy-harness
uv tool install --reinstall 'git+https://github.com/lazynet/lazy-harness@vX.Y.Z'

# 4. Grep SITE-PACKAGES, not the checkout. This is the step that catches a cached wheel.
SP=$(uv tool dir)/lazy-harness/lib/python3.*/site-packages/lazy_harness
grep -rn "<a string introduced by this wave>" "$SP" || echo "NOT IN BINARY — stop here"

# 5. Only now touch config.toml, if the wave needs it.
# 6. Deploy and verify the artefact, not the exit code.
lh deploy
# 7. Health check.
lh selftest
# 8. chezmoi, if the file is managed.
chezmoi re-add ~/.config/lazy-harness/config.toml
```

`--force` is not sufficient — it reuses a cached wheel. `--reinstall` is the flag.

## Availability gates, per wave

These are the checks that make "release in order without affecting availability" true rather than hoped for. Each one exists because the corresponding wave can break something already in use.

### Wave 1 — config persistence

**Risk:** `save_config` is the only path that rewrites the user's config. A wrong fix corrupts it rather than preserving it.

**Gate, before merging:**
```bash
cp ~/.config/lazy-harness/config.toml /tmp/cfg-before.toml
uv run python -c "
from pathlib import Path
from lazy_harness.core.config import load_config, save_config
p = Path('/tmp/cfg-before.toml'); q = Path('/tmp/cfg-after.toml')
q.write_bytes(p.read_bytes()); save_config(load_config(q), q)
"
diff <(sort /tmp/cfg-before.toml) <(sort /tmp/cfg-after.toml)
```
Must show no removed lines. Run against the *real* config, not a fixture — the fixture is the unit test, this is the acceptance test.

**Gate, after deploying:** `lh selftest` passes, and `lh profile list` still shows both profiles.

### Wave 2 — schedule translation

**Risk:** this is a **behaviour change on upgrade**. Six jobs currently run hourly regardless of what they declare. After this wave they run on their declared cadence, which for most of them is *less often*.

**Mandatory manual gate before reinstalling.** Print what each job declares and what it will become:
```bash
uv run python -c "
from pathlib import Path
from lazy_harness.core.config import load_config
from lazy_harness.core.paths import config_file
for j in load_config(config_file()).scheduler.jobs:
    print(f'{j.name:<22} declara {j.schedule:<16} {j.command}')
"
```
For each: decide whether the declared schedule is still what you want *now that it will be honoured*. A `qmd-sync` declaring `0 */6 * * *` has been syncing hourly for months; going to every six hours may be a freshness regression you would rather fix by editing the declaration than by keeping the bug.

**Do not skip this.** It is the one place in the train where the correct fix degrades something that currently works by accident.

**Gate, after deploying:**
```bash
lh scheduler install
plutil -p ~/Library/LaunchAgents/com.lazy-harness.*.plist | grep -A4 -E "StartCalendarInterval|StartInterval"
```
Confirm the intervals match the declarations. Then `lh status cron`.

### Wave 3 — job state

**Risk:** low. Read-only surfaces. `lh status cron` and `lh status overview` gain a `?` state that did not exist.

**Gate:** run both before and after; the macOS output must be equivalent, since `launchctl` is present and every job resolves to `loaded` or `not_loaded`. A `?` appearing on macOS means the backend detection broke.

### Wave 4 — systemd and cron backends

**Risk to macOS: none.** `detect_backend` returns `LaunchdBackend` on Darwin and the new code never executes.

**Risk on Linux: the whole point.** Verification is end-to-end and cannot be done in CI:

1. On the workstation: install a job declaring a non-daily schedule, confirm `systemctl --user list-timers` shows the declared interval.
2. On Octavio or Marge, over ssh, with `Linger=no`: confirm `install` warns and `lh selftest` fails the linger check.
3. Enable lingering, reinstall, **log out completely**, wait for the window, then `journalctl --user -u lazy-harness-<job>` must show it fired with nobody logged in.

Step 3 is the acceptance criterion. `systemctl` reporting `enabled` is not evidence that the job runs.

### Waves 5 and 6 — the refactors that do not release

**Risk:** they sit in `main`, unshipped, until wave 7 cuts `0.41.0`. That release then carries three waves at once, and a post-deploy failure cannot be bisected by version.

**Mitigation is the identity fixture, not the release cadence.**

- Wave 5: capture every `lh status <sub>` output into `tests/fixtures/status-output/`, assert byte-identical after the refactor.
- Wave 6: capture each profile's `settings.json` generated by `lh deploy`, assert byte-identical after `DEFAULT_HOOKS` becomes derived from the registry.

Wave 6's fixture is the more important of the two. A hook that the registry believes is enabled but that `lh deploy` no longer writes to `settings.json` disables it silently — the framework does not warn, the agent simply stops running it. That failure has occurred in this repo before.

**Extra gate for wave 6, after wave 7 deploys:**
```bash
for p in ~/.claude-lazy ~/.claude-flex; do
  echo "== $p"; python3 -c "
import json,sys
h=json.load(open('$p/settings.json')).get('hooks',{})
for ev,entries in sorted(h.items()):
    for e in entries:
        for c in e.get('hooks',[]):
            print(f'  {ev:<20}', c.get('command','')[-60:])
"; done
```
Compare against the same output captured before. Any hook that disappeared is a regression, not a cleanup.

### Waves 7 and 8 — TUI, read paths

**Risk:** additive. A new subcommand and an optional dependency. `lh status` is untouched.

**Gate:** `lh tui` without the extra installed must print the install hint and exit non-zero, not traceback. Verify in a non-TTY (`lh tui < /dev/null | cat`) that it exits cleanly instead of emitting escape codes.

### Wave 9 — TUI writes

**Risk:** highest in the train. An interactive surface writing config and triggering deploy.

**Gates:**
- The save transaction writes `config.toml.bak` before touching `config.toml`. Confirm the backup exists after the first save.
- The per-toggle verification step must be *observed failing*. Make one profile's config dir read-only, toggle a hook on, save, and confirm the TUI reports `✗` for that profile rather than a global success. A verification step never seen failing has not been tested.
- Toggle one hook, save, then diff the raw TOML. The only change may be the intended one — this is the regression net for wave 1.

## Rollback

Every wave is a separate release, so rollback is a pin:

```bash
uv tool install --reinstall 'git+https://github.com/lazynet/lazy-harness@vX.Y.Z-1'
lh deploy && lh selftest
```

Two waves need more than a version pin:

- **Wave 1:** if config was already rewritten, restore from `config.toml.bak` or from chezmoi's source before downgrading. Downgrading alone does not restore lost keys.
- **Wave 2:** downgrading restores the hourly-for-everything behaviour. Regenerate the plists with `lh scheduler install` after the downgrade, or the corrected plists stay on disk under an old binary.

## Commit and PR hygiene

- Branch names exactly as in the table. `/new-worktree <type>/<short-name>` creates them.
- Every commit inside the worktree, never bouncing to the root checkout.
- `/tdd-check` before every commit — pytest, ruff, and `mkdocs build --strict`, all three.
- No `Co-Authored-By`, no AI-attribution trailers, no `--no-verify`.
- Never run `uv sync` or `uv tool install` from a worktree. Config generators embed the invoking interpreter's path, and worktree runs have degraded `uv.lock` before. Those commands belong in the root checkout.
- `gh` is on the `mvago-flx` account by default. Switch to `lazynet` before any push or PR here, and switch back after.

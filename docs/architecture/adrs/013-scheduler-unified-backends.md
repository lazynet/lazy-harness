# ADR-013: Unified scheduler interface over launchd, systemd, and cron

**Status:** accepted
**Date:** 2026-04-13

## Context

Several framework features need recurring jobs: QMD re-index on a schedule, compound-loop sweeps, stats ingestion, learnings review. Each operating system offers a different scheduler:

- **macOS:** launchd, with property-list (`.plist`) files in `~/Library/LaunchAgents/`.
- **Linux with systemd:** systemd user units (`~/.config/systemd/user/*.timer` + `*.service`).
- **Linux without systemd / minimal distros:** cron.
- **Windows:** Task Scheduler (out of scope today, on the roadmap).

We need the user to declare recurring jobs once, in `config.toml`, and have `lh scheduler install` do the right thing regardless of platform. "The right thing" must be reversible — `lh scheduler uninstall` has to remove exactly what was installed.

## Decision

Plugin pattern over a small protocol. One `SchedulerBackend` protocol, three implementations, one auto-detector.

- **Protocol (`scheduler/base.py`).** Three methods: `install(jobs)`, `uninstall(jobs)`, `status()`. Each returns a list describing what happened or the current state.
- **Backends.**
  - `LaunchdBackend` (`scheduler/launchd.py`) — writes `.plist` files, loads them with `launchctl`, lists them by parsing `launchctl list`.
  - `SystemdBackend` (`scheduler/systemd.py`) — writes `.timer` + `.service` unit files, enables them with `systemctl --user`.
  - `CronBackend` (`scheduler/cron.py`) — edits the user's crontab, marks lazy-harness entries with a comment prefix for safe removal.
- **Auto-detection (`scheduler/manager.py:detect_backend`).** `platform.system() == "Darwin"` → launchd. Linux with `systemctl` on PATH → systemd. Otherwise → cron. Overridable via `[scheduler].backend` in config (`"auto" | "launchd" | "systemd" | "cron"`).
- **Job declaration.** In `config.toml`:
  ```toml
  [scheduler]
  backend = "auto"

  [scheduler.jobs.qmd_reindex]
  schedule = "0 */6 * * *"      # cron syntax, translated per backend
  command  = "qmd update"
  ```
  The config loader raises `ConfigError` if `schedule` or `command` is missing — silent omission is too easy a mistake.
- **Reversibility.** `install` returns the list of artefacts it wrote (plist paths, unit paths, cron lines). `uninstall` removes them by name. The state lives on disk, not in a framework-managed database.

## Alternatives considered

- **Python-level scheduler (APScheduler, Celery beat).** Requires a long-running process; the framework intentionally has no daemon ([ADR-006](006-hooks-subprocess-json.md), [ADR-008](008-compound-loop-async-worker.md)). Rejected.
- **Only cron.** Portable-ish, but cron on macOS is second-class (Full Disk Access quirks, PATH environment surprises) and systemd timers are the native answer on most modern Linux desktops. Rejected on UX grounds.
- **Only launchd + only systemd, drop cron fallback.** Fine on workstation distros, breaks on minimal VMs and containers where neither is installed. Cron is the ubiquitous floor.
- **Shell scripts the user copies into their own crontab / LaunchAgents.** Makes `lh scheduler uninstall` impossible without a separate tracking file. Rejected.
- **Don't ship a scheduler; recommend users run jobs manually.** Loses recurring-memory features that are the whole point of a harness. Rejected.

## Consequences

- Adding a new platform backend = implementing the protocol in one file plus a `detect_backend` branch. Windows Task Scheduler follows exactly this path when it arrives.
- The jobs defined in config are the single source of truth. A user versioning `config.toml` with chezmoi can replicate their scheduled jobs on a new machine with `lh scheduler install`, regardless of which platform they land on.
- Backend-specific quirks (environment variable propagation, PATH inheritance, working directory resolution) are isolated inside the backend. The rest of the framework does not care.
- `lh scheduler status` queries the live backend — it reports what the OS actually has scheduled, not what `config.toml` claims. This distinction matters when a user hand-edits their plists and the framework has to notice the drift.
- Cron schedule syntax is the lingua franca in `config.toml`. launchd and systemd backends translate it into their native formats on install. The translation is lossy for edge cases (e.g. launchd has no native second-level scheduling), documented in each backend module.
- The selftest has a `scheduler_check` that confirms the detected backend is reachable and every declared job is present. This is how we catch "you ran `lh scheduler install` on launchd but then switched to systemd" drift.

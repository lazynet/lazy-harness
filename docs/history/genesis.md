# Genesis

`lazy-harness` began as `lazy-claudecode`: a personal Claude Code harness, private, single-user, and deliberately unopinionated about being reusable.

The first version was a handful of bash scripts in `~/.local/bin/` — a pre-compact hook, a session exporter, a status line renderer — wired into Claude Code via `settings.json`. It was enough to prove an idea: Claude Code could be a daily driver if you gave it the scaffolding it lacked out of the box.

## The slow drift toward a framework

Over three months, `lazy-claudecode` grew organically. Each new need produced another script, another cron entry, another small abstraction. A profile system appeared when the author needed to isolate personal from work use. A monitoring pipeline appeared when the "how much did this cost" question became daily. A knowledge directory appeared when session amnesia became untenable.

What didn't appear was a boundary. Every feature was tangled with every other feature. Every path assumed one specific user on one specific machine. Upgrading from version `0.1.0` to `0.2.0` meant editing bash scripts in place and hoping the integration tests — the maintainer's daily workflow — caught the regressions.

By version `0.3.0`, the pattern was clear: the interesting half of the codebase was generic (profiles, hooks, knowledge, monitoring, scheduling) and the uninteresting half was personal (lazynet's specific `CLAUDE.md`, his specific skills, his vault paths). Mixing them in one repo had become the limiting factor.

## The extraction

The rewrite happened in four phases over two weeks:

1. **Phase 1 — bootstrap.** Stand up `lazy-harness` as a Python package with `click` for the CLI, `tomllib` for config, and a typed adapter for Claude Code. Port the core feature set (profiles, knowledge, basic monitoring).
2. **Phase 2 — hooks + monitoring.** Port the hook engine as a cross-platform system with built-in hooks. Migrate SQLite ingestion and add the `lh status` views.
3. **Phase 3 — knowledge, QMD, scheduler.** Port the knowledge directory and session exporter. Unify launchd / systemd / cron under `lh scheduler`. Add `qmd-context-gen` as a built-in scheduler job.
4. **Phase 4 — migrate + cutover.** Build `lh migrate` as the tool that took the maintainer's own `lazy-claudecode` installation and upgraded it to `lazy-harness`. Ship docs. Archive `lazy-claudecode`.

Phase 4 was the moment of truth. If `lh migrate` could not migrate the author's own machine — the project that the tool was born from — there was no chance it could work for anyone else.

It worked.

## Why this matters

`lazy-harness` is `lazy-claudecode` with the personal tangles excised. Every feature has a coherent responsibility. Every path is configurable. Every platform-specific detail sits behind an adapter. The tradeoff — a rewrite that cost two weeks of intense work — was worth it because the result is a framework, not a setup.

The original `lazy-claudecode` repo is archived read-only. It is preserved for context and for the lessons it taught, but it is no longer a living thing. The framework it became is.

If you are reading this because you are considering extracting a personal tool into a shared framework: the answer is "only when the ratio of reusable to personal exceeds one-to-one". Below that ratio, you are moving complexity around, not reducing it. Above it, the rewrite pays for itself within weeks.

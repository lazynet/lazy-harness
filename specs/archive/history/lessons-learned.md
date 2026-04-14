# Lessons learned

Patterns and mistakes from the evolution of `lazy-claudecode` into `lazy-harness`. Distilled from memory audits, session exports, and postmortem notes.

## The memory pipeline grows undisciplined fast

The original 3-layer memory system (session export, compound-loop learnings, session-context injection) shipped with a permissive 2-message threshold so that nothing meaningful would slip through. An audit in early 2026 found 992 exported sessions, of which 859 were trivial two-message exchanges produced by subagents and quick checks. The compound-loop layer had generated 200 learning notes, many in clusters of 3 to 5 near-duplicates of the same concept.

Two root causes compounded each other. The export filter let subagent JSONLs through, and the compound-loop deduplicated only by filename slug, so any title variation produced a fresh duplicate. Existing learnings were never injected into the Haiku prompt, so the model had no way to know it was repeating itself.

The framework now treats deduplication as a generation-time concern, not a storage-time one. Thresholds filter trivial sessions upstream, and prior learning titles are passed into the prompt with an explicit "do not repeat semantic equivalents" rule. The general lesson: in LLM-driven memory systems, push dedup into the decision context, not into post-hoc filters.

## CLAUDE.md duplication via symlinks is a silent trap

ADR-009 introduced profile isolation through `CLAUDE_CONFIG_DIR`, with `~/.claude` left as a symlink to `~/.claude-lazy` for compatibility with third-party tools that hardcode the canonical path. Claude Code does not deduplicate `CLAUDE.md` files by inode, so the same file gets loaded twice on every session, costing roughly 1.1k tokens of pure noise.

The cost is small in a 1M context window, but the failure mode is silent: nothing in the tooling reports it, and it only surfaces when someone manually inspects token accounting. The harness now treats "config layers may be loaded more than once" as an explicit invariant when designing profile structures, and prefers keeping per-profile `CLAUDE.md` files lean so any duplication is cheap.

## Bash scripts in monitoring code scale badly

`lcc-status` started life as a bash script using `printf` with hardcoded column widths and `jq` pipelines for aggregation. It worked until real data exceeded the assumed widths and the output table corrupted itself. Around the same time, log parsing in the cron status view broke because the regex did not match the actual timestamp format, and a missing `case` branch silently rendered an em dash instead of a real value for one of the tools.

The rewrite moved everything to Python with `rich` for rendering, split into a data layer, a render layer, and an orchestration entry point dispatched through a thin bash wrapper that uses `uv run --script` with PEP 723 metadata. The lesson generalises: once a shell script is doing aggregation, formatting, and presentation across multiple data sources, the bash idioms stop paying for themselves. Move to a real language before the printf widths bite.

## Post-deployment test passing is not operational readiness

When deprecated bash hooks were superseded by `lh` subcommands, the migration updated `settings.json` to reference the new entry points. The old script binaries were left in `~/.local/bin/` on the assumption that nothing would call them. They kept firing.

Two effects collided. Long-running Claude instances cache `settings.json` in memory at startup and do not reload it per session, so any previously-running process kept pointing at the old hooks. And because the binaries still existed on disk, those references resolved successfully and produced silent side effects.

The framework now treats hook deprecation as a removal checklist, not a config edit: update `settings.json`, delete the binary the same minute, and verify via logs that no further invocations land. Removing the file is what enforces fail-fast behavior on any cached configuration.

## Plans must validate output-consumer contracts

The lazy-harness phase 4 plan specified a TOML schema using `[profiles.items.<name>]` for the generated `config.toml`. The `core/config.py` parser iterated `raw.get('profiles', {})` directly, which means that schema would have produced a single profile literally named `items`. The mistake propagated through the generator step, the wizard, and three test files before anyone noticed, because reviewers checked code-against-spec rather than spec-against-runtime.

A second instance of the same shape: the launch agent detector used a glob of `com.lazy.*.plist`, but the actual labels on the system were `com.lazynet.*`, so the detector reported zero agents while five were running. Both bugs were specs that never round-tripped through their consumers.

The lesson is now a hard rule on plans that produce structured output: validate the output-consumer contract inside the plan itself, with a literal end-to-end example. Spec compliance is not the same as runtime correctness.

## The harness produces, the vault analyzes

`learnings-review.sh` was a weekly Sunday cron job living in `lazy-claudecode` that scanned `Meta/Learnings/` and asked Claude to flag contradictions, duplicates, and decay. It was technically functional, but it sat on the wrong side of a boundary: the harness writes to the vault as a side effect of agent interactions, and having the harness also analyze that data conflated two responsibilities.

The decision was to port the job to a `lazy-vault` subcommand and remove it from the harness entirely. The harness produces session exports, hook output, and compound-loop learnings; the vault tool owns higiene, contradiction detection, and weekly synthesis of that corpus. Clean separation makes both sides easier to reason about and prevents the harness from accumulating second-brain features that do not belong to it.

## Portability assumptions need version floors, not vibes

The first version of `lcc-admin` used `local -n` namerefs in its profile parser. Namerefs require bash 4.3+, but macOS still ships bash 3.2 by default, so the script broke on every machine that mattered. The fix was mechanical (rewrite to use globally-namespaced variables with a `P_` prefix) but the underlying mistake was treating "modern bash" as a default rather than a constraint to verify.

For any distributable shell script, the framework now establishes a minimum bash version explicitly and tests against the oldest target before merging. Namerefs, `mapfile`, and `declare -A` are all version-guarded or avoided. The general principle: portability claims are not defaults, they are requirements that need test evidence.

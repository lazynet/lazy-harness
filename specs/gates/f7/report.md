# F7 isolation gate — the step 4 measurement (2026-09-15, against 0.67.0)

**This is a frozen measurement, not a description of the current gate.** It records what
`isolation-gate.sh` asserted and found when three builtins were migrated and two were asserted.
Eight are migrated now, the asserted and known-gap sets are derived from the registry rather
than typed, and every count below is the 0.67.0 run's, not today's. Read the script's header for
what the gate asserts now; read this for what was measured then.

Artefacts, versioned under `specs/gates/f7/`:

| File | What it is |
|---|---|
| `isolation-gate.sh` | The gate. `./isolation-gate.sh <path-to-lh>`; exit 0 = PASS, 1 = FAIL, 2 = setup error. |
| `fake-lh.sh` | Shared body of the two control shims; not run directly. |
| `fake-lh-fixed.sh` | Control that must **exit 0**: every hook honours the invoking profile. |
| `fake-lh-security-only.sh` | Control that must **exit 1**: only `pre-tool-use-security` does. |

The `run-*/` trees and `run-*.log` files from the original runs are run artefacts and are
deliberately not versioned.

## The scope correction, verified

The correction is right, and the earlier report was wrong on this point. Verified against the
registry rather than by reading the file:

```
$ uv run python -c "from lazy_harness.hooks.loader import _BUILTIN_HOOKS; ..."
migrated  (3): ['context-inject', 'pre-tool-use-security', 'stop-verify-guard']
unmigrated(15): ['compound-loop', 'engram-persist', 'herdr-context-gauge',
                 'post-tool-use-ansible-lint', 'post-tool-use-format',
                 'post-tool-use-sync-claude', 'pre-compact', 'pre-tool-use-git-scope',
                 'pre-tool-use-memory-size', 'pre-tool-use-read-size',
                 'session-start-preflight', 'session-end', 'session-export',
                 'stop-context-rotate', 'user-prompt-goal']
```

`migrated=True` appears at exactly three sites in `hooks/loader.py` (lines 106, 143, 157).
`session-export`, `compound-loop` and `session-end` are unmigrated: `cli/hooks_cmd.py` takes the
`if spec.migrated:` branch only for the three, and otherwise calls `main_fn()` with **no
arguments** — the `--profile` click option is parsed and discarded. `loader.PRE_RUNNER_AGENT`
("claude-code") says so directly: *"a builtin that has not moved to the runner reads stdin
itself, in Claude Code's shape, and exits with its own code — so deploying one to any other agent
is a guess."* Asserting on those hooks made the gate fail for something outside the step 4
contract, and would have kept failing after a correct fix.

**`stop-verify-guard` is migrated but has no site in scope and is skipped.** It never writes
`hooks.log`: `grep -n "hooks.log\|make_log\|agent_runtime_dir\|get_agent"
src/lazy_harness/hooks/builtins/stop_verify_guard.py` returns nothing. Its only sink is the
metrics DB through `monitoring.db.resolve_db_path()` (`stop_verify_guard.py:64-67`, used at
`:111`), which is scoped by `LH_DATA_DIR`, not by the agent runtime dir. The gate prints the
skip and its reason on every run.

**Asserted: `context-inject`, `pre-tool-use-security`. Nothing else.**

## Blast radius — unchanged, and said out loud

Every child runs under `env -i` with:

```
CLAUDE_CONFIG_DIR -> $RUN/global-claude     # NOT ~/.claude-lazy, NOT ~/.claude-flex
HOME              -> $RUN/home              # so the `~/.codex` last resort is fake
LH_CONFIG_DIR / LH_DATA_DIR / LH_CACHE_DIR -> under $RUN
PATH              -> /usr/bin:/bin          # excludes ruff and ansible-lint (~/.local/bin)
```

`$RUN/global-claude` is what the assertions **treat as "the global dir"**: a line landing there
is scored as a leak, exactly as one in `~/.claude-lazy` would be. The four real directories are
fingerprinted as a check on this script's containment, not on the build — in the 0.67.0 run all
four came back `untouched (mtime + counts)` with zero token lines.

The `PATH` choice is load-bearing, not incidental: it is what drives `post-tool-use-format` and
`post-tool-use-ansible-lint` down their binary-missing branches, the only branches on which they
log at all.

## Fixture

`[agent].type = "claude-code"` globally while the throwaway profile declares `agent = "codex"`.
Without that divergence a global read and a per-profile read return the same directory and the
gate proves nothing. Two env modes (`codexhome` with `CODEX_HOME` set to the profile dir,
`noenv` with it absent — the state a real hook subprocess is in) × two asserted scenarios
(`full`, and `disabled` with `compound_loop.enabled = false`). `missing` and `broken` configs are
recorded, not asserted: with no profiles table even a correct build falls back to the global
agent.

## Result against 0.67.0 — FAIL, exit 1

17 failed assertions, 20 passed. Both asserted hooks leak, in all four scenario × mode cells:

| Site | Evidence (abridged) |
|---|---|
| `context_inject.py:759` — pre-config boot dir | `session-context: fired cwd=…-full-codexhome-context-inject` in `global-claude/logs/hooks.log:1` |
| `pre_tool_use_security.py:298` — `_log_block` | `pre-tool-use-security: blocked filesystem: rm -rf /tmp/<token>-full-codexhome-pre-tool-use-security-secblock` at `:2` |

Plus the 8 matching section-11a leak lines and the section-11b count delta on the global scratch.

## Known gap — printed on every run, never asserted

The seven unmigrated leakers are exercised with fixtures that reach their logging branch (an
over-threshold `MEMORY.md` write, an offsetless Read of a 600-line file, a `.py` edit with ruff
off `PATH`, a playbook edit with ansible-lint off `PATH`) and counted. From the 0.67.0 run:

```
GAP:  session-export — 4 line(s) leaked outside the profile dir
GAP:  compound-loop — 4 line(s) leaked outside the profile dir
GAP:  session-end — 4 line(s) leaked outside the profile dir
GAP:  pre-tool-use-memory-size — 4 line(s) leaked outside the profile dir
GAP:  pre-tool-use-read-size — 4 line(s) leaked outside the profile dir
GAP:  post-tool-use-format — 4 line(s) leaked outside the profile dir
GAP:  post-tool-use-ansible-lint — 4 line(s) leaked outside the profile dir
GAP:  TOTAL unmigrated lines leaked: 28
```

The gate prints, above that block, that these hooks reach `main()` with no arguments and assume
Claude Code's wire format, so they have no profile to honour — and that **a PASS means the
migrated hooks are isolated, not that nothing leaks.** The PASS banner repeats the count:
`known gap still open: 28 unmigrated line(s) leaked — step 5`. Nobody can read a green run as
"no leak anywhere".

## Discrimination — three cases

| Build | Exit | Detail |
|---|---|---|
| `lh` 0.67.0 (real, broken) | **1** | 17 failures; both migrated hooks leak |
| `fake-lh-fixed.sh` (both migrated hooks honour the profile) | **0** | 20 ok, 0 failures, gap still 28 |
| `fake-lh-security-only.sh` (only `pre-tool-use-security` fixed) | **1** | 9 failures: the 4 `context-inject` rows, their 4 leak lines, the count delta. The 4 `pre-tool-use-security` rows pass. |

The third case is the one that matters for the branch as it stands, where commit 1 is already
done: a gate that could not tell "security fixed, context-inject not" from "both fixed" would
sign off on a half-finished branch.

## Re-running it now

The gate is versioned, so this is a path in the repository rather than a ritual in `/tmp`.

1. Merge, let release-please cut, `uv tool install --reinstall` against the resolved tag.
2. Grep site-packages to confirm the fixed code shipped (binary-first deploy gate).
3. `specs/gates/f7/isolation-gate.sh "$(command -v lh)"` → must exit 0.
4. Both controls, which are what make this a checker rather than a one-way alarm. They need
   `F7_GATE_PYTHON`: the shims are shell scripts with no interpreter beside them, and the gate
   derives its hook sets from the registry.

   ```
   F7_GATE_PYTHON=.venv/bin/python3 specs/gates/f7/isolation-gate.sh \
     "$PWD/specs/gates/f7/fake-lh-fixed.sh"           # must exit 0
   F7_GATE_PYTHON=.venv/bin/python3 specs/gates/f7/isolation-gate.sh \
     "$PWD/specs/gates/f7/fake-lh-security-only.sh"   # must exit 1
   ```

   If either verdict flips, the gate itself regressed and its result means nothing.
5. Read the GAP block. It is derived, so it shrinks on its own as step 5 lands and reaching
   empty is the signal that the migration is done — not a number to keep in step by hand.

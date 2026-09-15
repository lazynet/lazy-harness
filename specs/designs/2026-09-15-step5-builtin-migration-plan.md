# Step 5 — Builtin Migration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Migrate the fifteen builtins still on the pre-runner path to `main(event: HookEvent) -> HookDecision`, each declaring its `Operation` and `Signal` sets, and delete the transitional branch that keeps them alive.

**Architecture:** Each builtin stops parsing stdin and stops serialising Claude Code's JSON; the adapter owns both translations and the builtin sees only `HookEvent` and returns only `HookDecision`. Three adapter- and substrate-level defects (tasks 1–3) block the bulk migration and land first. The fifteen migrations (tasks 4–18) parallelise apart from two shared files, named where the waves are. The second entry point, the transitional field and the literal sweep close behind them — **task 20 before task 19**, for the reason recorded there.

**Tech Stack:** Python 3.11+, `uv run --frozen`, `pytest`, `ruff`, strict type hints.

**Spec:** [`specs/designs/2026-09-13-multi-agent-harness-design.md`](2026-09-13-multi-agent-harness-design.md), step 5 (the numbered list at `design.md:1747`), decisions 1, 3, 9 and 11. Contract frozen by [ADR-041](../adrs/041-multi-agent-hook-contract.md), `accepted` 2026-09-15.

## Global Constraints

- **Byte identity is the acceptance test, with exactly one declared exception.** `parse_hook_input` and `format_hook_output` are identity for Claude Code, so the wire bytes Claude Code sees must not change. Every migrated builtin gets a golden captured **before** its `main()` is touched.
  - **The exception is unparseable stdin.** Decision 3 (`runner.py:119-124`) makes the runner refuse before the builtin is reached: exit 2 for a blocking hook, exit 0 with a warning otherwise. Today every builtin degrades to `{}` and exits 0. That changes the verdict channel for `pre-tool-use-git-scope` and the stderr text for the rest, deliberately — a guard handed `{}` abstains, which on the wire is indistinguishable from having looked. No other divergence is licensed by this bullet; a golden that differs for any other reason is a regression.
- **Strict TDD, no exceptions** (`CLAUDE.md` non-negotiable 2). Write the failing test, watch it fail, implement, watch it pass.
- **One worktree per task group**, via `/new-worktree` (non-negotiable 1). Commits are conventional, no AI trailers, no `--no-verify`.
- **`/tdd-check` passes before every commit**, all four checks pristine.
- **`uv run --frozen`** on every invocation. Without it `uv run` re-locks whenever it decides the environment is stale — measured 2026-09-14 rewriting `uv.lock` from 54 packages to 16, dropping `revision` and every `upload-time`. Editing a source and running the tests *is* this repo's TDD cycle, so every worktree accumulates it.
- **No builtin may read `event.raw` or `event.tool.raw_input`.** `tests/unit/hooks/test_builtin_contract.py` gates this through the AST and will fail the build.
- **Hooks handle every exception explicitly.** A non-blocking builtin returns `HookDecision()` on any failure; a blocking one refuses. The runner's blanket handler is a backstop, not the policy.
- **Versions are owned by release-please.** Never hand-bump.

---

## The substrate, measured

`agent_dir_for(cfg, profile)` (`_shared.py:233`) already exists and is the migration template: it is the one importable answer to "which agent does this profile run and where do its hooks write", and it is what `context-inject` and `pre-tool-use-security` were moved onto by PR #300. Every builtin in this plan replaces its own two-step resolution with one call to it.

### Payload → event mapping

The mapping every task below applies. Every row was checked against all fifteen builtins on 2026-09-15; the three traps the check found are called out under it, and each is a silent behaviour change rather than a compile error.

| Today | After |
|---|---|
| `json.load(sys.stdin)` | deleted; the runner parses and the adapter normalises |
| `payload.get("cwd")` | `event.cwd` — **but see trap 1** |
| `payload.get("session_id")` | `event.session_id` |
| `transcript_from_payload(payload)` | `event.transcript_path`, **plus an `.is_file()` check** — see task 3 |
| `payload.get("prompt")` | `event.prompt` |
| `payload.get("trigger")` | `event.trigger` |
| `payload.get("source")` | `event.source` |
| `payload.get("hook_event_name")` | `event.event` — **canonical, not the wire name; see trap 2** |
| `payload.get("hook_event_name")` | `event.event` — canonical, *not* the agent's wire name |
| `payload.get("tool_name")` | `event.tool.native_name`, but prefer `event.tool.operation` |
| `payload.get("tool_input")["command"]` | `event.tool.command` |
| `payload.get("tool_input")["file_path"]` (Read) | `event.tool.reads` |
| `payload.get("tool_input")` (Edit/Write) | `event.tool.edits` — `FileEdit.content`, `.replacements`, `.replace_all` |
| `payload.get("tool_input")["offset"/"limit"]` | `event.tool.offset` / `event.tool.limit` |
| `profile_name()` | `event.profile` |
| `get_agent("claude-code")` + `agent_runtime_dir(agent)` | `agent_dir_for(cfg, event.profile)` |
| `print(json.dumps({"systemMessage": X}))` | `return HookDecision(system_message=X)` |
| `print(json.dumps({"hookSpecificOutput": {"additionalContext": X}}))` | `return HookDecision(additional_context=X)` |
| `sys.exit(2)` + stderr text | `return HookDecision(verdict=Verdict.DENY, reason=X)` |
| `sys.exit(0)` | `return HookDecision()` |

**Trap 1 — four builtins do not read `cwd` from the payload at all.** `compound_loop.py:88`, `session_export.py:46`, `session_end.py:114` and `pre_compact.py:182` call `Path.cwd()`, the hook process's own directory; only `engram_persist.py:49` reads the payload with a `Path.cwd()` fallback. Swapping them to `event.cwd` looks like a normalisation and is a behaviour change: `parse_hook_input` yields `Path("")` when the payload names no cwd (`claude_code.py:414`), and `Path("")` is `Path(".")`. `project_key` resolves that back to the real directory, so the metrics survive — but `compound_loop.py:95` builds `"-" + str(cwd).replace("/", "-")` and would encode the project dir as `-.`, pointing every queued task at one shared garbage directory. Keep the `Path.cwd()` fallback for an empty `event.cwd`, as `stop_verify_guard` already does.

**And the fallback is only half of it: `Path.cwd()` and a non-empty `event.cwd` are not the same spelling either.** `os.getcwd()` returns a symlink-resolved path (`/private/var/...` on macOS) while the payload carries what the agent saw (`/var/...`), and these hooks encode that string into a directory *name*. Tasks 4 and 6 hit it independently: a golden captured pre-migration under an unresolved `tmp_path` picks a different project dir after the swap while every frozen channel stays byte-identical — the golden cannot see it. Neither "fixed" it by resolving the path, and that is right: the agent names its own directory with the string *it* saw, which is the payload's. What each did was stop the test from hiding the difference, by realpath'ing the working directory it feeds in. Rows 5 and 8 call `Path.cwd()` too and inherit this.

**Trap 5 — moving a writer to the profile orphans its reader, and neither process fails.** Step 4 tells each task to swap the boot-dir dance for `agent_dir_for(cfg, event.profile)`. It says nothing about who *else* names that directory, and wave A's single review found two pairs broken this way, both exiting 0:

- `compound-loop` and `session-end` queue into `<profile>/queue`; `compound_loop_worker.py:101` drained `<global>/queue` and the spawn at `compound_loop.py:133` passed it no profile at all. Measured against the real config with `CLAUDE_CONFIG_DIR` unset: producer `~/.claude-lazy/queue`, worker `~/.claude/queue`, every queued task orphaned. Pre-migration both resolved globally and *agreed*, so the migration is what broke it.
- `engram-persist` writes its metrics under the profile; `doctor_cmd.py:162` read them globally and reported `No runs yet (Stop hook not triggered)` — the health state a hook that never fires produces — while the hook was recording fine.

Neither the goldens nor the isolation tests can see this: the goldens pin `CLAUDE_CONFIG_DIR` to the agent dir, and the isolation tests never enable processing. The failure needs both conditions at once.

**So step 4 carries a second half: before changing a writer, grep for every reader of that directory and make the pair agree in one commit, with a test that invokes *both* sides.** `CLAUDE.md` already requires it — "where two paths answer one question, an integration test invokes both and asserts they agree" — and none of the four branches had one. The readers to check are the worker, `lh doctor`, `lh status`, the selftest checks, and `knowledge_cmd.py`. Every remaining task writes to a directory something else reads.

**Trap 4 — a shipped selftest runs a builtin as a script, and a migrated one has no `__main__`.** `selftest/checks/loop_events_check.py:75` invokes `[sys.executable, str(hook)]`. A migrated module imports, defines `main(event)`, and exits 0 without running anything — the same exit code the working hook returns, so `_run_hook`'s `returncode != 0` test cannot tell them apart. Found by task 5, which routed the call through `lh hook <name> --profile` on `spec.migrated`. **Scope, checked rather than assumed:** `:130` names `session_end.py` and nothing else, so this trap fires for task 5 alone — the check still passed in the other three wave A trees. It returns for any later task that adds a hook to that file.

**Trap 2 — `hook_event_name` carries the agent's wire name, `event.event` carries the canonical one.** `herdr_context_gauge.py:166` reads it and compares against `"PostToolUse"` (`:172`) and `"SessionEnd"` (`:175`). `HookEvent.event` holds `post_tool_use` and `session_end`. A direct swap leaves both comparisons permanently false: the hook stops throttling on every tool call and stops retracting a dead session's gauge, and nothing fails.

**Trap 3 — `MODIFY_FILE` is wider than `INSPECTED_TOOLS`, and the widening is real.** `_TOOL_OPERATIONS` maps `NotebookEdit` to `MODIFY_FILE` alongside `Edit` and `Write` (`claude_code.py:97`), while **four** builtins gate on `frozenset({"Edit", "Write"})`: `post_tool_use_format.py:18`, `post_tool_use_sync_claude.py:25`, `post_tool_use_ansible_lint.py:20`, `pre_tool_use_memory_size.py:26`.

An earlier draft called the widening inert because each of the four re-checks a suffix or a filename afterwards — `.py`, `.yml`/`.yaml`, `SEGMENT_FILES`, `MEMORY.md`/`CLAUDE.md`. **That reasoning assumed a notebook's path ends in `.ipynb`, and nothing in `ToolCall` enforces it.** A `NotebookEdit` whose normalised path is `notebook.py` clears `post_tool_use_format.py:45` and runs Ruff on a file that was never a Python source. So: **keep the native-name narrowing.** Check `event.tool.native_name` against the same set, or add an explicit `.ipynb` exclusion; do not replace the tool gate with the operation gate and call it a normalisation.

Deleting `INSPECTED_TOOLS` outright also drops the hook from `tests/unit/test_hook_matcher_coverage.py:83-88` with no failure.

### What the design's step 5 text gets wrong

Recorded here because the step text is never edited as things land, and a reader following it would chase two symbols that are already gone.

- **No syntactic criterion produces this number, and three attempts have now proved it.** The count is **at least ten** in the fifteen migration targets, and the plan states it that way on purpose.

  The history is the argument. A grep for `get_agent("claude-code")` finds **seven** and misses `engram_persist.py:75` and `pre_compact.py:158`, which write `get_agent(cfg.agent.type if cfg is not None else "claude-code")` — the second grapheme the backlog flags for `pre-compact`, unrecorded for `engram-persist`. Widening to an AST match on *calls whose argument mentions `claude-code`* gives **nine** and misses `post_tool_use_sync_claude.py:83`, whose `get_agent(agent_type)` falls back to the module constant `DEFAULT_AGENT_TYPE = "claude-code"` at `:29`. Each widening was written as the correction of the previous one, and each missed a case the next one found.

  So the audit is **per builtin, by reading**, and the number is an output of it rather than an input. Task 21's test matches the `get_agent` *call* with no reference to its argument at all, which is the only criterion that does not depend on how the next one is spelled. The ten known today: `compound_loop.py:62`, `engram_persist.py:75`, `post_tool_use_ansible_lint.py:140`, `post_tool_use_format.py:67`, `post_tool_use_sync_claude.py:83`, `pre_compact.py:158`, `pre_tool_use_memory_size.py:170`, `pre_tool_use_read_size.py:69`, `session_end.py:89`, `session_export.py:44`.

  Design line 207 is separately wrong about which ones survive: it names `pre_tool_use_security.py:298` and `context_inject.py:758`, and both are now **docstring prose** describing what PR #300 removed. Outside step 5 and staying: `_shared.py:258` and `:160` (inside `agent_dir_for` and `profile_name`, the documented degradations for a machine that has not run `lh init`), `knowledge/compound_loop_worker.py:98` and `:100`, `cli/memory_cmd.py:237` and `:264`, and `monitoring/statusline.py:44`. None is a builtin.
- **`profile_name()` cannot be deleted at step 5.** Six import statements and six call sites. Two are builtins (`session_end.py:35`, `user_prompt_goal.py:131`) and go with their migrations. Four calls across three modules survive, none of them a builtin: one in `cli/metrics_cmd.py:236`, two in `knowledge/compound_loop.py:1249` and `:1278`, and one in `hooks/runner.py:151`.

  That last one is `resolve_profile`'s fallback, and it is **live, tested behaviour on the ordinary path** — not, as an earlier draft of this plan claimed, compatibility for settings files nobody has redeployed.

  Measured: `--profile` is `default=None` on both entry points (`cli/hooks_cmd.py:78-83`, `:143`), and both hand that straight to `resolve_profile` (`cli/hooks_cmd.py:97`, `hooks/engine.py:67`). Every `lh hooks run <event>` without the flag therefore reaches `profile_name()`. `runner.py:66-72` documents it as a reachable state and two tests pin it (`test_entry_points.py:115`, `test_runner.py:276`).

  **This paragraph is a correction of a correction, and that is the point.** The first review pass asserted the callers pass a resolved profile; this plan adopted it without running the path, and the second pass falsified it against the `default=None`. A reviewer's finding is evidence to check, not a result to apply — the same standard this plan applies to the design. (The same draft also cited "`deploy` via `hooks/engine.py:64`"; `run_hooks_for_event` has exactly one caller, `cli/hooks_cmd.py:159`, and deploy never touches `hooks/engine.py`.)

  Step 5 removes the symbol from the builtins and leaves it standing. Task 21 records that.

---

## Task 1: A plain-text output channel for PreCompact

**Blocks every other task.** Migrating `pre-compact` without this silently destroys it, and does so while passing every unit test written against `HookDecision`.

`pre_compact.py:247` writes `print(f"{SUMMARY_PREAMBLE}\n\n{summary}")` — raw text, deliberately. Its module docstring records why: Claude Code's `hookSpecificOutput` union has **no PreCompact variant**, so a JSON payload fails schema validation, marks the hook failed, and discards its output. The PreCompact executor collects each successful hook's raw stdout and hands the joined text to the summariser as `newCustomInstructions`.

**Two claims, two evidence standards, kept apart.** That the adapter emits JSON here is measured against the installed adapter and reproducible in one command:

```
$ uv run --frozen python -c "...format_hook_output(<pre_compact event>, HookDecision(additional_context='X'))"
STDOUT REPR: '{"hookSpecificOutput": {"hookEventName": "PreCompact", "additionalContext": "X"}}\n'
```

That Claude Code *discards* that payload is the repository's prior finding, recorded against the 2.1.234 binary in `pre_compact.py:8` and in ADR-036 D2, and **not re-measured here** — it is a claim about a vendor binary that no test in this repo can assert. This task takes it as given because the repo already paid for it; an executor who wants to re-establish it does so against a live Claude Code, not against pytest. What does not depend on it: the two channels disagree either way, and a hook whose whole purpose is surviving compaction should not be the one we find out about in production.

`ClaudeCodeAdapter.format_hook_output` (`claude_code.py:474`) unconditionally emits `json.dumps(body) + "\n"`. `_HOOK_EVENTS["pre_compact"] = HookSupport("PreCompact")` carries an empty verdict set, so there is no verdict path to ride either. A migrated `pre-compact` returning `HookDecision(additional_context=summary)` serialises to `{"hookSpecificOutput": {"hookEventName": "PreCompact", "additionalContext": …}}` — exactly the payload the docstring says is discarded.

**Files:**
- Modify: `src/lazy_harness/agents/claude_code.py:474-520` (`format_hook_output`)
- Test: `tests/unit/test_agent_claude.py`

**Interfaces:**
- Consumes: `HookEvent`, `HookDecision`, `HookOutput` from `agents/base.py`
- Produces: `format_hook_output` returns `HookOutput(stdout=<raw text>, stderr="", exit_code=0)` when `event.event == "pre_compact"`. No other event changes shape.

**The branch must not silently narrow the decision.** `format_hook_output` today also serialises `system_message` (`claude_code.py:501`), `stop` (`:503`) and `suppress_output` (`:507`). A `pre_compact` early return that carries only `additional_context` drops all three without a word — the same silent-dropout class this plan exists to close. PreCompact's channel is raw text and cannot express them, so the branch **names what it cannot carry** rather than discarding it. The verdict check is *not* repeated: `format_hook_output:475` already rejects any verdict against `_HOOK_EVENTS`, and `pre_compact`'s support set is empty (`claude_code.py:80`), so every verdict is refused there already.

- [ ] **Step 1: Write the failing test**

```python
def test_pre_compact_additional_context_serialises_as_plain_text() -> None:
    """PreCompact has no hookSpecificOutput variant; JSON there is discarded.

    Asserted against the shape the executor actually reads -- raw stdout joined
    into `newCustomInstructions` -- rather than against a mapping, because a
    mapping here parses cleanly and displays nothing.
    """
    adapter = ClaudeCodeAdapter()
    event = HookEvent(
        event="pre_compact",
        profile="p",
        session_id="s",
        cwd=Path("/tmp"),
        transcript_path=None,
        trigger="auto",
    )
    out = adapter.format_hook_output(event, HookDecision(additional_context="Preserve X"))
    assert out.stdout == "Preserve X"
    assert "hookSpecificOutput" not in (out.stdout or "")
    assert out.exit_code == 0


def test_other_events_still_serialise_additional_context_as_json() -> None:
    """The narrowing is PreCompact's alone, not a change to the channel."""
    adapter = ClaudeCodeAdapter()
    event = HookEvent(
        event="session_start",
        profile="p",
        session_id="s",
        cwd=Path("/tmp"),
        transcript_path=None,
    )
    out = adapter.format_hook_output(event, HookDecision(additional_context="ctx"))
    assert json.loads(out.stdout)["hookSpecificOutput"]["additionalContext"] == "ctx"
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run --frozen pytest tests/unit/test_agent_claude.py -k pre_compact -v`
Expected: FAIL — `out.stdout` is the JSON document, not `"Preserve X"`.

- [ ] **Step 3: Implement**

In `format_hook_output`, before the `body` assembly:

```python
        # PreCompact is a text channel, not a JSON one. Claude Code's
        # `hookSpecificOutput` union has no PreCompact variant (recorded
        # against 2.1.234 in `pre_compact.py` and ADR-036 D2): a JSON payload
        # there fails schema validation, marks the hook failed and discards its
        # output. The executor joins each successful hook's raw stdout into
        # `newCustomInstructions`, so the summary arrives as the bytes the hook
        # wrote or it does not arrive.
        #
        # The verdict is already refused above -- `_HOOK_EVENTS["pre_compact"]`
        # declares no verdicts -- so the only narrowing left to name is the
        # three channels raw text cannot carry. Refusing beats dropping them:
        # a hook asking for a system message here would otherwise get silence
        # and a zero exit, which reads as success.
        if event.event == "pre_compact":
            unsupported = [
                name
                for name, set_ in (
                    ("system_message", bool(decision.system_message)),
                    ("stop", decision.stop),
                    ("suppress_output", decision.suppress_output),
                )
                if set_
            ]
            if unsupported:
                raise ValueError(
                    f"claude-code's PreCompact channel is plain text and cannot carry "
                    f"{', '.join(unsupported)}"
                )
            return HookOutput(
                stdout=decision.additional_context or None, stderr="", exit_code=0
            )
```

- [ ] **Step 4: Run to verify it passes**

Run: `uv run --frozen pytest tests/unit/test_agent_claude.py -v`
Expected: PASS, and no existing adapter test regresses.

> **Note (2026-09-15, from the review of the shipped commit).** The refusal
> this task prescribes is a deliberate trade, and the next fourteen tasks
> should not inherit it as a rule without seeing the argument against it.
> Raising loses *more* than the silent drop it replaces: the three channels,
> **and** the summary, **and** still no user-visible error, because the
> runner's blanket handler turns it into exit 0 with the reason on a stderr
> Claude Code does not surface outside `--debug`. The alternative —
> `HookOutput(stdout=text, stderr="<what could not be carried>", exit_code=0)`
> — keeps the payload and still names the narrowing. It was not taken here
> because no builtin sets those channels on `pre_compact`, so the raise is a
> programming-error signal that fires in tests rather than in production. A
> task where the same collision is *reachable* at runtime should choose the
> degrading form instead, and say which it chose.

- [ ] **Step 4b: Two things this branch gets wrong if written naively**

**The newline is part of the bytes.** `pre_compact.py:247` emits `print(...)`, which appends `\n`; the JSON path appends one deliberately (`claude_code.py:509-514`) for exactly this reason. Returning `decision.additional_context` unchanged makes the golden differ by one character that nothing else would account for. Either the builtin includes the trailing newline in what it returns, or the branch appends it — decide which and say so in the code, because the next reader will otherwise "fix" whichever half looks redundant.

**The `ValueError` is swallowed.** `run_hook` calls `format_hook_output` inside its try (`runner.py:149`), and the blanket handler at `:150-154` turns any exception from a non-blocking hook into exit 0 with the reason on stderr. `pre-compact` is non-blocking, and Claude Code does not surface a successful hook's stderr outside debug output — so a decision this branch refuses is lost *silently*, along with the summary, which is the failure mode the branch exists to prevent. That is the Global Constraint at the top of this plan biting: the blanket handler is a backstop, not a policy. Assert the raise in a unit test against `format_hook_output` directly, not through `run_hook`, and accept that at runtime the refusal degrades to a lost summary rather than a visible error.

- [ ] **Step 5: Prove the guard is load-bearing**

Delete the `if event.event == "pre_compact":` block by hand, re-run, watch `test_pre_compact_additional_context_serialises_as_plain_text` fail, restore by hand. **Never `git checkout`** — it reverts the uncommitted implementation too.

- [ ] **Step 6: Commit**

```bash
git add tests/unit/test_agent_claude.py src/lazy_harness/agents/claude_code.py
git commit -m "fix: serialise PreCompact additional context as plain text"
```

---

## Task 2: Decide the transcript-key narrowing, with evidence

`_shared._TRANSCRIPT_KEYS = ("transcript_path", "transcriptPath", "input")` (`_shared.py:21`) accepts three spellings. `ClaudeCodeAdapter.parse_hook_input` (`claude_code.py:407`) reads **only** `transcript_path`. Deleting `_TRANSCRIPT_KEYS` as step 5 prescribes therefore drops two accepted spellings from every migrated builtin — a silent narrowing, which is the class of defect the `CLAUDE.md` silent-dropout gate exists for.

This task produces a decision backed by measurement, not a guess. Either outcome is acceptable; an unrecorded one is not.

**Settled: narrow.** `parse_hook_input` keeps reading `transcript_path` alone,
and `test_transcript_path_is_the_only_spelling_the_adapter_reads`
(`tests/unit/test_agent_contract.py`) holds it. The measurement, the two
sources it rests on and the load-bearing proof are recorded in
`2026-09-13-multi-agent-harness-design.md` under step 5. Step 4 below is the
alternative that was rejected; it was applied by hand only to watch the test
fail, and reverted. Tasks 4-18 inherit the narrowing and do not re-litigate it.

**Files:**
- Modify: `src/lazy_harness/agents/claude_code.py:407` (only if the measurement says widen)
- Modify: `specs/designs/2026-09-13-multi-agent-harness-design.md` (record the decision either way)
- Test: `tests/unit/test_agent_claude.py`

- [ ] **Step 1: Measure what actually sends each spelling**

```bash
grep -rn "transcriptPath" --include="*.py" --include="*.json" --include="*.md" . | grep -v _TRANSCRIPT_KEYS
grep -rn '"input"' src/lazy_harness/hooks/ tests/
git log -S'transcriptPath' --oneline -- src/lazy_harness/hooks/builtins/_shared.py
```

Record every hit. `git log -S` is what says whether the two extra keys were ever observed on the wire or were defensive from the start.

- [ ] **Step 2: Write the test for the decision you reached**

If the evidence says **widen** (any live sender, or the git history shows a real payload):

```python
def test_parse_hook_input_accepts_every_transcript_spelling() -> None:
    adapter = ClaudeCodeAdapter()
    for key in ("transcript_path", "transcriptPath", "input"):
        event = adapter.parse_hook_input("session_start", {key: "/tmp/t.jsonl"}, profile="p")
        assert event.transcript_path == Path("/tmp/t.jsonl"), key
```

If the evidence says **narrow** (nothing has ever sent them):

```python
def test_parse_hook_input_reads_only_the_documented_transcript_key() -> None:
    """The narrowing from `_TRANSCRIPT_KEYS` is deliberate and measured.

    `transcriptPath` and `input` were defensive, never observed on the wire --
    see the design's step 5 note. Asserted so the drop is a decision with a
    test behind it rather than an omission nobody notices.
    """
    adapter = ClaudeCodeAdapter()
    assert adapter.parse_hook_input("session_start", {"transcriptPath": "/t"}, profile="p").transcript_path is None
    assert adapter.parse_hook_input("session_start", {"input": "/t"}, profile="p").transcript_path is None
```

- [ ] **Step 3: Run to verify it fails (widen) or passes (narrow)**

Run: `uv run --frozen pytest tests/unit/test_agent_claude.py -k transcript -v`

- [ ] **Step 4: Implement, if widening**

```python
        transcript = next(
            (
                payload[k]
                for k in ("transcript_path", "transcriptPath", "input")
                if isinstance(payload.get(k), str) and payload[k]
            ),
            "",
        )
        declared = transcript
```

- [ ] **Step 5: Record the decision in the design**

Add a note under step 5 naming the measurement and the outcome. A decision with no record reads as an oversight to the next reader.

- [ ] **Step 6: Run the gate and commit**

```bash
uv run --frozen pytest tests/unit/test_agent_claude.py tests/unit/test_agent_contract.py -v
git add -A && git commit -m "fix: settle the transcript key set the adapter accepts"
```

---

## Task 3: Move the `_shared` payload helpers onto the transcript path

Five helpers take the raw payload and reach into it through `_declared_transcript`: `transcript_from_payload`, `project_dir_from_payload`, `resolve_project_dir`, `resolve_memory_dir`, `memory_dir`. A migrated builtin has no payload, and `_TRANSCRIPT_KEYS` dies with them.

The second half matters as much: `transcript_from_payload` returns `None` unless the path `.is_file()`, while `HookEvent.transcript_path` is the **declared** path, un-stat'd. A call site that swaps one for the other without adding the check proceeds on a path that is not there — at `SessionStart` the transcript is routinely not written yet, which is exactly when several of these run.

**Files:**
- Modify: `src/lazy_harness/hooks/builtins/_shared.py:21` (`_TRANSCRIPT_KEYS`), `:49` `_declared_transcript`, `:60` `transcript_from_payload`, `:68` `project_dir_from_payload`, `:83` `resolve_project_dir`, `:174` `resolve_memory_dir`, `:192` `memory_dir`
- Test: `tests/unit/hooks/test_shared_memory_dir.py`, `tests/unit/hooks/builtins/`

**Interfaces:**
- Produces:
  - `existing_transcript(declared: Path | None) -> Path | None` — the `.is_file()` filter, named so every call site gets it from one place
  - `resolve_project_dir(transcript: Path | None, *, agent_dir: Path, sessions_subdir: str, cwd: Path) -> Path`
  - `resolve_memory_dir(transcript: Path | None, *, agent_dir: Path, sessions_subdir: str, cwd: Path) -> Path`
  - `memory_dir(transcript: Path | None, *, agent_dir: Path, sessions_subdir: str, cwd: Path, knowledge_root: Path | None) -> Path`
  - `transcript_from_payload` and `project_dir_from_payload` are **deleted**, not kept as shims.

- [ ] **Step 1: Write the failing tests**

```python
def test_existing_transcript_filters_a_declared_path_that_is_not_written_yet(tmp_path: Path) -> None:
    """SessionStart declares a transcript before the agent writes it.

    `HookEvent.transcript_path` is the declared path, un-stat'd, so the filter
    the old `transcript_from_payload` applied has to survive somewhere -- here.
    """
    assert existing_transcript(tmp_path / "absent.jsonl") is None
    written = tmp_path / "present.jsonl"
    written.write_text("{}\n")
    assert existing_transcript(written) == written
    assert existing_transcript(None) is None


def test_resolve_project_dir_honours_a_declared_dir_inside_the_sessions_root(tmp_path: Path) -> None:
    agent_dir = tmp_path / "agent"
    sessions_root = agent_dir / "projects"
    declared_dir = sessions_root / "-Users-x-repo"
    declared_dir.mkdir(parents=True)
    assert resolve_project_dir(
        declared_dir / "s.jsonl", agent_dir=agent_dir, sessions_subdir="projects", cwd=Path("/Users/x/repo")
    ) == declared_dir


def test_resolve_project_dir_rejects_a_declared_dir_outside_the_sessions_root(tmp_path: Path) -> None:
    """ADR-032: harness artifacts never escape the adapter's sessions root."""
    agent_dir = tmp_path / "agent"
    (agent_dir / "projects").mkdir(parents=True)
    outside = tmp_path / "elsewhere"
    outside.mkdir()
    assert resolve_project_dir(
        outside / "s.jsonl", agent_dir=agent_dir, sessions_subdir="projects", cwd=Path("/Users/x/repo")
    ) == agent_dir / "projects" / "-Users-x-repo"
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run --frozen pytest tests/unit/hooks/test_shared_memory_dir.py -v`
Expected: FAIL with `NameError: existing_transcript` and a `TypeError` on the changed signatures.

- [ ] **Step 3: Implement**

Replace `_declared_transcript(payload)` with the passed `transcript` throughout; delete `_TRANSCRIPT_KEYS`, `transcript_from_payload` and `project_dir_from_payload`; add:

```python
def existing_transcript(declared: Path | None) -> Path | None:
    """The declared transcript if it is on disk, else None.

    `HookEvent.transcript_path` is what the payload named, not what exists:
    at `SessionStart` the file is routinely not written yet. The pre-runner
    helper this replaces stat'd it as part of reading the payload, so without
    this the check disappears silently at every call site at once.
    """
    return declared if declared is not None and declared.is_file() else None


def _project_dir_of(transcript: Path | None) -> Path | None:
    if transcript is None:
        return None
    parent = transcript.parent
    return parent if parent.is_dir() else None
```

- [ ] **Step 4: Run to verify they pass**

Run: `uv run --frozen pytest tests/unit/hooks/ -v`
Expected: PASS. Unmigrated builtins still calling the old names fail to import — that is the point; they are fixed in their own tasks below, so this task's commit carries the call-site updates as mechanical renames with behaviour unchanged.

- [ ] **Step 5: Commit**

```bash
git add -A && git commit -m "refactor: take the transcript path rather than the payload in shared helpers"
```

> **Corrections (2026-09-15, from executing this task).** Five things above are
> wrong against the code; the line numbers in *Files* (`:21`, `:49`, `:60`,
> `:68`, `:83`, `:174`, `:192`) were all correct.
>
> 1. **Both sample tests in Step 1 pass before the implementation exists.**
>    `test_resolve_project_dir_honours_a_declared_dir_inside_the_sessions_root`
>    names the declared dir `-Users-x-repo` and the cwd `/Users/x/repo`, so the
>    cwd-derived fallback produces the identical path; the *rejects* case
>    asserts that same fallback. Neither discriminates. They were rewritten so
>    the declared dir name cannot be re-derived from the cwd.
> 2. **Step 2's expected failure is wrong.** Not `NameError` plus a `TypeError`
>    on the changed signatures: it is `ImportError` (the test imports the new
>    name), and no `TypeError` at all, because the old signature is
>    `payload: object` and swallows a `Path` in silence, falling through to the
>    cwd branch. That is *why* the tests in (1) passed.
> 3. **`_TRANSCRIPT_KEYS` cannot "die with them", and Step 4 contradicts
>    itself.** Six modules still read a raw stdin payload
>    (`compound_loop.py:94`, `session_end.py:116`, `session_export.py:75`,
>    `herdr_context_gauge.py:154`, `engram_persist.py:80`,
>    `pre_compact.py:196`), so deleting the three-spelling reader changes their
>    behaviour. Step 4 says unmigrated builtins "fail to import — that is the
>    point" and in the next sentence that this commit carries the call sites as
>    mechanical renames with behaviour unchanged; only the second is
>    achievable. Resolved by keeping `_declared_transcript` as the payload half
>    with the tuple inlined: the module-level constant is gone, the reader is
>    not, and tasks 4–18 delete it as each builtin stops taking a payload.
> 4. **The *Test* path is the wrong mirror.** `tests/` mirrors
>    `src/lazy_harness/` one-to-one, so `_shared.py`'s mirror is
>    `tests/unit/hooks/builtins/test_shared.py`, not
>    `tests/unit/hooks/test_shared_memory_dir.py`.
> 5. **The *Files → Modify* list omits the call sites** that must change in
>    the same commit — seven files, and more than seven calls.
>
> Two debts this task takes on rather than pays, both for tasks 4–18:
>
> - Inlining `_TRANSCRIPT_KEYS` leaves the three-spelling tuple in **two**
>   literal copies, `_shared.py:56` and `pre_compact.py:189`. That is a step
>   away from the *one answer lives in one importable place* gate. The
>   duplication predates this commit — `pre_compact` never imported the
>   constant — but the resolution in (3) is not as clean as it reads.
> - Two design documents still name deleted symbols.
>   `designs/2026-09-13-multi-agent-harness-design.md:128,201,1578,1748` names
>   `_TRANSCRIPT_KEYS` as a live symbol, and
>   `designs/2026-09-09-hook-import-guard-population-design.md:87,337,345,350`
>   names `transcript_from_payload` as the live import at
>   `herdr_context_gauge:31`. The second is the sharper one: that symbol no
>   longer exists anywhere in `src/`. Each of tasks 4–18 retires another
>   payload reader, so both files are worth rewriting once at the end rather
>   than per task.

---

## Tasks 4–18: the fifteen builtins

Each is one TDD cycle and one commit, and each depends only on tasks 1–3.

**They are not file-independent, and the plan does not pretend otherwise.** Every migration edits `hooks/loader.py`'s `_BUILTIN_HOOKS` (`loader.py:101`) to add its `signals` and flip `migrated` — one shared dict, fifteen times. There is a second: `tests/unit/hooks/test_abstention.py:41-75` derives `_NO_OBJECTION` from the registry and fails when a migrated hook wired to a blockable event has no entry. With `session_stop` honouring `BLOCK` and `pre_tool_use` honouring `DENY`, that reaches seven of the fifteen — tasks 4, 6, 7, 11, 16, 17 and 18. Both conflicts are appends and resolve mechanically, but a task that does not know about the second one lands red.

> **Wave A found three more, and the count is five, not two.** Measured from the four branches' `git diff --name-only main..HEAD`:
>
> | Surface | Branches touching it | In the plan? |
> |---|---|---|
> | `src/lazy_harness/hooks/loader.py` | 4 of 4 | yes — and PR #308 shrank it to `signals` + `migrated`, so it merged **clean** all four times |
> | `docs/how/hooks.md` | 4 of 4 | **no** |
> | `tests/unit/hooks/test_abstention.py` | 3 of 4 | yes |
> | `tests/unit/hooks/builtins/test_import_safety.py` | 3 of 4 | **no** — `GUARDED_HOOKS` must *drop* each hook as it migrates: a migrated module imports `agents.base` at module level, so the poisoned-import subprocess starts exiting non-zero |
> | `tests/integration/test_hook_log_profile_isolation.py` | 3 of 4 | **no** — recipe step 7 sends all fifteen to one file |
>
> Two further per-hook literals, found by task 4 and not general: `tests/unit/hooks/test_builtin_signals.py:14` and `tests/unit/hooks/test_signal_gaps.py:130` both hard-code `session-export` as *the* example of a builtin declaring no signals, and both go red when it declares `MESSAGES`. Whoever migrates a hook that some test uses as an example of the pre-migration state inherits that test.
>
> A trial merge of the four branches onto `main` conflicted only in `docs/how/hooks.md`, `test_import_safety.py`, `test_hook_log_profile_isolation.py` and `test_abstention.py` — every one an append, none in `src/`. Two workable orders, pick one and say which in the PR:

- **Serialise the registry.** Land one commit first that gives all fifteen specs their final `event`, `operations` and `blocking`, leaving `migrated=False`. **Taken, in PR #308, and narrower than written here: `signals` was excluded.** The other three have no reader that `migrated=False` does not gate, so a wrong row costs nothing until the hook migrates; `signals` is read by `signal_gaps.gaps_for_profile` regardless of `migrated`, and a wrong row there undeploys a working hook on any profile whose agent ships no `TranscriptReader`. Row 12 was left undeclared as this plan requires. The declarations are a fact about each hook and are true before its `main()` moves. **This does not make the migrations file-independent** — each still flips its own `migrated=True` in the same dict — but it reduces the shared edit to a one-token change per task instead of a multi-line block, and it puts the reviewable half in one diff. Full independence needs task 19 first, which is not possible while the branch it deletes is what keeps the unmigrated ones running.
- **Accept the rebases.** Each task rebases on `main` before pushing. Cheaper to start, and the cost lands on whoever merges last.

The first is preferred: it makes the declaration table reviewable in one diff, which is where a wrong `signals` set is actually visible.

**Per-builtin recipe, applied identically in each:**

1. **Capture the golden first.** `tests/goldens/hooks/<name>/` — feed the pre-migration `main()` a representative payload on stdin, record stdout bytes and exit code. The golden is captured from the **unmigrated** hook, so it is evidence and not a restatement of the new code.

   **For a hook whose output channel is "none" the golden alone discriminates nothing, and wave A measured that four times over.** Rows 4-7 all write on no channel, so every case froze to the identical `{"exit_code": 0, "stderr": "", "stdout": ""}` — seven files for `session-export`, fourteen for `session-end`, ten for `compound-loop`, twelve for `engram-persist`. A `main()` whose whole body is `return HookDecision()` reproduces all of them, so "the golden still matches" proves only that nothing reached stdout, which was already true of every branch. Each of the four independently moved the real evidence into the case: the `hooks.log` lines that branch writes, measured pre-migration, or the filesystem effect — a metrics row, a queued task, a cursor file. Rows 8 and 12 need the same; only 9-11 and 15-18 have a channel the golden can see.
2. Change the signature to `main(event: HookEvent) -> HookDecision`.
3. Apply the payload→event mapping table. Delete the `json.load(sys.stdin)` preamble and every `sys.exit`.
4. Replace the boot-dir dance with `agent, agent_dir = agent_dir_for(cfg, event.profile)`, **loading config before the first log line is written** — the ordering `context-inject` was fixed to in PR #300. Writing `fired` before config loads is what sent it to the global agent's directory.
5. Declare `signals=` on the builtin's `BuiltinHookSpec` in `hooks/loader.py` and flip `migrated=True`. **`event=`, `operations=` and `blocking=` are already there** — the coordination commit landed all fourteen (row 12 excepted) once those three were measured to be inert while `migrated` is `False`. Edit the existing entry; appending a second `event=` to it is a `SyntaxError`, not a merge conflict, and CI is where you would find out. `signals=` was deliberately left out of that commit: it is live in both states, so it lands here, where this task's golden and isolation assertion are the evidence for it. `test_no_unmigrated_builtin_declares_a_signal` holds that boundary.
6. Assert the golden still matches, byte for byte.
7. Assert profile isolation: invoke under `--profile <p>` and assert the `hooks.log` line lands in `<p>`'s directory **and is absent from the global one**. Presence alone does not detect the defect — PR #300 measured a weak presence assertion passing against a broken hook.

   **Clear the adapter's env var first, or this step re-creates the defect it exists to catch.** `agent_runtime_dir` resolves the adapter env var *above* the profile's `config_dir` (ADR-032 L3, resolution order at `core/paths.py:150-160`), so a test that pins `CLAUDE_CONFIG_DIR` to a temp directory makes the global answer and the per-profile answer the same path, and the absence half can never fail. Measured:

   ```
   CLAUDE_CONFIG_DIR=/tmp/pinned   global=/tmp/pinned  profile=/tmp/pinned   equal=True
   unset                           global=~/.claude    profile=/tmp/profile  equal=False
   ```

   Task 7 caught it because its first isolation test passed against the *unmigrated* hook. Unsetting the variable is also what a real hook subprocess sees, so the "global" probe is `~/.claude`. All fifteen inherit this: a step 7 test never run against the pre-migration hook is not evidence.

**The declarations, per builtin.** Derived from what each one reads **in its own process**, not from its matcher and not from what something downstream reads later.

> **All fifteen were read end to end on 2026-09-15 and the table is the output of that read.** An earlier draft derived rows 9–15 from greps over the output calls and the `INSPECTED_TOOLS` constants; three review passes each found a different one of those rows wrong, which is what a grep-derived table is worth. The read changed two rows — 8 and 12 — and found the three mapping traps above plus the two defects in the section that follows.
>
> A wrong `signals` set is not a documentation error: `deploy` refuses to install a hook whose signals the profile's agent does not supply, so an invented signal silently undeploys a working hook. That is why row 8 is now empty.

That distinction decides two rows. `session-end` (`session_end.py:115`, `:152`) and `compound-loop` (`compound_loop.py:93`, `:123`) *locate* a transcript and enqueue its path; the compound-loop worker reads messages and tool calls afterwards, out of process. Declaring `MESSAGES` for either would make the deploy refuse to install them on an agent whose reader cannot supply a signal the hook never touches. `session-export` is the contrast and keeps `MESSAGES`: it consumes message text in-process (`knowledge/session_export.py:43`).

| # | Builtin | `event` | `operations` | `signals` | `blocking` | Output channel today |
|---|---|---|---|---|---|---|
| 4 | `session-export` | `session_stop` | — | `MESSAGES` | no | none (log only) |
| 5 | `session-end` | `session_end` | — | **none** | no | none (log only) |
| 6 | `compound-loop` | `session_stop` | — | **none** | no | none (log only) |
| 7 | `engram-persist` | `session_stop` | — | — | no | none |
| 8 | `pre-compact` | `pre_compact` | — | **none** — see task 8 | no | **plain text** (task 1) |
| 9 | `session-start-preflight` | `session_start` | — | — | no | `additionalContext` |
| 10 | `user-prompt-goal` | `user_prompt_submit` | — | — | no | `additionalContext` |
| 11 | `stop-context-rotate` | `session_stop` | — | `TOKEN_USAGE` | no | `systemMessage` |
| 12 | `herdr-context-gauge` | **unset** — see below | — | **unresolved** — see below | no | none |
| 13 | `post-tool-use-format` | `post_tool_use` | `MODIFY_FILE` | — | no | none |
| 14 | `post-tool-use-sync-claude` | `post_tool_use` | `MODIFY_FILE` | — | no | none |
| 15 | `post-tool-use-ansible-lint` | `post_tool_use` | `MODIFY_FILE` | — | no | `additionalContext` |
| 16 | `pre-tool-use-read-size` | `pre_tool_use` | `READ_FILE` | — | no | `systemMessage` |
| 17 | `pre-tool-use-memory-size` | `pre_tool_use` | `MODIFY_FILE` | — | no | `systemMessage` |
| 18 | `pre-tool-use-git-scope` | `pre_tool_use` | `RUN_COMMAND` | — | **yes** | exit 2 + stderr |

**Wave ordering for parallel dispatch.** Within a wave the tasks share no files and can run concurrently; waves are sequential because each later one reuses a pattern the earlier one established.

- **Wave A** (tasks 4–7): the four session-lifecycle hooks. They share the identical boot-dir defect, and three of the four share the `find_latest_session` / `resolve_project_dir` call shape, so one reviewer sees the pattern repeatedly. `compound-loop` is the exception: `compound_loop.py:95-97` builds its project path by hand rather than calling `resolve_project_dir`, so task 6 cannot copy task 4's diff.
- **Wave B** (task 8): `pre-compact` alone. It is the only consumer of task 1 and the only plain-text channel; it gets its own review.
**Task 9 inherits the F7 defect in a second spelling.** `session_start_preflight._credentials_path()` (`:54-57`) reads `os.environ["CLAUDE_CONFIG_DIR"]` directly, falling back to `~/.claude`. That is the same "resolve globally, ignore the profile" shape PR #300 fixed for `hooks.log`, wearing a different mask: a hook invoked with `--profile p` checks whichever profile the ambient environment names, so the preflight can report a healthy login for a profile the session is not running under — which is exactly the failure the check exists to catch. It is not a `get_agent` call, so the task 21 audit does not see it.

  The fix is `agent_dir_for(cfg, event.profile)` and the adapter's own credentials location, but **note the scope**: this hook reads a Claude Code credentials file by name, so the per-profile fix and the per-agent one are different changes. Task 9 does the first and records the second.

**Row 12 is left unresolved on purpose, and task 12's first job is to resolve it.** The table asserts nothing it knows to be wrong.

  `herdr-context-gauge` *handles* four events and special-cases two: `main` branches on `PostToolUse` (`:172`) and `SessionEnd` (`:175`) and falls through for everything else. Its docstring claims three (`:12-13`) and `docs/how/hooks.md:486` names four. But which events it actually receives is the operator's placement, not the code's: `BuiltinHookSpec.event` is already unset (`loader.py:109`) and `plugins/builtins.py:62` says so. So `event=` **stays unset** — not a guess at `post_tool_use` — and that is safe because a payload naming its own event wins over the registry (`runner._canonical_event`).

  The signal set has no correct single value, which is why the row says so. `signals` applies to every placement of one spec, and this hook's placements disagree: the Stop path reads token usage, while the SessionEnd path deliberately reads no transcript at all (`:175`) because its whole job is retracting a dead session's gauge. Declaring `TOKEN_USAGE` makes `deploy` omit *both* on an adapter lacking the signal, leaving the gauge on the pane forever. Task 12 chooses — split the retract into its own builtin, or model the capability per placement — and records which. Trap 2 above applies here first, before either.

- **Wave C** (tasks 9–12): the context-emitting hooks. `stop-context-rotate` imports `context_tokens` from `herdr_context_gauge` (`stop_context_rotate.py:39`), so those two land together or task 11 goes second.
- **Wave D** (tasks 13–15): PostToolUse. Each reads `event.tool.edits` where it used to read `tool_input["file_path"]`.

  > **`MODIFY_FILE` is wider than `INSPECTED_TOOLS` and the difference is `NotebookEdit`.** Five builtins gate on `frozenset({"Edit", "Write"})` (`post_tool_use_format.py:18`, `post_tool_use_sync_claude.py:25`, `post_tool_use_ansible_lint.py:20`, `pre_tool_use_memory_size.py:26`); `_TOOL_OPERATIONS` maps `NotebookEdit` to `MODIFY_FILE` too (`claude_code.py:97`). Switching the guard from the tool set to the operation therefore makes all five act on `.ipynb` for the first time — effective immediately for `post-tool-use-format`, which carries no matcher. Keep the narrowing explicit (check `event.tool.native_name` against the same set, or exclude notebooks by suffix) and say which; do not let a widening ride in as a normalisation. Deleting `INSPECTED_TOOLS` outright also drops the hook from `tests/unit/test_hook_matcher_coverage.py:83-88` without a failure.
- **Wave E** (tasks 16–18): PreToolUse. Task 18 is the only blocking hook in this plan and is the one that must be exercised through the `Verdict.DENY` path with dependencies mocked away.

**Task 8, `pre-compact`, carries two defects the migration must decide about — neither is a migration defect, and both become permanent if the migration papers over them.**

**It is the only builtin built to run without the package, and the runner removes that.** `_resolve_agent_dirs` (`:144-149`) catches `ImportError` and falls back to reading `CLAUDE_CONFIG_DIR` directly; `_bootstrap_log` (`:31`) and `_bootstrap_project_dir` (`:42`) stand in for the `_shared` helpers on that path, and `main:175-180` binds them. The docstring says why: *"this hook has to run as a bare script, so nothing outside this guard may import from the package"*. A migrated `main(event)` is reached only through `hooks.runner`, which imports the module from inside the package — so every one of those fallbacks becomes unreachable. Task 8 deletes them **deliberately and says so in the commit**, or the migration is a silent capability loss dressed as a refactor. (Nothing else in the fifteen has this shape; it is `pre-compact`'s alone.)

**Its transcript parser has been reading nothing, and its declared signals describe that dead code.** `parse_transcript` (`:63-64`) reads `obj.get("role")` and `obj.get("content")` at the **top level** of each JSONL line. Claude Code nests both under `message` — `herdr_context_gauge._usage_of:47-52` already knows this and reaches through `entry["message"]["usage"]`. Measured across 40 session files, 5,153 lines: **zero** carry a top-level `role`, and zero match the `assistant` + list-`content` branch the tool-use extraction needs. Both loops are dead. The only thing this hook has ever emitted is `build_memory_tails(memory_dir)`.

That is why row 8 declares **no signals**. Declaring `MESSAGES` and `TOOL_CALLS` would name reads that do not happen and would let `deploy` omit the hook on an agent whose reader lacks them — losing the memory tails, which are the part that works, over a transcript read that does not.

`specs/backlog.md:36` says this hook *"ya re-inyecta tasks (últimos user_msgs) + archivos (`file_path` de tool_use blocks)"* and closes with *"No queda gap accionable."* Both halves are false. **Already fixed, ahead of this plan** — corrected on 2026-09-15 in `1e602f2` via the docs short-path, together with step 3 of `docs/how/hooks.md`, which described the extraction as fact. Task 8 inherits nothing here; the parser repair itself is still open as its own backlog entry, and [ADR-010](../adrs/010-pre-compact-preservation.md) still carries the same dead claim because `specs/adrs/**` is off the short-path. Prose that names a mechanism is grepped against the code in both directions, and this one survived because nobody ran it.

Repairing `parse_transcript` is **out of scope for step 5** and belongs in its own commit with its own test, because it changes what the hook emits and every golden captured before it. Open it as a backlog entry; do not fold it into a migration whose acceptance test is byte identity.

- [ ] Task 8 step 0: open the backlog entry for the dead parser, correct `specs/backlog.md:36`, and decide the bootstrap deletion — before writing the first test.

---

**Worked instance — Task 18, `pre-tool-use-git-scope`**, written out because it is the one with a refusal path and the recipe alone is not enough for it.

**What this hook actually does, read from the code rather than from its name.** It guards `git stash`, and nothing else. `_STASH_CALL` (`:84`) matches `git … stash <args>` through shell keywords, assignments and wrappers; `_classify` sorts the subcommand into read-only (`list`, `show`), always-unsafe (`pop`, `store`, `create`, …) or safe. `should_block` (`:321`) refuses **only** when all three hold: the command contains an unsafe stash, `stash_stack_is_shared(cwd)` is true, and no configured allow pattern matches. That middle condition is **not** "is this a linked worktree", which an earlier draft of this plan said three times. `stash_stack_is_shared` (`:254-278`) returns true for a linked worktree *or* for the main checkout of a repository that has at least one — its docstring (`:257-259`) says so, because the stack belongs to the repository and both sides reach it. A repository with no linked worktrees keeps its stack private and is left alone. Everything else exits 0. A test built around a forced push — which an earlier draft of this plan used — captures a passing hook and proves nothing: a file name says a guard exists, never what it guards.

> **The guard fires on prose about the guard.** Writing this task set it off: a shell command whose *argument* merely contains `git stash pop` is refused, because `_STASH_CALL` matches command text and cannot tell an invocation from a quoted example. Not a defect to fix here — the hook is correct to be literal — but it is the cheapest available evidence that step 6's evasion testing has real surface to work on, and it is why this file was written through an editor rather than a heredoc.

**Files:**
- Modify: `src/lazy_harness/hooks/builtins/pre_tool_use_git_scope.py:350` (`_read_stdin_json`), `:365-395` (`main`)
- Modify: `src/lazy_harness/hooks/loader.py` (the `pre-tool-use-git-scope` entry)
- Test: `tests/unit/hooks/builtins/test_pre_tool_use_git_scope.py`
- Create: `tests/goldens/hooks/pre-tool-use-git-scope/`

- [ ] **Step 1: Capture the golden from the unmigrated hook**

The cwd must reach a shared stack — a linked worktree, or a main checkout that has one — or `should_block` returns `None` and the golden records a pass. **And the golden is environment-dependent:** `load_allowlist` (`:289`) reads the real `config.toml`, so a profile carrying a matching `allow_patterns` entry turns the refusal into a pass and the golden records the wrong thing. Pin the allowlist empty. Build the payload in a file rather than inline: the guard refuses a command line carrying its own trigger text.

```bash
mkdir -p tests/goldens/hooks/pre-tool-use-git-scope
python3 - <<'EOF' > /tmp/gitscope-payload.json
import json, subprocess
wt = subprocess.run(["git","rev-parse","--show-toplevel"],capture_output=True,text=True).stdout.strip()
print(json.dumps({"tool_name":"Bash","tool_input":{"command":"git st"+"ash pop"},"cwd":wt,"session_id":"s"}))
EOF
uv run --frozen python -m lazy_harness.hooks.builtins.pre_tool_use_git_scope \
  < /tmp/gitscope-payload.json \
  > tests/goldens/hooks/pre-tool-use-git-scope/deny.stdout \
  2> tests/goldens/hooks/pre-tool-use-git-scope/deny.stderr
echo $? > tests/goldens/hooks/pre-tool-use-git-scope/deny.exit
```

Assert before moving on: `deny.exit` is `2` and `deny.stderr` starts `Blocked by lazy-harness PreToolUse: unsafe git stash (scope).`. If it is `0`, either the cwd reached no shared stack or an allow pattern matched — worthless either way.

**Use the existing harness, do not invent files.** `tests/unit/hooks/builtins/_goldens.py` already owns golden capture here: JSON per branch, a pinned environment, capture gated behind `LH_CAPTURE_GOLDENS`, comparison through `assert_golden` (`:171`). Three raw files captured against ambient config and cwd are unreproducible *and* a second answer to a question that already has one — this plan's own constraint about one importable place applies to test infrastructure too. The shell above is the *shape* of the capture; run it through `_goldens.py`.

- [ ] **Step 2: Write the failing test**

```python
_POP = "git st" + "ash pop"  # kept out of one literal so the guard does not refuse the test run


def test_git_scope_refuses_an_unsafe_stash_through_the_verdict(worktree_cwd: Path) -> None:
    """An always-unsafe stash subcommand from a linked worktree.

    All three conditions of `should_block` are supplied: the unsafe subcommand,
    a cwd whose stash stack is shared, and no allow pattern.
    """
    event = HookEvent(
        event="pre_tool_use",
        profile="p",
        session_id="s",
        cwd=worktree_cwd,
        transcript_path=None,
        tool=ToolCall(
            native_name="Bash", operation=Operation.RUN_COMMAND, command=_POP
        ),
    )
    decision = main(event)
    assert decision.verdict is Verdict.DENY
    assert "unsafe git stash" in decision.reason


def test_git_scope_abstains_where_no_one_else_reaches_the_stack(plain_repo: Path) -> None:
    """The same command in a repository whose stash stack nobody else reaches.

    `plain_repo` is a real checkout with an absent or empty `.git/worktrees`,
    not a bare `tmp_path`: a directory with no `.git` at all exercises
    `_find_dot_git` returning None, a different branch, and would let this
    test pass against a guard that had lost the worktree check entirely.
    """
    event = HookEvent(
        event="pre_tool_use",
        profile="p",
        session_id="s",
        cwd=plain_repo,
        transcript_path=None,
        tool=ToolCall(
            native_name="Bash", operation=Operation.RUN_COMMAND, command=_POP
        ),
    )
    assert main(event).verdict is None


def test_git_scope_still_refuses_from_the_main_checkout_of_a_repo_with_worktrees(
    main_checkout_with_worktrees: Path,
) -> None:
    """The stack belongs to the repository, so both sides are guarded.

    `stash_stack_is_shared` is true for a linked worktree *or* for the main
    checkout of a repo that has one (`pre_tool_use_git_scope.py:254-278`).
    Without this, the pair above passes against a guard narrowed to linked
    worktrees only -- which is what an earlier draft of this plan described.
    The suite already has the fixture: `_make_main_checkout_with_worktrees`
    (`test_pre_tool_use_git_scope.py:117`).
    """
    event = HookEvent(
        event="pre_tool_use",
        profile="p",
        session_id="s",
        cwd=main_checkout_with_worktrees,
        transcript_path=None,
        tool=ToolCall(
            native_name="Bash", operation=Operation.RUN_COMMAND, command=_POP
        ),
    )
    assert main(event).verdict is Verdict.DENY


def test_git_scope_declares_the_operation_it_guards() -> None:
    """Declared, not inferred from the `Bash` matcher, which names Claude Code's
    own tool. Another agent's translated matcher still has to be asked whether
    the operation exists there."""
    spec = _BUILTIN_HOOKS["pre-tool-use-git-scope"]
    assert spec.operations == frozenset({Operation.RUN_COMMAND})
    assert spec.blocking is True


def test_git_scope_refuses_rather_than_abstains_when_it_cannot_run() -> None:
    """Exit 0 with no output is how a hook says 'no objection'.

    Reached through the runner's failure policy on an unparseable payload, not
    through a denied command, so the refusal is the *blocking* path and not the
    guard working normally.
    """
    out = run_hook("pre-tool-use-git-scope", profile="p", stdin_text="not json")
    assert out.exit_code == 2
```

- [ ] **Step 3: Run to verify it fails**

Run: `uv run --frozen pytest tests/unit/hooks/builtins/test_pre_tool_use_git_scope.py -v`
Expected: FAIL — `main()` takes no argument.

- [ ] **Step 4: Implement**

Delete `_read_stdin_json`; change `main` to take `event` and return `HookDecision`. `INSPECTED_TOOLS` and the `tool_input` guards collapse into `event.tool is None or event.tool.operation is not Operation.RUN_COMMAND`, and the command comes from `event.tool.command`. `cwd` comes from `event.cwd`, keeping the `os.getcwd()` fallback for `Path("")`. Replace `sys.stderr.write(...); sys.exit(2)` with `return HookDecision(verdict=Verdict.DENY, reason=_format_block_message(verdict))` — the adapter puts `reason` on stderr and exits 2 (`claude_code.py:520-521`), which is what makes the bytes identical. Every `sys.exit(0)` becomes `return HookDecision()`. The blanket `except Exception: sys.exit(0)` becomes `return HookDecision()`; keep it, the fail-open is deliberate and documented.

**Two failure policies meet here and the plan must not pretend they agree.** The Global Constraints say a *blocking* builtin refuses when it cannot run, and this is the only blocking hook in the fifteen. Its own `except Exception` abstains instead, on purpose: "a bug here must not block honest work" (`:394`). Both survive, at different layers — the builtin fails open on a bug *inside its own logic*, `run_hook` refuses when it cannot even construct the event (decision 3, `runner.py:119-124`). Do not collapse them.

That layering is also **the one exception to this plan's byte-identity constraint**, and it belongs in the PR body rather than looking like a regression in a diff: today `_read_stdin_json` (`:350`) returns `{}` on unparseable stdin and the hook exits 0; after migration the runner refuses with exit 2 before the builtin is reached.

In `loader.py`:

```python
    "pre-tool-use-git-scope": BuiltinHookSpec(
        module="lazy_harness.hooks.builtins.pre_tool_use_git_scope",
        matcher="Bash",
        event="pre_tool_use",
        blocking=True,
        operations=frozenset({Operation.RUN_COMMAND}),
        migrated=True,
    ),
```

- [ ] **Step 5: Run to verify it passes, and the golden with it**

Run: `uv run --frozen pytest tests/unit/hooks/ -v`
Expected: PASS, and the bytes on all three channels equal to `deny.stdout` / `deny.stderr` / `deny.exit`. The golden is compared by a test you write under `tests/unit/hooks/builtins/`; `tests/goldens/` holds fixtures and collects nothing on its own, so `pytest tests/goldens` verifies nothing.

- [ ] **Step 6: Attack the denylist with evasions of its own patterns**

Mutation coverage proves the guard has branches, not that it covers anything. `_STASH_CALL` is a regex over shell text, so attack it there: repeated whitespace between `git`, `stash` and the subcommand; a global option between them (`-c core.pager=cat`); an assignment prefix (`GIT_DIR=.`); a wrapper (`env`); and a compound where the unsafe call is second, which `is_unsafe_stash` claims to judge because it iterates every match. Those five are inside what the regex declares it covers, so they check that it does what it says. The interesting set is outside it, found by reading `_COMMAND_START` (`:61`): a quoted invocation (`sh -c "…"`), a backslash-escaped command name, a quoted subcommand, and a redirect before the command.

**Record what got through in a versioned file** — `specs/backlog.md`, or a docstring on `_STASH_CALL`. A PR body is not where a future reader looks for a guard's known gaps.

- [ ] **Step 7: Commit**

```bash
git add -A && git commit -m "refactor: migrate pre-tool-use-git-scope to the hook contract"
```

---

## Task 19: Delete the transitional branch

Only once all fifteen are `migrated=True`. The field, the constant and both branches reading them die together — that is what the docstrings on each promise.

**Files:**
- Modify: `src/lazy_harness/hooks/loader.py` — delete `BuiltinHookSpec.migrated`, `PRE_RUNNER_AGENT`, `builtin_migrated()`
- Modify: `src/lazy_harness/cli/hooks_cmd.py:88-121` — delete the `if spec.migrated:` branch and everything after it in the `else`
- Modify: `src/lazy_harness/hooks/engine.py:59` — `execute_hook` reads `spec.migrated`; **task 20 must land first or this task's own test suite fails with `AttributeError`**
- Modify: `src/lazy_harness/deploy/engine.py:204-233` and `:223` — `_warn_unmigrated` has nothing left to warn about
- Delete: `tests/unit/test_deploy_unmigrated_hooks.py` in full
- Test: `tests/unit/hooks/test_builtin_registry.py`, `tests/unit/hooks/test_entry_points.py:141-152` and `:213-224` (both call `register(..., migrated=False)`), `tests/unit/hooks/test_abstention.py:62`, `tests/integration/test_deploy_signal_agreement.py`

**Ordering.** This task is numbered 19 and runs *after* 20, not before. Task 20 removes the last reader of `migrated` outside the registry; with it still in place, step 4 below fails on `hooks/engine.py:59`. Running 20 first is safe in the other direction — `cli/hooks_cmd.py:96-121` still routes unmigrated builtins while it stands.

- [ ] **Step 1: Write the failing test**

```python
def test_no_transitional_migration_field_survives() -> None:
    """The field, the constant and the branches reading them die together.

    Asserted on the declaration rather than on behaviour: a leftover
    `migrated=True` on every spec is inert and would never fail a behavioural
    test, while still being the forked answer the design set out to remove.

    Asserted on the dataclass fields and the call graph rather than on the
    source text, because a substring check over a file passes or fails on the
    comments explaining the removal as readily as on the removal itself.
    """
    import ast
    import dataclasses

    from lazy_harness.hooks.loader import BuiltinHookSpec, _BUILTIN_HOOKS

    # The field, not the word: `"migrated" not in source` also matches the
    # prose explaining why it is gone, so it passes on a file that still
    # declares it under a comment and fails on one that merely mentions it.
    fields = {f.name for f in dataclasses.fields(BuiltinHookSpec)}
    assert "migrated" not in fields, fields
    assert not hasattr(loader_module, "PRE_RUNNER_AGENT")
    assert not hasattr(loader_module, "builtin_migrated")

    # The dispatch, not the import: `importlib` may return to `hooks_cmd.py`
    # for an unrelated reason, and its absence would then read as proof of
    # something it never established. Assert on the call graph instead.
    tree = ast.parse((SRC / "cli" / "hooks_cmd.py").read_text(encoding="utf-8"))
    called = {
        node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }
    assert "import_module" not in called, "the pre-runner dispatch still imports a builtin"
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run --frozen pytest tests/unit/hooks/test_builtin_registry.py -v`

- [ ] **Step 3: Implement the deletions**

- [ ] **Step 4: Run the full suite**

Run: `uv run --frozen pytest -v`
Expected: PASS. A failure here names a builtin whose migration task is not actually finished.

- [ ] **Step 5: Confirm the deploy no longer emits the warning**

Run: `uv run --frozen lh deploy --dry-run --profile <a codex profile>`
Expected: no `unmigrated` line in the output. Read the deploy's own output — a registered hook is not a hook that runs.

- [ ] **Step 6: Commit**

```bash
git add -A && git commit -m "refactor: delete the pre-runner hook dispatch branch"
```

---

## Task 20: Collapse the second execution mechanism

**Read the code before this task, not the design.** The design's decision 1 says `hooks/engine.py:27-33` runs `subprocess.run([sys.executable, str(hook.path)], …)` for everything, so a builtin whose `main` requires an argument breaks at `if __name__ == "__main__":`. **That is step 3's text and the code has moved past it.** `execute_hook` today (`engine.py:58`) already routes a `migrated` builtin through `[sys.executable, "-c", CLI_BOOTSTRAP, "hook", <name>, "--profile", …]` and uses the hook *file* only for an unmigrated builtin or a user hook (`:69`); its own docstring says so. An earlier draft of this plan asserted the design's version and would have sent an executor chasing a bug that was fixed.

What is actually left is smaller and is a consequence of task 19: once `migrated` is gone, `engine.py:58`'s condition has nothing to read. The branch becomes "is this a builtin at all" — builtins through the CLI, user hooks through the file — and `PRE_RUNNER_AGENT`'s last reader goes with it.

The `subprocess` stays. Calling `run_hook` in-process cannot honour `timeout`: Python cannot interrupt a synchronous call, so that branch ignored the argument and reported `timed_out=False` unconditionally. `engine.py:42-53` records this; do not "simplify" it away.

**Files:**
- Modify: `src/lazy_harness/hooks/engine.py:58-70` (`execute_hook`)
- Test: `tests/unit/hooks/test_entry_points.py`

**Interfaces:**
- Consumes: `hooks.loader.HookInfo.is_builtin`
- Produces: `execute_hook` dispatches on `hook.is_builtin` alone; no caller signature changes.

- [ ] **Step 1: Write the failing test**

`lh hooks run` hands the runner `payload={}` (`cli/hooks_cmd.py:159`) and does not read stdin, so an assertion comparing the two entry points on a fed payload compares nothing. Assert the *dispatch*, which is the thing that changes.

```python
def test_every_builtin_is_executed_through_the_cli_not_its_file(monkeypatch) -> None:
    """One execution mechanism for builtins, whatever the registry says.

    Asserted on the argv `execute_hook` builds rather than on output: the
    defect this catches is a builtin being spawned as a script, which on a
    migrated `main(event)` fails at `__main__` and reports a non-zero exit that
    looks like the hook having an opinion.
    """
    seen: list[list[str]] = []
    monkeypatch.setattr(
        "lazy_harness.hooks.engine.subprocess.run",
        lambda cmd, **kw: seen.append(cmd) or _completed(),
    )
    for name in list_builtin_hooks():
        info = resolve_hook(name)
        assert info is not None
        execute_hook(info, event="session_start", payload={}, profile="p")
    assert all("-c" in cmd and "hook" in cmd for cmd in seen), seen
    assert not any(cmd[-1].endswith(".py") for cmd in seen), seen


def test_a_user_hook_is_still_executed_as_a_file(tmp_path: Path, monkeypatch) -> None:
    """The registry never heard of it and it has no `main(event)` to call."""
    script = tmp_path / "mine.py"
    script.write_text("import sys; sys.exit(0)\n")
    seen: list[list[str]] = []
    monkeypatch.setattr(
        "lazy_harness.hooks.engine.subprocess.run",
        lambda cmd, **kw: seen.append(cmd) or _completed(),
    )
    execute_hook(
        HookInfo(name="mine", path=script, is_builtin=False),
        event="session_start",
        payload={},
        profile="p",
    )
    assert seen[0][-1] == str(script)
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run --frozen pytest tests/unit/hooks/test_entry_points.py -v`
Expected: FAIL before task 19 lands — the unmigrated builtins are spawned as files, so `seen` carries `.py` paths.

- [ ] **Step 3: Implement**

```python
    if hook.is_builtin:
        cmd = [
            sys.executable,
            "-c",
            CLI_BOOTSTRAP,
            "hook",
            hook.name,
            "--profile",
            resolve_profile(profile),
        ]
    else:
        cmd = [sys.executable, str(hook.path)]
```

- [ ] **Step 4: Run to verify it passes**

Run: `uv run --frozen pytest tests/unit/hooks/ -v`

- [ ] **Step 5: Exercise it for real, not through the mock**

Run: `uv run --frozen lh hooks run session_start --profile <a declared profile>`
Expected: every configured hook reports, none with a traceback. A registered hook is not a hook that runs, and this is the only step here that proves the argv is well-formed.

- [ ] **Step 6: Commit**

```bash
git add -A && git commit -m "refactor: dispatch builtins on is_builtin rather than a migration flag"
```

---

## Task 21: The literal sweep, and what `profile_name()` keeps

**Files:**
- Modify: nothing new — the ten global resolutions are removed by tasks 4–18, each in its own commit. This task is the audit that proves none was missed, plus the two records below.
- Modify: `src/lazy_harness/hooks/builtins/_shared.py` — `profile_name()` gains a docstring naming its four surviving callers
- Modify: `specs/backlog.md` — close *Ocho builtins resuelven su `hooks.log` globalmente*
- Test: `tests/unit/hooks/test_builtin_contract.py`

- [ ] **Step 1: Write the failing test**

```python
def test_no_builtin_resolves_its_agent_globally() -> None:
    """Ten global resolutions, by mechanism rather than by spelling.

    A grep for `get_agent("claude-code")` finds seven of the ten and misses
    `engram_persist.py:75` and `pre_compact.py:158`, which write
    `get_agent(cfg.agent.type if cfg is not None else "claude-code")` -- the
    exact difference the CLAUDE.md gate is written for, and the one an earlier
    draft of this plan walked into. Matching the `get_agent` *call* rather than
    any spelling of its argument is what makes the count independent of how the
    next one is written.
    """
    offenders = {}
    for path in _BUILTINS_DIR.glob("*.py"):
        if path.name == "_shared.py":
            continue  # `agent_dir_for`'s documented no-config degradation
        src = path.read_text(encoding="utf-8")
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and getattr(node.func, "id", "") == "get_agent":
                offenders.setdefault(path.name, []).append(node.lineno)
    assert offenders == {}, f"builtins resolving an agent without a profile: {offenders}"
```

- [ ] **Step 2: Give the test a red phase it would otherwise never have**

Run as written after tasks 4–18 this test passes on its first execution, which is the shape of a test that covers nothing. It gets its red phase the only honest way available: **write and land it first**, before task 4, where it fails naming all ten sites; then each migration task removes one name from the failure. Add it to task 3's commit.

If it is instead written last, prove it by hand: reintroduce `get_agent("claude-code")` into one migrated builtin, watch the test name that file, remove it by hand. **Never `git checkout`** — it reverts the uncommitted work too.

Run: `uv run --frozen pytest tests/unit/hooks/test_builtin_contract.py -v`

- [ ] **Step 3: Record what `profile_name()` keeps**

It is not deleted. Add to its docstring:

```python
    """...

    Survives step 5 rather than being deleted with the builtins' other
    pre-runner helpers. Four call sites remain across three modules, none of
    them a builtin: one in `cli/metrics_cmd.py`, two in
    `knowledge/compound_loop.py`, and one in `hooks/runner.py:resolve_profile`.

    That last is `resolve_profile`'s fallback, and it is live behaviour on the
    ordinary path rather than compatibility for stale settings files: both
    entry points declare `--profile` with `default=None` and hand it straight
    through, so every flagless invocation lands here. Two tests pin it.

    The design's step 5 text says "delete"; the code says "remove from the
    builtins", and this is the difference.
    """
```

- [ ] **Step 4: Commit**

```bash
git add -A && git commit -m "refactor: sweep the global agent literals out of the builtins"
```

---

## Task 22: Re-run the isolation gate against the shipped binary

The step 4 gate lived in `/tmp/f7-gate/`, outside the repo, where CI could not reproduce it. It is now versioned under `specs/gates/f7/`, which is what makes the rest of this task a set of paths rather than a ritual. Running it is not optional.

- [ ] **Step 1: Merge, let release-please cut, and install the tag explicitly**

```bash
TAG=$(gh release view --json tagName --jq .tagName)   # resolve it, do not type it
uv tool install --reinstall "git+https://github.com/lazynet/lazy-harness@${TAG}"
```

`--reinstall` alone reinstalls the **pinned** rev from `uv-receipt.toml` and its exit code proves nothing about which revision landed, so the tag is passed explicitly and resolved from the release rather than written by hand.

- [ ] **Step 2: Grep site-packages for a changed signature, not a version**

```bash
SP=$(uv tool dir)/lazy-harness/lib/python3*/site-packages/lazy_harness
test -d $SP || { echo "site-packages not found at $SP"; exit 1; }
grep -rn 'PRE_RUNNER_AGENT' $SP; echo "grep exit=$?"
```

**Unquoted on purpose, and the `test -d` is the point.** `python3*` is a glob and does not expand inside double quotes — quoted, `grep` is handed a literal `python3*` directory, reports it missing, and a missing directory reads exactly like a missing symbol. The absence proves the fix shipped only once the directory is proven to exist.

Expected: no hits. **The absence of a symbol that used to be there is the cheap proof the fix shipped.** A version number is not — it moves whether or not the code did.

- [ ] **Step 3: Run the gate with all fifteen in scope**

```bash
specs/gates/f7/isolation-gate.sh "$(command -v lh)"
```

The known-gap list should print empty, and `pre-compact` must be **invoked** rather than skipped — it is absent from the step 4 counts only because the gate never called it, not because it was clean.

**Neither is something to arrange by hand.** The gate's asserted and known-gap sets are derived from the registry (`list_builtin_hooks()` + `builtin_migrated()`), so the gap list empties itself as tasks 4–18 land and `pre-compact` enters the asserted set the moment it is marked migrated. An empty gap block is therefore evidence that the migration is complete, not a number someone remembered to update. If the block is not empty, name which builtins are still in it.

Run both controls in the same sitting — `fake-lh-fixed.sh` must exit 0 and `fake-lh-security-only.sh` must exit 1, per the repo's gate about feeding a checker a case it must pass *and* one it must fail. If either verdict flips, the gate regressed and this task's result means nothing.

- [ ] **Step 4: Record the result**

A single run that exercises all four properties at once. The step 4 pass was **composite** — run 2 (0.67.0) carried A+B+C1/C2/C3 through a real `codex exec` and failed on isolation; run 3 (0.67.1) was the isolation half alone. No binary has passed all four properties in one run. Do not let this one inherit that phrasing: say which run proved what.

- [ ] **Step 5: Close the backlog entry with the measurement, not the intent**

---

## Self-review

**Spec coverage.** Step 5's four clauses: migrate the fifteen (tasks 4–18) ✓; declare `Operation` and `Signal` per builtin (the table, and step 5 of each recipe) ✓; delete `profile_name()` (task 21 — **narrowed, with evidence**, and the divergence recorded) ✓; delete `_TRANSCRIPT_KEYS` (task 3) ✓; the literals (task 21 — **ten, not the seven the step text implies**; no syntactic criterion found them all, see the count's own history above) ✓. The design's two displaced prerequisites — the second entry point and the transitional field — are tasks 20 and 19.

**Gaps this plan opens deliberately.** `_shared.py:258`, `knowledge/compound_loop_worker.py:98` and `:100`, `cli/memory_cmd.py:237` and `:264`, and `monitoring/statusline.py:44` stay global by decision, not oversight; none is a builtin, and task 21's test excludes `_shared.py` explicitly because it is the one inside the replacement helper itself.

**Risk that outranks the rest.** Task 1. `pre-compact` is the only builtin whose migration can pass every test and still be dead on the wire, because the channel it speaks is not the channel the contract serialises to. If only one task gets an independent review by a different model, it is that one.

# Step 5 — Builtin Migration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Migrate the fifteen builtins still on the pre-runner path to `main(event: HookEvent) -> HookDecision`, each declaring its `Operation` and `Signal` sets, and delete the transitional branch that keeps them alive.

**Architecture:** Each builtin stops parsing stdin and stops serialising Claude Code's JSON; the adapter owns both translations and the builtin sees only `HookEvent` and returns only `HookDecision`. Three adapter- and substrate-level defects (tasks 1–3) block the bulk migration and land first. The fifteen migrations (tasks 4–18) parallelise apart from two shared files, named where the waves are. The second entry point, the transitional field and the literal sweep close behind them — **task 20 before task 19**, for the reason recorded there.

**Tech Stack:** Python 3.11+, `uv run --frozen`, `pytest`, `ruff`, strict type hints.

**Spec:** [`specs/designs/2026-09-13-multi-agent-harness-design.md`](2026-09-13-multi-agent-harness-design.md), step 5 (the numbered list at `design.md:1747`), decisions 1, 3, 9 and 11. Contract frozen by [ADR-041](../adrs/041-multi-agent-hook-contract.md), `accepted` 2026-09-15.

## Global Constraints

- **Byte identity is the acceptance test.** `parse_hook_input` and `format_hook_output` are identity for Claude Code, so the wire bytes Claude Code sees must not change. Every migrated builtin gets a golden under `tests/goldens/hooks/<name>/` captured **before** its `main()` is touched.
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

The mapping every task below applies. **It is not exhaustive and must not be treated as such** — `herdr-context-gauge:166` reads `payload.get("hook_event_name")`, which has no row here and maps to `event.event`. Each task confirms its own builtin's reads against the source before applying the table; a key with no row is a gap in the table, not a field to drop.

| Today | After |
|---|---|
| `json.load(sys.stdin)` | deleted; the runner parses and the adapter normalises |
| `payload.get("cwd")` | `event.cwd` |
| `payload.get("session_id")` | `event.session_id` |
| `transcript_from_payload(payload)` | `event.transcript_path`, **plus an `.is_file()` check** — see task 3 |
| `payload.get("prompt")` | `event.prompt` |
| `payload.get("trigger")` | `event.trigger` |
| `payload.get("source")` | `event.source` |
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

---

## Tasks 4–18: the fifteen builtins

Each is one TDD cycle and one commit, and each depends only on tasks 1–3.

**They are not file-independent, and the plan does not pretend otherwise.** Every migration edits `hooks/loader.py`'s `_BUILTIN_HOOKS` (`loader.py:101`) to add its `operations`, `signals`, `event` and `migrated` — one shared dict, fifteen times. There is a second: `tests/unit/hooks/test_abstention.py:41-75` derives `_NO_OBJECTION` from the registry and fails when a migrated hook wired to a blockable event has no entry. With `session_stop` honouring `BLOCK` and `pre_tool_use` honouring `DENY`, that reaches seven of the fifteen — tasks 4, 6, 7, 11, 16, 17 and 18. Both conflicts are appends and resolve mechanically, but a task that does not know about the second one lands red. Two workable orders, pick one and say which in the PR:

- **Serialise the registry.** Land one commit first that gives all fifteen specs their final `event`, `operations`, `signals` and `blocking`, leaving `migrated=False`. The declarations are a fact about each hook and are true before its `main()` moves. Then the fifteen migrations touch only their own module and genuinely parallelise.
- **Accept the rebases.** Each task rebases on `main` before pushing. Cheaper to start, and the cost lands on whoever merges last.

The first is preferred: it makes the declaration table reviewable in one diff, which is where a wrong `signals` set is actually visible.

**Per-builtin recipe, applied identically in each:**

1. **Capture the golden first.** `tests/goldens/hooks/<name>/` — feed the pre-migration `main()` a representative payload on stdin, record stdout bytes and exit code. The golden is captured from the **unmigrated** hook, so it is evidence and not a restatement of the new code.
2. Change the signature to `main(event: HookEvent) -> HookDecision`.
3. Apply the payload→event mapping table. Delete the `json.load(sys.stdin)` preamble and every `sys.exit`.
4. Replace the boot-dir dance with `agent, agent_dir = agent_dir_for(cfg, event.profile)`, **loading config before the first log line is written** — the ordering `context-inject` was fixed to in PR #300. Writing `fired` before config loads is what sent it to the global agent's directory.
5. Declare `operations=` and `signals=` on the builtin's `BuiltinHookSpec` in `hooks/loader.py`, and set `event=` and `blocking=` where they apply. Leave `migrated=True`.
6. Assert the golden still matches, byte for byte.
7. Assert profile isolation: invoke under `--profile <p>` and assert the `hooks.log` line lands in `<p>`'s directory **and is absent from the global one**. Presence alone does not detect the defect — PR #300 measured a weak presence assertion passing against a broken hook.

**The declarations, per builtin.** Derived from what each one reads **in its own process**, not from its matcher and not from what something downstream reads later.

> **Provenance, stated because it bounds how far this table can be trusted.** Rows 4–8 and 16–18 were derived by reading each `main()` and its output helpers. Rows 9–15 were derived from greps over the output calls and the `INSPECTED_TOOLS` constants, which is weaker — and three review passes have each found a different row wrong that way, most recently row 12. **Step 0 of each of tasks 9–15 is to read that builtin end to end and correct its row before writing any test.** A wrong `signals` set is not a documentation error: `deploy` refuses to install a hook whose signals the profile's agent does not supply, so an invented signal silently undeploys a working hook.

That distinction decides two rows. `session-end` (`session_end.py:115`, `:152`) and `compound-loop` (`compound_loop.py:93`, `:123`) *locate* a transcript and enqueue its path; the compound-loop worker reads messages and tool calls afterwards, out of process. Declaring `MESSAGES` for either would make the deploy refuse to install them on an agent whose reader cannot supply a signal the hook never touches. `session-export` is the contrast and keeps `MESSAGES`: it consumes message text in-process (`knowledge/session_export.py:43`).

| # | Builtin | `event` | `operations` | `signals` | `blocking` | Output channel today |
|---|---|---|---|---|---|---|
| 4 | `session-export` | `session_stop` | — | `MESSAGES` | no | none (log only) |
| 5 | `session-end` | `session_end` | — | **none** | no | none (log only) |
| 6 | `compound-loop` | `session_stop` | — | **none** | no | none (log only) |
| 7 | `engram-persist` | `session_stop` | — | — | no | none |
| 8 | `pre-compact` | `pre_compact` | — | `MESSAGES`, `TOOL_CALLS` | no | **plain text** (task 1) |
| 9 | `session-start-preflight` | `session_start` | — | — | no | `additionalContext` |
| 10 | `user-prompt-goal` | `user_prompt_submit` | — | — | no | `additionalContext` |
| 11 | `stop-context-rotate` | `session_stop` | — | `TOKEN_USAGE` | no | `systemMessage` |
| 12 | `herdr-context-gauge` | **four, see below** | — | `TOKEN_USAGE` (but see below) | no | none |
| 13 | `post-tool-use-format` | `post_tool_use` | `MODIFY_FILE` | — | no | none |
| 14 | `post-tool-use-sync-claude` | `post_tool_use` | `MODIFY_FILE` | — | no | none |
| 15 | `post-tool-use-ansible-lint` | `post_tool_use` | `MODIFY_FILE` | — | no | `additionalContext` |
| 16 | `pre-tool-use-read-size` | `pre_tool_use` | `READ_FILE` | — | no | `systemMessage` |
| 17 | `pre-tool-use-memory-size` | `pre_tool_use` | `MODIFY_FILE` | — | no | `systemMessage` |
| 18 | `pre-tool-use-git-scope` | `pre_tool_use` | `RUN_COMMAND` | — | **yes** | exit 2 + stderr |

**Wave ordering for parallel dispatch.** Within a wave the tasks share no files and can run concurrently; waves are sequential because each later one reuses a pattern the earlier one established.

- **Wave A** (tasks 4–7): the four session-lifecycle hooks. They share the identical boot-dir defect, and three of the four share the `find_latest_session` / `resolve_project_dir` call shape, so one reviewer sees the pattern repeatedly. `compound-loop` is the exception: `compound_loop.py:95-97` builds its project path by hand rather than calling `resolve_project_dir`, so task 6 cannot copy task 4's diff.
- **Wave B** (task 8): `pre-compact` alone. It is the only consumer of task 1 and the only plain-text channel; it gets its own review.
**Row 12 does not fit the table and task 12 has to resolve it.** `herdr-context-gauge` is wired to Stop, SessionEnd, SessionStart *and* PostToolUse (docstring `:12-13`, dispatch `main:172-175`) and branches on `payload.get("hook_event_name")`. `BuiltinHookSpec.event` is a single canonical name, so the single-value column above cannot express it — which is fine at runtime, because a payload that names its event wins over the registry (`runner._canonical_event`), but it means `event=` must be left **unset** rather than guessed at `post_tool_use`. Declaring `TOKEN_USAGE` is the second half of the problem: it makes `deploy` omit the hook entirely on an agent without that signal, including its SessionEnd retract path, which reads no transcript at all. Task 12 decides between a narrower signal set and splitting the hook, and records which.

- **Wave C** (tasks 9–12): the context-emitting hooks. `stop-context-rotate` imports `context_tokens` from `herdr_context_gauge` (`stop_context_rotate.py:39`), so those two land together or task 11 goes second.
- **Wave D** (tasks 13–15): PostToolUse. Each reads `event.tool.edits` where it used to read `tool_input["file_path"]`.

  > **`MODIFY_FILE` is wider than `INSPECTED_TOOLS` and the difference is `NotebookEdit`.** Five builtins gate on `frozenset({"Edit", "Write"})` (`post_tool_use_format.py:18`, `post_tool_use_sync_claude.py:25`, `post_tool_use_ansible_lint.py:20`, `pre_tool_use_memory_size.py:26`); `_TOOL_OPERATIONS` maps `NotebookEdit` to `MODIFY_FILE` too (`claude_code.py:97`). Switching the guard from the tool set to the operation therefore makes all five act on `.ipynb` for the first time — effective immediately for `post-tool-use-format`, which carries no matcher. Keep the narrowing explicit (check `event.tool.native_name` against the same set, or exclude notebooks by suffix) and say which; do not let a widening ride in as a normalisation. Deleting `INSPECTED_TOOLS` outright also drops the hook from `tests/unit/test_hook_matcher_coverage.py:83-88` without a failure.
- **Wave E** (tasks 16–18): PreToolUse. Task 18 is the only blocking hook in this plan and is the one that must be exercised through the `Verdict.DENY` path with dependencies mocked away.

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

    Asserted on the source rather than on behaviour: a leftover `migrated=True`
    on every spec is inert and would never fail a behavioural test, while still
    being the forked answer the design set out to remove.
    """
    loader = (SRC / "hooks" / "loader.py").read_text(encoding="utf-8")
    assert "migrated" not in loader
    assert "PRE_RUNNER_AGENT" not in loader
    cmd = (SRC / "cli" / "hooks_cmd.py").read_text(encoding="utf-8")
    assert "importlib" not in cmd, "the unmigrated import path is still reachable"
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
    """Nine literals, by mechanism rather than by spelling.

    A grep for `get_agent("claude-code")` finds seven of the nine and misses
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

    That last is the fallback for a deployed command written before `--profile`
    existed. Both live callers pass a resolved profile, so it is compatibility
    for settings files not yet redeployed rather than a mechanism anything
    depends on -- but it is a caller, and it is why the symbol stays. The
    design's step 5 text says "delete"; the code says "remove from the
    builtins", and this is the difference.
    """
```

- [ ] **Step 4: Commit**

```bash
git add -A && git commit -m "refactor: sweep the global agent literals out of the builtins"
```

---

## Task 22: Re-run the isolation gate against the shipped binary

The step 4 gate lives in `/tmp/f7-gate/`, outside the repo, and CI cannot reproduce it. Whether it gets versioned is an open question this plan does not settle; running it is not optional.

- [ ] **Step 1: Merge, let release-please cut, and install the tag explicitly**

```bash
uv tool install --reinstall "git+https://github.com/lazynet/lazy-harness@v<tag>"
```

`--reinstall` alone reinstalls the **pinned** rev from `uv-receipt.toml`. Pass `git+<url>@<tag>` explicitly.

- [ ] **Step 2: Grep site-packages for a changed signature, not a version**

```bash
grep -rn "PRE_RUNNER_AGENT" "$(uv tool dir)/lazy-harness/lib/python3*/site-packages/lazy_harness/" ; echo "exit=$?"
```

Expected: no hits. **The absence of a symbol that used to be there is the cheap proof the fix shipped.** A version number is not — it moves whether or not the code did.

- [ ] **Step 3: Run the gate with all fifteen in scope**

`KNOWN_GAP_HOOKS` should be empty, and `pre-compact` must be **invoked** rather than skipped — it is absent from the step 4 counts only because the gate never called it, not because it was clean. Add the invoke.

- [ ] **Step 4: Record the result**

A single run that exercises all four properties at once. The step 4 pass was **composite** — run 2 (0.67.0) carried A+B+C1/C2/C3 through a real `codex exec` and failed on isolation; run 3 (0.67.1) was the isolation half alone. No binary has passed all four properties in one run. Do not let this one inherit that phrasing: say which run proved what.

- [ ] **Step 5: Close the backlog entry with the measurement, not the intent**

---

## Self-review

**Spec coverage.** Step 5's four clauses: migrate the fifteen (tasks 4–18) ✓; declare `Operation` and `Signal` per builtin (the table, and step 5 of each recipe) ✓; delete `profile_name()` (task 21 — **narrowed, with evidence**, and the divergence recorded) ✓; delete `_TRANSCRIPT_KEYS` (task 3) ✓; the literals (task 21 — **nine, not the seven the step text implies**, counted by AST rather than by grep) ✓. The design's two displaced prerequisites — the second entry point and the transitional field — are tasks 20 and 19.

**Gaps this plan opens deliberately.** Whether `/tmp/f7-gate/` gets versioned is unresolved and stays that way; task 22 runs it from where it lives. `_shared.py:258`, `knowledge/compound_loop_worker.py:98` and `:100`, `cli/memory_cmd.py:237` and `:264`, and `monitoring/statusline.py:44` stay global by decision, not oversight; none is a builtin, and task 21's test excludes `_shared.py` explicitly because it is the one inside the replacement helper itself.

**Risk that outranks the rest.** Task 1. `pre-compact` is the only builtin whose migration can pass every test and still be dead on the wire, because the channel it speaks is not the channel the contract serialises to. If only one task gets an independent review by a different model, it is that one.

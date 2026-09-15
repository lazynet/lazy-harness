# Step 5 — Builtin Migration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Migrate the fifteen builtins still on the pre-runner path to `main(event: HookEvent) -> HookDecision`, each declaring its `Operation` and `Signal` sets, and delete the transitional branch that keeps them alive.

**Architecture:** Each builtin stops parsing stdin and stops serialising Claude Code's JSON; the adapter owns both translations and the builtin sees only `HookEvent` and returns only `HookDecision`. Three adapter- and substrate-level defects (tasks 1–3) block the bulk migration and land first. The fifteen migrations (tasks 4–18) are independent of one another and parallelise. The transitional field, the second entry point and the literal sweep (tasks 19–21) close behind them.

**Tech Stack:** Python 3.11+, `uv run --frozen`, `pytest`, `ruff`, strict type hints.

**Spec:** [`specs/designs/2026-09-13-multi-agent-harness-design.md`](2026-09-13-multi-agent-harness-design.md), step 5 (line 1674 ff.), decisions 1, 3, 9 and 11. Contract frozen by [ADR-041](../adrs/041-multi-agent-hook-contract.md), `accepted` 2026-09-15.

## Global Constraints

- **Byte identity is the acceptance test.** `parse_hook_input` and `format_hook_output` are identity for Claude Code, so the wire bytes Claude Code sees must not change. Every migrated builtin gets a golden under `tests/goldens/hooks/<name>/` captured **before** its `main()` is touched.
- **Strict TDD, no exceptions** (`CLAUDE.md` non-negotiable 2). Write the failing test, watch it fail, implement, watch it pass.
- **One worktree per task group**, via `/new-worktree` (non-negotiable 1). Commits are conventional, no AI trailers, no `--no-verify`.
- **`/tdd-check` passes before every commit**, all four checks pristine.
- **`uv run --frozen`** on every invocation. A bare `uv run` discards the lockfile.
- **No builtin may read `event.raw` or `event.tool.raw_input`.** `tests/unit/hooks/test_builtin_contract.py` gates this through the AST and will fail the build.
- **Hooks handle every exception explicitly.** A non-blocking builtin returns `HookDecision()` on any failure; a blocking one refuses. The runner's blanket handler is a backstop, not the policy.
- **Versions are owned by release-please.** Never hand-bump.

---

## The substrate, measured

`agent_dir_for(cfg, profile)` (`_shared.py:233`) already exists and is the migration template: it is the one importable answer to "which agent does this profile run and where do its hooks write", and it is what `context-inject` and `pre-tool-use-security` were moved onto by PR #300. Every builtin in this plan replaces its own two-step resolution with one call to it.

### Payload → event mapping

The mapping every task below applies. It is exhaustive for what the fifteen actually read.

| Today | After |
|---|---|
| `json.load(sys.stdin)` | deleted; the runner parses and the adapter normalises |
| `payload.get("cwd")` | `event.cwd` |
| `payload.get("session_id")` | `event.session_id` |
| `transcript_from_payload(payload)` | `event.transcript_path`, **plus an `.is_file()` check** — see task 3 |
| `payload.get("prompt")` | `event.prompt` |
| `payload.get("trigger")` | `event.trigger` |
| `payload.get("source")` | `event.source` |
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

- **The live literals are nine, not ten.** Design line 207 counts `pre_tool_use_security.py:298` and `context_inject.py:758` as live `get_agent("claude-code")` literals. Both are now **docstring prose** describing what PR #300 removed — the code literals are gone. The two that genuinely stay out of step 5 are `knowledge/compound_loop_worker.py:100` (not a builtin, never reaches the runner) and `_shared.py:258` (inside `agent_dir_for`, the documented degradation for a machine that has not run `lh init`). The count of **seven** for step 5 survives; the roster does not.
- **`profile_name()` cannot be deleted at step 5.** Five import sites, and only two are builtins (`session_end.py:35`, `user_prompt_goal.py:131`). The other three are outside the hook path — `cli/metrics_cmd.py:236`, `knowledge/compound_loop.py:1249` and `:1278` — and a fourth, `hooks/runner.py:151`, is the runner's *own* `resolve_profile` fallback, which is the mechanism this whole migration depends on. Step 5 removes it from the builtins; the symbol survives. Task 21 records that.

---

## Task 1: A plain-text output channel for PreCompact

**Blocks every other task.** Migrating `pre-compact` without this silently destroys it, and does so while passing every unit test written against `HookDecision`.

`pre_compact.py:247` writes `print(f"{SUMMARY_PREAMBLE}\n\n{summary}")` — raw text, deliberately. Its module docstring records why, verified against the 2.1.234 binary: Claude Code's `hookSpecificOutput` union has **no PreCompact variant**, so a JSON payload fails schema validation, marks the hook failed, and discards its output. The PreCompact executor collects each successful hook's raw stdout and hands the joined text to the summariser as `newCustomInstructions`.

`ClaudeCodeAdapter.format_hook_output` (`claude_code.py:474`) unconditionally emits `json.dumps(body) + "\n"`. `_HOOK_EVENTS["pre_compact"] = HookSupport("PreCompact")` carries an empty verdict set, so there is no verdict path to ride either. A migrated `pre-compact` returning `HookDecision(additional_context=summary)` serialises to `{"hookSpecificOutput": {"hookEventName": "PreCompact", "additionalContext": …}}` — exactly the payload the docstring says is discarded.

**Files:**
- Modify: `src/lazy_harness/agents/claude_code.py:474-520` (`format_hook_output`)
- Test: `tests/unit/agents/test_claude_code_adapter.py`

**Interfaces:**
- Consumes: `HookEvent`, `HookDecision`, `HookOutput` from `agents/base.py`
- Produces: `format_hook_output` returns `HookOutput(stdout=<raw text>, stderr="", exit_code=0)` when `event.event == "pre_compact"` and `decision.additional_context` is set. No other event changes shape.

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

Run: `uv run --frozen pytest tests/unit/agents/test_claude_code_adapter.py -k pre_compact -v`
Expected: FAIL — `out.stdout` is the JSON document, not `"Preserve X"`.

- [ ] **Step 3: Implement**

In `format_hook_output`, before the `body` assembly:

```python
        # PreCompact is a text channel, not a JSON one. Claude Code's
        # `hookSpecificOutput` union has no PreCompact variant (verified
        # against 2.1.234): a JSON payload there fails schema validation, marks
        # the hook failed and discards its output. The executor joins each
        # successful hook's raw stdout into `newCustomInstructions`, so the
        # summary has to arrive as the bytes the hook wrote.
        if event.event == "pre_compact":
            if decision.verdict is not None:
                raise ValueError(
                    f"claude-code does not honour {decision.verdict.value!r} on 'pre_compact'"
                )
            return HookOutput(
                stdout=decision.additional_context or None, stderr="", exit_code=0
            )
```

- [ ] **Step 4: Run to verify it passes**

Run: `uv run --frozen pytest tests/unit/agents/test_claude_code_adapter.py -v`
Expected: PASS, and no existing adapter test regresses.

- [ ] **Step 5: Prove the guard is load-bearing**

Delete the `if event.event == "pre_compact":` block by hand, re-run, watch `test_pre_compact_additional_context_serialises_as_plain_text` fail, restore by hand. **Never `git checkout`** — it reverts the uncommitted implementation too.

- [ ] **Step 6: Commit**

```bash
git add tests/unit/agents/test_claude_code_adapter.py src/lazy_harness/agents/claude_code.py
git commit -m "fix: serialise PreCompact additional context as plain text"
```

---

## Task 2: Decide the transcript-key narrowing, with evidence

`_shared._TRANSCRIPT_KEYS = ("transcript_path", "transcriptPath", "input")` (`_shared.py:21`) accepts three spellings. `ClaudeCodeAdapter.parse_hook_input` (`claude_code.py:407`) reads **only** `transcript_path`. Deleting `_TRANSCRIPT_KEYS` as step 5 prescribes therefore drops two accepted spellings from every migrated builtin — a silent narrowing, which is the class of defect the `CLAUDE.md` silent-dropout gate exists for.

This task produces a decision backed by measurement, not a guess. Either outcome is acceptable; an unrecorded one is not.

**Files:**
- Modify: `src/lazy_harness/agents/claude_code.py:407` (only if the measurement says widen)
- Modify: `specs/designs/2026-09-13-multi-agent-harness-design.md` (record the decision either way)
- Test: `tests/unit/agents/test_claude_code_adapter.py`

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

Run: `uv run --frozen pytest tests/unit/agents/test_claude_code_adapter.py -k transcript -v`

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
uv run --frozen pytest tests/unit/agents/ -v
git add -A && git commit -m "fix: settle the transcript key set the adapter accepts"
```

---

## Task 3: Move the `_shared` payload helpers onto the transcript path

Four helpers take the raw payload and reach into it through `_declared_transcript`: `transcript_from_payload`, `project_dir_from_payload`, `resolve_project_dir`, `resolve_memory_dir`, `memory_dir`. A migrated builtin has no payload, and `_TRANSCRIPT_KEYS` dies with them.

The second half matters as much: `transcript_from_payload` returns `None` unless the path `.is_file()`, while `HookEvent.transcript_path` is the **declared** path, un-stat'd. A call site that swaps one for the other without adding the check proceeds on a path that is not there — at `SessionStart` the transcript is routinely not written yet, which is exactly when several of these run.

**Files:**
- Modify: `src/lazy_harness/hooks/builtins/_shared.py:21` (`_TRANSCRIPT_KEYS`), `:48-95` (the four helpers)
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

Each is one TDD cycle and one commit. They are independent of one another and of nothing but tasks 1–3, so they parallelise across worktrees. **Per-builtin recipe, applied identically in each:**

1. **Capture the golden first.** `tests/goldens/hooks/<name>/` — feed the pre-migration `main()` a representative payload on stdin, record stdout bytes and exit code. The golden is captured from the **unmigrated** hook, so it is evidence and not a restatement of the new code.
2. Change the signature to `main(event: HookEvent) -> HookDecision`.
3. Apply the payload→event mapping table. Delete the `json.load(sys.stdin)` preamble and every `sys.exit`.
4. Replace the boot-dir dance with `agent, agent_dir = agent_dir_for(cfg, event.profile)`, **loading config before the first log line is written** — the ordering `context-inject` was fixed to in PR #300. Writing `fired` before config loads is what sent it to the global agent's directory.
5. Declare `operations=` and `signals=` on the builtin's `BuiltinHookSpec` in `hooks/loader.py`, and set `event=` and `blocking=` where they apply. Leave `migrated=True`.
6. Assert the golden still matches, byte for byte.
7. Assert profile isolation: invoke under `--profile <p>` and assert the `hooks.log` line lands in `<p>`'s directory **and is absent from the global one**. Presence alone does not detect the defect — PR #300 measured a weak presence assertion passing against a broken hook.

**The declarations, per builtin.** Derived from what each one reads, not from its matcher.

| # | Builtin | `event` | `operations` | `signals` | `blocking` | Output channel today |
|---|---|---|---|---|---|---|
| 4 | `session-export` | `session_stop` | — | `MESSAGES` | no | none (log only) |
| 5 | `session-end` | `session_end` | — | `MESSAGES` | no | none (log only) |
| 6 | `compound-loop` | `session_stop` | — | `MESSAGES` | no | none (log only) |
| 7 | `engram-persist` | `session_stop` | — | — | no | none |
| 8 | `pre-compact` | `pre_compact` | — | `MESSAGES`, `TOOL_CALLS` | no | **plain text** (task 1) |
| 9 | `session-start-preflight` | `session_start` | — | — | no | `additionalContext` |
| 10 | `user-prompt-goal` | `user_prompt_submit` | — | — | no | `additionalContext` |
| 11 | `stop-context-rotate` | `session_stop` | — | `TOKEN_USAGE` | no | `systemMessage` |
| 12 | `herdr-context-gauge` | `post_tool_use` | — | `TOKEN_USAGE` | no | none |
| 13 | `post-tool-use-format` | `post_tool_use` | `MODIFY_FILE` | — | no | none |
| 14 | `post-tool-use-sync-claude` | `post_tool_use` | `MODIFY_FILE` | — | no | none |
| 15 | `post-tool-use-ansible-lint` | `post_tool_use` | `MODIFY_FILE` | — | no | `additionalContext` |
| 16 | `pre-tool-use-read-size` | `pre_tool_use` | `READ_FILE` | — | no | `systemMessage` |
| 17 | `pre-tool-use-memory-size` | `pre_tool_use` | `MODIFY_FILE` | — | no | `systemMessage` |
| 18 | `pre-tool-use-git-scope` | `pre_tool_use` | `RUN_COMMAND` | — | **yes** | exit 2 + stderr |

**Wave ordering for parallel dispatch.** Within a wave the tasks share no files and can run concurrently; waves are sequential because each later one reuses a pattern the earlier one established.

- **Wave A** (tasks 4–7): the four session-lifecycle hooks. They share the identical boot-dir defect and the `find_latest_session` / `resolve_project_dir` call shape, so one reviewer sees the pattern four times.
- **Wave B** (task 8): `pre-compact` alone. It is the only consumer of task 1 and the only plain-text channel; it gets its own review.
- **Wave C** (tasks 9–12): the context-emitting hooks. `stop-context-rotate` imports `context_tokens` from `herdr_context_gauge`, so those two land together or task 11 goes second.
- **Wave D** (tasks 13–15): PostToolUse. Each reads `event.tool.edits` where it used to read `tool_input["file_path"]`.
- **Wave E** (tasks 16–18): PreToolUse. Task 18 is the only blocking hook in this plan and is the one that must be exercised through the `Verdict.DENY` path with dependencies mocked away.

**Worked instance — Task 18, `pre-tool-use-git-scope`**, written out because it is the one with a refusal path and the recipe alone is not enough for it.

**Files:**
- Modify: `src/lazy_harness/hooks/builtins/pre_tool_use_git_scope.py:353` (`_read_payload`), `:365-395` (`main`)
- Modify: `src/lazy_harness/hooks/loader.py` (the `pre-tool-use-git-scope` entry)
- Test: `tests/unit/hooks/builtins/test_pre_tool_use_git_scope.py`
- Create: `tests/goldens/hooks/pre-tool-use-git-scope/`

- [ ] **Step 1: Capture the golden from the unmigrated hook**

```bash
echo '{"tool_name":"Bash","tool_input":{"command":"git push --force origin main"},"cwd":"/tmp","session_id":"s"}' \
  | uv run --frozen python -m lazy_harness.hooks.builtins.pre_tool_use_git_scope \
  > tests/goldens/hooks/pre-tool-use-git-scope/deny.stdout 2> tests/goldens/hooks/pre-tool-use-git-scope/deny.stderr; \
  echo $? > tests/goldens/hooks/pre-tool-use-git-scope/deny.exit
```

- [ ] **Step 2: Write the failing test**

```python
def test_git_scope_refuses_through_the_verdict_rather_than_an_exit_code() -> None:
    event = HookEvent(
        event="pre_tool_use",
        profile="p",
        session_id="s",
        cwd=Path("/tmp"),
        transcript_path=None,
        tool=ToolCall(
            native_name="Bash",
            operation=Operation.RUN_COMMAND,
            command="git push --force origin main",
        ),
    )
    decision = main(event)
    assert decision.verdict is Verdict.DENY
    assert "force" in decision.reason


def test_git_scope_declares_the_operation_it_guards() -> None:
    """Declared, not inferred from the `Bash` matcher, which names Claude Code's
    own tool. Another agent's translated matcher still has to be asked whether
    the operation exists there."""
    assert _BUILTIN_HOOKS["pre-tool-use-git-scope"].operations == frozenset({Operation.RUN_COMMAND})
    assert _BUILTIN_HOOKS["pre-tool-use-git-scope"].blocking is True


def test_git_scope_refuses_when_it_cannot_run(monkeypatch) -> None:
    """Exit 0 with no output is how a hook says 'no objection'.

    Exercised with the config read mocked to raise, so the refusal is reached
    through the failure path and not through a denied command.
    """
    monkeypatch.setattr("lazy_harness.hooks.builtins.pre_tool_use_git_scope.config_file", _raises)
    out = run_hook("pre-tool-use-git-scope", profile="p", stdin_text="not json")
    assert out.exit_code == 2
```

- [ ] **Step 3: Run to verify it fails**

Run: `uv run --frozen pytest tests/unit/hooks/builtins/test_pre_tool_use_git_scope.py -v`
Expected: FAIL — `main()` takes no argument.

- [ ] **Step 4: Implement**

Delete `_read_payload`; change `main` to take `event` and return `HookDecision`; replace `sys.exit(2)` with `return HookDecision(verdict=Verdict.DENY, reason=<the text it wrote to stderr>)` and every `sys.exit(0)` with `return HookDecision()`. Read the command from `event.tool.command`, guarding `event.tool is None`. In `loader.py`:

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

Run: `uv run --frozen pytest tests/unit/hooks/ tests/goldens -v`
Expected: PASS, `deny.stdout` byte-identical.

- [ ] **Step 6: Attack the denylist with evasions of its own patterns**

Mutation coverage proves the guard has branches, not that it covers anything. Feed it whitespace variants, reordered flags and alternate path spellings of the commands it claims to refuse, and **record what got through** in the PR body.

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
- Modify: `src/lazy_harness/deploy/engine.py:204-233` — `_warn_unmigrated` has nothing left to warn about
- Test: `tests/unit/hooks/test_builtin_registry.py`, `tests/unit/hooks/test_entry_points.py`, `tests/integration/test_deploy_signal_agreement.py`

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

## Task 20: Route `lh hooks run` through the runner

`hooks/engine.py:27-33` executes the hook **file** via `subprocess.run([sys.executable, str(hook.path)], …)`, reached from `cli/hooks_cmd.py:124-133`. A builtin whose `main` now requires an argument breaks at its `if __name__ == "__main__":`. The design names this explicitly: a migration that changes only the builtins and `hook_invoke` leaves `lh hooks run` broken **and silent**.

**Files:**
- Modify: `src/lazy_harness/cli/hooks_cmd.py:124-165` (`hooks_run`)
- Modify: `src/lazy_harness/hooks/engine.py:27-33` (`execute_hook` keeps the subprocess path for **user** hooks only)
- Test: `tests/unit/hooks/test_entry_points.py`

**Interfaces:**
- Consumes: `hooks.runner.run_hook(name, *, profile, stdin_text) -> HookOutput`
- Produces: `hooks_run` dispatches a builtin through `run_hook` and a user hook through `execute_hook`, and the two report identically.

- [ ] **Step 1: Write the failing test**

```python
def test_hooks_run_and_hook_invoke_agree_on_a_builtin(tmp_path: Path) -> None:
    """Two entry points, one execution mechanism.

    An integration assertion rather than two unit tests, because the defect
    this catches is precisely the two paths disagreeing -- which neither half
    can observe alone.
    """
    payload = '{"tool_name":"Read","tool_input":{"file_path":"/etc/hosts"},"cwd":"/tmp"}'
    via_hook = CliRunner().invoke(hook_invoke, ["pre-tool-use-read-size", "--profile", "p"], input=payload)
    via_run = CliRunner().invoke(hooks_run, ["pre_tool_use", "--profile", "p"], input=payload)
    assert via_hook.exit_code == via_run.exit_code
    assert via_hook.stdout in via_run.stdout
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run --frozen pytest tests/unit/hooks/test_entry_points.py -v`
Expected: FAIL — `hooks_run` spawns the file, whose `main()` now needs an argument.

- [ ] **Step 3: Implement**

- [ ] **Step 4: Run to verify it passes**

- [ ] **Step 5: Commit**

```bash
git add -A && git commit -m "refactor: run builtins through the runner from lh hooks run"
```

---

## Task 21: The literal sweep, and what `profile_name()` keeps

**Files:**
- Modify: the seven builtins carrying `get_agent("claude-code")` (already handled in their own tasks; this is the audit that proves it)
- Modify: `src/lazy_harness/hooks/builtins/_shared.py` — `profile_name()` gains a docstring naming its four surviving callers
- Modify: `specs/backlog.md` — close *Ocho builtins resuelven su `hooks.log` globalmente*
- Test: `tests/unit/hooks/test_builtin_contract.py`

- [ ] **Step 1: Write the failing test**

```python
def test_no_builtin_resolves_its_agent_globally() -> None:
    """Seven literals, by mechanism rather than by spelling.

    A grep for `get_agent("claude-code")` finds seven and misses `pre-compact`,
    which does the same thing as `cfg.agent.type if cfg is not None else
    "claude-code"` -- the exact difference the CLAUDE.md gate is written for.
    Both shapes are matched here.
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

- [ ] **Step 2: Run to verify it fails before the migrations and passes after**

Run: `uv run --frozen pytest tests/unit/hooks/test_builtin_contract.py -v`

- [ ] **Step 3: Record what `profile_name()` keeps**

It is not deleted. Add to its docstring:

```python
    """...

    Survives step 5 rather than being deleted with the builtins' other
    pre-runner helpers. Four callers remain and none of them is a builtin:
    `cli/metrics_cmd.py`, `knowledge/compound_loop.py` (twice), and
    `hooks/runner.py:resolve_profile`, which is the runner's own fallback for a
    deployed command written before `--profile` existed -- the mechanism this
    migration depends on. The design's step 5 text says "delete"; the code says
    "remove from the builtins", and this is the difference.
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

**Spec coverage.** Step 5's four clauses: migrate the fifteen (tasks 4–18) ✓; declare `Operation` and `Signal` per builtin (the table, and step 5 of each recipe) ✓; delete `profile_name()` (task 21 — **narrowed, with evidence**, and the divergence recorded) ✓; delete `_TRANSCRIPT_KEYS` (task 3) ✓; seven of the ten literals (task 21, roster corrected) ✓. The design's two displaced prerequisites — the second entry point and the transitional field — are tasks 20 and 19.

**Gaps this plan opens deliberately.** Whether `/tmp/f7-gate/` gets versioned is unresolved and stays that way; task 22 runs it from where it lives. `knowledge/compound_loop_worker.py:100` and `_shared.py:258` stay global by decision, not oversight, and task 21's test excludes `_shared.py` explicitly for that reason.

**Risk that outranks the rest.** Task 1. `pre-compact` is the only builtin whose migration can pass every test and still be dead on the wire, because the channel it speaks is not the channel the contract serialises to. If only one task gets an independent review by a different model, it is that one.

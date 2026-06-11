# lazy-harness Adequacy Plan — 2026-06-11

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the architectural debt (ADR-032 leaks, ADR-033 not implemented), fix Fable 5 cost tracking, close the open learning loop (proposals/failures pipeline), and slim the CLAUDE.md hierarchy — in dependency order.

**Architecture:** Five phases. Phase 0 is non-code hygiene. Phase 0.5 is a one-file pricing fix (urgent: Fable 5 sessions currently record $0 cost). Phase 1 centralizes agent-dir resolution behind the AgentAdapter protocol (ADR-032). Phase 2 introduces the LLMBackend protocol per ADR-033 (unblocks local models). Phase 3 closes the self-healing loop (proposals visibility, failure promotion, lifecycle). Phase 4 is doc dedup. Phases 2-4 get their detailed TDD plan authored at their phase boundary, informed by the prior phase's refactor.

**Tech Stack:** Python 3.11+, uv, pytest, ruff, strict TDD, worktrees per repo non-negotiables.

**Quality gates (every code phase):** `/tdd-check` before every commit; `superpowers:requesting-code-review` before PR; security pass on any hook/subprocess code (no shell=True, timeouts on subprocess, paths never derived from untrusted input); no `Any`; conventional commits without AI trailers.

---

## Phase 0 — Hygiene (no code; needs user decisions D1-D3)

**Decisions required:**
- D1: delete `~/.claude-server-commander/` (3.6MB, frozen 53d) and `~/.claude-lazy/settings.json.bak*` (39d)?
- D2: QMD collection `lazy-claudecode` (empty, undocumented): delete or document?
- D3: the 2 pending proposals in `claude-md.proposal.md` (2026-05-20 docs-coherence-pre-release rule; 2026-05-27 verify-persistence rule): merge into repo CLAUDE.md or discard?

### Task 0.1: Process pending proposals
**Files:** `~/.claude-lazy/projects/-Users-lazynet-repos-lazy-lazy-harness/memory/claude-md.proposal.md`; if merging → repo `CLAUDE.md` (governance surface → worktree `chore/merge-proposals`).
- [ ] Apply D3 (merge via worktree+PR, or discard by archiving the proposal entries with a dated note)
- [ ] Leave proposal file empty of pending items either way

### Task 0.2: Delete fossils (if D1 = yes)
- [ ] `rm -rf ~/.claude-server-commander`
- [ ] `rm ~/.claude-lazy/settings.json.bak ~/.claude-lazy/settings.json.bak-mcp-cleanup`

### Task 0.3: Resolve lazy-claudecode QMD collection (per D2)
- [ ] Either remove from qmd registry or add a one-line purpose note in `~/.config/lazy-harness/profiles/lazy/docs/vault.md`

### Task 0.4: Fix CLAUDE.tail.md contradiction
**Files:** `~/.config/lazy-harness/profiles/lazy/CLAUDE.tail.md` (profile source, outside repo — direct edit).
- [ ] Change "el `context_inject` hook ya carga MEMORY.md + decisions/failures recientes" → "CC carga MEMORY.md nativamente; el `context_inject` hook agrega decisions/failures recientes, handoff y proposals"
- [ ] Run `~/.config/lazy-harness/profiles/_common/sync-claude-md.sh` and verify diff

---

## Phase 0.5 — Fable 5 pricing (worktree `fix/fable-5-pricing`)

Fable 5: $10/MTok input, $50/MTok output (claude-api skill, cached 2026-06-04). Cache rates follow the table convention (read=0.1×, create=1.25×): 1.0 / 12.5.

### Task 0.5.1: Add claude-fable-5 to DEFAULT_PRICING
**Files:**
- Modify: `src/lazy_harness/monitoring/pricing.py:5-16`
- Test: `tests/monitoring/test_pricing.py` (verify exact mirror path at execution)

- [ ] **Step 1: Write the failing test**

```python
def test_default_pricing_includes_claude_fable_5():
    pricing = default_pricing()
    assert pricing["claude-fable-5"] == {
        "input": 10.0,
        "output": 50.0,
        "cache_read": 1.0,
        "cache_create": 12.5,
    }
```

- [ ] **Step 2: Run test, verify it fails** — `uv run pytest tests/monitoring/test_pricing.py -k fable -v` → FAIL (KeyError)
- [ ] **Step 3: Add the entry**

```python
    "claude-fable-5": {"input": 10.0, "output": 50.0, "cache_read": 1.0, "cache_create": 12.5},
```

- [ ] **Step 4: Run test, verify it passes**
- [ ] **Step 5: Check for other model-keyed surfaces** — `grep -rn "opus-4-8" src/ tests/` to find any companion tables (statusline, dashboards) that also need the entry; apply same TDD loop to each
- [ ] **Step 6: `/tdd-check`, commit `fix: add claude-fable-5 to pricing table`, PR**

**Known impact to report:** sessions run on Fable 5 before this fix recorded cost 0.0 in metrics.db (calculate_cost returns 0.0 on unknown model). Backfill is optional — decide with user after fix lands.

---

## Phase 1 — ADR-032 leak closure (worktree `refactor/adr-032-leaks`)

ADR-032 is `accepted`; protocol methods exist on `AgentAdapter` (`agents/base.py`) and `ClaudeCodeAdapter`. Remaining leaks are L3/L4 call sites that read `CLAUDE_CONFIG_DIR` / hardcode `"projects"` directly:

| Call site | Leak |
|---|---|
| `hooks/builtins/session_end.py:56,77` | L3 + L4 |
| `hooks/builtins/session_export.py:45` | L3 |
| `hooks/builtins/engram_persist.py:57` | L3 |
| `hooks/builtins/compound_loop.py:70` | L3 (pre-config bootstrap, partially justified) |
| `hooks/builtins/post_compact.py:45` | L3 |
| `hooks/builtins/pre_compact.py:119` | L3 |
| `hooks/builtins/context_inject.py:607,649` | L3 |
| `knowledge/compound_loop_worker.py:98` | L3 |
| `cli/doctor_cmd.py:43`, `cli/knowledge_cmd.py:209` | L3 |
| `monitoring/statusline.py:29` | L3 |

### Task 1.1: `agent_runtime_dir()` helper in core/paths.py
**Files:**
- Modify: `src/lazy_harness/core/paths.py`
- Test: `tests/core/test_paths.py` (mirror — verify exact path at execution)

- [ ] **Step 1: Write failing tests**

```python
def test_agent_runtime_dir_uses_adapter_env_var(monkeypatch):
    from lazy_harness.agents.claude_code import ClaudeCodeAdapter
    from lazy_harness.core.paths import agent_runtime_dir

    monkeypatch.setenv("CLAUDE_CONFIG_DIR", "/tmp/fake-claude")
    assert agent_runtime_dir(ClaudeCodeAdapter()) == Path("/tmp/fake-claude")


def test_agent_runtime_dir_falls_back_to_home_dotclaude(monkeypatch):
    from lazy_harness.agents.claude_code import ClaudeCodeAdapter
    from lazy_harness.core.paths import agent_runtime_dir

    monkeypatch.delenv("CLAUDE_CONFIG_DIR", raising=False)
    assert agent_runtime_dir(ClaudeCodeAdapter()) == Path.home() / ".claude"
```

- [ ] **Step 2: Verify fail** (ImportError)
- [ ] **Step 3: Implement**

```python
def agent_runtime_dir(agent: "AgentAdapter") -> Path:
    """Resolve the agent's runtime config dir: adapter env var, else its global link."""
    env_value = os.environ.get(agent.env_var())
    if env_value:
        return Path(env_value)
    link = agent.global_config_link()
    if link is not None:
        return link
    return Path.home() / f".{agent.name}"
```

(Import `AgentAdapter` under `TYPE_CHECKING` to avoid a runtime cycle; verify `core` may import `agents` — if layering forbids it, place the helper in `agents/resolve.py` instead and keep the same signature.)

- [ ] **Step 4: Verify pass, ruff clean**
- [ ] **Step 5: Commit** `refactor: add agent_runtime_dir helper for ADR-032 L3`

### Task 1.2: Migrate hook builtins to the helper (one commit per hook)
**Files:** the 7 hook files above; tests added per hook in `tests/hooks/builtins/` (most have NO test file today — create them; this also pays down the 9/10-untested-hooks debt).

Per hook, the loop is:
- [ ] Write failing test: monkeypatch `CLAUDE_CONFIG_DIR` + stub config; assert the hook resolves dirs via `agent_runtime_dir(get_agent(cfg.agent.type))` post-config (observable: paths it writes/logs land under the fake dir)
- [ ] Replace `Path(os.environ.get("CLAUDE_CONFIG_DIR", Path.home() / ".claude"))` with the helper; keep a documented bare-env fallback ONLY where the hook logs before config load (compound_loop bootstrap), re-resolving after config is available
- [ ] In `session_end.py:77`: replace `claude_dir / "projects" / encoded` with `claude_dir / agent.session_dirs()["sessions"] / encoded` (L4)
- [ ] `/tdd-check`, commit `refactor: route <hook> paths through agent adapter`

### Task 1.3: Migrate CLI + worker + statusline call sites
Same loop for `compound_loop_worker.py:98`, `doctor_cmd.py:43`, `knowledge_cmd.py:209`, `statusline.py:29`.
- [ ] One commit per module, test-first

### Task 1.4: Deduplicate hook helpers
**Files:**
- Create: `src/lazy_harness/hooks/builtins/_shared.py`
- Test: `tests/hooks/builtins/test_shared.py`

- [ ] Move `_find_latest_session()` (3 verbatim copies: compound_loop, session_end, context_inject) and `_log()` (5 copies) into `_shared.py`, test-first; replace call sites; keep behavior byte-identical
- [ ] `/tdd-check`, commit `refactor: extract shared hook helpers`

### Task 1.5: Close-out
- [ ] `grep -rn "CLAUDE_CONFIG_DIR" src/lazy_harness --include="*.py"` → remaining hits only in `agents/claude_code.py`, docstrings, and the documented pre-config bootstrap
- [ ] Code review (skill), PR, merge, `/cleanup-worktree`
- [ ] Propose ADR-032 status note update (implemented) via doc short-path

---

## Phase 2 — ADR-033 LLMBackend (worktree `feat/llm-backend`)

ADR-033 (`accepted-deferred`) contains the full design INCLUDING code for protocol, both backends, registry, config fields, and an 8-step shippable sequence. The detailed TDD plan is authored at phase start (writing-plans skill) translating ADR steps 1-8 into red-green tasks:

- [ ] 2.1 `llm/base.py`: `LLMBackend` Protocol + `LLMBackendError` (+ conformance test mirroring `test_agent_protocol.py` pattern)
- [ ] 2.2 `llm/claude.py`: `ClaudeBackend` extracting the subprocess call from `compound_loop.py:713` verbatim — safety checkpoint: full suite + `lh selftest` identical behavior
- [ ] 2.3 Rename `invoke_claude` → `invoke_llm(prompt, backend, model, timeout)`; thread backend through callers (`compound_loop.py`, `cli/memory_cmd.py`)
- [ ] 2.4 `CompoundLoopConfig.backend` + `backend_options` in `core/config.py` (defaults `"claude"` / `{}`); update `lh config compound-loop --init` wizard
- [ ] 2.5 `llm/openai_compat.py`: `OpenAICompatibleBackend` (httpx, explicit dependency)
- [ ] 2.6 `llm/registry.py`: `get_backend()` with aliases claude/ollama/mlx/openai-compatible (`_DEFAULT_URLS` per ADR table)
- [ ] 2.7 Wire `get_backend(cfg.compound_loop)` into worker startup + `memory_cmd.py`
- [ ] 2.8 `lh doctor`: backend reachability check (ADR-025 pattern)
- [ ] Status flip ADR-033 `accepted-deferred` → `accepted` in the PR
- [ ] Public docs: config reference gets the `[compound_loop] backend` table (docs are user-facing → in scope)

**Acceptance:** with `backend = "ollama"` and a local Ollama, compound-loop grades a session with zero `claude` binary involvement; with default config, behavior is byte-identical to today.

---

## Phase 3 — Close the learning loop (3 worktrees, sequential)

Detailed TDD plans authored at phase start. Design constraints fixed now:

### 3a `feat/proposals-always-visible` — proposals never silently dropped
- `context_inject.py` drop chain (lines 461-490) keeps dropping the proposals BODY under budget, but a 1-line summary (`⚠ N claude-md proposals pending since <oldest date> — review with: lh memory proposals`) is emitted OUTSIDE the droppable body (like the truncation banner)
- Config: `context_inject.proposals_summary` (default true)

### 3b `feat/failure-promotion` — failures.jsonl → [EVITAR] proposals
- In the compound-loop worker (post Phase 2: runs on any backend): cluster failures by root-cause similarity; when a cluster reaches ≥2 occurrences, emit a proposal entry prefixed `[EVITAR]` into `claude-md.proposal.md`
- NEVER writes MEMORY.md directly — human gate stays (vault: agents-feedback-loops, Karpathy immunity)
- Dedup against existing proposals AND against rejected ones (needs 3c registry; ship behind config flag if 3c not yet merged)

### 3c `feat/proposals-lifecycle` — accept/reject with memory
- `lh memory proposals` subcommand: list / accept (moves rule to MEMORY.md or prints for CLAUDE.md paste) / reject (moves to `claude-md.rejected.md` with date+reason)
- Grading prompt gets the rejected list appended ("do not re-propose these")

### 3d maintenance schedule
- `lh schedule` job (existing scheduler backends) that enqueues a periodic review task: prune MEMORY.md stale rules, flag proposals pending >14d, flag failures clusters never promoted

---

## Phase 4 — CLAUDE.md hierarchy diet (doc short-path, no worktree needed for profile files)

- [ ] 4.1 Dedupe "Memoria" section: `_common/CLAUDE.common.md` keeps the 5-layer table; `profiles/lazy/docs/vault.md` keeps operational detail and links back — no duplicated table. Re-run sync script.
- [ ] 4.2 Runbook-lens inventory: list every imperative rule in the hierarchy; classify knowledge vs enforceable-constraint; for each enforceable one note whether a hook enforces it (pre_tool_use_security, pre_tool_use_memory_size, post_tool_use_format already exist). Output: short gap table appended to this plan; new hooks become future backlog items, not part of this phase.
- [ ] 4.3 Verify SessionStart total load shrank (line counts before/after).

---

## Phase 4.2 output — runbook-lens gap table (knowledge vs control layer)

Imperative rules in the instruction hierarchy, classified by whether a hook/gate enforces them (2026-06-11):

| Rule (knowledge layer) | Enforcement today (control layer) | Status |
|---|---|---|
| MEMORY.md ≤200 lines | `pre_tool_use_memory_size` hook + `lh doctor` memory hygiene | ✓ covered |
| Sync CLAUDE.md after editing head/tail/common | `post-tool-use-sync-claude` hook | ✓ covered |
| Pre-commit gate = pytest+ruff+mkdocs | `/tdd-check` command (manual invocation) | partial — not blocking |
| decisions/failures.jsonl append-only | nothing — an Edit could rewrite history | **gap** — candidate: PreToolUse Edit\|Write matcher on `*.jsonl` under memory/ |
| No `--no-verify` on commits | nothing (`pre_tool_use_security.py` has 0 mentions) | **gap** — candidate: add pattern to security hook |
| No AI trailers in commits | nothing | **gap** — candidate: security-hook regex on `git commit` args |
| Worktrees for every code change | nothing programmatic | **gap** — candidate: PreToolUse Edit/Write warn when cwd == main checkout of a worktree-rule repo |
| No personal info in public surface | nothing — and one real instance exists: `tests/unit/test_statusline.py` carries `/Users/lazynet` paths (pre-existing, flagged in PR #96 review) | **gap** — candidate: CI grep or pre-push check |
| Strict TDD (failing test first) | convention + review only | inherently hard to enforce mechanically — accept |

These gaps are backlog candidates, deliberately NOT implemented in this plan (scope).

## Execution status (2026-06-11)

- Phase 0 ✓ (fossils trashed, QMD collection removed, contradiction fixed + synced, proposals merged via PR #93)
- Phase 0.5 ✓ (PR #94 — claude-fable-5 pricing; note: Fable sessions before this fix recorded $0 cost in metrics.db; live `lh` picks it up at next release upgrade)
- Phase 1 ✓ (PR #96 — ADR-032 leaks closed, helpers deduped, +16 routing tests, import-safety contract restored after review blocker)
- Phase 2 ✓ (PR #97 — ADR-033 implemented, llm/ package, ollama/mlx/openai-compatible aliases, doctor backend check; ADR statuses flipped)
- Phase 3a ✓ (PR #98), 3c ✓ (PR #99), 3b+3d ✓ (PR #100 — piggyback promotion approved by owner; 3d implemented as doctor section instead of scheduler job, deviation approved)
- Phase 4 ✓ (Memoria table slimmed in CLAUDE.common.md, storage detail → vault.md + lazy-homelab added, synced both profiles; gap table above)

## Execution order & checkpoints

1. Phase 0 (after D1-D3 answered) → 0.5 (PR) → 1 (PR) → 2 (PR) → 3a/3b/3c/3d (PRs) → 4
2. Stop-for-user points: D1-D3 now; PR merges (user merges or authorizes); Phase 3 design review before 3b implementation (grading-prompt changes affect LLM cost/quality)
3. Each phase ends with: `/tdd-check` green, code review, PR, decisions.jsonl entry

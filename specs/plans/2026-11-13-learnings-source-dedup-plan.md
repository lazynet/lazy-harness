# Learnings source dedup and attribution — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fewer rewritten learnings at the source, and every new learning names the agent and host that produced it.

**Architecture:** The compound loop's `collect_existing_learnings` stops returning the last 50 titles. It returns the k active titles most similar to the session being distilled, ranked in-process. `persist_results` writes `agent` and `host` into each learning's frontmatter. Two drained proposals land in the governance surface.

**Tech Stack:** Python 3.11+, stdlib only (no new dependency), pytest, ruff.

**Spec:** `lazy-ai-tools/docs/superpowers/specs/2026-11-13-learnings-loop-closure-design.md`, §3 "Source-side fixes" and §Sequencing step 1. The lazy-ai-tools half has its own plan in that repo.

## Global Constraints

- Strict TDD: every production line follows a failing test run and shown (AGENTS.md non-negotiable 2).
- `/tdd-check` gate before every commit: `uv run --frozen pytest`, `uv run --frozen ruff check src tests`, `uv run --frozen ruff format --check src tests`, `uv run --frozen --group docs mkdocs build --strict`. Run each one in its own command and read its exit code.
- Embeddings are a non-goal. No new dependency in `pyproject.toml`.
- Frontmatter field names: `agent`, `host`. Values for `agent`: the adapter's `name` (`claude-code`, `codex`), or `unknown`.
- The existing fields (`status`, `deprecated_by`, `deprecated_on`, `deprecated_reason`) keep their names and order, because `core/decay.py` and lazy-vault rewrite them line by line.

## Review Focus

1. A learnings store of ~10.6k notes: ranking reads every note's frontmatter on each worker task. It must stay under 2 s on the Mac (Task 2 adds a timing test with 12k synthetic notes).
2. Notes with `status: superseded`, or with malformed or absent frontmatter, must never be offered as "existing" titles, and must not crash the scan (Task 2).
3. An empty or whitespace-only session summary (an insight-bypass task) must fall back to the most recent titles, not return nothing (Task 2).
4. The worker runs with no resolvable profile (`profile_name()` returns `''`): the agent field must be `unknown`, never an exception (Task 1).
5. `lh memory decay` must still parse and rewrite a note that carries the new `agent`/`host` lines (Task 1, a load-cycle test through `core/decay.py`).

---

### Task 1: `agent` and `host` in learning frontmatter

**Files:**
- Modify: `src/lazy_harness/knowledge/compound_loop.py` (`persist_results` ~L1137, the learning template ~L1203; `process_task` ~L1563 call site)
- Test: `tests/unit/test_compound_loop.py`, `tests/unit/test_decay.py` (or the existing decay test module; `grep -l find_decay_candidates tests/unit`)

**Interfaces:**
- Produces: `persist_results(..., *, agent: str = "unknown", ...)`, a new keyword. `_agent_label(cfg: Config) -> str` in `compound_loop.py` returns `agent_for_profile(cfg, profile_name()).name`, or `"unknown"` when the profile is empty or resolution raises.

- [ ] **Step 1: Write the failing tests**
  - `test_persisted_learning_names_agent_and_host`: `persist_results(data_with_one_learning, ..., agent="codex")`. The written file's frontmatter contains `agent: codex` and `host: <origin_host()>`, placed after `scope:` and before `status:`.
  - `test_persisted_learning_agent_defaults_to_unknown`: the call without `agent` writes `agent: unknown`.
  - `test_agent_label_is_unknown_without_profile`: monkeypatch `profile_name` to return `""`, and `_agent_label(cfg) == "unknown"`.
  - `test_agent_label_is_unknown_when_resolution_raises`: monkeypatch `agent_for_profile` to raise `KeyError`, and the result is `"unknown"`.
  - `test_decay_round_trips_a_note_with_agent_and_host` (decay tests): write a note through `persist_results` with an old `origin_session`, then run `find_decay_candidates` and `apply_decay`. The rewritten file has `status: superseded` and still contains `agent:` and `host:` unchanged.
- [ ] **Step 2: Run and watch them fail.** Run `uv run --frozen pytest tests/unit/test_compound_loop.py -k "agent" -v` and the decay test. Expected: FAIL, because `persist_results` has no `agent` keyword and `_agent_label` is undefined.
- [ ] **Step 3: Implement.** Add the keyword and the two template lines. `_agent_label` wraps the resolution in `try/except Exception` and returns `"unknown"`. `process_task` passes `agent=_agent_label(cfg)`.
- [ ] **Step 4: Run the tests and watch them pass.** Then delete the `agent:` template line, watch `test_persisted_learning_names_agent_and_host` fail, and restore it by hand.
- [ ] **Step 5: Run the gate** (four commands, one per command) **and commit:** `feat: learnings record the agent and host that wrote them`

### Task 2: similarity-ranked existing titles

**Files:**
- Modify: `src/lazy_harness/knowledge/compound_loop.py` (`collect_existing_learnings` ~L743, its call ~L1517)
- Create: `src/lazy_harness/knowledge/title_rank.py`
- Test: `tests/unit/test_title_rank.py`, `tests/unit/test_compound_loop.py` (update `test_collect_existing_learnings` ~L605)

**Interfaces:**
- Produces: `rank_titles(query: str, titles: list[TitleEntry], k: int, project: str | None) -> list[TitleEntry]` in `title_rank.py`. `TitleEntry` is a frozen dataclass `(title: str, origin: str, mtime: float)`.
- Produces: `collect_existing_learnings(learnings_dir: Path, query: str = "", limit: int = 50, project: str | None = None) -> str`. The output format stays `"- <title>"` per line.
- Consumes: the session `summary` already computed in `process_task` (from `extract_messages`), and `project_name`.

- [ ] **Step 1: Write the failing tests** in `test_title_rank.py`:
  - `test_old_similar_title_beats_recent_unrelated`: 60 recent unrelated titles plus one 90-day-old title `"grep -q under pipefail gives a false negative"`. With query `"pipefail grep -q false negative in a pipe"` and `k=50`, the old title is at index 0.
  - `test_same_project_breaks_ties`: two titles with identical scores, `origin` `"lazy-harness"` and `"other"`. With `project="lazy-harness"`, the lazy-harness title ranks first.
  - `test_empty_query_returns_most_recent`: with query `"  "`, the result is the k titles with the highest `mtime`, newest first.
  - `test_ranking_12k_titles_under_two_seconds`: 12,000 synthetic entries. `rank_titles` returns within `2.0` s (`time.perf_counter`).
- [ ] **Step 2: Write the failing tests** in `test_compound_loop.py`:
  - `test_collect_existing_learnings_skips_superseded_and_malformed`: one note with `status: superseded`, one with no frontmatter, one valid. Only the valid title appears, and nothing raises.
  - Update `test_collect_existing_learnings` to pass `query=` and assert on ranking, not on recency.
- [ ] **Step 3: Run and watch them fail.** Run `uv run --frozen pytest tests/unit/test_title_rank.py tests/unit/test_compound_loop.py -k "rank or existing_learnings" -v`. Expected: an import error for `title_rank`, then FAIL.
- [ ] **Step 4: Implement `rank_titles`.** Tokenize to lowercase alphanumeric runs of 3 or more characters, so `-q` stays out, and score by cosine over token counts. Ties go to same `origin` first, then higher `mtime`. Keep it stdlib only.
- [ ] **Step 5: Implement `collect_existing_learnings`.** Read only the frontmatter block of each `*.md` (stop at the second `---`). Skip `_review-*`, `status` other than `active`, and parse failures. Build `TitleEntry` and call `rank_titles`. `process_task` passes `query=summary` and `project=project_name`.
- [ ] **Step 6: Run the tests and watch them pass.** Mutate by removing the `status` filter, watch the superseded test fail, and restore by hand.
- [ ] **Step 7: Run the gate and commit:** `feat: compound loop dedups learnings against the most similar titles`

### Task 3: drained proposals and the backlog correction

**Files:**
- Modify: `AGENTS.md` (gate "A test that passes with and without the thing it claims to cover…")
- Modify: `specs/incidents.md` (the section paired with that gate, same order)
- Modify: `.claude/commands/tdd-check.md`
- Modify: `specs/backlog.md:221`

- [ ] **Step 1: AGENTS.md.** Append one clause to that gate: before each mutation run, set `PYTHONDONTWRITEBYTECODE=1` or clear `__pycache__`. A same-size mutant reverted within the same second reuses stale bytecode. The AGENTS.md file must stay within 200 lines and 12 KB; check with `uv run --frozen lh memory rightsize`.
- [ ] **Step 2: incidents.md.** Add the evidence under that gate's section: three no-op mutations (2026-11-01 sed on macOS, 2026-11-07 misplaced backup, 2026-11-07 bytecode cache), plus the 35-byte same-second case already recorded in the backlog entry for PR #387.
- [ ] **Step 3: tdd-check.md.** Add one line under the intro: run each check as its own command and read its exit code before committing or merging. Never chain the checks with `&&`, and never read the tail of a combined background command.
- [ ] **Step 4: backlog.md:221.** Correct the entry. The weekly learnings review is `lazy-vault learnings-review` in lazy-ai-tools, scheduled on the agents CT (Sun 10:00 ART), and writing `Meta/Weekly-Reviews/LR-YYYY-WNN.md`. Link the design.
- [ ] **Step 5: Verify the prose against the code in both directions:** `grep -rn "PYTHONDONTWRITEBYTECODE" AGENTS.md specs/incidents.md` and `ssh lazy-agents 'lh scheduler status' | grep learnings-review`.
- [ ] **Step 6: Run the gate and commit:** `docs: fold drained proposals into the mutation gate and tdd-check`

### Task 4: ship

- [ ] Push the branch, open the PR with the `pr` skill, wait for CI to go green, and get the user's merge decision. Merge was not pre-authorized for this repo.
- [ ] After merge: `/cleanup-worktree`. The release is cut by release-please and needs no hand action. Deploying to the Mac and the CT follows the binary-first gate (`uv tool install --reinstall`, grep site-packages for `title_rank`). The CT counts as a real host: ask the user at that moment.

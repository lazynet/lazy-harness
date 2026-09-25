# Graph assist Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Answer identifier-shaped code searches in Claude Code from a prebuilt graph index, scope the upstream graphify search guard to Codex, give SessionStart real graph content, and measure it all against the spec's kill criteria.

**Architecture:** A new module `knowledge/graph_assist.py` owns the index (build from `graph.json`, persist under `graphify-out/cache/`, lookup, render) and the search-command classifier. A thin non-blocking builtin `pre-tool-use-graph-assist` calls it and appends one metrics line per evaluation. `ExternalHookConfig` and `BuiltinHookSpec` both gain an agent allow-list that `deploy.engine._hook_entries_for` enforces and names. A read-only CLI computes the §6 metrics.

**Tech Stack:** Python 3.11, click, pytest, ruff. No new dependencies.

**Spec:** `specs/designs/2026-09-24-graph-assist-design.md`

## Global Constraints

- Hook: event `PreToolUse`, matcher `Bash|Grep`, non-blocking, always exit 0, `claude-code` only.
- Identifier regex, verbatim: `^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)*\(?\)?$`, after stripping quotes and a leading `def `/`class `/`function `.
- Index path: `graphify-out/cache/lh-graph-assist.json`; key = lowercased label with a trailing `()` stripped.
- Relations used: `calls`, `indirect_call`, `references`, `uses`.
- Output capped near 600 tokens (2 400 chars); at most three definitions; information, never an imperative ("MANDATORY" is banned).
- Lazy build abandoned after 1.5 s → `skip: index_building`.
- Freshness: `graph.json` mtime ≥ HEAD commit time, the same rule as `graphify_section`.
- Metrics file: `<agent dir>/logs/graph_assist_metrics.jsonl`, fields `ts, session_id, repo, pattern, outcome (hit|miss|skip), reason, latency_ms, definitions, symbol_in_output`.
- `agents` on an external hook: unknown name → load-time `ConfigError` naming the value and the known names; empty/absent = every agent.
- Frozen calibration from day 0 to day 14.

## Review Focus

1. `rg -n foo -- src` / `grep -e foo` / `rg --type py foo`: flags carrying values must not be mistaken for the pattern — expect the real pattern or silence, never a wrong hit.
2. A Bash command chaining two searches (`grep a x && grep b y`): expect the first executed search to be evaluated, never a crash.
3. A repository whose `graph.json` is huge and index missing: the hook must answer within the 1.5 s cutoff (skip) and not block the tool call.
4. A symbol with more than three definitions (`main()` has dozens): expect three listed plus a `(+N more)` count, never an unbounded dump.
5. `cwd` inside a worktree of an indexed repo: the worktree has no `graphify-out/`; expect silence (the spec keys on the cwd's own root), not a lookup against the main checkout's possibly-mismatched graph.

Each line has a test in the task that owns the code (Tasks 3 and 4).

---

### Task 1: `agents` scoping for external hooks

**Files:**
- Modify: `src/lazy_harness/core/config.py` (`ExternalHookConfig`, `_parse_external_hooks`, serializer ~L993)
- Modify: `src/lazy_harness/deploy/engine.py` (`_hook_entries_for`, external loop)
- Test: `tests/unit/test_external_hook_agents.py`

**Interfaces:**
- Produces: `ExternalHookConfig(command: str, matcher: str | None = None, agents: list[str] = [])`.
- Consumes: `agents.registry.list_agents()`, `agents.registry.agent_for_profile(cfg, profile)`.

- [ ] Failing tests: parse table with `agents = ["codex"]`; misspelled `"codx"` raises `ConfigError` whose message contains `'codx'` and `claude-code`; non-list/non-str raises; round-trip save→load→save→load on a new document and merged into an existing file keeps `agents` and keeps shorthand strings shorthand; deploy of a cfg with one codex profile and one claude-code profile emits the scoped external only to codex and prints `· graphify hook-guard search omitted in '<claude profile>': declared for agents codex`.
- [ ] Implement: `_KNOWN_AGENTS` resolved lazily from `list_agents()` inside the parser (import inside the function to avoid a cycle); serializer emits the table form when `matcher` or `agents` is set; deploy skips `ext` when `ext.agents and agent.name not in ext.agents`, echoing the line.
- [ ] Guard-removal check: delete the `agents` skip in deploy, watch the deploy test go red, restore by hand.
- [ ] Commit `feat: scope external hooks to agents`.

### Task 2: graph-assist index

**Files:**
- Create: `src/lazy_harness/knowledge/graph_assist.py`
- Test: `tests/unit/knowledge/test_graph_assist_index.py`, fixture `tests/fixtures/graph_assist/graph.json`

**Interfaces (produced):**
```python
INDEX_NAME = "lh-graph-assist.json"
def normalise(label: str) -> str
def build_index(graph: dict) -> dict[str, list[dict]]           # key -> definitions
def index_path(repo_root: Path) -> Path
def write_index(repo_root: Path) -> Path                          # reads graph.json, writes index with graph_mtime
def load_index(repo_root: Path, *, deadline_s: float = 1.5, clock=time.monotonic) -> dict | None
def lookup(index: dict, pattern: str) -> tuple[str, list[dict]] | None  # exact key, else unique suffix
def render(label: str, defs: list[dict], *, max_defs: int = 3, max_chars: int = 2400) -> str
```
A definition: `{"label", "source_file", "source_location", "calls_in": [...], "calls_out": [...], "docs": [...]}`; lists capped at 5 with a total count kept in `*_total`.

- [ ] Failing tests from the small fixture: homonym key `check_version` → two definitions; document reference lands in `docs`; `contains`/`rationale_for` edges ignored; file nodes (label == basename of source_file) and non-`code` nodes are not keys; suffix lookup `graphify.check_version` resolves only when unique; render lists ≤ 3 with `(+N more)` (Review Focus 4) and contains no `MANDATORY`.
- [ ] Failing test against the real 0.9.67 graph: copy `graphify-out/graph.json` from the main checkout when present (skip otherwise), assert `check_version` has two definitions at `knowledge/graphify.py:L64` and `memory/engram.py:L59`, and `atomic_write_text` has ≥ 1 doc under `specs/`.
- [ ] Failing tests for `load_index`: stale index (index `graph_mtime` < graph mtime) rebuilds; a build whose clock passes 1.5 s returns `None` (frozen fake clock, never wall time).
- [ ] Implement; commit `feat: build a graph-assist index from graph.json`.

### Task 3: search classifier

**Files:** `src/lazy_harness/knowledge/graph_assist.py` (same module), test `tests/unit/knowledge/test_graph_assist_filter.py`

**Interfaces (produced):**
```python
SEARCH_TOOLS = frozenset({"grep", "rg", "ugrep", "egrep"})
IDENTIFIER_RE: re.Pattern[str]
def identifier(pattern: str) -> str | None
def search_target(tool_name: str, tool_input: object, repo_root: Path, cwd: Path) -> str | None
```
`search_target` returns the identifier-shaped pattern or `None`.

- [ ] Failing table test: inject — `grep -rn check_version src`, `rg check_version`, `rg -n -e check_version`, `Grep{pattern: "check_version"}` with no path, `Grep` with a path inside root, `"def check_version"`; silent — `cat x | grep y`, `grep foo /var/log/x`, `grep 'a.*b' src`, `grep "two words" src`, `Grep` path outside root, `rg -t py foo` evaluates `foo` (Review Focus 1), `grep a x && grep b y` evaluates `a` (Review Focus 2), `git grep`, non-dict input, `None`.
- [ ] Implement with `shlex` split on `;`/`&&`/`||` segments, first segment whose executable basename is a search tool and that is not preceded by `|`; skip option args, consuming the value of `-e/-f/-t/-g/-m/-A/-B/-C/--type/--glob` style flags; relative paths resolve against `cwd`.
- [ ] Commit `feat: classify identifier searches for graph assist`.

### Task 4: `pre-tool-use-graph-assist` builtin

**Files:**
- Create: `src/lazy_harness/hooks/builtins/pre_tool_use_graph_assist.py`
- Modify: `src/lazy_harness/hooks/loader.py` (`BuiltinHookSpec.agents`, registry entry, `builtin_agents()`), `src/lazy_harness/deploy/engine.py` (builtin agent filter), docs listing of builtins if a completeness test demands it
- Test: `tests/unit/hooks/builtins/test_pre_tool_use_graph_assist.py`, `tests/unit/test_deploy_builtin_agents.py`

**Interfaces:**
- Consumes: Task 2/3 functions; `_shared.agent_dir_for`; `core.project_identity.main_repo_root` is **not** used — root is `git rev-parse --show-toplevel` of cwd's own checkout, so a worktree without `graphify-out/` stays silent (Review Focus 5).
- Produces: `BuiltinHookSpec.agents: frozenset[str] = frozenset()`; `loader.builtin_agents(name) -> frozenset[str]`.

- [ ] Failing tests: hit returns `HookDecision(additional_context=...)` containing the file:line; every silent case yields `HookDecision()` and a metrics line with the right `reason` (`not_search`, `no_graph`, `stale`, `index_building`, `miss`, `error:<Type>`); malformed/`null`/int/list payload through the runner exits 0 silently; metrics write failure still answers; `symbol_in_output` true on hit; stale via frozen mtimes.
- [ ] Failing deploy test: `pre-tool-use-graph-assist` in `[hooks.pre_tool_use].scripts` for a codex profile is omitted with `· pre-tool-use-graph-assist omitted in 'cx': declared for agents claude-code`; kept for claude-code.
- [ ] Implement; register with `matcher="Bash|Grep"`, `event="pre_tool_use"`, `operations={RUN_COMMAND}`, `agents={"claude-code"}`; not default-on.
- [ ] Commit `feat: add pre-tool-use-graph-assist builtin`.

### Task 5: index on graph update, SessionStart content

**Files:** `src/lazy_harness/cli/knowledge_cmd.py` (`knowledge_graph_update`), `src/lazy_harness/hooks/builtins/context_inject.py` (`graphify_section`); tests in `tests/unit/cli/test_knowledge_graph_update.py` (or existing), `tests/unit/test_builtin_context_inject.py`.

- [ ] Failing tests: successful `graphify update` writes the index; index failure is logged and does not fail the repo; fresh `graphify_section` lists five highest-degree non-file code nodes with `file:line`, three `graphify explain/path` examples and the when-to-use line; reads `links` (today it reads `edges` and prints `0 edges`); stale banner unchanged.
- [ ] Implement; commit `feat: surface god nodes at session start and index on graph update`.

### Task 6: `lh knowledge graph-assist report`

**Files:** `src/lazy_harness/knowledge/graph_assist_report.py`, `src/lazy_harness/cli/knowledge_cmd.py`; test `tests/unit/knowledge/test_graph_assist_report.py`.

- [ ] Failing tests over fixture JSONL + a Claude and a Codex transcript with known counts: (a'), hit precision, p95 latency, (a), (b), deflection, per agent; kill verdict lines; parameter-less smoke test via `CliRunner` on an empty home.
- [ ] Implement using each profile's `TranscriptReader.locate_sessions/read` and the transcript's recorded `cwd`; commit `feat: report graph-assist adoption metrics`.

### Task 7: ship

- [ ] `/tdd-check` pristine; PR; merge; release-please release; `uv tool install --reinstall`; grep site-packages for the builtin.
- [ ] dotfiles `config.toml.tmpl`: `agents = ["codex"]` on the search guard, builtin in `[hooks.pre_tool_use].scripts` (grep the section first); chezmoi apply; `lh deploy` Mac + CT `agents`; fire a real search in each profile; record day 0 in the backlog.

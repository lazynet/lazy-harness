# Graph assist: answer code-symbol searches from the graph

Status: **implemented** on branch `feat/graph-assist` (2026-09-25), plan
`specs/plans/2026-09-25-graph-assist-plan.md`. Rollout (§6) pending. §8 records
where the implementation departed from or sharpened this text.

## 1. Problem

Graphify is installed, indexed and fresh in every repository that matters, and
Claude Code sessions barely use it. Codex sessions, with the same guard hook and
the same instructions, do.

Baseline, last 7 days to 2026-09-24, sessions whose cwd sits in a repository with
`graphify-out/graph.json`:

| | Claude Code (claude-lazy + claude-flex) | Codex (codex-lazy) |
| --- | --- | --- |
| Sessions | 398 | 31 |
| (a) sessions with ≥ 1 graphify call (CLI `query`/`path`/`explain` or MCP) | **23 / 398 = 5.8%** | **23 / 31 = 74.2%** |
| (b) graphify calls / (graphify calls + code greps) | 29 / 3 678 = **0.8%** | 60 / 211 = **28.4%** |

A "code grep" is the `Grep` tool with no path or a path inside the repository, or
a Bash `grep`/`rg`/`ugrep`/`egrep` that is not fed by a pipe and whose absolute
paths all sit inside the repository. The classifier is approximate, which is why
(b) is informative only (§6).

What the numbers rule out:

- **Not the instructions.** The Claude and Codex system docs carry the same four
  graphify mentions.
- **Not orchestration briefs.** Most Codex sessions that used graphify were
  interactive, with no mention of graphify in the first prompt. Prompts that did
  mention it rarely led to use.

The working hypothesis, not verified: Claude Code delivers a `PreToolUse`
`additionalContext` alongside the tool result. By the time the agent reads
"MANDATORY: run graphify query", the grep has already answered, and the order
competes with an answer in hand. The upstream nudge
(`graphify hook-guard search`) is an order with no content. It fires only on a
search command in executed position, but it fires the same for a grep over logs
or JSON as for a symbol lookup in code.

What SessionStart injects today (`context_inject.graphify_section`) is a count
line: `N nodes · M edges · K communities` and three community ids. No names, no
guidance on when the graph beats grep.

## 2. Goal

Make the graph's answer arrive where the agent is already looking, instead of
ordering the agent to go and ask. Scope: Claude Code profiles. Codex keeps the
upstream guard unchanged and serves as the control group.

## 3. Components

### 3.1 `pre-tool-use-graph-assist` (new builtin)

`hooks/builtins/`, event `PreToolUse`, matcher `Bash|Grep`, non-blocking, always
exit 0. Declared for the `claude-code` agent only.

**Filter.** It acts only when all of these hold, and is silent otherwise:

1. The cwd resolves to a repository root holding `graphify-out/graph.json`.
2. The graph is fresh: `graph.json` mtime ≥ HEAD commit time. The same rule as
   `graphify_section`.
3. The search targets the repository. For the `Grep` tool: `path` absent or
   inside the root. For Bash: a search tool runs in executed position, is not fed
   by a pipe, and every absolute path argument is inside the root.
4. The pattern is identifier-shaped. It must match
   `^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)*\(?\)?$` after stripping
   quotes and a leading `def `/`class `/`function `. Regexes, globs and
   multi-word strings fall out.

**Lookup.** Against the index (§3.2): exact match on the normalised label first,
then a unique suffix match (`mod.func`, `Class.method`). Homonyms are expected:
`check_version()` is defined in both `knowledge/graphify.py:64` and
`memory/engram.py:59`. So the result lists up to three definitions, never picks
one silently.

**Output.** `hookSpecificOutput.additionalContext`, markdown, capped near 600
tokens. The shape is illustrative; the caller and document lists are not
measured:

```
Graph: check_version() — 2 definitions
- src/lazy_harness/knowledge/graphify.py:64
  called by: collect_feature_statuses(), doctor_cmd.py … (+3)
  calls: parse_version()
  named in: specs/adrs/023-graphify-code-structure.md, docs/reference/config.md
- src/lazy_harness/memory/engram.py:59
  …
```

It is information, not an instruction: no "MANDATORY", no imperative.

### 3.2 Graph-assist index

A compact derivative of `graph.json` at
`graphify-out/cache/lh-graph-assist.json`, keyed by normalised label. The key is
lowercased, with a trailing `()` stripped. Each entry holds:

- definition: `source_file`, `source_location`;
- one-hop `calls` in and out, labels only, capped;
- documents that reference it: `references`/`uses` edges whose other end is a
  node with `file_type` `document` or a `.md` source;
- the `graph.json` mtime it was built from.

Built from these `graph.json` fields, all verified present in 0.9.67:

- `nodes[].id`, `label`, `source_file`, `source_location`, `file_type`;
- `links[].source`, `target`, `relation`.

The relations used are `calls`, `indirect_call`, `references` and `uses`.

**Who builds it:**

- The `graphify-update` scheduled job, as a last step of `lh knowledge graph
  update` for each repository it rebuilds.
- The hook itself, lazily, when the index is missing or older than
  `graph.json`. The hook abandons the build after 1.5 s: it injects nothing and
  logs `skip: index_building`.

Why an index and not `graphify explain`: measured on 2026-09-24, `explain` takes
1.09–1.13 s on lazy-harness (15 009 nodes) and 0.55–0.62 s on the smaller repos.
About 0.5 s of that is process start-up. A lookup in a prebuilt index costs a few
milliseconds and does not parse graphify's text output. The cost is a dependency
on the `graph.json` schema, pinned by a test against the real 0.9.67 file (§5).

### 3.3 Per-agent scoping of external hooks

`ExternalHookConfig` gains an optional `agents: list[str]`. When it is set,
`lh deploy` emits that external hook only to profiles whose resolved agent is in
the list, through `agents.registry.agent_for_profile`, never by reading the
profile field. An unknown agent name is a load-time diagnostic naming the value
and the known names. Empty or absent means every agent, which is today's
behaviour.

Config after the change (dotfiles `config.toml.tmpl`):

```toml
external = [
    { command = "graphify hook-guard search", matcher = "Bash|Grep", agents = ["codex"] },
    { command = "graphify hook-guard read",   matcher = "Read|Glob" },
]
```

The builtin goes in `[hooks.pre_tool_use].scripts`. Before wiring it, grep that
section: an explicit `scripts` list replaces `DEFAULT_HOOKS` wholesale.

### 3.4 SessionStart section

`graphify_section` keeps the stale banner. On a fresh graph it replaces the count
line with:

- the five highest-degree non-file nodes: label and `file:line`;
- three example commands built from those nodes, for example
  `graphify explain "<label>"` or `graphify path "<a>" "<b>"`;
- one line on when to prefer the graph: who calls X, what breaks if Y changes,
  which docs name Z.

It stays inside the existing `max_body_chars` budget and drop order.

### 3.5 Measurement

Each hook evaluation appends one line to
`<agent log dir>/graph_assist_metrics.jsonl`:

```json
{"ts": "…", "session_id": "…", "repo": "…", "pattern": "…",
 "outcome": "hit|miss|skip", "reason": "…", "latency_ms": 12,
 "definitions": 2, "symbol_in_output": true}
```

A new read-only report, `lh knowledge graph-assist report [--since DATE]`,
computes the §6 metrics from this file plus the transcripts, for both agents.
The transcript scan reuses the classifier that produced the §1 baseline.

## 4. Error handling

- Any exception: no output, exit 0, `outcome: skip, reason: error:<type>`.
- Malformed JSON on stdin, or valid JSON of the wrong type (`null`, int, list):
  silent. Type guards come before every `.get()`.
- Stale graph: silent, `reason: stale`.
- Missing or unreadable index, and the rebuild exceeds 1.5 s: silent,
  `reason: index_building`.
- Metrics write failure: swallowed, and the hook still answers.

## 5. Tests

Strict TDD, one failing test first per behaviour. The gates from `AGENTS.md`
that apply:

- **Filter table.** Payloads that must inject, and payloads that must stay
  silent:
  - inject: a Bash `grep -rn check_version src`, the `Grep` tool with no path;
  - silent: `cat x | grep y`, `grep foo /var/log/x`, a regex pattern, a
    multi-word pattern, a path outside the repo, a stale graph, malformed JSON,
    and each wrong JSON type.
- **Index from the real consumer.** Built from a small fixture **and** from a
  copy of a real 0.9.67 `graph.json`. Assert the homonym case (`check_version()`
  → two definitions) and one document reference.
- **Frozen time.** Stale detection and the 1.5 s build cutoff use frozen clocks
  and mtimes, never wall-clock budgets.
- **Config schema.** `agents` round-trips save→load→save→load, on a new document
  and merged into an existing one. A misspelled agent asserts the diagnostic
  text. A test fails when the filter is removed: delete the guard, watch it go
  red, restore it by hand.
- **Wiring.** Fire the real operation in each profile. Read `lh deploy` output
  for `· pre-tool-use-graph-assist omitted in '<profile>'`. Confirm the upstream
  search guard is absent from claude-lazy and claude-flex settings and present
  in codex-lazy `hooks.json`.
- **Report.** `lh knowledge graph-assist report` over a fixture JSONL and
  transcript set with known counts, plus a parameter-less smoke test.

## 6. Rollout and kill criteria

**Deploy order** (binary first):

1. merge, then release;
2. `uv tool install --reinstall`, then grep site-packages for the builtin;
3. the dotfiles `config.toml.tmpl` change, applied through chezmoi;
4. `lh deploy` on the Mac and the CT `agents`;
5. exercise it in claude-lazy, claude-flex and codex-lazy.

**Day 0** is the date step 4 completes. The calibration is frozen from day 0 to
day 14: the filter regex, the caps and the thresholds do not change inside the
window.

| Metric | Definition | Role |
| --- | --- | --- |
| (a') graph touch | Claude sessions in indexed repos with ≥ 1 agent graphify call **or** ≥ 1 `hit` injection | **Kill** if < 20% at day 14 |
| Hit precision | `hit` injections where the searched symbol appears in the injected text / all `hit` injections | **Kill** if < 50% |
| Latency | p95 of `latency_ms` over all evaluations | **Kill** if > 1 500 ms |
| (a) agent calls | the §1 metric | Informative: does injected context lead to asking the graph |
| (b) graph vs code grep | the §1 metric | Informative |
| Deflection | after a `hit` for symbol S, no Grep/Read of S within the next three tool calls | Informative |
| Codex control | (a) and (b) for codex-lazy | Informative: a Codex drop alongside a Claude rise points away from the hook |

**Removal** when a kill criterion trips:

- drop the builtin from `[hooks.pre_tool_use].scripts`;
- drop `agents` from the upstream search guard, so every agent gets the nudge
  again;
- `lh deploy`;
- record the measured numbers in `specs/backlog.md`.

The SessionStart section is judged separately. It stays unless it measurably
displaces a higher-priority section.

## 7. Out of scope

- The upstream `graphify hook-guard read`: it stays for both agents, unchanged.
- Graphify strict mode.
- MCP tool loading. The tools stay deferred behind ToolSearch, as today.

## 8. Implementation notes (2026-09-25)

- **`Grep` is normalised, not read raw.** A builtin may not read
  `ToolCall.raw_input` (`tests/unit/hooks/test_builtin_contract.py`), so
  `Operation` gained `SEARCH_CODE` and `ToolCall` gained `search_pattern` and
  `search_path`, filled by the Claude Code adapter for `Grep`. A shell `grep`
  stays `RUN_COMMAND`.
- **Builtins can be agent-scoped too.** `BuiltinHookSpec.agents` mirrors the
  external field: `pre-tool-use-graph-assist` declares `claude-code`, and
  deploy omits it elsewhere with `· <hook> omitted in '<profile>': declared for
  agents claude-code`. It is opt-in, not in `DEFAULT_HOOKS`, because removal
  (§6) is dropping it from `scripts`.
- **Only search calls are evaluations.** A shell command that runs no search
  tool returns before any git call and writes no metrics line, so the p95 in §6
  is over searches, not over every `Bash`.
- **Narrowing an external entry does not uninstall it.** Deploy preserves hook
  groups it cannot prove it owns, so the upstream search guard already in the
  Claude profiles' `settings.json` has to be removed once by hand at rollout.
- **Baseline, re-measured with the shipped report.** `lh knowledge
  graph-assist report --since 2026-09-17` on 2026-09-25: Claude Code 39/638
  sessions = 6.1% (a), 1.0% (b) — consistent with §1. Codex 24/60 = 40.0% (a),
  29.0% (b): (b) matches §1, (a) does not, because this population counts
  spawned Codex agents as sessions. The report skips sessions with no tool
  call (about 800 headless evaluations in the Claude window) and reads each
  profile from its own `config_dir`. Day-0 comparisons use the report, never
  §1.
- **SessionStart counts `links`.** The old section read `edges`, which graphify
  0.9.67 does not write, and printed `0 edges`. It now reads `links`, falling
  back to `edges`.

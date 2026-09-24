# Graphify 0.9.41 → 0.9.67: probe evidence

Date: 2026-09-24. Probed with `graphifyy[mcp,ollama]==0.9.67` installed into an
isolated venv, so the real install was left alone. The repository probe ran
against a `git clone --local` of this repository with its existing
`graphify-out/` copied in. Each row names the surface lh depends on, the
command, and what came back.

| Surface | Where lh depends on it | Command | Observed |
| --- | --- | --- | --- |
| Version probe | `knowledge/graphify.py:check_version` parses stdout | `graphify --version` | stdout is exactly `graphify 0.9.67`, exit 0. New: three stale-skill warnings go to **stderr**, one per installed skill older than the package, so they do not reach the parser |
| Incremental rebuild | `lh knowledge graph update` → `run_graphify("update", path)` | `graphify update .` | exit 0 in 20 s. Nodes 14 955 → 15 009, edges 33 407 → 36 821 (+10%) on the same tree |
| Query | agents, `graphify-update` consumers | `graphify query "who calls check_version"` | answers from the rebuilt graph, and the header names the graph and its node count |
| Search guard | `[hooks.pre_tool_use].external`, matcher `Bash\|Grep` | `graphify hook-guard search` with a Bash `grep` payload | `hookSpecificOutput.hookEventName = PreToolUse`, `additionalContext` nudge, no `permissionDecision`. Silent for a Read payload |
| Read guard | same, matcher `Read\|Glob` | `graphify hook-guard read` with a Read payload for a `.py` file | same shape. Silent for a Bash payload |
| MCP server | `mcp_server_config()` → `graphify-mcp` | `initialize` + `tools/list` over stdio | ten tools, same names as before: `query_graph`, `get_node`, `get_neighbors`, `get_community`, `god_nodes`, `graph_stats`, `shortest_path`, `list_prs`, `get_pr_impact`, `triage_prs` |
| Claude skill | `profiles/<p>/claude-code/skills/graphify` (dotfiles) | `graphify install --platform claude` into a scratch `HOME` and `CLAUDE_CONFIG_DIR` | `SKILL.md` and `references/` byte-identical to the 0.9.61 copy; only `.graphify_version` changes. The same run **wrote `$CLAUDE_CONFIG_DIR/CLAUDE.md`**, so never run it against a real profile: refresh the stamp in the dotfiles source instead |

## What changed upstream that matters here

Read from `CHANGELOG.md` 0.9.42–0.9.67 in `Graphify-Labs/graphify`, filtered to
the languages and features this setup uses. The larger edge count above comes
from the first two rows.

- **Python imports resolve locally** (0.9.67). `import pkg.sub` / `from pkg.sub
  import x` now resolve to the in-tree module node. A `pkg/` package next to a
  `pkg.py` module no longer produces a phantom import cycle.
- **Markdown code spans link to code** (0.9.62, 0.9.63). A backticked
  `` `Symbol` `` or `` `mod.func` `` in a `.md` file emits a `references` edge when
  exactly one callable matches. ADRs and specs here name code in backticks, so
  "which documents name this symbol" becomes a graph query.
- **Deterministic `graph.json`** (0.9.66). `PYTHONHASHSEED` is pinned through a
  re-exec, so community detection and the file bytes are stable run-to-run.
  Hook-triggered and scheduled rebuilds stop disagreeing.
- **Terraform topology and attributes** (0.9.62, 0.9.64, 0.9.67). Local module
  sources resolve to directory-scoped nodes. Resource attributes are kept, with
  secret-named values redacted before they reach `graph.json`, including values
  nested in lists. Upstream asks for one `graphify update .` after upgrading so
  Terraform ids regenerate.
- **Guard hooks carry a timeout** (0.9.62), and the search guard only fires on
  a search command in executed position (0.9.53), not on prose or heredocs.
- Not new in this range, but unused here: **strict mode**, upstream since
  2026-07-17 (`689dd6c`, before 0.9.41) (`graphify install --project --strict`, or
  `GRAPHIFY_HOOK_STRICT=1`) denies the first raw `Read` of indexed, fresh,
  in-project code per session until a `graphify query` has run within
  `GRAPHIFY_HOOK_STRICT_TTL` (default 1800 s). It blocks at most once per session;
  search stays nudge-only.

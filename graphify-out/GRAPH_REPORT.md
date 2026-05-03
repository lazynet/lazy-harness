# Graph Report - lazy-harness  (2026-05-03)

## Corpus Check
- 264 files · ~308,230 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 2359 nodes · 5482 edges · 63 communities detected
- Extraction: 68% EXTRACTED · 32% INFERRED · 0% AMBIGUOUS · INFERRED: 1764 edges (avg confidence: 0.68)
- Token cost: 0 input · 0 output

## Community Hubs (Navigation)
- [[_COMMUNITY_Community 0|Community 0]]
- [[_COMMUNITY_Community 1|Community 1]]
- [[_COMMUNITY_Community 2|Community 2]]
- [[_COMMUNITY_Community 3|Community 3]]
- [[_COMMUNITY_Community 4|Community 4]]
- [[_COMMUNITY_Community 5|Community 5]]
- [[_COMMUNITY_Community 6|Community 6]]
- [[_COMMUNITY_Community 7|Community 7]]
- [[_COMMUNITY_Community 8|Community 8]]
- [[_COMMUNITY_Community 9|Community 9]]
- [[_COMMUNITY_Community 10|Community 10]]
- [[_COMMUNITY_Community 11|Community 11]]
- [[_COMMUNITY_Community 12|Community 12]]
- [[_COMMUNITY_Community 13|Community 13]]
- [[_COMMUNITY_Community 14|Community 14]]
- [[_COMMUNITY_Community 15|Community 15]]
- [[_COMMUNITY_Community 16|Community 16]]
- [[_COMMUNITY_Community 17|Community 17]]
- [[_COMMUNITY_Community 18|Community 18]]
- [[_COMMUNITY_Community 19|Community 19]]
- [[_COMMUNITY_Community 20|Community 20]]
- [[_COMMUNITY_Community 21|Community 21]]
- [[_COMMUNITY_Community 22|Community 22]]
- [[_COMMUNITY_Community 23|Community 23]]
- [[_COMMUNITY_Community 24|Community 24]]
- [[_COMMUNITY_Community 25|Community 25]]
- [[_COMMUNITY_Community 26|Community 26]]
- [[_COMMUNITY_Community 27|Community 27]]
- [[_COMMUNITY_Community 28|Community 28]]
- [[_COMMUNITY_Community 29|Community 29]]
- [[_COMMUNITY_Community 30|Community 30]]
- [[_COMMUNITY_Community 31|Community 31]]
- [[_COMMUNITY_Community 32|Community 32]]
- [[_COMMUNITY_Community 33|Community 33]]
- [[_COMMUNITY_Community 34|Community 34]]
- [[_COMMUNITY_Community 35|Community 35]]
- [[_COMMUNITY_Community 36|Community 36]]
- [[_COMMUNITY_Community 37|Community 37]]
- [[_COMMUNITY_Community 38|Community 38]]
- [[_COMMUNITY_Community 39|Community 39]]
- [[_COMMUNITY_Community 40|Community 40]]
- [[_COMMUNITY_Community 41|Community 41]]
- [[_COMMUNITY_Community 42|Community 42]]
- [[_COMMUNITY_Community 43|Community 43]]
- [[_COMMUNITY_Community 44|Community 44]]
- [[_COMMUNITY_Community 45|Community 45]]
- [[_COMMUNITY_Community 46|Community 46]]
- [[_COMMUNITY_Community 47|Community 47]]
- [[_COMMUNITY_Community 48|Community 48]]
- [[_COMMUNITY_Community 49|Community 49]]
- [[_COMMUNITY_Community 52|Community 52]]
- [[_COMMUNITY_Community 53|Community 53]]
- [[_COMMUNITY_Community 54|Community 54]]
- [[_COMMUNITY_Community 55|Community 55]]
- [[_COMMUNITY_Community 57|Community 57]]
- [[_COMMUNITY_Community 58|Community 58]]
- [[_COMMUNITY_Community 59|Community 59]]
- [[_COMMUNITY_Community 62|Community 62]]
- [[_COMMUNITY_Community 63|Community 63]]
- [[_COMMUNITY_Community 64|Community 64]]
- [[_COMMUNITY_Community 65|Community 65]]
- [[_COMMUNITY_Community 66|Community 66]]
- [[_COMMUNITY_Community 102|Community 102]]

## God Nodes (most connected - your core abstractions)
1. `MetricsDB` - 132 edges
2. `Config` - 95 edges
3. `ConfigError` - 75 edges
4. `load_config()` - 74 edges
5. `m()` - 65 edges
6. `ProfileEntry` - 64 edges
7. `config()` - 52 edges
8. `H()` - 49 edges
9. `e()` - 46 edges
10. `ProfilesConfig` - 46 edges

## Surprising Connections (you probably didn't know these)
- `test_qmd_run_returns_result()` --calls--> `run_qmd()`  [INFERRED]
  tests/unit/test_qmd.py → src/lazy_harness/knowledge/qmd.py
- `Tests for QMD CLI wrapper.` --uses--> `QmdResult`  [INFERRED]
  tests/unit/test_qmd.py → src/lazy_harness/knowledge/qmd.py
- `Tests for the move_projects core module.` --uses--> `MoveError`  [INFERRED]
  tests/unit/test_move_projects.py → src/lazy_harness/core/move_projects.py
- `Tests for built-in context-inject hook.` --uses--> `ProfileEntry`  [INFERRED]
  tests/unit/test_builtin_context_inject.py → src/lazy_harness/core/config.py
- `test_registry_get_claude()` --calls--> `get_agent()`  [INFERRED]
  tests/unit/test_agent_claude.py → src/lazy_harness/agents/registry.py

## Communities

### Community 0 - "Community 0"
Cohesion: 0.02
Nodes (165): _mk_event(), test_drain_flushes_pending_events(), _seed(), test_status_reports_pending_count(), MetricsConfig, _parse_metrics(), Options for a named sink as declared under [metrics.sink_options.<name>]., Top-level [metrics] block.      Default (no block): only `sqlite_local` runs, ze (+157 more)

### Community 1 - "Community 1"
Cohesion: 0.04
Nodes (202): _(), a(), aa(), Ae(), ai(), an(), Ao(), ar() (+194 more)

### Community 2 - "Community 2"
Cohesion: 0.02
Nodes (178): AgentAdapter, Agent adapter protocol — defines what an agent adapter must expose., Protocol that all agent adapters must implement., Resolve the agent's config directory for a profile., Return list of hook events this agent supports., Generate agent-native hook config (e.g., settings.json for Claude Code)., Generate agent-native MCP server config block.          `servers` is a mapping o, Locate the agent's executable on disk.          Returns the absolute path, or No (+170 more)

### Community 3 - "Community 3"
Cohesion: 0.02
Nodes (186): config(), Configure optional features interactively., hooks_list(), List all configured and built-in hooks., AgentConfig, _config_to_dict(), ContextInjectConfig, EngramConfig (+178 more)

### Community 4 - "Community 4"
Cohesion: 0.03
Nodes (96): _backups_parent(), _home(), _latest_backup_dir(), _maybe_deploy_envrc(), migrate(), Deploy .envrc into all profile roots after a successful migration., Migrate an existing Claude Code / lazy-claudecode setup to lazy-harness., detect_claude_code() (+88 more)

### Community 5 - "Community 5"
Cohesion: 0.04
Nodes (121): _find_latest_session(), _log(), main(), _rotate_log(), _find_latest_session(), _log(), main(), CompoundLoopConfig (+113 more)

### Community 6 - "Community 6"
Cohesion: 0.04
Nodes (75): arrayToHash(), balanced(), braceExpand(), childrenIgnored(), cleanUpNextTick(), collectNonEnumProps(), _deepEqual(), deprecationWarning() (+67 more)

### Community 7 - "Community 7"
Cohesion: 0.05
Nodes (59): check_cli(), Verify all lh subcommands respond to --help without crashing., check_config(), Validate that config.toml exists, parses, and has required fields., check_hooks(), Verify declared hooks resolve to executable files (without running them)., check_knowledge(), Verify knowledge path exists, is writable, and expected subdirs are present. (+51 more)

### Community 8 - "Community 8"
Cohesion: 0.05
Nodes (55): Tests for `lh status` view helpers., test_count_errors_today(), test_count_errors_today_missing_log(), test_decode_project_name_known_container_fallback(), test_decode_project_name_root(), test_format_size_returns_question_for_missing(), test_format_size_units(), test_format_tokens_thresholds() (+47 more)

### Community 9 - "Community 9"
Cohesion: 0.05
Nodes (40): lh scheduler — scheduled jobs management., Manage scheduled jobs., Show scheduler backend and job status., Install scheduled jobs for current OS., Remove all scheduled jobs., scheduler(), scheduler_install(), scheduler_status() (+32 more)

### Community 10 - "Community 10"
Cohesion: 0.06
Nodes (44): _build_command(), check_version(), GraphifyResult, is_graphify_available(), mcp_server_config(), Graphify CLI wrapper — code structure index for AI coding agents.  Pinned versio, Declarative MCP entry for Graphify (consumed by deploy_mcp_servers)., Probe `graphify --version` and compare against PINNED_VERSION.      Returns `(ma (+36 more)

### Community 11 - "Community 11"
Cohesion: 0.07
Nodes (46): _classify_handoff_staleness(), _compose_banner(), episodic_context(), _expand(), git_context(), handoff_context(), _join_sections(), _jsonl_tail_summaries() (+38 more)

### Community 12 - "Community 12"
Cohesion: 0.07
Nodes (44): s(), _(), a(), b(), d(), e(), f(), i() (+36 more)

### Community 13 - "Community 13"
Cohesion: 0.09
Nodes (39): append(), Simple append-only log file with size-based rotation.  Used by scheduled command, Append a timestamped line to `path`, rotating if it grows past `max_bytes`., _rotate(), ContextGenResult, _generate_auto_part(), _merge_context(), _parse_and_update() (+31 more)

### Community 14 - "Community 14"
Cohesion: 0.08
Nodes (32): main(), PostToolUse auto-format hook — runs `ruff format` on Python edits.  Fail-soft: a, _read_stdin_json(), BlockDecision, BlockRule, _format_block_message(), _load_allowlist(), main() (+24 more)

### Community 15 - "Community 15"
Cohesion: 0.07
Nodes (32): knowledge_cmd(), memory_cmd(), lh config — interactive wizards for optional features (per ADR-018, ADR-026)., Configure episodic memory backends ([memory] section)., Configure knowledge backends ([knowledge] section)., Interactive wizard for [knowledge.structure] (lh config knowledge --init)., Run the [knowledge.structure] wizard for Graphify. Returns True if written., wizard_knowledge() (+24 more)

### Community 16 - "Community 16"
Cohesion: 0.08
Nodes (26): ClaudeCodeAdapter, Claude Code agent adapter., Adapter for Claude Code (Anthropic's CLI agent)., Locate the claude binary.          Preference order:           1. ~/.local/share, Generate Claude Code settings.json hooks section., list_agents(), Agent discovery and registration., Return list of registered agent type names. (+18 more)

### Community 17 - "Community 17"
Cohesion: 0.1
Nodes (26): execute_hook(), HookResult, Hook execution engine — run hooks and collect results., run_hooks_for_event(), _find_builtin(), _find_user_hook(), HookInfo, list_builtin_hooks() (+18 more)

### Community 18 - "Community 18"
Cohesion: 0.28
Nodes (30): _(), a(), b(), c(), d(), E(), er(), f() (+22 more)

### Community 19 - "Community 19"
Cohesion: 0.14
Nodes (26): _find_latest_session(), _log(), main(), _atomic_write(), _classify(), _decode_project_dir(), _existing_message_count(), export_session() (+18 more)

### Community 20 - "Community 20"
Cohesion: 0.28
Nodes (25): _(), a(), b(), c(), d(), e(), f(), g() (+17 more)

### Community 21 - "Community 21"
Cohesion: 0.12
Nodes (22): lh statusline — render a Claude Code statusline from JSON on stdin., Read a Claude Code status payload on stdin and print the formatted line.      Co, statusline(), format_statusline(), _profile_label(), Statusline renderer for Claude Code.  Claude Code's statusline pipes a JSON payl, Derive the profile name from CLAUDE_CONFIG_DIR.      Examples:       ~/.claude-l, Convert a raw token count to 'NK' (round-half-up).      Python's round() uses ba (+14 more)

### Community 22 - "Community 22"
Cohesion: 0.19
Nodes (22): collect_feature_statuses(), _engram_status(), FeatureStatus, _graphify_status(), _probe_version(), _qmd_status(), Feature status helper for lh doctor (per ADR-018, ADR-025)., Collect status for every optional tool the harness knows about. (+14 more)

### Community 23 - "Community 23"
Cohesion: 0.17
Nodes (20): _home(), init(), _maybe_deploy_envrc(), lh init — interactive setup wizard., Initialize lazy-harness for a new user., Best-effort .envrc deploy. Silent if no roots configured yet., test_check_existing_claude_dir(), test_check_existing_lazy_profile() (+12 more)

### Community 24 - "Community 24"
Cohesion: 0.18
Nodes (19): list_projects(), move_project(), move_projects(), MoveResult, Move project conversation history between profile config dirs.  Each profile kee, Return the encoded project dir names under a profile., Move a single project dir from src profile to dst profile.      Idempotent: if t, Move many projects in order, collecting results. Stops on MoveError. (+11 more)

### Community 25 - "Community 25"
Cohesion: 0.18
Nodes (16): _build_block(), Generate / update direnv .envrc files for profile roots.  Each root gets a manag, Return the new .envrc content with the managed block inserted/updated.      If `, Create or update root/.envrc with the managed block. Idempotent., render_envrc(), write_envrc(), Tests for direnv .envrc generator., test_render_appends_block_when_no_markers() (+8 more)

### Community 26 - "Community 26"
Cohesion: 0.23
Nodes (14): _(), a(), c(), d(), f(), i(), l(), m() (+6 more)

### Community 27 - "Community 27"
Cohesion: 0.21
Nodes (13): _(), a(), c(), e(), f(), i(), k(), l() (+5 more)

### Community 28 - "Community 28"
Cohesion: 0.21
Nodes (13): a(), b(), c(), d(), e(), h(), i(), l() (+5 more)

### Community 29 - "Community 29"
Cohesion: 0.19
Nodes (14): a(), c(), d(), e(), f(), l(), m(), n() (+6 more)

### Community 30 - "Community 30"
Cohesion: 0.21
Nodes (13): extract_project_name(), extract_session_date(), iter_assistant_messages(), parse_session(), Session JSONL collector — parse agent sessions into token stats., Yield one dict per assistant message in a JSONL session file.      Each dict has, Tests for session JSONL collector., test_extract_project_name() (+5 more)

### Community 31 - "Community 31"
Cohesion: 0.28
Nodes (13): a(), b(), c(), f(), i(), k(), l(), m() (+5 more)

### Community 32 - "Community 32"
Cohesion: 0.21
Nodes (10): User identity resolution for metrics events.  Tries (in order): explicit profile, resolve_identity(), ResolvedIdentity, Tests for core.identity., test_explicit_empty_string_is_ignored(), test_explicit_user_id_wins(), test_gh_reader_returning_empty_string_treated_as_missing(), test_gh_used_when_explicit_missing() (+2 more)

### Community 33 - "Community 33"
Cohesion: 0.21
Nodes (7): _(), i(), l(), n(), s(), t(), u()

### Community 34 - "Community 34"
Cohesion: 0.29
Nodes (11): _interactive_session_jsonl(), _patch_config_lookup(), Tests for built-in session-end hook., Emit a minimal lh.toml so load_config succeeds with compound_loop enabled., Invoke session_end.main() in a controlled environment.      stdin is replaced wi, Force path: a freshly-queued task must not suppress a SessionEnd run.      Regre, _run_session_end(), test_session_end_hook_queues_task_even_when_debounced() (+3 more)

### Community 35 - "Community 35"
Cohesion: 0.33
Nodes (10): a(), c(), f(), l(), m(), n(), o(), r() (+2 more)

### Community 36 - "Community 36"
Cohesion: 0.33
Nodes (10): a(), c(), d(), e(), l(), m(), n(), o() (+2 more)

### Community 37 - "Community 37"
Cohesion: 0.24
Nodes (9): ensure_knowledge_dir(), list_sessions(), Knowledge directory management — ensure structure, list content, resolve paths., session_export_path(), Tests for knowledge directory management., test_ensure_knowledge_dir(), test_ensure_knowledge_dir_existing(), test_list_sessions() (+1 more)

### Community 38 - "Community 38"
Cohesion: 0.22
Nodes (1): Unit tests for post_tool_use_format hook.

### Community 39 - "Community 39"
Cohesion: 0.33
Nodes (7): a(), c(), e(), i(), s(), t(), u()

### Community 40 - "Community 40"
Cohesion: 0.25
Nodes (7): config_dir(), data_dir(), home_dir(), Shared test fixtures for lazy-harness., Temporary config directory mimicking ~/.config/lazy-harness/., Temporary data directory mimicking ~/.local/share/lazy-harness/., Temporary home directory. Patches HOME and relevant env vars.

### Community 41 - "Community 41"
Cohesion: 0.43
Nodes (6): _memory_dir(), Tests for built-in post-compact hook., _run_hook(), test_post_compact_injects_fresh_summary(), test_post_compact_skips_when_summary_missing(), test_post_compact_skips_when_summary_stale()

### Community 42 - "Community 42"
Cohesion: 0.48
Nodes (6): Integration smoke tests — spawn the hook modules as Claude Code would., _run_hook(), test_both_hooks_exit_zero_on_empty_stdin(), test_post_tool_use_format_exits_zero_on_python_edit(), test_pre_tool_use_security_allows_innocent_command(), test_pre_tool_use_security_blocks_rm_rf()

### Community 43 - "Community 43"
Cohesion: 0.53
Nodes (5): Unit tests for lh doctor., test_doctor_does_not_warn_when_ruff_present(), test_doctor_renders_features_section(), test_doctor_warns_when_ruff_missing(), _write_config()

### Community 44 - "Community 44"
Cohesion: 0.33
Nodes (1): Integration tests for `lh statusline`.

### Community 45 - "Community 45"
Cohesion: 0.4
Nodes (2): s(), t()

### Community 46 - "Community 46"
Cohesion: 0.33
Nodes (5): cli(), Top-level CLI entrypoint for lazy-harness., lazy-harness — A cross-platform harnessing framework for AI coding agents., Register all subcommands. Called after imports to avoid circular deps., register_commands()

### Community 47 - "Community 47"
Cohesion: 0.4
Nodes (1): Tests for the lh config CLI command group.

### Community 48 - "Community 48"
Cohesion: 0.4
Nodes (1): Integration tests for lh init wizard (C3).

### Community 49 - "Community 49"
Cohesion: 0.7
Nodes (4): e(), n(), r(), t()

### Community 52 - "Community 52"
Cohesion: 0.7
Nodes (4): build_summary(), _log(), main(), parse_transcript()

### Community 53 - "Community 53"
Cohesion: 0.67
Nodes (3): _pyproject_version(), Version coherence guardrails.  The package version lives in two places — `pyproj, test_pyproject_and_dunder_version_agree()

### Community 54 - "Community 54"
Cohesion: 0.5
Nodes (1): Tests for built-in pre-compact hook.

### Community 55 - "Community 55"
Cohesion: 0.83
Nodes (3): _minimal_config(), test_selftest_json_output(), test_selftest_runs_and_reports()

### Community 57 - "Community 57"
Cohesion: 0.67
Nodes (3): Integration test: `lh metrics ingest` routes events to http_remote., test_metrics_ingest_posts_to_remote(), _write_fake_session()

### Community 58 - "Community 58"
Cohesion: 0.5
Nodes (3): Test: `lh metrics ingest` surfaces config validation errors for unnamed sinks., Sink named in [metrics].sinks but no [metrics.sink_options.X] block → error., test_ingest_errors_on_unnamed_config_block()

### Community 59 - "Community 59"
Cohesion: 0.83
Nodes (3): _log(), main(), _strip_html_comments()

### Community 62 - "Community 62"
Cohesion: 1.0
Nodes (1): lazy-harness — A cross-platform harnessing framework for AI coding agents.

### Community 63 - "Community 63"
Cohesion: 1.0
Nodes (1): Episodic memory backends — Engram and friends.

### Community 64 - "Community 64"
Cohesion: 1.0
Nodes (1): Plugin system: contracts, registry, errors.

### Community 65 - "Community 65"
Cohesion: 1.0
Nodes (1): Built-in metrics sinks.

### Community 66 - "Community 66"
Cohesion: 1.0
Nodes (1): Interactive wizards for `lh config <feature> --init`.

### Community 102 - "Community 102"
Cohesion: 1.0
Nodes (1): Unique identifier for this agent type.

## Knowledge Gaps
- **147 isolated node(s):** `Shared test fixtures for lazy-harness.`, `Temporary config directory mimicking ~/.config/lazy-harness/.`, `Temporary data directory mimicking ~/.local/share/lazy-harness/.`, `Temporary home directory. Patches HOME and relevant env vars.`, `Version coherence guardrails.  The package version lives in two places — `pyproj` (+142 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **Thin community `Community 38`** (9 nodes): `Unit tests for post_tool_use_format hook.`, `test_exits_zero_on_malformed_stdin()`, `test_exits_zero_when_ruff_not_installed()`, `test_exits_zero_when_ruff_times_out()`, `test_runs_ruff_format_on_python_edit()`, `test_runs_ruff_format_on_python_write()`, `test_skips_non_edit_tools()`, `test_skips_non_python_files()`, `test_post_tool_use_format.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 44`** (6 nodes): `Integration tests for `lh statusline`.`, `test_statusline_handles_array_payload()`, `test_statusline_handles_empty_stdin()`, `test_statusline_handles_invalid_json()`, `test_statusline_renders_payload_from_stdin()`, `test_statusline_cmd.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 45`** (6 nodes): `e()`, `n()`, `o()`, `s()`, `t()`, `lunr.da.min.js`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 47`** (5 nodes): `Tests for the lh config CLI command group.`, `test_config_knowledge_init_invokes_wizard()`, `test_config_memory_init_invokes_wizard()`, `test_config_memory_without_init_prints_usage()`, `test_config_cmd.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 48`** (5 nodes): `Integration tests for lh init wizard (C3).`, `test_init_blocks_on_existing_lazy_claudecode()`, `test_init_blocks_on_vanilla_claude()`, `test_init_on_empty_home()`, `test_init_cmd.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 54`** (4 nodes): `test_builtin_pre_compact.py`, `Tests for built-in pre-compact hook.`, `test_pre_compact_empty_input()`, `test_pre_compact_returns_zero()`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 62`** (2 nodes): `lazy-harness — A cross-platform harnessing framework for AI coding agents.`, `__init__.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 63`** (2 nodes): `Episodic memory backends — Engram and friends.`, `__init__.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 64`** (2 nodes): `Plugin system: contracts, registry, errors.`, `__init__.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 65`** (2 nodes): `Built-in metrics sinks.`, `__init__.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 66`** (2 nodes): `__init__.py`, `Interactive wizards for `lh config <feature> --init`.`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 102`** (1 nodes): `Unique identifier for this agent type.`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `next()` connect `Community 22` to `Community 3`, `Community 6`, `Community 7`?**
  _High betweenness centrality (0.238) - this node is a cross-community bridge._
- **Why does `o()` connect `Community 1` to `Community 12`?**
  _High betweenness centrality (0.175) - this node is a cross-community bridge._
- **Why does `load_config()` connect `Community 3` to `Community 0`, `Community 2`, `Community 4`, `Community 5`, `Community 7`, `Community 9`, `Community 11`, `Community 19`, `Community 23`?**
  _High betweenness centrality (0.172) - this node is a cross-community bridge._
- **Are the 111 inferred relationships involving `MetricsDB` (e.g. with `Tests for SQLite metrics store.` and `Tests for the metrics ingest pipeline.`) actually correct?**
  _`MetricsDB` has 111 INFERRED edges - model-reasoned connections that need verification._
- **Are the 93 inferred relationships involving `Config` (e.g. with `Tests for deploy_mcp_servers — MCP block writer in deploy/engine.py.` and `Tests for the features helper used by lh doctor.`) actually correct?**
  _`Config` has 93 INFERRED edges - model-reasoned connections that need verification._
- **Are the 69 inferred relationships involving `ConfigError` (e.g. with `Tests for TOML config loading and validation.` and `Tests for the [metrics] config block.`) actually correct?**
  _`ConfigError` has 69 INFERRED edges - model-reasoned connections that need verification._
- **Are the 53 inferred relationships involving `load_config()` (e.g. with `test_load_config_from_file()` and `test_load_config_missing_file()`) actually correct?**
  _`load_config()` has 53 INFERRED edges - model-reasoned connections that need verification._
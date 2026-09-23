# Profiles are identity × agent — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Strict TDD: every production line is preceded by a failing test you watched fail.

**Goal:** `ProfileEntry.identity` (optional) keys the source tree and generated docs by identity, validates `{prefix}-{identity}[-{suffix}]` names, adds `lh run|exec --agent`, and ships `lh metrics rename-profile`.

**Architecture:** One helper resolves identity (`entry.identity or name`), one resolves the source dir, one map resolves agent prefixes. Every current `profiles / <name>` join routes through the source-dir helper. `sync_profiles` iterates configured profiles instead of directories when it has a config.

**Tech Stack:** Python 3.11+, click, pytest, ruff, uv, SQLite (`monitoring/db.py`).

**Spec:** `specs/designs/2026-09-23-profile-identity-design.md` (ADR-068). Read it before Task 1.

## Global Constraints

- Work only in `.worktrees/profile-identity` (branch `docs/profile-identity`; rename to `feat/profile-identity` is NOT needed — the PR title carries the type).
- Commits: `type: short description`, no AI trailers, never `--no-verify`.
- Before every commit run the four gate commands and paste their tails in your report:
  `uv run --frozen pytest -q`, `uv run --frozen ruff check src tests`, `uv run --frozen ruff format --check src tests`, `uv run --group docs --frozen mkdocs build --strict` (this flag order; the order in AGENTS.md fails on the installed uv).
- Never hand-bump versions. Never touch `~/.config/lazy-harness`, `~/.claude-*`, `~/.codex-*` or run `lh deploy` — this plan changes the package only.
- Public repo: no personal names in `docs/`, code, commit messages. Examples use `personal`/`work` identities.
- `identity` token regex: `^[a-z0-9]+(-[a-z0-9]+)*$`. Suffix uses the same regex.
- Prefix map values: `claude-code`→`claude`, `codex`→`codex`, `copilot`→`copilot`.

## Review Focus

1. A profile **without** `identity` must behave byte-for-byte as today (source dir, sync output, deploy plan) — 102 test files depend on it; the existing suite passing is the evidence.
2. Two profiles with the same identity and same agent (`codex-personal`, `codex-personal-alt`) must produce one system-doc write, not a race or a duplicate error.
3. `lh run --agent codex` in a cwd matching no root must not launch a Claude profile.
4. `rename-profile` run twice, or run after rows already carry the new name, must not double-count or fail.
5. A `ProfileEntry` constructed directly in code (not loaded) with `identity=""` must resolve through the helper, never read `.identity` raw.

---

### Task 1: Prefix map in the registry, `identity` field, loader validation

**Files:**
- Modify: `src/lazy_harness/agents/registry.py` (add `PROFILE_PREFIXES`, `profile_prefix`)
- Modify: `src/lazy_harness/init/wizard.py` (delete `_CONFIG_DIR_PREFIXES`, import from registry)
- Modify: `src/lazy_harness/core/config.py` (`ProfileEntry.identity`, `_PROFILE_ENTRY_KEYS`, `_parse_profiles`, `_config_to_dict`, new `_validate_profile_identities`, call it in `load_config` after `cfg.agent` and `cfg.profiles` are parsed)
- Create: `src/lazy_harness/core/profile_identity.py` (`profile_identity`)
- Test: `tests/unit/agents/test_profile_prefixes.py`, `tests/unit/core/test_profile_identity_config.py` (check `tests/` layout first and follow it)

**Interfaces — Produces:**
- `agents.registry.PROFILE_PREFIXES: dict[str, str]`
- `agents.registry.profile_prefix(agent_name: str) -> str` — raises `KeyError`-free `ValueError(f"agent {agent_name!r} has no profile prefix")` when absent.
- `core.profile_identity.profile_identity(name: str, entry: ProfileEntry) -> str` → `entry.identity or name`.
- `ProfileEntry.identity: str = ""`.

Validation lives in `load_config` (not `_parse_profiles`) because the agent of a profile falls back to `[agent].type`, which `_parse_profiles` does not see. Resolve the agent name as `entry.agent or cfg.agent.type` — do NOT call `agent_for_profile` (it instantiates adapters). Import `profile_prefix` locally inside the validator, matching `_validate_root_defaults`' local-import pattern, to avoid a cycle.

- [ ] **Step 1: failing tests**

```python
# test_profile_prefixes.py
from lazy_harness.agents.registry import PROFILE_PREFIXES, _AGENTS, profile_prefix
import pytest

def test_every_registered_agent_has_a_prefix():
    assert set(PROFILE_PREFIXES) == set(_AGENTS)

def test_prefixes_are_unique():
    assert len(set(PROFILE_PREFIXES.values())) == len(PROFILE_PREFIXES)

def test_claude_code_prefix_is_claude():
    assert profile_prefix("claude-code") == "claude"

def test_unknown_agent_is_refused():
    with pytest.raises(ValueError, match="'nope' has no profile prefix"):
        profile_prefix("nope")
```

```python
# test_profile_identity_config.py — write TOML to tmp_path, call load_config
BASE = '[agent]\ntype = "claude-code"\n[profiles]\ndefault = "{default}"\n'

def _load(tmp_path, body, default="claude-personal"):
    p = tmp_path / "config.toml"
    p.write_text(BASE.format(default=default) + body)
    return load_config(p)

def test_profile_without_identity_is_unvalidated(tmp_path):
    cfg = _load(tmp_path, '[profiles.p1]\nconfig_dir = "~/.x"\n', default="p1")
    assert cfg.profiles.items["p1"].identity == ""
    assert profile_identity("p1", cfg.profiles.items["p1"]) == "p1"

def test_identity_with_matching_name_loads(tmp_path):
    cfg = _load(tmp_path, '[profiles.claude-personal]\nidentity = "personal"\nconfig_dir = "~/.claude-personal"\n')
    assert profile_identity("claude-personal", cfg.profiles.items["claude-personal"]) == "personal"

def test_identity_with_suffix_loads(tmp_path):
    _load(tmp_path, '[profiles.codex-personal-alt]\nidentity = "personal"\nagent = "codex"\nconfig_dir = "~/.codex-personal-alt"\n', default="codex-personal-alt")

def test_name_not_matching_prefix_is_refused(tmp_path):
    with pytest.raises(ConfigError, match=r"\[profiles\.personal\].*claude-personal"):
        _load(tmp_path, '[profiles.personal]\nidentity = "personal"\nconfig_dir = "~/.x"\n', default="personal")

def test_wrong_agent_prefix_is_refused(tmp_path):
    with pytest.raises(ConfigError, match=r"\[profiles\.claude-personal\].*codex-personal"):
        _load(tmp_path, '[profiles.claude-personal]\nidentity = "personal"\nagent = "codex"\nconfig_dir = "~/.x"\n')

def test_empty_suffix_is_refused(tmp_path):
    with pytest.raises(ConfigError, match=r"\[profiles\.claude-personal-\]"):
        _load(tmp_path, '[profiles.claude-personal-]\nidentity = "personal"\nconfig_dir = "~/.x"\n', default="claude-personal-")

@pytest.mark.parametrize("bad", ["Personal", "_common", "a_b", "-x", "x-", ""])
def test_invalid_identity_token_is_refused(tmp_path, bad):
    with pytest.raises(ConfigError, match=r"\[profiles\.claude-x\]\.identity"):
        _load(tmp_path, f'[profiles.claude-x]\nidentity = "{bad}"\nconfig_dir = "~/.x"\n', default="claude-x")

def test_identity_round_trips(tmp_path):
    # save, load, save, load — new document and merge-on-existing both
    cfg = _load(tmp_path, '[profiles.claude-personal]\nidentity = "personal"\nconfig_dir = "~/.claude-personal"\n')
    out = tmp_path / "out.toml"
    save_config(cfg, out); cfg2 = load_config(out); save_config(cfg2, out); cfg3 = load_config(out)
    assert cfg3.profiles.items["claude-personal"].identity == "personal"

def test_absent_identity_round_trips_absent(tmp_path):
    cfg = _load(tmp_path, '[profiles.p1]\nconfig_dir = "~/.x"\n', default="p1")
    out = tmp_path / "out.toml"
    save_config(cfg, out)
    assert "identity" not in out.read_text()
```

Note on `identity = ""` in the parametrize: an explicitly empty string is present-but-invalid, not absent. Distinguish with `"identity" in value` in `_parse_profiles`; store a sentinel-free representation by validating in `_parse_profiles` that a present key is non-empty and matches the regex (that check needs no agent), and do the name check in `load_config`.

Serialization: `_config_to_dict` emits `identity` only when non-empty, so a config without it round-trips without gaining the key (Review Focus 1).

- [ ] **Step 2:** run `uv run --frozen pytest tests/.../test_profile_prefixes.py tests/.../test_profile_identity_config.py -q` — expect ImportError/failures.
- [ ] **Step 3:** implement. Wizard: `from lazy_harness.agents.registry import PROFILE_PREFIXES` and `prefix = PROFILE_PREFIXES.get(agent, agent)`; keep its existing comment's *why*, moved to the registry map.
- [ ] **Step 4:** targeted tests pass; full gate passes.
- [ ] **Step 5:** delete the name check from the validator, confirm `test_name_not_matching_prefix_is_refused` fails, restore it by hand (not `git checkout`). Commit `feat: add optional profile identity with validated names`.

---

### Task 2: `profile_source_dir` and every call site

**Files:**
- Modify: `src/lazy_harness/core/profile_identity.py` (add `profile_source_dir`)
- Modify: `src/lazy_harness/deploy/engine.py:~269` (`src_dir = profiles_src / name`)
- Modify: `src/lazy_harness/deploy/snapshot.py:~122` (`src_dir = profiles_src / name`)
- Modify: `src/lazy_harness/core/artifact_version.py:~164` (`doc = profiles_dir / profile / rel`)
- Modify: `src/lazy_harness/cli/profile_cmd.py:~386` (`profile_dir = config_dir() / "profiles" / name`) and any other join in that file (`grep -n '"profiles"' src/lazy_harness/cli/profile_cmd.py`)
- Test: `tests/unit/core/test_profile_source_dir.py`, plus one test per call site in its existing test module

**Interfaces — Produces:** `profile_source_dir(cfg: Config, name: str, profiles_root: Path | None = None) -> Path` → `(profiles_root or config_dir() / "profiles") / profile_identity(name, cfg.profiles.items[name])`. Unknown `name` (not in config) → `profiles_root / name` (today's behaviour for `lh profile migrate` on a directory the config no longer names).

- [ ] **Step 1: failing tests**

```python
def test_source_dir_is_keyed_by_identity(tmp_path):
    cfg = _cfg(claude_personal=dict(identity="personal"), codex_personal=dict(identity="personal", agent="codex"))
    assert profile_source_dir(cfg, "claude-personal", tmp_path) == tmp_path / "personal"
    assert profile_source_dir(cfg, "codex-personal", tmp_path) == tmp_path / "personal"

def test_source_dir_without_identity_is_the_name(tmp_path):
    cfg = _cfg(p1=dict())
    assert profile_source_dir(cfg, "p1", tmp_path) == tmp_path / "p1"

def test_no_stray_profile_joins_in_src():
    # Any `"profiles" / <var>` or `profiles_src / name`-style join outside the helper is a regression.
    import re, pathlib
    src = pathlib.Path(lazy_harness.__file__).parent
    pattern = re.compile(r'(profiles_src|profiles_dir|"profiles")\s*/\s*(name|profile|entry\.name)\b')
    hits = [f"{p}:{i}" for p in src.rglob("*.py") if p.name != "profile_identity.py"
            for i, line in enumerate(p.read_text().splitlines(), 1) if pattern.search(line)]
    assert hits == []
```

For each call site add a test where two profiles share an identity and assert the call site reads `profiles/<identity>/` (e.g. the deploy link plan for `codex-personal` links from `personal/`). Follow each module's existing test fixtures.

- [ ] **Step 2:** run, watch the grep test list the 4+ current hits and the call-site tests fail.
- [ ] **Step 3:** route each site through `profile_source_dir`. `deploy/ledger.py` takes `profile_src` from its caller — verify its callers now pass the identity dir; do not change the ledger itself.
- [ ] **Step 4:** gate passes. Mutation check: revert one call site by hand, watch its test fail, restore.
- [ ] **Step 5:** commit `refactor: resolve profile source dirs through identity`.

---

### Task 3: `sync_profiles` is profile-driven

**Files:**
- Modify: `src/lazy_harness/core/sync_agent_md.py:141-291`
- Modify: `src/lazy_harness/hooks/builtins/post_tool_use_sync_system_doc.py` (only if its `only=` / tree detection assumes dir == profile)
- Test: the existing `sync_agent_md` test module

**Behaviour:**
- `cfg is None` → unchanged directory-driven path (keeps every current caller and test green).
- `cfg` given → iterate `cfg.profiles.items`; for each, `(profile_source_dir(cfg, name, profiles_dir), agent_for_profile(cfg, name))`; dedupe on `(source_dir, system_doc_relpath)`; generate each pair once. `only=<profile>` selects that profile's pair. Directories under `profiles_dir` (not `_`-prefixed) that no profile resolves to → one `SyncResult(profile=<dir name>, action="orphaned", path=<dir>)`, never written.
- `SyncResult.action` gains `"orphaned"`; grep every consumer of `.action` (`grep -rn '\.action' src/lazy_harness`) and make each render or ignore it explicitly.

- [ ] **Step 1: failing tests**
  - two agents, one identity → `personal/CLAUDE.md` and `personal/AGENTS.md` both written;
  - `codex-personal` + `codex-personal-alt` → exactly one `written` result for `personal/AGENTS.md`;
  - leftover `profiles/old/` with `head.md` → `orphaned`, file mtime unchanged;
  - `only="codex-personal"` → only `AGENTS.md` touched;
  - `cfg=None` → existing behaviour (existing tests cover it; confirm they still run this path).
- [ ] **Step 2–4:** red, implement, green, gate.
- [ ] **Step 5:** commit `feat: sync system docs per profile identity`.

---

### Task 4: `--agent` on `lh run` and `lh exec`

**Files:**
- Modify: `src/lazy_harness/core/profiles.py` (`resolve_profile_with_source(cfg, cwd=None, override=None, agent=None)`)
- Modify: `src/lazy_harness/agents/launch.py` (`resolve_launch(..., agent: str | None = None)` passes it through)
- Modify: `src/lazy_harness/cli/run_cmd.py`, `src/lazy_harness/cli/exec_cmd.py` (`--agent` option, help: "Only consider profiles of this agent (claude, codex, copilot)")
- Test: existing resolver and run/exec test modules

**Semantics (`agent` is a prefix, e.g. `"codex"`):**
- Unknown prefix (not in `PROFILE_PREFIXES.values()`) → `ProfileError("unknown agent 'x'; expected one of claude, codex, copilot")`.
- `override` + `agent`: override's agent prefix must equal `agent`, else `ProfileError` naming both.
- Filter candidates to profiles whose `profile_prefix(entry.agent or cfg.agent.type) == agent` **before** the root loop; rest of root logic unchanged.
- No root match → `profiles.default` if it passes the filter; else the single filtered profile if exactly one; else `ProfileError(f"no {agent} profile claims {cwd}; pass --profile")`.

- [ ] **Step 1: failing tests** — shared root with `root_default` on the claude profile: `agent=None` → claude, `agent="codex"` → codex; `agent="codex"` from `/tmp`-like cwd with one codex profile → codex (never the claude default); two codex profiles, no root match, default is claude → error naming `codex`; override/agent conflict; unknown prefix. CLI: `lh run --agent codex --dry-run` prints `CODEX_HOME`; **plus a parameter-less smoke test** `lh run --dry-run` unchanged.
- [ ] **Step 2–4:** red, implement, green, gate.
- [ ] **Step 5:** probe and record in the PR body: `lh run --profile X --bypass=enable --bypass=activate --dry-run` — which value wins? (Needed by the dotfiles aliases.)
- [ ] **Step 6:** commit `feat: filter profile resolution by agent`.

---

### Task 5: `lh metrics rename-profile`

**Files:**
- Modify: `src/lazy_harness/monitoring/db.py` (method `rename_profile(old: str, new: str) -> dict[str, int]`)
- Modify: `src/lazy_harness/cli/metrics_cmd.py` (subcommand)
- Test: existing db and metrics_cmd test modules

**Behaviour:** one transaction; `UPDATE <t> SET profile=? WHERE profile=?` for `session_stats`, `loop_events`, `launches`; returns per-table rowcount; CLI prints `table: N` lines. Refuses (exit 1) when `new` is not in `cfg.profiles.items`, or `old == new`. Before writing, check the table list against `sqlite_master` for every table with a `profile` column and fail the test if a new one appears that the method does not cover (derive the list, assert it equals the declared three).

- [ ] **Step 1: failing tests** — rows in all three tables move; second run returns zeros; pre-existing `new` rows untouched and counted once; unknown target refused; `old == new` refused; completeness test over `PRAGMA table_info`.
- [ ] **Step 2–4:** red, implement, green, gate.
- [ ] **Step 5:** commit `feat: add lh metrics rename-profile`.

---

### Task 6: wizard naming and doctor warning

**Files:**
- Modify: `src/lazy_harness/init/wizard.py`, `src/lazy_harness/cli/init_cmd.py` (prompt `Identity` default `personal`; profile name derived as `{prefix}-{identity}`; `config_dir = ~/.{profile_name}`; write `identity`)
- Modify: `src/lazy_harness/cli/doctor_cmd.py` (warning when some profiles declare `identity` and others do not; names the ones without)
- Test: existing wizard/init and doctor test modules

- [ ] **Step 1: failing tests** — wizard with agent codex, identity `work` writes `[profiles.codex-work]`, `identity = "work"`, `config_dir = "~/.codex-work"`, `default = "codex-work"`, and the written file loads; doctor mixed config → warning naming the profile without identity, exit code unchanged (warning, not failure); uniform config → no warning.
- [ ] **Step 2–4:** red, implement, green, gate.
- [ ] **Step 5:** commit `feat: name new profiles by agent and identity`.

---

### Task 7: public docs

**Files:** `docs/reference/cli.md` (`--agent`, `metrics rename-profile`), the config reference page that documents `[profiles.*]` keys (`grep -rln "root_default" docs/`), and the profiles concept page if one exists. Examples use `personal`/`work`.

- [ ] **Step 1:** grep every identifier the new prose names against `src/` (gate: prose that names a mechanism). Include the output in the report.
- [ ] **Step 2:** mark ADR-068 `accepted` with an `**Implemented:**` line, update its README row status, set the spec `Status: accepted`.
- [ ] **Step 3:** gate; commit `docs: document profile identity and --agent`.

---

### Task 8: PR

- [ ] `git push -u origin docs/profile-identity`; `gh pr create` titled `feat: profiles are identity × agent (ADR-068)`, body: summary, the Task 4 step 5 probe result, gate tails. Do not merge.
- [ ] Report: PR URL, commit list, gate output, anything deviating from this plan with the reason.

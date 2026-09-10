# Hook Import-Guard Population — Design and Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the ADR-006 import-safety gap on the eight builtin hooks the guard suite never looked at, then make the suite's population derive from the source tree so a new hook cannot be added without one.

**Architecture:** `tests/unit/hooks/builtins/test_import_safety.py` parametrises over a hardcoded `GUARDED_HOOKS` list of six names. There are fourteen builtin hooks. The three tasks that fix real crashes come first, so the population guard lands on a tree that is already clean; the last two tasks replace the hardcoded list with a glob over `BUILTINS_DIR` plus a completeness assertion that fails when a hook has no test case.

**Tech Stack:** Python 3.11+, `pytest`, `subprocess` with a poisoned `PYTHONPATH`.

**Spec:** this document. Sections 1–4 are the design; section 7 onward is the plan.

## Global Constraints

- Python 3.11+, strict type hints. No `Any` unless unavoidable.
- Strict TDD: no production code without a failing test that exercises it first. Every task below runs the test and observes the failure before the fix.
- **Hooks handle every exception explicitly and exit 0.** ADR-006. `pre_tool_use_security` is the one documented divergence — it exits 2 to block — and that divergence is preserved, not widened.
- **A test that passes with and without the thing it claims to cover, covers nothing.** Each task proves the new case fails first. Restore by hand-editing, never `git checkout` — that would revert the uncommitted implementation too.
- Conventional commits, no AI trailers, no `--no-verify`.
- Pre-commit gate is all three: `uv run pytest`, `uv run ruff check src tests`, `uv run --group docs mkdocs build --strict`.
- Worktree flow — this touches `src/**` and `tests/**`, so the doc short-path does not apply to the implementation.

---

## 1. Problem

`tests/unit/hooks/builtins/test_import_safety.py:21` enumerates the hooks under the ADR-006 import-safety contract by hand:

```python
GUARDED_HOOKS = [
    "compound_loop",
    "context_inject",
    "pre_compact",
    "session_end",
    "session_export",
    "user_prompt_goal",
]
```

`src/lazy_harness/hooks/builtins/` holds fourteen hooks (fifteen files, minus `_shared.py`, which is a library and not invoked as a script). Eight are absent from the list: `engram_persist`, `herdr_context_gauge`, `post_tool_use_ansible_lint`, `post_tool_use_format`, `post_tool_use_sync_claude`, `pre_tool_use_memory_size`, `pre_tool_use_read_size`, `pre_tool_use_security`.

The list is not a scoping decision — nothing in the file says these eight are exempt. It is the population the suite happened to start with, and it has not tracked the tree since.

## 2. Evidence

Probe run 2026-09-09 from a clean `main` at `5d09907`. Every hook invoked as a bare script with a `PYTHONPATH` whose `lazy_harness/__init__.py` raises `ImportError`, stdin `{}`:

```
compound_loop                  rc=0 traceback=0
context_inject                 rc=0 traceback=0
engram_persist                 rc=0 traceback=0
herdr_context_gauge            rc=1 traceback=1   ← unguarded
post_tool_use_ansible_lint     rc=0 traceback=0   ← false green, exits before the import
post_tool_use_format           rc=0 traceback=0   ← false green, exits before the import
post_tool_use_sync_claude      rc=1 traceback=1   ← unguarded
pre_compact                    rc=0 traceback=0
pre_tool_use_memory_size       rc=0 traceback=0   ← false green, exits before the import
pre_tool_use_read_size         rc=0 traceback=0   ← false green, exits before the import
pre_tool_use_security          rc=1 traceback=1   ← unguarded
session_end                    rc=0 traceback=0
session_export                 rc=0 traceback=0
user_prompt_goal               rc=0 traceback=0
```

Reproduce:

```bash
S=$(mktemp -d); mkdir -p "$S/poison/lazy_harness" "$S/home" "$S/cwd"
echo 'raise ImportError("simulated broken install")' > "$S/poison/lazy_harness/__init__.py"
for f in src/lazy_harness/hooks/builtins/*.py; do
  n=$(basename "$f" .py)
  case "$n" in __init__|_shared) continue;; esac
  out=$(cd "$S/cwd" && PYTHONPATH=$S/poison HOME=$S/home CLAUDE_CONFIG_DIR=$S/home/claude \
        python3 "$PWD/$f" <<< '{}' 2>&1); rc=$?
  printf "%-30s rc=%s traceback=%s\n" "$n" "$rc" "$(echo "$out" | grep -c Traceback)"
done
```

### 2.1 The three crashes

Each is a single top-level `lazy_harness` import used in exactly one place, with no guard around it:

| Hook | Import | Used at | Degradation once guarded |
|---|---|---|---|
| `pre_tool_use_security:20` | `from lazy_harness.core.paths import config_file` | `_load_allowlist()` line 227 | Empty allowlist — the hook keeps blocking |
| `post_tool_use_sync_claude:18` | `from lazy_harness.core.sync_agent_md import sync_profiles` | `main()` line 78 | Sync skipped, exit 0 |
| `herdr_context_gauge:31` | `from lazy_harness.hooks.builtins._shared import transcript_from_payload` | `_tokens_of()` line 154 | `tokens=None`, the gauge path `main()` already handles |

`pre_tool_use_security` is the one that matters. Its rules are pure `re` patterns held in the module itself — they need nothing from `lazy_harness`. Only the *allowlist* does, and `_load_allowlist()` already documents the right answer:

```python
def _load_allowlist() -> list[str]:
    """...
    Returns empty list on any failure (missing file, malformed TOML, missing
    section). Empty list means stricter blocking — fail-safe by design.
    """
```

Today a broken install does not reach that fail-safe. The module-level import raises first, the process dies at exit 1, and Claude Code treats a non-2 exit from `PreToolUse` as a non-blocking error: the tool call proceeds. **A broken install silently turns destructive-command blocking off** — and it fails open at exactly the moment the environment is already known to be broken.

Two of the three fixes are a one-line move, because the destination `try` already exists and already catches `Exception` (which covers `ImportError`): `post_tool_use_sync_claude` has one at line 64, `pre_tool_use_security` has one at line 226.

### 2.2 The four false greens

`post_tool_use_ansible_lint`, `post_tool_use_format`, `pre_tool_use_memory_size` and `pre_tool_use_read_size` exit 0 under the probe, but not because they are guarded. They defer their `lazy_harness` imports into a logging helper that a `{}` payload never reaches:

```python
def _log_warning(file_path: str, breach: str) -> None:
    """Record the warning so its frequency is auditable after the fact."""
    try:
        from lazy_harness.agents.registry import get_agent
        ...
```

The pattern is sound. It is simply unproven — which is the shape the existing file already warns about at line 30:

> *A hook fed `{}` may return before importing anything, which would make this suite pass without exercising the guard at all.*

Adding them with a `{}` payload would grow the population without growing the coverage. Each needs a payload, and two also need a filesystem fixture and a stripped `PATH`, to drive execution into the helper that holds the import.

## 3. Decision

Four changes, in this order:

1. Guard the three crashing hooks, one task each, smallest degradation that preserves the hook's own contract.
2. Add the five remaining hooks to the suite with cases that actually reach their imports.
3. Replace `GUARDED_HOOKS` with a glob over `BUILTINS_DIR`, and add a completeness test that fails when a hook in the tree has no case.

The ordering is deliberate. The population guard is a ratchet, and a ratchet is installed on a clean tree — otherwise it lands red and the first instinct is to widen the exemption set to get to green.

## 4. Why derive instead of extending the list

Extending `GUARDED_HOOKS` to fourteen names fixes today and not tomorrow: the next hook is added the same way the last eight were, and nothing fails. Deriving from the tree makes the test population a function of the source, so the only way to add an untested hook is to write down an exemption and a reason for it.

This is the technique from `Gentleman-Programming/gentle-ai`'s `internal/agents/adapter_forbidden_construction_guard_test.go`, which walks its adapter file set rather than naming the files it checks. The header there states the intent plainly: the design's own audit found the tree clean, and the test exists so a future change *cannot silently* reintroduce what the audit ruled out.

It is also this repo's own rule applied to itself:

> *Behavioural automation ships with kill criteria... A documented practice without enforcement runs around 60% non-compliance.*

ADR-006 is a documented practice. Its enforcement covered 6 of 14.

## 5. Out of scope

- **Widening ADR-006's contract.** `pre_tool_use_security` exits 2 on block by design, recorded in its own docstring and in `specs/designs/2026-04-17-security-hooks-cluster-design.md`. Task 1 preserves that; it does not turn the hook into an exit-0-always hook.
- **Any other guard-population audit.** The same "hardcoded list vs. the tree" shape may exist elsewhere (`_BUILTIN_HOOKS` registration, the selftest checks, the docs coherence suites). Worth a sweep, not in this plan.
- **A `.guard-population-baseline.txt` ratchet file.** gentle-ai tracks baselines as committed artifacts. Here the completeness test is the ratchet and a baseline file would be a second source of truth. Revisit only if exemptions ever become numerous.
- **Refactoring the four deferred-import hooks** to the top-level-import-plus-guard shape used by `compound_loop`. Both shapes satisfy the contract. Changing them is out-of-task refactoring.

## 6. Verification

After Task 5, the probe in section 2 must print `rc=0 traceback=0` for all fourteen. Re-run it; do not infer the result from a green pytest.

Then prove the population guard is not inert: create `src/lazy_harness/hooks/builtins/zz_probe.py` containing only `import sys; from lazy_harness.core.paths import config_file; sys.exit(0)`, run the suite, confirm the completeness test fails naming `zz_probe`, and delete the file by hand.

---

## 7. Tasks

### Task 1: `pre_tool_use_security` survives a broken install and still blocks

**Files:**
- Modify: `src/lazy_harness/hooks/builtins/pre_tool_use_security.py:20` (remove), `:226-229` (add)
- Test: `tests/unit/hooks/builtins/test_import_safety.py`

**Interfaces:**
- Consumes: `GUARDED_HOOKS`, `_PAYLOADS`, `test_hook_exits_zero_when_lazy_harness_not_importable` — all existing in the test module.
- Produces: nothing later tasks import. Task 5 re-reads `GUARDED_HOOKS`.

- [ ] **Step 1: Write the failing tests**

Add `"pre_tool_use_security"` to `GUARDED_HOOKS` in `tests/unit/hooks/builtins/test_import_safety.py:21`, keeping the list alphabetical. Then append this second test to the same file — the parametrised one proves the hook does not crash, this one proves it still does its job:

```python
def test_security_hook_still_blocks_when_lazy_harness_not_importable(tmp_path: Path) -> None:
    """The block rules are plain `re` patterns in the module itself. Only the
    allowlist needs the package, and an absent allowlist means stricter
    blocking — so a broken install must not turn the hook into a no-op."""
    poison = tmp_path / "poison"
    (poison / "lazy_harness").mkdir(parents=True)
    (poison / "lazy_harness" / "__init__.py").write_text(
        'raise ImportError("simulated broken install")\n'
    )

    env = os.environ.copy()
    env["PYTHONPATH"] = str(poison)
    env["HOME"] = str(tmp_path / "home")
    env["CLAUDE_CONFIG_DIR"] = str(tmp_path / "claude")

    result = subprocess.run(
        [sys.executable, str(BUILTINS_DIR / "pre_tool_use_security.py")],
        input='{"tool_name": "Bash", "tool_input": {"command": "rm -rf /"}}',
        capture_output=True,
        text=True,
        env=env,
        cwd=str(tmp_path),
    )

    assert result.returncode == 2, f"security hook failed open: rc={result.returncode}"
    assert "Traceback" not in result.stderr
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/unit/hooks/builtins/test_import_safety.py -v -k security`

Expected: both FAIL. The parametrised case fails on `assert result.returncode == 0` with the `ImportError: simulated broken install` traceback in `result.stderr`; the blocking case fails on `rc=1` instead of `2`.

Confirm the traceback names `pre_tool_use_security.py", line 20, in <module>`. If it names any other line, the import moved since this plan was written — stop and re-read the file.

- [ ] **Step 3: Move the import inside the existing guard**

Delete line 20 of `src/lazy_harness/hooks/builtins/pre_tool_use_security.py`:

```python
from lazy_harness.core.paths import config_file
```

`Path` stays imported at the top — other code uses it. Then in `_load_allowlist`, move the import inside the `try` that already stands there:

```python
    try:
        from lazy_harness.core.paths import config_file

        cfg_path: Path = config_file()
    except Exception:
        return []
```

`except Exception` already covers `ImportError`; no new handler is needed.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/unit/hooks/builtins/ -v`

Expected: PASS, including the pre-existing `pre_tool_use_security` suite.

Then confirm the fix is what made the difference — hand-edit line 20 back, re-run, watch both fail, hand-edit it out again. Do not use `git checkout`.

- [ ] **Step 5: Full gate and commit**

```bash
uv run pytest
uv run ruff check src tests
uv run --group docs mkdocs build --strict
git add src/lazy_harness/hooks/builtins/pre_tool_use_security.py tests/unit/hooks/builtins/test_import_safety.py
git commit -m "fix: keep the security hook blocking when lazy_harness is not importable"
```

---

### Task 2: `post_tool_use_sync_claude` no-ops on a broken install

**Files:**
- Modify: `src/lazy_harness/hooks/builtins/post_tool_use_sync_claude.py:18` (remove), `:64-68` (add)
- Test: `tests/unit/hooks/builtins/test_import_safety.py:21`

**Interfaces:**
- Consumes: `GUARDED_HOOKS` from Task 1's edit of the same list.
- Produces: nothing.

- [ ] **Step 1: Write the failing test**

Add `"post_tool_use_sync_claude"` to `GUARDED_HOOKS`, alphabetical. No `_PAYLOADS` entry — the import is at module level, so `{}` reaches it.

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/unit/hooks/builtins/test_import_safety.py -v -k sync_claude`

Expected: FAIL, `rc=1`, traceback naming `post_tool_use_sync_claude.py", line 18, in <module>`.

- [ ] **Step 3: Move the import into the existing try block**

Delete line 18:

```python
from lazy_harness.core.sync_agent_md import sync_profiles
```

and add it to the import group already inside `main()`'s `try` at line 64, keeping the group alphabetical:

```python
    try:
        from lazy_harness.agents.registry import get_agent
        from lazy_harness.core.config import ConfigError, load_config
        from lazy_harness.core.paths import config_file
        from lazy_harness.core.sync_agent_md import sync_profiles
```

The enclosing `except Exception: pass` at the end of that block already produces the right degradation: the sync is skipped, `sys.exit(0)` runs.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/unit/hooks/builtins/ tests/unit/test_sync_claude.py -v`

Expected: PASS. If `tests/unit/test_sync_claude.py` does not exist, run `uv run pytest -k sync` instead and note which suites cover the hook.

Prove the coverage: hand-edit the import back to line 18, re-run, watch it fail, hand-edit it out.

- [ ] **Step 5: Full gate and commit**

```bash
uv run pytest
uv run ruff check src tests
uv run --group docs mkdocs build --strict
git add src/lazy_harness/hooks/builtins/post_tool_use_sync_claude.py tests/unit/hooks/builtins/test_import_safety.py
git commit -m "fix: guard post_tool_use_sync_claude against an unimportable package"
```

---

### Task 3: `herdr_context_gauge` no-ops on a broken install

**Files:**
- Modify: `src/lazy_harness/hooks/builtins/herdr_context_gauge.py:31` (remove), `:153-156` (add)
- Test: `tests/unit/hooks/builtins/test_import_safety.py:21,33`

**Interfaces:**
- Consumes: `GUARDED_HOOKS`, `_PAYLOADS`.
- Produces: nothing.

- [ ] **Step 1: Write the failing test**

Add `"herdr_context_gauge"` to `GUARDED_HOOKS`, alphabetical. This hook exits at line 159 unless `HERDR_ENV=1` and `HERDR_PANE_ID` are set, so the parametrised test's fixed env is not enough on its own — but the failing import is at module level and fires before `main()` is ever called, so `{}` still reaches it. No `_PAYLOADS` entry.

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/unit/hooks/builtins/test_import_safety.py -v -k herdr`

Expected: FAIL, `rc=1`, traceback naming `herdr_context_gauge.py", line 31, in <module>`.

- [ ] **Step 3: Defer the import into its only caller**

Delete line 31:

```python
from lazy_harness.hooks.builtins._shared import transcript_from_payload
```

and rewrite `_tokens_of` at line 153:

```python
def _tokens_of(payload: dict[str, object]) -> int | None:
    try:
        from lazy_harness.hooks.builtins._shared import transcript_from_payload
    except ImportError:
        # Broken/uninstalled package: no gauge rather than a crashed hook.
        return None

    transcript = transcript_from_payload(payload)
    return None if transcript is None else context_tokens(transcript)
```

`main()` already treats `tokens is None` as a valid state — it is the `SessionEnd` path — so no other change is needed.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/unit/hooks/builtins/ -v -k "herdr or import_safety"`

Expected: PASS.

Prove the coverage: hand-edit the import back to line 31, re-run, watch it fail, hand-edit it out.

- [ ] **Step 5: Full gate and commit**

```bash
uv run pytest
uv run ruff check src tests
uv run --group docs mkdocs build --strict
git add src/lazy_harness/hooks/builtins/herdr_context_gauge.py tests/unit/hooks/builtins/test_import_safety.py
git commit -m "fix: guard herdr_context_gauge against an unimportable package"
```

---

### Task 4: Cases that actually reach the deferred imports

**Files:**
- Modify: `tests/unit/hooks/builtins/test_import_safety.py` (replace `_PAYLOADS` with `_CASES`, add five hooks)

**Interfaces:**
- Consumes: `BUILTINS_DIR`, `GUARDED_HOOKS` as left by Task 3.
- Produces: `Case` (frozen dataclass, fields `payload: str`, `setup: Callable[[Path], None] | None`, `env: dict[str, str]`) and `_CASES: dict[str, Case]`. Task 5 reads `_CASES` by name.

No production code changes in this task. The five hooks added here already satisfy the contract — the task exists because nothing proves it.

- [ ] **Step 1: Replace `_PAYLOADS` with `_CASES`**

Replace lines 30–35 of `tests/unit/hooks/builtins/test_import_safety.py`:

```python
@dataclass(frozen=True)
class Case:
    """What it takes to drive one hook past its early exits and into the
    imports the guard has to cover. A hook fed `{}` may return before
    importing anything, which would make this suite pass without exercising
    the guard at all.

    `setup` runs against the test's `tmp_path` and returns nothing; anything
    it needs to name in `payload` is interpolated by the caller instead.
    `env` is merged over the poisoned base env.
    """

    payload: str = "{}"
    setup: Callable[[Path], None] | None = None
    env: dict[str, str] = field(default_factory=dict)


def _ansible_repo(root: Path) -> None:
    (root / "ansible.cfg").write_text("[defaults]\n")
    (root / "site.yml").write_text("- hosts: all\n")


def _big_file(root: Path) -> None:
    (root / "big.py").write_text("x = 1\n" * 600)


_CASES: dict[str, Case] = {
    "user_prompt_goal": Case(payload='{"session_id": "s1", "prompt": "fix db.py", "cwd": "."}'),
}
```

Add `from collections.abc import Callable` and `from dataclasses import dataclass, field` to the imports.

Then update the test body to read from `_CASES`:

```python
@pytest.mark.parametrize("hook_name", GUARDED_HOOKS)
def test_hook_exits_zero_when_lazy_harness_not_importable(tmp_path: Path, hook_name: str) -> None:
    case = _CASES.get(hook_name, Case())
    if case.setup is not None:
        case.setup(tmp_path)

    poison = tmp_path / "poison"
    (poison / "lazy_harness").mkdir(parents=True)
    (poison / "lazy_harness" / "__init__.py").write_text(
        'raise ImportError("simulated broken install")\n'
    )

    env = os.environ.copy()
    env["PYTHONPATH"] = str(poison)
    env["HOME"] = str(tmp_path / "home")
    env["CLAUDE_CONFIG_DIR"] = str(tmp_path / "claude")
    env.update({k: v.format(tmp=tmp_path) for k, v in case.env.items()})

    result = subprocess.run(
        [sys.executable, str(BUILTINS_DIR / f"{hook_name}.py")],
        input=case.payload.format(tmp=tmp_path),
        capture_output=True,
        text=True,
        env=env,
        cwd=str(tmp_path),
    )

    assert result.returncode == 0, result.stderr
    assert "Traceback" not in result.stderr
```

Run `uv run pytest tests/unit/hooks/builtins/test_import_safety.py -v` — expected PASS, nine cases, no behaviour change yet.

- [ ] **Step 2: Add the five remaining hooks and watch the reach assertions**

Add all five names to `GUARDED_HOOKS` (alphabetical) and these entries to `_CASES`. `engram_persist` guards a module-level import and needs nothing; the other four need to reach a logging helper.

```python
_CASES: dict[str, Case] = {
    "user_prompt_goal": Case(payload='{"session_id": "s1", "prompt": "fix db.py", "cwd": "."}'),
    # Guarded at module level — `{}` reaches the import.
    "engram_persist": Case(),
    # `_log_unavailable` holds the import and only runs when ruff is missing.
    "post_tool_use_format": Case(
        payload='{{"tool_name": "Write", "tool_input": {{"file_path": "{tmp}/x.py"}}}}',
        env={"PATH": ""},
    ),
    # `_log_unavailable` needs an ansible.cfg root, an in-scope YAML, and no
    # ansible-lint on PATH. `site.yml` sits directly in the root, which
    # `_in_lint_scope` accepts (empty `dir_parts`).
    "post_tool_use_ansible_lint": Case(
        payload='{{"tool_name": "Write", "tool_input": {{"file_path": "{tmp}/site.yml"}}}}',
        setup=_ansible_repo,
        env={"PATH": ""},
    ),
    # `_log_warning` fires only on a breach. MAX_LINES is 200, so 250 breaches.
    # `Write` takes its projected text straight from `content`, so no file on
    # disk is needed — but `_is_memory_md_path` requires the /memory/ segment.
    "pre_tool_use_memory_size": Case(
        payload=(
            '{{"tool_name": "Write", "tool_input": {{'
            '"file_path": "{tmp}/memory/MEMORY.md", "content": "'
            + "line\\n" * 250
            + '"}}}}'
        ),
    ),
    # `_log_warning` fires only on a Read with no offset/limit over 500 lines.
    "pre_tool_use_read_size": Case(
        payload='{{"tool_name": "Read", "tool_input": {{"file_path": "{tmp}/big.py"}}}}',
        setup=_big_file,
    ),
}
```

Note the doubled braces: these strings pass through `str.format` for `{tmp}`, so every literal JSON brace is escaped.

- [ ] **Step 3: Prove each new case reaches its import**

A case that misses its helper passes for the wrong reason, which is precisely the false green this task exists to remove. Prove reach one hook at a time:

For each of `post_tool_use_format`, `post_tool_use_ansible_lint`, `pre_tool_use_memory_size`, `pre_tool_use_read_size`: hand-edit its logging helper's `try:` to `if True:` — removing the guard without removing the import — then run

```bash
uv run pytest tests/unit/hooks/builtins/test_import_safety.py -v -k <hook_name>
```

Expected: FAIL with the `ImportError` traceback. That is the proof the payload arrives at the import. Hand-edit the `try:` back and confirm PASS.

If a case passes with the guard removed, the payload never reached the helper — fix the payload, do not move on.

- [ ] **Step 4: Run the full suite**

Run: `uv run pytest tests/unit/hooks/builtins/ -v`

Expected: PASS, fourteen parametrised cases.

- [ ] **Step 5: Full gate and commit**

```bash
uv run pytest
uv run ruff check src tests
uv run --group docs mkdocs build --strict
git add tests/unit/hooks/builtins/test_import_safety.py
git commit -m "test: cover every builtin hook's import guard with a case that reaches it"
```

---

### Task 5: Derive the population from the tree

**Files:**
- Modify: `tests/unit/hooks/builtins/test_import_safety.py:20-28` (replace `GUARDED_HOOKS`)

**Interfaces:**
- Consumes: `BUILTINS_DIR`, `_CASES` from Task 4.
- Produces: `_NOT_A_HOOK`, `_EXEMPT`, `GUARDED_HOOKS` (derived), `test_every_builtin_hook_has_an_import_safety_case`.

- [ ] **Step 1: Write the failing test**

Add to `tests/unit/hooks/builtins/test_import_safety.py`, leaving `GUARDED_HOOKS` hardcoded for now:

```python
def test_every_builtin_hook_has_an_import_safety_case() -> None:
    """The suite's population is the tree, not a list someone remembered to
    extend. Eight hooks sat outside the hardcoded list for months; three of
    them crashed on a broken install and one was the security hook.

    A new hook belongs in `_CASES` with a payload that reaches its imports,
    or in `_EXEMPT` with a reason. There is no third option.
    """
    on_disk = {
        path.stem
        for path in BUILTINS_DIR.glob("*.py")
        if path.stem not in _NOT_A_HOOK
    }
    missing = sorted(on_disk - set(GUARDED_HOOKS) - set(_EXEMPT))
    assert not missing, (
        f"builtin hooks with no import-safety case: {missing}. "
        f"Add each to _CASES, or to _EXEMPT with a reason."
    )
```

and the two sets it reads:

```python
# Not invoked as hooks: `__init__` is package glue, `_shared` is the library
# the hooks import.
_NOT_A_HOOK = frozenset({"__init__", "_shared"})

# Hook -> why it is outside the ADR-006 import-safety contract. Empty by
# design: an entry here is a documented hole, not a shortcut to green.
_EXEMPT: dict[str, str] = {}
```

- [ ] **Step 2: Run the test to verify it fails**

Temporarily remove `"pre_tool_use_read_size"` from `GUARDED_HOOKS` by hand, then run:

Run: `uv run pytest tests/unit/hooks/builtins/test_import_safety.py::test_every_builtin_hook_has_an_import_safety_case -v`

Expected: FAIL with `builtin hooks with no import-safety case: ['pre_tool_use_read_size']`.

Hand-edit the name back and confirm PASS. Without this step the test is asserting over a list that trivially satisfies it, and would pass whether or not the logic is right.

- [ ] **Step 3: Replace the hardcoded list with the derivation**

Delete the fourteen-name `GUARDED_HOOKS` literal and derive it:

```python
GUARDED_HOOKS = sorted(
    path.stem
    for path in BUILTINS_DIR.glob("*.py")
    if path.stem not in _NOT_A_HOOK and path.stem not in _EXEMPT
)
```

`_NOT_A_HOOK`, `_EXEMPT` and `_CASES` must be defined above this line — module-level `parametrize` reads `GUARDED_HOOKS` at collection time.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/unit/hooks/builtins/ -v`

Expected: PASS, fourteen parametrised cases plus the completeness test.

Then run section 6's inert-guard check:

```bash
cat > src/lazy_harness/hooks/builtins/zz_probe.py <<'EOF'
import sys

from lazy_harness.core.paths import config_file

sys.exit(0)
EOF
uv run pytest tests/unit/hooks/builtins/test_import_safety.py -v
```

Expected: the completeness test FAILS naming `zz_probe`, and the parametrised case for `zz_probe` FAILS with a traceback. That is the ratchet working on both dimensions. Then:

```bash
rm src/lazy_harness/hooks/builtins/zz_probe.py
uv run pytest tests/unit/hooks/builtins/ -v
```

Expected: PASS.

- [ ] **Step 5: Re-run the section 2 probe**

A green pytest is not proof the deployed hooks degrade correctly — the suite and the probe resolve paths differently. Run the section 2 reproduce block again from the repo root.

Expected: `rc=0 traceback=0` on all fourteen lines. Paste the output into the PR body.

- [ ] **Step 6: Full gate and commit**

```bash
uv run pytest
uv run ruff check src tests
uv run --group docs mkdocs build --strict
git add tests/unit/hooks/builtins/test_import_safety.py
git commit -m "test: derive the import-safety population from the builtins tree"
```

---

## 8. Follow-ups (not this plan)

- **Sweep for the same shape elsewhere.** Any other place a test or a check enumerates by hand what the tree already knows: `_BUILTIN_HOOKS` registration vs. `config.toml [hooks.*]` entries, `src/lazy_harness/selftest/checks/`, the two `tests/docs/*_coherence.py` suites.
- **Signature checking on `runtime_checkable` Protocols.** `isinstance(adapter, HeadlessAgent)` at `src/lazy_harness/agents/launch.py:66` and `src/lazy_harness/cli/exec_cmd.py:372` checks that the methods *exist*, not that they have the right signature — verified 2026-09-09, a class whose `f(self)` bears no resemblance to the Protocol's `f(self, *, a: int, b: str)` still returns `True`. An adapter with a stale signature passes the assert and raises at call time, after `lh exec` has committed to the subprocess. A test over `_AGENTS` comparing `inspect.signature` against each Protocol member would close it.
- **A grep guard for the CLAUDE.md prohibitions that are textual.** The pre-rename name in the listed public-surface files, `--show-toplevel` in project-key derivation, `Co-Authored-By` in commit templates. Same technique, different subject.

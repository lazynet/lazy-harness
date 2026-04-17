# Security Hooks Cluster — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement two new hook builtins — `pre_tool_use_security` (blocks destructive / credential-exfiltration shell commands with an allowlist escape hatch) and `post_tool_use_format` (auto-runs `ruff format` on `.py` edits) — along with the small wiring changes in `loader.py`, `claude_code.py`, `wizard.py` and `doctor_cmd.py` needed to deploy them across profiles.

**Architecture:** Both hooks follow the existing builtin pattern: Python module under `src/lazy_harness/hooks/builtins/`, registered in `loader.py:_BUILTIN_HOOKS`, invoked by Claude Code via the JSON stdin/stdout subprocess contract (ADR-006). `pre_tool_use_security` deliberately deviates from the ADR by exiting `2` on block (Claude Code semantics) — the PostToolUse one keeps exit 0 always. Pattern modeling uses a frozen `BlockRule` dataclass with (category, compiled-regex, reason) — hardcoded, not TOML. Allowlist comes from user's `config.toml` under `[hooks.pre_tool_use].allow_patterns`.

**Tech Stack:** Python 3.11+, `uv` for dep management and script running, `pytest` + `pytest.parametrize` for table-driven unit tests, stdlib `tomllib` for config loading, `ruff` on global PATH (via `uv tool install ruff`) for formatting.

**Context for the implementer:** You do not need to read the full spec to work each task, but when something is unclear consult `specs/designs/2026-04-17-security-hooks-cluster-design.md`. **Every task follows strict TDD**: failing test first, watch it fail with the expected error, then minimal code to green, commit. This is repo rule (see `CLAUDE.md` non-negotiable #2). Do not batch. Do not skip the red step.

**Current state snapshot (so you don't need to guess):**

- `src/lazy_harness/hooks/builtins/` already contains `compound_loop.py`, `context_inject.py`, `pre_compact.py`, `session_end.py`, `session_export.py`. Follow the shape of `pre_compact.py` — it's the closest sibling: reads JSON stdin, writes structured result, handles missing keys defensively, logs to `$CLAUDE_CONFIG_DIR/logs/hooks.log`.
- `src/lazy_harness/hooks/loader.py:19` holds `_BUILTIN_HOOKS: dict[str, str]`. You will add two entries.
- `src/lazy_harness/agents/claude_code.py:59` holds `hook_event_map`. **It already includes `pre_tool_use` and `post_tool_use` entries.** What you need to change is the hardcoded `"matcher": ""` at line 77 — it must become `"Bash"` for PreToolUse and `"Edit|Write"` for PostToolUse. Other events keep `""`.
- `src/lazy_harness/init/wizard.py::run_wizard` writes the initial `config.toml`. There is **no `[hooks.*]` block** today. You will add the two blocks to the default output.
- `src/lazy_harness/cli/doctor_cmd.py` is where the `lh doctor` check lives. You will add a "ruff on PATH" check.
- Tests mirror `src/` at `tests/` one-to-one. Unit tests live under `tests/unit/`, integration under `tests/integration/`.
- There is no `tests/unit/hooks/` directory yet. You will create it.

**Conventions to follow:**

- Every new module under `src/lazy_harness/` gets a mirrored test file under `tests/`.
- Type hints everywhere. `Any` only at parser boundaries when unavoidable.
- All new files start with a docstring explaining their one responsibility.
- Commits are Conventional Commits. **No `Co-Authored-By` trailers. No `--no-verify`.** Use `feat:`, `test:`, `refactor:`, `chore:`, `docs:`.
- Run `uv run pytest -q` before every commit.
- Run `uv run ruff check src tests` before every commit.
- Run `uv run --group docs mkdocs build --strict` when you touched any doc/spec file.
- Never skip TDD. If you wrote code before the test, delete it.
- Work inside the worktree at `/Users/lazynet/repos/lazy/lazy-harness/.worktrees/security-hooks-cluster` on branch `feat/security-hooks-cluster`.

---

## File Structure (what you will create or modify)

**New files:**

```
src/lazy_harness/hooks/builtins/pre_tool_use_security.py
src/lazy_harness/hooks/builtins/post_tool_use_format.py
tests/unit/hooks/__init__.py
tests/unit/hooks/builtins/__init__.py
tests/unit/hooks/builtins/test_pre_tool_use_security.py
tests/unit/hooks/builtins/test_post_tool_use_format.py
tests/integration/test_security_hooks.py
```

**Modified files:**

```
src/lazy_harness/hooks/loader.py                    # Register two new builtins
src/lazy_harness/agents/claude_code.py              # Matcher per-event
src/lazy_harness/init/wizard.py                     # Default-on hooks blocks
src/lazy_harness/cli/doctor_cmd.py                  # ruff-on-PATH check
tests/unit/test_agents_claude_code.py               # (if exists) update for matcher
tests/unit/init/test_wizard.py                      # (if exists) assert hooks blocks
tests/unit/cli/test_doctor_cmd.py                   # (if exists) assert ruff check
specs/backlog.md                                    # Move cluster items to Done
```

**Note on test-file existence:** some of the "modified test files" above may or may not exist — the first step of each task that touches those is to check. If the test file does not exist, create it with the standard header and then add the test.

---

## Task 1: Scaffold `pre_tool_use_security` module with data types

**Files:**
- Create: `src/lazy_harness/hooks/builtins/pre_tool_use_security.py` (stub: types only)
- Create: `tests/unit/hooks/__init__.py` (empty)
- Create: `tests/unit/hooks/builtins/__init__.py` (empty)
- Create: `tests/unit/hooks/builtins/test_pre_tool_use_security.py`

- [ ] **Step 1.1: Write the failing test for `BlockRule` dataclass**

Create `tests/unit/hooks/builtins/test_pre_tool_use_security.py`:

```python
"""Unit tests for pre_tool_use_security hook."""

from __future__ import annotations

import re

import pytest


def test_block_rule_is_frozen_and_has_category_pattern_reason() -> None:
    from lazy_harness.hooks.builtins.pre_tool_use_security import BlockRule

    rule = BlockRule(
        category="filesystem",
        pattern=re.compile(r"\brm\b"),
        reason="demo",
    )
    assert rule.category == "filesystem"
    assert rule.pattern.search("rm foo") is not None
    assert rule.reason == "demo"
    with pytest.raises(Exception):
        rule.category = "sql"  # type: ignore[misc]  # frozen


def test_block_decision_holds_rule_and_matched_text() -> None:
    from lazy_harness.hooks.builtins.pre_tool_use_security import BlockDecision, BlockRule

    rule = BlockRule(category="filesystem", pattern=re.compile(r"rm"), reason="demo")
    decision = BlockDecision(rule=rule, matched_text="rm")
    assert decision.rule is rule
    assert decision.matched_text == "rm"
```

- [ ] **Step 1.2: Run the tests — expect ImportError**

Run: `uv run pytest tests/unit/hooks/builtins/test_pre_tool_use_security.py -v`

Expected: both tests FAIL with `ModuleNotFoundError: No module named 'lazy_harness.hooks.builtins.pre_tool_use_security'`.

- [ ] **Step 1.3: Create the stub module**

Create `src/lazy_harness/hooks/builtins/pre_tool_use_security.py`:

```python
"""PreToolUse security hook — blocks destructive / exfiltration commands.

Deliberately diverges from ADR-006's "exit 0 always" contract: exits 2 on
block per Claude Code PreToolUse semantics. See spec
`specs/designs/2026-04-17-security-hooks-cluster-design.md`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

Category = Literal["filesystem", "sql", "terraform", "credentials", "git"]


@dataclass(frozen=True)
class BlockRule:
    category: Category
    pattern: re.Pattern[str]
    reason: str


@dataclass(frozen=True)
class BlockDecision:
    rule: BlockRule
    matched_text: str
```

- [ ] **Step 1.4: Run the tests — expect PASS**

Run: `uv run pytest tests/unit/hooks/builtins/test_pre_tool_use_security.py -v`

Expected: both tests PASS.

- [ ] **Step 1.5: Run ruff**

Run: `uv run ruff check src tests`

Expected: `All checks passed!`

- [ ] **Step 1.6: Commit**

```bash
git add src/lazy_harness/hooks/builtins/pre_tool_use_security.py \
        tests/unit/hooks/__init__.py \
        tests/unit/hooks/builtins/__init__.py \
        tests/unit/hooks/builtins/test_pre_tool_use_security.py
git commit -m "feat(hooks): scaffold pre_tool_use_security types"
```

---

## Task 2: `BLOCK_RULES` tuple with all regex patterns

**Files:**
- Modify: `src/lazy_harness/hooks/builtins/pre_tool_use_security.py` (add `BLOCK_RULES`)
- Modify: `tests/unit/hooks/builtins/test_pre_tool_use_security.py` (add compilation test)

- [ ] **Step 2.1: Write the failing test for `BLOCK_RULES`**

Append to `tests/unit/hooks/builtins/test_pre_tool_use_security.py`:

```python
def test_block_rules_is_nonempty_tuple_of_block_rule() -> None:
    from lazy_harness.hooks.builtins.pre_tool_use_security import BLOCK_RULES, BlockRule

    assert isinstance(BLOCK_RULES, tuple)
    assert len(BLOCK_RULES) >= 10
    for rule in BLOCK_RULES:
        assert isinstance(rule, BlockRule)


def test_block_rules_cover_all_categories() -> None:
    from lazy_harness.hooks.builtins.pre_tool_use_security import BLOCK_RULES

    categories = {rule.category for rule in BLOCK_RULES}
    assert categories == {"filesystem", "sql", "terraform", "credentials", "git"}
```

- [ ] **Step 2.2: Run tests — expect 2 new FAIL (ImportError)**

Run: `uv run pytest tests/unit/hooks/builtins/test_pre_tool_use_security.py -v`

Expected: the 2 new tests FAIL with `ImportError` on `BLOCK_RULES`; the original 2 still PASS.

- [ ] **Step 2.3: Add `BLOCK_RULES` to the module**

Append to `src/lazy_harness/hooks/builtins/pre_tool_use_security.py`:

```python
BLOCK_RULES: tuple[BlockRule, ...] = (
    BlockRule(
        category="filesystem",
        pattern=re.compile(r"\brm\s+-[rRf]*[rRf][rRf]*\b.+"),
        reason="Recursive delete",
    ),
    BlockRule(
        category="filesystem",
        pattern=re.compile(r"\btruncate\s+(-s\s+\d+\s+)?[^\s-]"),
        reason="File truncation",
    ),
    BlockRule(
        category="git",
        pattern=re.compile(r"\bgit\s+push\s+(--force\b|-f\b)(?!.*--force-with-lease)"),
        reason="Force-push without lease",
    ),
    BlockRule(
        category="git",
        pattern=re.compile(r"\bgit\s+reset\s+--hard\b"),
        reason="Hard reset discards work",
    ),
    BlockRule(
        category="git",
        pattern=re.compile(
            r"\bgit\s+add\s+(-f\b|--force\b)[^|;&]*"
            r"(\.env|\.pem|\.key|\.p12|credentials|id_rsa|id_ed25519)"
        ),
        reason="Forced add of secret",
    ),
    BlockRule(
        category="sql",
        pattern=re.compile(r"\b(drop|truncate)\s+(table|database)\b", re.IGNORECASE),
        reason="SQL destruction",
    ),
    BlockRule(
        category="terraform",
        pattern=re.compile(r"\bterraform\s+destroy\b"),
        reason="Infra destruction",
    ),
    BlockRule(
        category="terraform",
        pattern=re.compile(r"\bterraform\s+apply\s+[^|;&]*-auto-approve\b"),
        reason="Skips plan review",
    ),
    BlockRule(
        category="terraform",
        pattern=re.compile(r"\bterraform\s+apply\s+[^|;&]*-replace=\S+"),
        reason="Forces resource recreation",
    ),
    BlockRule(
        category="terraform",
        pattern=re.compile(r"\bterraform\s+state\s+(rm|push)\b"),
        reason="State mutation",
    ),
    BlockRule(
        category="credentials",
        pattern=re.compile(
            r"\b(cat|bat|less|more|head|tail|grep|rg|awk|sed)\b[^|;&]*"
            r"\.env\b(?!\.(example|sample|template))"
        ),
        reason="Read of .env",
    ),
    BlockRule(
        category="credentials",
        pattern=re.compile(r"\b(cat|bat|less|more|head|tail)\b[^|;&]*\.ssh/id_\S+"),
        reason="Read of SSH private key",
    ),
    BlockRule(
        category="credentials",
        pattern=re.compile(
            r"\b(cat|bat|less|more|head|tail)\b[^|;&]*\.aws/(credentials|config)\b"
        ),
        reason="Read of AWS credentials",
    ),
    BlockRule(
        category="credentials",
        pattern=re.compile(r"\b(cat|bat|less|more|head|tail)\b[^|;&]*\.(pem|key|p12)\b"),
        reason="Read of cert/key file",
    ),
)
```

- [ ] **Step 2.4: Run tests — expect PASS**

Run: `uv run pytest tests/unit/hooks/builtins/test_pre_tool_use_security.py -v`

Expected: all 4 tests PASS.

- [ ] **Step 2.5: Ruff + commit**

```bash
uv run ruff check src tests
git add src/lazy_harness/hooks/builtins/pre_tool_use_security.py \
        tests/unit/hooks/builtins/test_pre_tool_use_security.py
git commit -m "feat(hooks): add BLOCK_RULES catalog for pre_tool_use_security"
```

---

## Task 3: `should_block` pure function with table-driven tests

**Files:**
- Modify: `src/lazy_harness/hooks/builtins/pre_tool_use_security.py` (add `should_block`, `_safe_search`)
- Modify: `tests/unit/hooks/builtins/test_pre_tool_use_security.py` (add parametrized table)

- [ ] **Step 3.1: Write the failing table-driven test**

Append to `tests/unit/hooks/builtins/test_pre_tool_use_security.py`:

```python
# Format: (command, expected_category_or_None, human_label)
BLOCK_CASES: list[tuple[str, str | None, str]] = [
    # Filesystem
    ("rm -rf /", "filesystem", "rm -rf root"),
    ("rm -rf /tmp/foo", "filesystem", "rm -rf /tmp path"),
    ("rm -rf ./build", "filesystem", "rm -rf relative"),
    ("rm file.txt", None, "plain rm single file"),
    ("rm -r dir", None, "rm -r without -f"),
    ("truncate -s 0 log.txt", "filesystem", "truncate with size"),
    # Git
    ("git push --force origin main", "git", "force push plain"),
    ("git push -f origin main", "git", "short force flag"),
    ("git push --force-with-lease origin main", None, "lease is safe"),
    ("git push origin main", None, "normal push"),
    ("git reset --hard HEAD~3", "git", "hard reset"),
    ("git reset --soft HEAD~3", None, "soft reset"),
    ("git add -f .env", "git", "forced add of dotenv"),
    ("git add -f README.md", None, "forced add of non-secret"),
    # SQL
    ("DROP TABLE users", "sql", "drop table uppercase"),
    ("drop database prod", "sql", "drop database lower"),
    ("SELECT * FROM users", None, "select"),
    # Terraform
    ("terraform destroy", "terraform", "tf destroy"),
    ("terraform destroy -auto-approve", "terraform", "tf destroy auto"),
    ("terraform apply -auto-approve", "terraform", "tf apply auto"),
    ("terraform apply", None, "tf apply interactive"),
    ("terraform apply -replace=aws_instance.web", "terraform", "tf replace"),
    ("terraform state rm aws_instance.web", "terraform", "tf state rm"),
    ("terraform state push state.tfstate", "terraform", "tf state push"),
    ("terraform plan", None, "tf plan"),
    # Credentials
    ("cat .env", "credentials", "cat .env"),
    ("cat .env.example", None, "example allowed"),
    ("cat .env.local", "credentials", "cat env local"),
    ("less /home/user/.ssh/id_rsa", "credentials", "less private ssh"),
    ("cat /home/user/.ssh/id_rsa.pub", None, "public ssh key ok"),
    ("grep AWS_KEY /home/user/.aws/credentials", "credentials", "grep aws creds"),
    ("head server.pem", "credentials", "head cert"),
]


@pytest.mark.parametrize(
    "command,expected_category,label",
    BLOCK_CASES,
    ids=[c[2] for c in BLOCK_CASES],
)
def test_should_block_matrix(
    command: str, expected_category: str | None, label: str
) -> None:
    from lazy_harness.hooks.builtins.pre_tool_use_security import should_block

    decision = should_block(command, allow_patterns=[])
    if expected_category is None:
        assert decision is None, f"expected allow for {label}: {command!r}"
    else:
        assert decision is not None, f"expected block for {label}: {command!r}"
        assert decision.rule.category == expected_category


def test_should_block_allowlist_rescues_match() -> None:
    from lazy_harness.hooks.builtins.pre_tool_use_security import should_block

    assert should_block("rm -rf .worktrees/foo", allow_patterns=[r"\.worktrees/"]) is None


def test_should_block_invalid_allow_pattern_is_ignored() -> None:
    from lazy_harness.hooks.builtins.pre_tool_use_security import should_block

    decision = should_block("rm -rf /tmp/x", allow_patterns=["(["])
    assert decision is not None
    assert decision.rule.category == "filesystem"
```

- [ ] **Step 3.2: Run tests — expect all new FAIL (ImportError)**

Run: `uv run pytest tests/unit/hooks/builtins/test_pre_tool_use_security.py -v`

Expected: 30+ new tests FAIL on `ImportError: cannot import name 'should_block'`.

- [ ] **Step 3.3: Implement `should_block` + `_safe_search`**

Append to `src/lazy_harness/hooks/builtins/pre_tool_use_security.py`:

```python
def _safe_search(pattern: str, text: str) -> bool:
    """Compile-and-search; broken user regexes are skipped, never raised."""
    try:
        return re.search(pattern, text) is not None
    except re.error:
        return False


def should_block(command: str, allow_patterns: list[str]) -> BlockDecision | None:
    """Return BlockDecision if command matches a rule and no allow_pattern rescues it.

    First match wins; later rules are not evaluated even if more specific.
    """
    for rule in BLOCK_RULES:
        match = rule.pattern.search(command)
        if match is None:
            continue
        if any(_safe_search(ap, command) for ap in allow_patterns):
            return None
        return BlockDecision(rule=rule, matched_text=match.group(0))
    return None
```

- [ ] **Step 3.4: Run tests — expect all PASS**

Run: `uv run pytest tests/unit/hooks/builtins/test_pre_tool_use_security.py -v`

Expected: all tests PASS (36+).

- [ ] **Step 3.5: Ruff + commit**

```bash
uv run ruff check src tests
git add src/lazy_harness/hooks/builtins/pre_tool_use_security.py \
        tests/unit/hooks/builtins/test_pre_tool_use_security.py
git commit -m "feat(hooks): implement should_block with allowlist rescue"
```

---

## Task 4: Stdin parsing and block-message formatter helpers

**Files:**
- Modify: `src/lazy_harness/hooks/builtins/pre_tool_use_security.py`
- Modify: `tests/unit/hooks/builtins/test_pre_tool_use_security.py`

- [ ] **Step 4.1: Write failing tests**

Append to `tests/unit/hooks/builtins/test_pre_tool_use_security.py`:

```python
def test_read_stdin_json_returns_dict_when_valid(monkeypatch: pytest.MonkeyPatch) -> None:
    import io
    from lazy_harness.hooks.builtins.pre_tool_use_security import _read_stdin_json

    monkeypatch.setattr("sys.stdin", io.StringIO('{"tool_name": "Bash"}'))
    assert _read_stdin_json() == {"tool_name": "Bash"}


def test_read_stdin_json_returns_empty_dict_on_invalid(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import io
    from lazy_harness.hooks.builtins.pre_tool_use_security import _read_stdin_json

    monkeypatch.setattr("sys.stdin", io.StringIO("not json at all"))
    assert _read_stdin_json() == {}


def test_format_block_message_contains_reason_category_and_hint() -> None:
    import re as _re
    from lazy_harness.hooks.builtins.pre_tool_use_security import (
        BlockDecision,
        BlockRule,
        _format_block_message,
    )

    rule = BlockRule(
        category="filesystem",
        pattern=_re.compile(r"rm -rf"),
        reason="Recursive delete",
    )
    msg = _format_block_message(BlockDecision(rule=rule, matched_text="rm -rf /tmp"))
    assert "Blocked by lazy-harness PreToolUse" in msg
    assert "Recursive delete" in msg
    assert "filesystem" in msg
    assert "rm -rf /tmp" in msg
    assert "allow_patterns" in msg


def test_format_block_message_truncates_long_match() -> None:
    import re as _re
    from lazy_harness.hooks.builtins.pre_tool_use_security import (
        BlockDecision,
        BlockRule,
        _format_block_message,
    )

    rule = BlockRule(category="filesystem", pattern=_re.compile(r"x"), reason="r")
    huge = "x" * 500
    msg = _format_block_message(BlockDecision(rule=rule, matched_text=huge))
    # Truncated to MAX_MATCH_LEN (120) + ellipsis
    assert huge not in msg
    assert "…" in msg or "..." in msg
```

- [ ] **Step 4.2: Run — expect FAIL**

Run: `uv run pytest tests/unit/hooks/builtins/test_pre_tool_use_security.py -v -k "stdin or format_block"`

Expected: all 4 new tests FAIL on `ImportError`.

- [ ] **Step 4.3: Implement helpers**

Append to `src/lazy_harness/hooks/builtins/pre_tool_use_security.py`:

```python
import json
import sys
from typing import Any

MAX_MATCH_LEN = 120


def _read_stdin_json() -> dict[str, Any]:
    """Read and parse stdin as JSON; return {} on any parse error or empty input."""
    try:
        data = sys.stdin.read()
    except (OSError, ValueError):
        return {}
    if not data.strip():
        return {}
    try:
        parsed = json.loads(data)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _format_block_message(decision: BlockDecision) -> str:
    """Format the stderr message surfaced back to the agent by Claude Code."""
    matched = decision.matched_text
    if len(matched) > MAX_MATCH_LEN:
        matched = matched[:MAX_MATCH_LEN] + "…"
    return (
        f"Blocked by lazy-harness PreToolUse: {decision.rule.reason} "
        f"({decision.rule.category}).\n"
        f"Matched: {matched}\n"
        f"If this is intentional, add a regex pattern to "
        f"[hooks.pre_tool_use] allow_patterns in your profile config.toml.\n"
        f"See specs/designs/2026-04-17-security-hooks-cluster-design.md "
        f"for the full rule list.\n"
    )
```

Note: move the `import json` and `import sys` to the top of the file with the other imports — do not leave them mid-file. Run ruff to catch this automatically.

- [ ] **Step 4.4: Run — expect PASS**

Run: `uv run pytest tests/unit/hooks/builtins/test_pre_tool_use_security.py -v`

Expected: all tests PASS.

- [ ] **Step 4.5: Ruff + commit**

```bash
uv run ruff check src tests
git add src/lazy_harness/hooks/builtins/pre_tool_use_security.py \
        tests/unit/hooks/builtins/test_pre_tool_use_security.py
git commit -m "feat(hooks): add stdin parser and block message formatter"
```

---

## Task 5: Allowlist loader from `config.toml`

**Files:**
- Modify: `src/lazy_harness/hooks/builtins/pre_tool_use_security.py`
- Modify: `tests/unit/hooks/builtins/test_pre_tool_use_security.py`

- [ ] **Step 5.1: Write failing tests**

Append to `tests/unit/hooks/builtins/test_pre_tool_use_security.py`:

```python
def test_load_allowlist_returns_empty_when_config_missing(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from lazy_harness.hooks.builtins.pre_tool_use_security import _load_allowlist

    monkeypatch.setenv("LH_CONFIG_DIR", str(tmp_path))
    assert _load_allowlist() == []


def test_load_allowlist_reads_patterns_from_config_toml(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from lazy_harness.hooks.builtins.pre_tool_use_security import _load_allowlist

    cfg = tmp_path / "config.toml"
    cfg.write_text(
        '[hooks.pre_tool_use]\n'
        'scripts = ["pre-tool-use-security"]\n'
        'allow_patterns = ["\\\\.worktrees/", "/tmp/"]\n'
    )
    monkeypatch.setenv("LH_CONFIG_DIR", str(tmp_path))
    assert _load_allowlist() == ["\\.worktrees/", "/tmp/"]


def test_load_allowlist_returns_empty_when_section_missing(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from lazy_harness.hooks.builtins.pre_tool_use_security import _load_allowlist

    cfg = tmp_path / "config.toml"
    cfg.write_text('[monitoring]\nenabled = true\n')
    monkeypatch.setenv("LH_CONFIG_DIR", str(tmp_path))
    assert _load_allowlist() == []


def test_load_allowlist_returns_empty_on_malformed_toml(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from lazy_harness.hooks.builtins.pre_tool_use_security import _load_allowlist

    cfg = tmp_path / "config.toml"
    cfg.write_text("this is not [ valid toml")
    monkeypatch.setenv("LH_CONFIG_DIR", str(tmp_path))
    assert _load_allowlist() == []
```

- [ ] **Step 5.2: Run — expect FAIL**

Run: `uv run pytest tests/unit/hooks/builtins/test_pre_tool_use_security.py -v -k allowlist`

Expected: 4 tests FAIL on `ImportError`.

- [ ] **Step 5.3: Implement loader**

Append to `src/lazy_harness/hooks/builtins/pre_tool_use_security.py`:

```python
import tomllib
from pathlib import Path

from lazy_harness.core.paths import config_file


def _load_allowlist() -> list[str]:
    """Load pre_tool_use.allow_patterns from the harness config.toml.

    Returns empty list on any failure (missing file, malformed TOML, missing
    section). Empty list means stricter blocking — fail-safe by design.
    """
    try:
        cfg_path: Path = config_file()
    except Exception:
        return []
    if not cfg_path.is_file():
        return []
    try:
        data = tomllib.loads(cfg_path.read_text())
    except (OSError, tomllib.TOMLDecodeError):
        return []
    section = data.get("hooks", {}).get("pre_tool_use", {})
    patterns = section.get("allow_patterns", [])
    if not isinstance(patterns, list):
        return []
    return [p for p in patterns if isinstance(p, str)]
```

Move all imports to the top of the file.

**Note on `config_file()`:** that helper is defined in `src/lazy_harness/core/paths.py` and respects `LH_CONFIG_DIR` / `XDG_CONFIG_HOME`. That is why the tests use `monkeypatch.setenv("LH_CONFIG_DIR", ...)` instead of patching the function directly.

- [ ] **Step 5.4: Run — expect PASS**

Run: `uv run pytest tests/unit/hooks/builtins/test_pre_tool_use_security.py -v`

Expected: all tests PASS.

- [ ] **Step 5.5: Ruff + commit**

```bash
uv run ruff check src tests
git add src/lazy_harness/hooks/builtins/pre_tool_use_security.py \
        tests/unit/hooks/builtins/test_pre_tool_use_security.py
git commit -m "feat(hooks): load allow_patterns from profile config.toml"
```

---

## Task 6: `main()` entry point for `pre_tool_use_security`

**Files:**
- Modify: `src/lazy_harness/hooks/builtins/pre_tool_use_security.py`
- Modify: `tests/unit/hooks/builtins/test_pre_tool_use_security.py`

- [ ] **Step 6.1: Write failing tests**

Append to `tests/unit/hooks/builtins/test_pre_tool_use_security.py`:

```python
def test_main_exits_zero_when_tool_is_not_bash(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    import io
    from lazy_harness.hooks.builtins import pre_tool_use_security as mod

    monkeypatch.setattr(
        "sys.stdin", io.StringIO('{"tool_name": "Read", "tool_input": {}}')
    )
    with pytest.raises(SystemExit) as exc_info:
        mod.main()
    assert exc_info.value.code == 0


def test_main_exits_zero_for_allowed_bash_command(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    import io
    from lazy_harness.hooks.builtins import pre_tool_use_security as mod

    monkeypatch.setenv("LH_CONFIG_DIR", str(tmp_path))
    monkeypatch.setattr(
        "sys.stdin",
        io.StringIO('{"tool_name": "Bash", "tool_input": {"command": "ls -la"}}'),
    )
    with pytest.raises(SystemExit) as exc_info:
        mod.main()
    assert exc_info.value.code == 0


def test_main_exits_two_and_writes_stderr_on_block(
    monkeypatch: pytest.MonkeyPatch, tmp_path, capsys: pytest.CaptureFixture[str]
) -> None:
    import io
    from lazy_harness.hooks.builtins import pre_tool_use_security as mod

    monkeypatch.setenv("LH_CONFIG_DIR", str(tmp_path))
    monkeypatch.setattr(
        "sys.stdin",
        io.StringIO(
            '{"tool_name": "Bash", "tool_input": {"command": "rm -rf /tmp/foo"}}'
        ),
    )
    with pytest.raises(SystemExit) as exc_info:
        mod.main()
    assert exc_info.value.code == 2
    captured = capsys.readouterr()
    assert "Blocked by lazy-harness PreToolUse" in captured.err
    assert "filesystem" in captured.err


def test_main_exits_zero_on_empty_stdin(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    import io
    from lazy_harness.hooks.builtins import pre_tool_use_security as mod

    monkeypatch.setenv("LH_CONFIG_DIR", str(tmp_path))
    monkeypatch.setattr("sys.stdin", io.StringIO(""))
    with pytest.raises(SystemExit) as exc_info:
        mod.main()
    assert exc_info.value.code == 0
```

- [ ] **Step 6.2: Run — expect FAIL**

Run: `uv run pytest tests/unit/hooks/builtins/test_pre_tool_use_security.py -v -k "main"`

Expected: 4 tests FAIL with `AttributeError: module ... has no attribute 'main'`.

- [ ] **Step 6.3: Implement `main()`**

Append to `src/lazy_harness/hooks/builtins/pre_tool_use_security.py`:

```python
def main() -> None:
    """Entry point invoked by Claude Code as a PreToolUse hook command."""
    payload = _read_stdin_json()
    if payload.get("tool_name") != "Bash":
        sys.exit(0)
    command = str(payload.get("tool_input", {}).get("command", ""))
    allow = _load_allowlist()
    decision = should_block(command, allow)
    if decision is None:
        sys.exit(0)
    sys.stderr.write(_format_block_message(decision))
    sys.exit(2)


if __name__ == "__main__":
    main()
```

- [ ] **Step 6.4: Run — expect PASS**

Run: `uv run pytest tests/unit/hooks/builtins/test_pre_tool_use_security.py -v`

Expected: all tests PASS (40+).

- [ ] **Step 6.5: Ruff + commit**

```bash
uv run ruff check src tests
git add src/lazy_harness/hooks/builtins/pre_tool_use_security.py \
        tests/unit/hooks/builtins/test_pre_tool_use_security.py
git commit -m "feat(hooks): add pre_tool_use_security main() entry point"
```

---

## Task 7: Register `pre-tool-use-security` in `_BUILTIN_HOOKS`

**Files:**
- Modify: `src/lazy_harness/hooks/loader.py`
- Modify: `tests/unit/test_hook_loader.py` (check if it exists first)

- [ ] **Step 7.1: Check test file exists**

Run: `ls tests/unit/test_hook_loader.py 2>&1 || echo MISSING`

If MISSING, create it with:

```python
"""Unit tests for hooks.loader registry."""

from __future__ import annotations

from lazy_harness.hooks.loader import _BUILTIN_HOOKS, list_builtin_hooks, resolve_hook
```

- [ ] **Step 7.2: Write failing test**

Append (or add) to `tests/unit/test_hook_loader.py`:

```python
def test_pre_tool_use_security_is_registered_as_builtin() -> None:
    assert "pre-tool-use-security" in _BUILTIN_HOOKS
    assert (
        _BUILTIN_HOOKS["pre-tool-use-security"]
        == "lazy_harness.hooks.builtins.pre_tool_use_security"
    )


def test_pre_tool_use_security_resolves_to_concrete_file() -> None:
    info = resolve_hook("pre-tool-use-security")
    assert info is not None
    assert info.is_builtin is True
    assert info.path.name == "pre_tool_use_security.py"
    assert info.path.is_file()
```

- [ ] **Step 7.3: Run — expect FAIL**

Run: `uv run pytest tests/unit/test_hook_loader.py -v -k "pre_tool_use"`

Expected: both tests FAIL — key not in dict.

- [ ] **Step 7.4: Register the builtin**

In `src/lazy_harness/hooks/loader.py`, update `_BUILTIN_HOOKS`:

```python
_BUILTIN_HOOKS: dict[str, str] = {
    "compound-loop": "lazy_harness.hooks.builtins.compound_loop",
    "context-inject": "lazy_harness.hooks.builtins.context_inject",
    "pre-compact": "lazy_harness.hooks.builtins.pre_compact",
    "pre-tool-use-security": "lazy_harness.hooks.builtins.pre_tool_use_security",
    "session-end": "lazy_harness.hooks.builtins.session_end",
    "session-export": "lazy_harness.hooks.builtins.session_export",
}
```

- [ ] **Step 7.5: Run — expect PASS**

Run: `uv run pytest tests/unit/test_hook_loader.py -v`

Expected: all tests PASS.

- [ ] **Step 7.6: Ruff + commit**

```bash
uv run ruff check src tests
git add src/lazy_harness/hooks/loader.py tests/unit/test_hook_loader.py
git commit -m "feat(hooks): register pre-tool-use-security builtin"
```

---

## Task 8: `post_tool_use_format` hook (full module)

**Files:**
- Create: `src/lazy_harness/hooks/builtins/post_tool_use_format.py`
- Create: `tests/unit/hooks/builtins/test_post_tool_use_format.py`

- [ ] **Step 8.1: Write failing tests**

Create `tests/unit/hooks/builtins/test_post_tool_use_format.py`:

```python
"""Unit tests for post_tool_use_format hook."""

from __future__ import annotations

import io
import subprocess
from unittest.mock import MagicMock

import pytest


def test_runs_ruff_format_on_python_edit(monkeypatch: pytest.MonkeyPatch) -> None:
    from lazy_harness.hooks.builtins import post_tool_use_format as mod

    fake_run = MagicMock(return_value=subprocess.CompletedProcess([], returncode=0))
    monkeypatch.setattr("subprocess.run", fake_run)
    monkeypatch.setattr(
        "sys.stdin",
        io.StringIO(
            '{"tool_name": "Edit", "tool_input": {"file_path": "/abs/foo.py"}}'
        ),
    )

    with pytest.raises(SystemExit) as exc_info:
        mod.main()

    assert exc_info.value.code == 0
    fake_run.assert_called_once()
    args, kwargs = fake_run.call_args
    assert args[0] == ["ruff", "format", "/abs/foo.py"]
    assert kwargs.get("check") is False
    assert kwargs.get("timeout") == 10


def test_runs_ruff_format_on_python_write(monkeypatch: pytest.MonkeyPatch) -> None:
    from lazy_harness.hooks.builtins import post_tool_use_format as mod

    fake_run = MagicMock(return_value=subprocess.CompletedProcess([], returncode=0))
    monkeypatch.setattr("subprocess.run", fake_run)
    monkeypatch.setattr(
        "sys.stdin",
        io.StringIO(
            '{"tool_name": "Write", "tool_input": {"file_path": "/abs/bar.py"}}'
        ),
    )
    with pytest.raises(SystemExit) as exc_info:
        mod.main()
    assert exc_info.value.code == 0
    fake_run.assert_called_once()


def test_skips_non_python_files(monkeypatch: pytest.MonkeyPatch) -> None:
    from lazy_harness.hooks.builtins import post_tool_use_format as mod

    fake_run = MagicMock()
    monkeypatch.setattr("subprocess.run", fake_run)
    monkeypatch.setattr(
        "sys.stdin",
        io.StringIO(
            '{"tool_name": "Edit", "tool_input": {"file_path": "/abs/readme.md"}}'
        ),
    )
    with pytest.raises(SystemExit) as exc_info:
        mod.main()
    assert exc_info.value.code == 0
    fake_run.assert_not_called()


def test_skips_non_edit_tools(monkeypatch: pytest.MonkeyPatch) -> None:
    from lazy_harness.hooks.builtins import post_tool_use_format as mod

    fake_run = MagicMock()
    monkeypatch.setattr("subprocess.run", fake_run)
    monkeypatch.setattr(
        "sys.stdin",
        io.StringIO('{"tool_name": "Read", "tool_input": {"file_path": "/a.py"}}'),
    )
    with pytest.raises(SystemExit) as exc_info:
        mod.main()
    assert exc_info.value.code == 0
    fake_run.assert_not_called()


def test_exits_zero_on_malformed_stdin(monkeypatch: pytest.MonkeyPatch) -> None:
    from lazy_harness.hooks.builtins import post_tool_use_format as mod

    fake_run = MagicMock()
    monkeypatch.setattr("subprocess.run", fake_run)
    monkeypatch.setattr("sys.stdin", io.StringIO("not json"))
    with pytest.raises(SystemExit) as exc_info:
        mod.main()
    assert exc_info.value.code == 0
    fake_run.assert_not_called()


def test_exits_zero_when_ruff_not_installed(monkeypatch: pytest.MonkeyPatch) -> None:
    from lazy_harness.hooks.builtins import post_tool_use_format as mod

    def raise_fnf(*_: object, **__: object) -> subprocess.CompletedProcess[str]:
        raise FileNotFoundError("ruff not found")

    monkeypatch.setattr("subprocess.run", raise_fnf)
    monkeypatch.setattr(
        "sys.stdin",
        io.StringIO('{"tool_name": "Edit", "tool_input": {"file_path": "/a.py"}}'),
    )
    with pytest.raises(SystemExit) as exc_info:
        mod.main()
    assert exc_info.value.code == 0


def test_exits_zero_when_ruff_times_out(monkeypatch: pytest.MonkeyPatch) -> None:
    from lazy_harness.hooks.builtins import post_tool_use_format as mod

    def raise_timeout(*_: object, **__: object) -> subprocess.CompletedProcess[str]:
        raise subprocess.TimeoutExpired(cmd="ruff", timeout=10)

    monkeypatch.setattr("subprocess.run", raise_timeout)
    monkeypatch.setattr(
        "sys.stdin",
        io.StringIO('{"tool_name": "Edit", "tool_input": {"file_path": "/a.py"}}'),
    )
    with pytest.raises(SystemExit) as exc_info:
        mod.main()
    assert exc_info.value.code == 0
```

- [ ] **Step 8.2: Run — expect FAIL (ImportError)**

Run: `uv run pytest tests/unit/hooks/builtins/test_post_tool_use_format.py -v`

Expected: all 7 tests FAIL on `ModuleNotFoundError`.

- [ ] **Step 8.3: Implement the module**

Create `src/lazy_harness/hooks/builtins/post_tool_use_format.py`:

```python
"""PostToolUse auto-format hook — runs `ruff format` on Python edits.

Fail-soft: all errors are swallowed and exit 0, because a formatter failure
must never block the agent's progress. See spec
`specs/designs/2026-04-17-security-hooks-cluster-design.md`.
"""

from __future__ import annotations

import json
import subprocess
import sys
from typing import Any

RUFF_TIMEOUT_SECS = 10


def _read_stdin_json() -> dict[str, Any]:
    try:
        data = sys.stdin.read()
    except (OSError, ValueError):
        return {}
    if not data.strip():
        return {}
    try:
        parsed = json.loads(data)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def main() -> None:
    payload = _read_stdin_json()
    if payload.get("tool_name") not in ("Edit", "Write"):
        sys.exit(0)
    path = str(payload.get("tool_input", {}).get("file_path", ""))
    if not path.endswith(".py"):
        sys.exit(0)
    try:
        subprocess.run(
            ["ruff", "format", path],
            check=False,
            capture_output=True,
            timeout=RUFF_TIMEOUT_SECS,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    sys.exit(0)


if __name__ == "__main__":
    main()
```

- [ ] **Step 8.4: Run — expect PASS**

Run: `uv run pytest tests/unit/hooks/builtins/test_post_tool_use_format.py -v`

Expected: all 7 tests PASS.

- [ ] **Step 8.5: Ruff + commit**

```bash
uv run ruff check src tests
git add src/lazy_harness/hooks/builtins/post_tool_use_format.py \
        tests/unit/hooks/builtins/test_post_tool_use_format.py
git commit -m "feat(hooks): add post_tool_use_format builtin with ruff-on-PATH"
```

---

## Task 9: Register `post-tool-use-format` in `_BUILTIN_HOOKS`

**Files:**
- Modify: `src/lazy_harness/hooks/loader.py`
- Modify: `tests/unit/test_hook_loader.py`

- [ ] **Step 9.1: Write failing test**

Append to `tests/unit/test_hook_loader.py`:

```python
def test_post_tool_use_format_is_registered_as_builtin() -> None:
    assert "post-tool-use-format" in _BUILTIN_HOOKS
    assert (
        _BUILTIN_HOOKS["post-tool-use-format"]
        == "lazy_harness.hooks.builtins.post_tool_use_format"
    )


def test_post_tool_use_format_resolves_to_concrete_file() -> None:
    info = resolve_hook("post-tool-use-format")
    assert info is not None
    assert info.is_builtin is True
    assert info.path.name == "post_tool_use_format.py"
    assert info.path.is_file()
```

- [ ] **Step 9.2: Run — expect FAIL**

Run: `uv run pytest tests/unit/test_hook_loader.py -v -k "post_tool_use"`

Expected: FAIL (key not present).

- [ ] **Step 9.3: Register**

In `src/lazy_harness/hooks/loader.py`, update `_BUILTIN_HOOKS`:

```python
_BUILTIN_HOOKS: dict[str, str] = {
    "compound-loop": "lazy_harness.hooks.builtins.compound_loop",
    "context-inject": "lazy_harness.hooks.builtins.context_inject",
    "post-tool-use-format": "lazy_harness.hooks.builtins.post_tool_use_format",
    "pre-compact": "lazy_harness.hooks.builtins.pre_compact",
    "pre-tool-use-security": "lazy_harness.hooks.builtins.pre_tool_use_security",
    "session-end": "lazy_harness.hooks.builtins.session_end",
    "session-export": "lazy_harness.hooks.builtins.session_export",
}
```

- [ ] **Step 9.4: Run — expect PASS**

Run: `uv run pytest tests/unit/test_hook_loader.py -v`

Expected: all tests PASS.

- [ ] **Step 9.5: Commit**

```bash
uv run ruff check src tests
git add src/lazy_harness/hooks/loader.py tests/unit/test_hook_loader.py
git commit -m "feat(hooks): register post-tool-use-format builtin"
```

---

## Task 10: Per-event matcher in Claude Code settings generator

**Files:**
- Modify: `src/lazy_harness/agents/claude_code.py:59-82`
- Modify: `tests/unit/test_agents_claude_code.py` (check-and-create if missing)

**Problem:** today the generator writes `"matcher": ""` for every event. PreToolUse needs `"Bash"` and PostToolUse needs `"Edit|Write"`. Everything else keeps the empty string.

- [ ] **Step 10.1: Check test file exists**

Run: `ls tests/unit/test_agents_claude_code.py 2>&1 || ls tests/unit/agents/ 2>&1 || echo MISSING`

If the file/dir does not exist, create `tests/unit/test_agents_claude_code.py` with:

```python
"""Unit tests for ClaudeCodeAgent settings generator."""

from __future__ import annotations

from lazy_harness.agents.claude_code import ClaudeCodeAgent
```

- [ ] **Step 10.2: Write failing tests**

Append (or create) in `tests/unit/test_agents_claude_code.py`:

```python
def test_generate_hook_config_uses_bash_matcher_for_pre_tool_use() -> None:
    agent = ClaudeCodeAgent()
    result = agent.generate_hook_config({"pre_tool_use": ["pre-tool-use-security"]})
    assert "PreToolUse" in result
    entries = result["PreToolUse"]
    assert len(entries) == 1
    assert entries[0]["matcher"] == "Bash"


def test_generate_hook_config_uses_edit_write_matcher_for_post_tool_use() -> None:
    agent = ClaudeCodeAgent()
    result = agent.generate_hook_config({"post_tool_use": ["post-tool-use-format"]})
    assert "PostToolUse" in result
    entries = result["PostToolUse"]
    assert len(entries) == 1
    assert entries[0]["matcher"] == "Edit|Write"


def test_generate_hook_config_keeps_empty_matcher_for_other_events() -> None:
    agent = ClaudeCodeAgent()
    result = agent.generate_hook_config({"session_start": ["context-inject"]})
    entries = result["SessionStart"]
    assert entries[0]["matcher"] == ""
```

- [ ] **Step 10.3: Run — expect FAIL**

Run: `uv run pytest tests/unit/test_agents_claude_code.py -v -k matcher`

Expected: the first two tests FAIL (matcher is `""` not `"Bash"`/`"Edit|Write"`).

- [ ] **Step 10.4: Update the generator**

In `src/lazy_harness/agents/claude_code.py` around lines 59-82, replace the `generate_hook_config` body with:

```python
    def generate_hook_config(self, hooks: dict[str, list[str]]) -> dict:
        """Generate Claude Code settings.json hooks section."""
        hook_event_map = {
            "session_start": "SessionStart",
            "session_stop": "Stop",
            "session_end": "SessionEnd",
            "pre_compact": "PreCompact",
            "pre_tool_use": "PreToolUse",
            "post_tool_use": "PostToolUse",
            "notification": "Notification",
        }
        matcher_map = {
            "pre_tool_use": "Bash",
            "post_tool_use": "Edit|Write",
        }
        settings_hooks: dict[str, list[dict]] = {}
        for event, scripts in hooks.items():
            cc_event = hook_event_map.get(event)
            if not cc_event:
                continue
            matcher = matcher_map.get(event, "")
            matchers = []
            for script in scripts:
                matchers.append(
                    {
                        "matcher": matcher,
                        "hooks": [{"type": "command", "command": script}],
                    }
                )
            settings_hooks[cc_event] = matchers
        return settings_hooks
```

- [ ] **Step 10.5: Run — expect PASS**

Run: `uv run pytest tests/unit/test_agents_claude_code.py -v`

Expected: all tests PASS. Also run the full suite to catch any regression: `uv run pytest -q`.

- [ ] **Step 10.6: Commit**

```bash
uv run ruff check src tests
git add src/lazy_harness/agents/claude_code.py tests/unit/test_agents_claude_code.py
git commit -m "feat(agents): per-event matcher in Claude Code hook config"
```

---

## Task 11: Integration smoke tests — subprocess end-to-end

**Files:**
- Create: `tests/integration/test_security_hooks.py`

- [ ] **Step 11.1: Write failing test**

Create `tests/integration/test_security_hooks.py`:

```python
"""Integration smoke tests — spawn the hook modules as Claude Code would."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest


def _run_hook(module: str, payload: dict | str, env_extra: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    import os

    env = os.environ.copy()
    if env_extra:
        env.update(env_extra)
    stdin = payload if isinstance(payload, str) else json.dumps(payload)
    return subprocess.run(
        [sys.executable, "-m", module],
        input=stdin,
        capture_output=True,
        text=True,
        env=env,
        timeout=30,
    )


def test_pre_tool_use_security_blocks_rm_rf(tmp_path: Path) -> None:
    result = _run_hook(
        "lazy_harness.hooks.builtins.pre_tool_use_security",
        {"tool_name": "Bash", "tool_input": {"command": "rm -rf /tmp/foo"}},
        env_extra={"LH_CONFIG_DIR": str(tmp_path)},
    )
    assert result.returncode == 2
    assert "Blocked by lazy-harness PreToolUse" in result.stderr
    assert "filesystem" in result.stderr


def test_pre_tool_use_security_allows_innocent_command(tmp_path: Path) -> None:
    result = _run_hook(
        "lazy_harness.hooks.builtins.pre_tool_use_security",
        {"tool_name": "Bash", "tool_input": {"command": "ls -la"}},
        env_extra={"LH_CONFIG_DIR": str(tmp_path)},
    )
    assert result.returncode == 0
    assert result.stderr == ""


def test_post_tool_use_format_exits_zero_on_python_edit(tmp_path: Path) -> None:
    py = tmp_path / "foo.py"
    py.write_text("x=1\n")
    result = _run_hook(
        "lazy_harness.hooks.builtins.post_tool_use_format",
        {"tool_name": "Edit", "tool_input": {"file_path": str(py)}},
    )
    assert result.returncode == 0


def test_both_hooks_exit_zero_on_empty_stdin() -> None:
    for module in (
        "lazy_harness.hooks.builtins.pre_tool_use_security",
        "lazy_harness.hooks.builtins.post_tool_use_format",
    ):
        result = _run_hook(module, "")
        assert result.returncode == 0, f"{module} non-zero on empty stdin"
```

- [ ] **Step 11.2: Run — expect PASS**

Run: `uv run pytest tests/integration/test_security_hooks.py -v`

Expected: all 4 tests PASS (these tests use real subprocesses against the modules built in Tasks 1-9).

If any test fails, do NOT push forward — fix the root cause in the hook module first. This is the contract validation gate.

- [ ] **Step 11.3: Commit**

```bash
uv run ruff check src tests
git add tests/integration/test_security_hooks.py
git commit -m "test(hooks): add integration smoke tests for security cluster"
```

---

## Task 12: Wizard writes `[hooks.*]` blocks by default

**Files:**
- Modify: `src/lazy_harness/init/wizard.py`
- Modify: `tests/unit/init/test_wizard.py` (check-and-create if missing)

- [ ] **Step 12.1: Check test file exists**

Run: `ls tests/unit/init/test_wizard.py 2>&1 || echo MISSING`

If MISSING, create `tests/unit/init/__init__.py` (empty) and `tests/unit/init/test_wizard.py` with:

```python
"""Unit tests for init.wizard."""

from __future__ import annotations

import tomllib
from pathlib import Path

from lazy_harness.init.wizard import WizardAnswers, run_wizard
```

- [ ] **Step 12.2: Write failing test**

Append (or include) in `tests/unit/init/test_wizard.py`:

```python
def test_run_wizard_writes_pre_tool_use_hook_block(tmp_path: Path) -> None:
    cfg = tmp_path / "config.toml"
    answers = WizardAnswers(
        profile_name="demo",
        agent="claude-code",
        knowledge_path=tmp_path / "kb",
        enable_qmd=False,
    )
    run_wizard(answers, config_path=cfg)
    parsed = tomllib.loads(cfg.read_text())
    block = parsed.get("hooks", {}).get("pre_tool_use", {})
    assert block.get("scripts") == ["pre-tool-use-security"]
    assert block.get("allow_patterns") == []


def test_run_wizard_writes_post_tool_use_hook_block(tmp_path: Path) -> None:
    cfg = tmp_path / "config.toml"
    answers = WizardAnswers(
        profile_name="demo",
        agent="claude-code",
        knowledge_path=tmp_path / "kb",
        enable_qmd=False,
    )
    run_wizard(answers, config_path=cfg)
    parsed = tomllib.loads(cfg.read_text())
    block = parsed.get("hooks", {}).get("post_tool_use", {})
    assert block.get("scripts") == ["post-tool-use-format"]
```

- [ ] **Step 12.3: Run — expect FAIL**

Run: `uv run pytest tests/unit/init/test_wizard.py -v -k hook`

Expected: both FAIL (no `hooks` key in TOML).

- [ ] **Step 12.4: Update wizard**

In `src/lazy_harness/init/wizard.py::run_wizard`, extend the `data` dict:

```python
    data: dict = {
        "harness": {"version": "1"},
        "agent": {"type": answers.agent},
        "profiles": {
            "default": answers.profile_name,
            answers.profile_name: {
                "config_dir": f"~/.claude-{answers.profile_name}",
            },
        },
        "knowledge": {"path": contract_path(answers.knowledge_path)},
        "monitoring": {"enabled": True},
        "scheduler": {"backend": "auto"},
        "hooks": {
            "pre_tool_use": {
                "scripts": ["pre-tool-use-security"],
                "allow_patterns": [],
            },
            "post_tool_use": {
                "scripts": ["post-tool-use-format"],
            },
        },
    }
```

- [ ] **Step 12.5: Run — expect PASS**

Run: `uv run pytest tests/unit/init/test_wizard.py -v`

Expected: all tests PASS. Run the full suite too: `uv run pytest -q`.

- [ ] **Step 12.6: Commit**

```bash
uv run ruff check src tests
git add src/lazy_harness/init/wizard.py tests/unit/init/test_wizard.py tests/unit/init/__init__.py
git commit -m "feat(init): default-on security hooks in new profile config"
```

---

## Task 13: `lh doctor` warns if `ruff` is not on PATH

**Files:**
- Modify: `src/lazy_harness/cli/doctor_cmd.py`
- Modify: `tests/unit/cli/test_doctor_cmd.py` (check-and-create if missing)

- [ ] **Step 13.1: Read the current doctor_cmd to follow its style**

Run: `cat src/lazy_harness/cli/doctor_cmd.py | head -80`

Note the existing check style (how warnings are printed, whether there's a list of checks, etc.) and mirror it.

- [ ] **Step 13.2: Check test file exists**

Run: `ls tests/unit/cli/test_doctor_cmd.py 2>&1 || echo MISSING`

If MISSING, create `tests/unit/cli/__init__.py` (empty) and `tests/unit/cli/test_doctor_cmd.py` starter:

```python
"""Unit tests for lh doctor."""

from __future__ import annotations
```

- [ ] **Step 13.3: Write failing test**

Append to `tests/unit/cli/test_doctor_cmd.py`:

```python
import pytest
from click.testing import CliRunner


def test_doctor_warns_when_ruff_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    from lazy_harness.cli.doctor_cmd import doctor

    monkeypatch.setattr("shutil.which", lambda _name: None)
    runner = CliRunner()
    result = runner.invoke(doctor, [])
    assert "ruff" in result.output.lower()


def test_doctor_does_not_warn_when_ruff_present(monkeypatch: pytest.MonkeyPatch) -> None:
    from lazy_harness.cli.doctor_cmd import doctor

    monkeypatch.setattr(
        "shutil.which", lambda name: "/opt/bin/ruff" if name == "ruff" else None
    )
    runner = CliRunner()
    result = runner.invoke(doctor, [])
    # Some doctor runs print an all-clear message; ensure no warning line
    assert "ruff not found" not in result.output.lower()
```

If the real `doctor_cmd.py` structure is materially different from a plain Click command (e.g., it's a class or has required config), adjust the test to match — but keep the assertion shape: warn iff `shutil.which("ruff") is None`.

- [ ] **Step 13.4: Run — expect FAIL**

Run: `uv run pytest tests/unit/cli/test_doctor_cmd.py -v`

Expected: FAIL (no ruff check yet).

- [ ] **Step 13.5: Add the check**

In `src/lazy_harness/cli/doctor_cmd.py`, wherever the existing checks are run, add:

```python
import shutil

# ... inside the main check flow (follow existing style):
if shutil.which("ruff") is None:
    console.print(
        "[yellow]![/yellow] ruff not found on PATH. "
        "PostToolUse auto-format hook will no-op until you "
        "run `uv tool install ruff`."
    )
```

Adapt exact message/style to the existing doctor output conventions.

- [ ] **Step 13.6: Run — expect PASS**

Run: `uv run pytest tests/unit/cli/test_doctor_cmd.py -v`

Expected: all tests PASS.

- [ ] **Step 13.7: Commit**

```bash
uv run ruff check src tests
git add src/lazy_harness/cli/doctor_cmd.py tests/unit/cli/test_doctor_cmd.py tests/unit/cli/__init__.py
git commit -m "feat(doctor): warn when ruff missing (needed by post_tool_use_format)"
```

---

## Task 14: Update backlog and run the full pre-commit gate

**Files:**
- Modify: `specs/backlog.md`

- [ ] **Step 14.1: Move the two cluster items from Open to Done**

In `specs/backlog.md`:

1. Under `## Done`, append:

```markdown
- [x] **PreToolUse security hook** — blocks destructive filesystem/git/sql/terraform commands + credentials reads + forced secret commits, with per-profile `allow_patterns` escape hatch (feat/security-hooks-cluster)
- [x] **PostToolUse auto-format hook** — runs `ruff format` on `.py` edits/writes fail-soft (feat/security-hooks-cluster)
```

2. Remove the entire `## Open — Prioridad ALTA` cluster callout (the `> **Cluster de hooks (ship juntos):** ...` block) and the two item bodies `### PreToolUse security: destructive command blocking` and `### PostToolUse auto-format (ruff)`.

3. The surviving HIGH-priority item (`### compound-loop: insight capture + learnings lost on long sessions`) becomes the only HIGH item and keeps its heading.

- [ ] **Step 14.2: Run the full pre-commit gate**

Run each separately and confirm pristine output:

```bash
uv run pytest -q
uv run ruff check src tests
uv run --group docs mkdocs build --strict
```

Each must pass with no warnings (non-negotiable #4).

- [ ] **Step 14.3: Commit and push the branch**

```bash
git add specs/backlog.md
git commit -m "docs(backlog): move security hooks cluster items to Done"
git push -u origin feat/security-hooks-cluster
```

- [ ] **Step 14.4: Open the PR**

```bash
gh pr create --title "feat: security hooks cluster (PreToolUse blocker + PostToolUse ruff format)" --body "$(cat <<'EOF'
## Summary

Ships the security hooks cluster designed in
`specs/designs/2026-04-17-security-hooks-cluster-design.md`:

1. **PreToolUse security** (`pre-tool-use-security`) blocks destructive
   filesystem / git / sql / terraform shell commands plus reads of common
   credentials files and `git add -f` of secrets. User-editable
   `allow_patterns` in `[hooks.pre_tool_use]` provides the escape hatch
   (example: `"\\.worktrees/"` to let `/cleanup-worktree` keep working).

2. **PostToolUse auto-format** (`post-tool-use-format`) runs
   `ruff format` on every `Edit`/`Write` to a `.py` file. Fail-soft: no
   ruff on PATH → no-op. Timeout 10s so a hung ruff cannot block the
   agent.

Both hooks ship default-on for **new** profiles via `lh init`. Existing
profiles (`lazy`, `flex`) need the snippet below pasted into their
`~/.config/lazy-harness/config.toml` once:

\`\`\`toml
[hooks.pre_tool_use]
scripts = ["pre-tool-use-security"]
allow_patterns = [
  # Example: "\\\\.worktrees/" to let /cleanup-worktree work
]

[hooks.post_tool_use]
scripts = ["post-tool-use-format"]
\`\`\`

`lh doctor` now warns if `ruff` is not on PATH.

### PreToolUse deviates from ADR-006

ADR-006 says hooks exit 0 always. PreToolUse deliberately exits 2 on
block because Claude Code interprets that as a "block this tool call"
signal and surfaces the stderr message back to the agent. The PostToolUse
hook keeps exit 0 always. An addendum to ADR-006 documenting this
divergence can land in a follow-up PR.

## Test plan

- [x] `uv run pytest` — full suite green, ~40+ new tests
- [x] `uv run ruff check src tests` — clean
- [x] `uv run --group docs mkdocs build --strict` — clean
- [x] Integration smoke tests spawn the hook modules as subprocesses with
      real stdin JSON payloads (matches Claude Code's invocation shape).

## Out of scope (deferred)

- Bypass via `LH_FORCE=1` env prefix. Allowlist-only — easier for the
  agent to reason about, harder to nullify accidentally.
- Multi-formatter (JSON / YAML / Markdown) in PostToolUse. Python only.
- `ruff check --fix --unsafe-fixes`. Unsafe fixes can change semantics
  silently; kept out.
EOF
)"
```

---

## Self-review checklist

Before declaring the plan complete, walk through:

1. **Spec coverage:**
   - ✅ `pre_tool_use_security` data model → Task 1
   - ✅ `BLOCK_RULES` catalog → Task 2
   - ✅ `should_block` pure logic → Task 3
   - ✅ Stdin / message formatting → Task 4
   - ✅ Allowlist loader → Task 5
   - ✅ `main()` entry point → Task 6
   - ✅ Builtin registration (pre) → Task 7
   - ✅ `post_tool_use_format` full module → Task 8
   - ✅ Builtin registration (post) → Task 9
   - ✅ Matcher per-event in claude_code.py → Task 10
   - ✅ Integration smoke → Task 11
   - ✅ Default-on in wizard → Task 12
   - ✅ `lh doctor` ruff check → Task 13
   - ✅ Backlog update + PR → Task 14

2. **No placeholders:** confirmed — every task has actual code blocks. The only "check if file exists" branches are explicit conditional commands with fallbacks, not TBDs.

3. **Type consistency:**
   - `should_block(command: str, allow_patterns: list[str]) -> BlockDecision | None` — same signature used in Tasks 3, 6.
   - `BlockRule(category, pattern, reason)` — same across Tasks 1, 2, 4.
   - `_read_stdin_json() -> dict[str, Any]` — same in Tasks 4, 6, 8.
   - Builtin keys use **kebab-case** in `_BUILTIN_HOOKS` (`pre-tool-use-security`) and module paths use **snake_case** (`pre_tool_use_security`). Consistent in Tasks 7, 9.

4. **Scope check:** single PR, ~14 tasks, each 2-5 minutes. No subsystem drift.

5. **Ambiguity check:**
   - First-match-wins semantic stated explicitly in spec and Task 3 docstring.
   - Allowlist fail-safe (empty list on error) stated in Task 5 docstring and tests.
   - PostToolUse fail-soft (always exit 0) covered by Tasks 8.1 tests (7 cases).

# Loop Engineering Implementation Plan — Phases 0 and 1

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Measure how often sessions declare a verifiable success criterion, then make the harness ask for one when they do not.

**Architecture:** A `loop_events` table in the existing metrics DB records what sessions do. A `UserPromptSubmit` hook classifies incoming prompts deterministically and records whether a goal was declared. Injection is gated behind a config flag that stays off until a two-week baseline exists — the hook ships as a sensor and becomes an actuator by configuration, not by a second deployment.

**Tech Stack:** Python 3.11+, SQLite via `sqlite3`, `click` for CLI, `pytest`.

**Spec:** [`specs/designs/2026-08-16-loop-engineering-design.md`](2026-08-16-loop-engineering-design.md)

## Global Constraints

- Python 3.11+, strict type hints. No `Any` unless unavoidable.
- Strict TDD: no production code without a failing test that exercises it first.
- **Hooks handle every exception explicitly and exit 0.** An unhandled error crashes the chain instead of degrading.
- **Hook tests cover wrong-type input** (null, int, list where a dict is expected) alongside malformed JSON, and out-of-scope cases alongside the happy path.
- **CLI tests pair each explicit-parameter unit test with a parameter-less smoke test.**
- Never run `uv` against live profiles from a worktree. Deploy with the installed `lh`, never `uv run`.
- Conventional commits, no AI trailers, no `--no-verify`.
- Pre-commit gate is all three: `uv run pytest`, `uv run ruff check src tests`, `uv run --group docs mkdocs build --strict`.
- **Injection stays off by default.** `[loops] inject_goal_prompt` defaults to `false` and is flipped only after Phase 0 has two weeks of baseline.

## Out of scope for this plan

- **The `verify-before-done` skill.** The harness does not manage skills — profiles deploy `CLAUDE.md`, `commands/`, `docs/` and `settings.json` only. The skill is authored directly in `~/.claude-<profile>/skills/verify-before-done/SKILL.md` and is not a repo artifact. Do it, but not as a task here.
- **The soft block on `Stop`.** It fires when a session declared a goal and no `verify_ran` event exists — but `verify_ran` is emitted by the `verify-before-done` skill, which lives outside the repo and does not exist yet. Building the guard before the thing it guards produces a hook that blocks on a condition nothing can satisfy. It gets its own plan once the skill emits the event.
- **The separate evaluator subagent.** Invoked from the skill, not from a hook — hooks cannot spawn subagents. It ships with the skill, outside this repo.
- **Phases 2, 3 and 4.** Separate plans; Phase 4 depends on the hook this plan builds.

---

### Task 1: `loop_events` table and its read/write API

**Files:**
- Modify: `src/lazy_harness/monitoring/db.py:29-74` (`_create_tables`)
- Test: `tests/unit/monitoring/test_db_loop_events.py`

**Interfaces:**
- Consumes: `MetricsDB(path)` — existing constructor, takes a `Path` or `":memory:"`.
- Produces:
  - `MetricsDB.record_loop_event(session: str, kind: str, project: str = "", profile: str = "", detail: str = "") -> None`
  - `MetricsDB.loop_event_counts(since_ts: float | None = None) -> dict[str, int]` — maps `kind` to occurrence count.

- [ ] **Step 1: Write the failing test**

```python
"""Tests for the loop_events table."""

from __future__ import annotations

import pytest

from lazy_harness.monitoring.db import MetricsDB


@pytest.fixture
def db() -> MetricsDB:
    return MetricsDB(":memory:")


def test_records_and_counts_events_by_kind(db: MetricsDB) -> None:
    db.record_loop_event(session="s1", kind="goal_absent", project="p")
    db.record_loop_event(session="s1", kind="goal_absent", project="p")
    db.record_loop_event(session="s2", kind="goal_declared", project="p")

    assert db.loop_event_counts() == {"goal_absent": 2, "goal_declared": 1}


def test_counts_respect_the_since_cutoff(db: MetricsDB) -> None:
    db.record_loop_event(session="old", kind="goal_absent")
    cutoff = db._now()  # noqa: SLF001 - test seam, see Step 3
    db.record_loop_event(session="new", kind="goal_declared")

    assert db.loop_event_counts(since_ts=cutoff) == {"goal_declared": 1}


def test_detail_round_trips(db: MetricsDB) -> None:
    db.record_loop_event(session="s1", kind="goal_declared", detail="tests pass")

    rows = db._conn.execute("SELECT detail FROM loop_events").fetchall()  # noqa: SLF001
    assert rows[0]["detail"] == "tests pass"


def test_empty_table_counts_to_an_empty_mapping(db: MetricsDB) -> None:
    assert db.loop_event_counts() == {}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/monitoring/test_db_loop_events.py -v`
Expected: FAIL with `AttributeError: 'MetricsDB' object has no attribute 'record_loop_event'`

- [ ] **Step 3: Write minimal implementation**

Add to `_create_tables`, after the `sink_outbox` block and before `self._migrate_identity_columns()`:

```python
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS loop_events (
                session TEXT NOT NULL,
                ts      REAL NOT NULL,
                project TEXT NOT NULL DEFAULT '',
                profile TEXT NOT NULL DEFAULT '',
                kind    TEXT NOT NULL,
                detail  TEXT NOT NULL DEFAULT ''
            )
        """)
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_loop_events_session ON loop_events(session, ts)"
        )
```

`CREATE TABLE IF NOT EXISTS` is the idempotent-migration pattern this file already uses; no `ALTER TABLE` path is needed because the table is new.

Add the methods to `MetricsDB`:

```python
    def _now(self) -> float:
        """Seam for tests that need a cutoff between two writes."""
        return time.time()

    def record_loop_event(
        self,
        session: str,
        kind: str,
        project: str = "",
        profile: str = "",
        detail: str = "",
    ) -> None:
        self._conn.execute(
            "INSERT INTO loop_events (session, ts, project, profile, kind, detail) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (session, self._now(), project, profile, kind, detail),
        )
        self._conn.commit()

    def loop_event_counts(self, since_ts: float | None = None) -> dict[str, int]:
        if since_ts is None:
            rows = self._conn.execute(
                "SELECT kind, COUNT(*) AS n FROM loop_events GROUP BY kind"
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT kind, COUNT(*) AS n FROM loop_events WHERE ts >= ? GROUP BY kind",
                (since_ts,),
            ).fetchall()
        return {row["kind"]: row["n"] for row in rows}
```

`time` is already imported at the top of the module.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/monitoring/test_db_loop_events.py -v`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add src/lazy_harness/monitoring/db.py tests/unit/monitoring/test_db_loop_events.py
git commit -m "feat: add loop_events table to the metrics store"
```

---

### Task 2: `lh metrics loops`

**Files:**
- Modify: `src/lazy_harness/cli/metrics_cmd.py` (append a new `@metrics.command`)
- Test: `tests/unit/cli/test_metrics_loops.py`

**Interfaces:**
- Consumes: `MetricsDB.loop_event_counts(since_ts)` from Task 1.
- Produces: `lh metrics loops [--days N]` — prints a per-kind count table and the declared-goal rate.

- [ ] **Step 1: Write the failing test**

The parameter-less smoke test is not optional here — it is the case that exercises default DB resolution, which is exactly where two `Path.cwd()` bugs have hidden before.

```python
"""Tests for `lh metrics loops`."""

from __future__ import annotations

from pathlib import Path

import pytest
from click.testing import CliRunner

from lazy_harness.cli.metrics_cmd import metrics
from lazy_harness.monitoring.db import MetricsDB


def _seed(db_path: Path) -> None:
    db = MetricsDB(db_path)
    db.record_loop_event(session="s1", kind="goal_declared")
    db.record_loop_event(session="s2", kind="goal_absent")
    db.record_loop_event(session="s3", kind="goal_absent")


def test_reports_counts_and_declared_rate(tmp_path: Path) -> None:
    db_path = tmp_path / "metrics.db"
    _seed(db_path)

    result = CliRunner().invoke(metrics, ["loops", "--db", str(db_path)])

    assert result.exit_code == 0
    assert "goal_declared" in result.output
    assert "33" in result.output, "expected a 33% declared rate (1 of 3)"


def test_reports_zero_rate_without_dividing_by_zero(tmp_path: Path) -> None:
    db_path = tmp_path / "empty.db"
    MetricsDB(db_path)

    result = CliRunner().invoke(metrics, ["loops", "--db", str(db_path)])

    assert result.exit_code == 0
    assert "0" in result.output


def test_runs_with_no_parameters_at_all(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Smoke test: the default DB path must resolve without an explicit --db."""
    monkeypatch.setattr("lazy_harness.cli.metrics_cmd.data_dir", lambda: tmp_path)

    result = CliRunner().invoke(metrics, ["loops"])

    assert result.exit_code == 0, result.output
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/cli/test_metrics_loops.py -v`
Expected: FAIL — `No such command 'loops'`

- [ ] **Step 3: Write minimal implementation**

Append to `src/lazy_harness/cli/metrics_cmd.py`:

```python
@metrics.command("loops")
@click.option("--days", type=int, default=None, help="Only count events from the last N days.")
@click.option("--db", "db_override", type=click.Path(path_type=Path), default=None)
def metrics_loops(days: int | None, db_override: Path | None) -> None:
    """Report loop-event counts and the declared-goal rate."""
    console = Console()

    if db_override is not None:
        db_path = db_override
    else:
        try:
            cfg = load_config(config_file())
        except ConfigError:
            cfg = None
        configured = cfg.monitoring.db if cfg and cfg.monitoring.db else None
        db_path = expand_path(configured) if configured else data_dir() / "metrics.db"

    since = None if days is None else time.time() - days * 86400
    counts = MetricsDB(db_path).loop_event_counts(since_ts=since)

    if not counts:
        console.print("[yellow]no loop events recorded yet.[/yellow]")
        return

    for kind in sorted(counts):
        console.print(f"{kind:<20} {counts[kind]}")

    declared = counts.get("goal_declared", 0)
    considered = declared + counts.get("goal_absent", 0)
    rate = 0 if considered == 0 else round(100 * declared / considered)
    console.print(f"\ndeclared rate: {rate}% ({declared}/{considered})")
```

Add `import time` to the module imports.

The `ConfigError` fallback matters: the smoke test runs without a config file, and a command that only works with one is a command that was never tested at its default.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/cli/test_metrics_loops.py -v`
Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add src/lazy_harness/cli/metrics_cmd.py tests/unit/cli/test_metrics_loops.py
git commit -m "feat: add lh metrics loops"
```

---

### Task 3: Deterministic prompt classifier

**Files:**
- Create: `src/lazy_harness/hooks/builtins/user_prompt_goal.py`
- Test: `tests/unit/hooks/builtins/test_user_prompt_goal.py`

**Interfaces:**
- Consumes: nothing from earlier tasks — pure function, no I/O.
- Produces: `is_non_trivial(prompt: str) -> bool`, used by Task 4.

The classifier runs on every prompt, so it stays pure Python with no LLM call and no file access. Determinism is the requirement, not cleverness.

- [ ] **Step 1: Write the failing test**

```python
"""Tests for the UserPromptSubmit goal hook."""

from __future__ import annotations

import pytest

from lazy_harness.hooks.builtins.user_prompt_goal import is_non_trivial


@pytest.mark.parametrize(
    "prompt",
    [
        "arreglá el bug de canonicalización en compound_loop.py y agregá el test",
        "implement the loop_events table and wire it into metrics_cmd",
        "refactor the ingest path so it stops reading the whole transcript",
    ],
)
def test_treats_substantial_work_requests_as_non_trivial(prompt: str) -> None:
    assert is_non_trivial(prompt) is True


@pytest.mark.parametrize(
    "prompt",
    [
        "gracias",
        "sí",
        "que hora es?",
        "y eso por qué?",
    ],
)
def test_treats_short_conversational_turns_as_trivial(prompt: str) -> None:
    assert is_non_trivial(prompt) is False


def test_a_long_prompt_without_an_action_verb_is_trivial() -> None:
    """Length alone must not trigger: pasted logs and questions are long too."""
    prompt = "no entiendo por qué " + "el output dice eso " * 20
    assert is_non_trivial(prompt) is False


def test_a_short_prompt_naming_a_file_is_non_trivial() -> None:
    assert is_non_trivial("fix db.py") is True


def test_empty_and_whitespace_prompts_are_trivial() -> None:
    assert is_non_trivial("") is False
    assert is_non_trivial("   \n  ") is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/hooks/builtins/test_user_prompt_goal.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'lazy_harness.hooks.builtins.user_prompt_goal'`

- [ ] **Step 3: Write minimal implementation**

```python
"""UserPromptSubmit hook: record whether non-trivial work declares a goal.

Ships as a sensor. Injection is gated behind `[loops] inject_goal_prompt`,
which stays false until a baseline exists — see the phase 0 rationale in
specs/designs/2026-08-16-loop-engineering-design.md.

Fail-soft: every path exits 0. A hook that raises takes down the chain.
"""

from __future__ import annotations

import re

_ACTION_VERBS = frozenset(
    {
        "add",
        "agregá",
        "agrega",
        "arreglá",
        "arregla",
        "build",
        "cableá",
        "cablea",
        "cambiá",
        "cambia",
        "create",
        "escribí",
        "escribe",
        "fix",
        "hacé",
        "hace",
        "implement",
        "implementá",
        "implementa",
        "migrate",
        "migrá",
        "move",
        "refactor",
        "refactorizá",
        "remove",
        "rename",
        "sacá",
        "saca",
        "wire",
    }
)

_FILE_RE = re.compile(r"\b[\w./-]+\.(py|md|toml|yaml|yml|json|sh|lock)\b")
_MIN_CHARS = 25


def is_non_trivial(prompt: str) -> bool:
    """True when the prompt reads like a unit of work rather than a remark.

    Two independent signals, either sufficient: a file reference, or an
    action verb in a prompt long enough to carry a request. Length alone is
    deliberately not a signal — pasted logs and long questions are not work.
    """
    text = prompt.strip()
    if not text:
        return False
    if _FILE_RE.search(text):
        return True
    if len(text) < _MIN_CHARS:
        return False
    words = {word.strip(".,;:!?¿¡\"'()").lower() for word in text.split()}
    return bool(words & _ACTION_VERBS)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/hooks/builtins/test_user_prompt_goal.py -v`
Expected: 10 passed

- [ ] **Step 5: Commit**

```bash
git add src/lazy_harness/hooks/builtins/user_prompt_goal.py tests/unit/hooks/builtins/test_user_prompt_goal.py
git commit -m "feat: add deterministic prompt classifier for goal tracking"
```

---

### Task 4: Hook entry point that records, and never injects

**Files:**
- Modify: `src/lazy_harness/hooks/builtins/user_prompt_goal.py`
- Test: `tests/unit/hooks/builtins/test_user_prompt_goal.py`

**Interfaces:**
- Consumes: `is_non_trivial` (Task 3), `MetricsDB.record_loop_event` (Task 1).
- Produces: `main() -> None` — the hook entry point. Exits 0 on every path, prints nothing.

- [ ] **Step 1: Write the failing test**

The wrong-type cases are the ones that have bitten this codebase before: a `null` `prompt` field parses as valid JSON and then explodes on `.strip()`.

```python
import io
import json
from pathlib import Path


def _run(monkeypatch, payload: object, capsys) -> str:
    from lazy_harness.hooks.builtins import user_prompt_goal as mod

    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(payload)))
    with pytest.raises(SystemExit) as exc:
        mod.main()
    assert exc.value.code == 0
    return capsys.readouterr().out


def test_records_goal_absent_for_non_trivial_work(monkeypatch, tmp_path: Path, capsys) -> None:
    from lazy_harness.hooks.builtins import user_prompt_goal as mod
    from lazy_harness.monitoring.db import MetricsDB

    db_path = tmp_path / "m.db"
    monkeypatch.setattr(mod, "_db_path", lambda: db_path)

    out = _run(
        monkeypatch,
        {"session_id": "s1", "prompt": "implementá el hook y agregá el test", "cwd": "/tmp"},
        capsys,
    )

    assert out == "", "the sensor phase must stay silent"
    assert MetricsDB(db_path).loop_event_counts() == {"goal_absent": 1}


def test_records_nothing_for_a_trivial_prompt(monkeypatch, tmp_path: Path, capsys) -> None:
    from lazy_harness.hooks.builtins import user_prompt_goal as mod
    from lazy_harness.monitoring.db import MetricsDB

    db_path = tmp_path / "m.db"
    monkeypatch.setattr(mod, "_db_path", lambda: db_path)

    _run(monkeypatch, {"session_id": "s1", "prompt": "gracias", "cwd": "/tmp"}, capsys)

    assert MetricsDB(db_path).loop_event_counts() == {}


@pytest.mark.parametrize("prompt", [None, 42, ["a"], {"nested": "dict"}])
def test_exits_zero_on_valid_json_wrong_type(monkeypatch, tmp_path, capsys, prompt) -> None:
    from lazy_harness.hooks.builtins import user_prompt_goal as mod

    monkeypatch.setattr(mod, "_db_path", lambda: tmp_path / "m.db")

    _run(monkeypatch, {"session_id": "s1", "prompt": prompt, "cwd": "/tmp"}, capsys)


def test_exits_zero_on_malformed_json(monkeypatch, tmp_path, capsys) -> None:
    from lazy_harness.hooks.builtins import user_prompt_goal as mod

    monkeypatch.setattr(mod, "_db_path", lambda: tmp_path / "m.db")
    monkeypatch.setattr("sys.stdin", io.StringIO("{not json at all"))

    with pytest.raises(SystemExit) as exc:
        mod.main()
    assert exc.value.code == 0


def test_exits_zero_when_the_database_is_unwritable(monkeypatch, tmp_path, capsys) -> None:
    """A broken metrics store must never take down the session."""
    from lazy_harness.hooks.builtins import user_prompt_goal as mod

    blocked = tmp_path / "file-not-a-dir"
    blocked.write_text("x")
    monkeypatch.setattr(mod, "_db_path", lambda: blocked / "m.db")

    _run(monkeypatch, {"session_id": "s1", "prompt": "fix db.py", "cwd": "/tmp"}, capsys)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/hooks/builtins/test_user_prompt_goal.py -v`
Expected: FAIL — `AttributeError: module ... has no attribute 'main'`

- [ ] **Step 3: Write minimal implementation**

Append to `user_prompt_goal.py`:

```python
import json
import sys
from pathlib import Path


def _read_stdin_json() -> dict[str, object]:
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


def _db_path() -> Path:
    from lazy_harness.core.paths import data_dir

    return data_dir() / "metrics.db"


def main() -> None:
    try:
        payload = _read_stdin_json()
        prompt = payload.get("prompt")
        if not isinstance(prompt, str) or not is_non_trivial(prompt):
            sys.exit(0)

        session = payload.get("session_id")
        cwd = payload.get("cwd")
        from lazy_harness.monitoring.db import MetricsDB

        MetricsDB(_db_path()).record_loop_event(
            session=session if isinstance(session, str) else "",
            kind="goal_absent",
            project=cwd if isinstance(cwd, str) else "",
        )
    except Exception:  # noqa: BLE001 - a hook must degrade, never crash the chain
        pass
    sys.exit(0)


if __name__ == "__main__":
    main()
```

`goal_absent` is unconditional in this phase because nothing yet reports that a goal *was* declared — Task 6 adds the other side. The baseline this produces is the denominator.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/hooks/builtins/test_user_prompt_goal.py -v`
Expected: 18 passed

- [ ] **Step 5: Commit**

```bash
git add src/lazy_harness/hooks/builtins/user_prompt_goal.py tests/unit/hooks/builtins/test_user_prompt_goal.py
git commit -m "feat: record goal_absent from UserPromptSubmit"
```

---

### Task 5: Register and wire the hook, then prove it runs

**Files:**
- Modify: `src/lazy_harness/hooks/loader.py:44-79` (`_BUILTIN_HOOKS`)
- Test: `tests/unit/hooks/test_loader.py` (existing file — add a case)

**Interfaces:**
- Consumes: `user_prompt_goal.main` (Task 4).
- Produces: the hook name `"user-prompt-goal"`, referenced by `config.toml`.

**This is the task the gate exists for.** Registration alone passes every test and never executes; the `config.toml` wiring is what makes it run.

- [ ] **Step 1: Write the failing test**

```python
def test_user_prompt_goal_is_registered() -> None:
    from lazy_harness.hooks.loader import builtin_hook_names

    assert "user-prompt-goal" in builtin_hook_names()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/hooks/test_loader.py -k user_prompt_goal -v`
Expected: FAIL — assertion error, name absent from the registry

- [ ] **Step 3: Write minimal implementation**

Add to `_BUILTIN_HOOKS`, keeping alphabetical order (after `"session-export"`):

```python
    "user-prompt-goal": BuiltinHookSpec(
        module="lazy_harness.hooks.builtins.user_prompt_goal"
    ),
```

No matcher: `UserPromptSubmit` carries no tool name to match against.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/hooks/ -v`
Expected: all pass, including the docs-coherence test that asserts every registered hook is documented. If that test fails, add the hook to the hooks reference page it names — the failure is the gate working.

- [ ] **Step 5: Verify the hook actually executes**

Registration is not execution. After deploying with the **installed** `lh` (never `uv run`, never from a worktree):

```bash
lh deploy
python3 -c "import json;print([h for e,v in json.load(open('$HOME/.claude-lazy/settings.json'))['hooks'].items() if e=='UserPromptSubmit' for h in v])"
```

Expected: an entry whose command path ends in `user_prompt_goal.py`. If `UserPromptSubmit` is absent from `settings.json`, the `config.toml [hooks.user_prompt_submit]` entry is missing — add it and redeploy.

Then send any non-trivial prompt in a fresh session and confirm the sensor fired:

```bash
lh metrics loops
```

Expected: `goal_absent` count greater than zero. A zero count after a real prompt means the hook is registered and not running.

- [ ] **Step 6: Commit**

```bash
git add src/lazy_harness/hooks/loader.py tests/unit/hooks/test_loader.py
git commit -m "feat: register the user-prompt-goal hook"
```

---

### Task 6: Config flag and the injection path

**Files:**
- Modify: `src/lazy_harness/core/config.py` (add the `[loops]` section)
- Modify: `src/lazy_harness/hooks/builtins/user_prompt_goal.py`
- Test: `tests/unit/core/test_config_loops.py`
- Test: `tests/unit/hooks/builtins/test_user_prompt_goal.py`

**Interfaces:**
- Consumes: `is_non_trivial` and `main` (Tasks 3-4).
- Produces: `LoopsConfig.inject_goal_prompt: bool` (default `False`), reachable as `cfg.loops.inject_goal_prompt`.

**Do not flip the default.** This task builds the actuator and leaves it off. Two weeks of baseline first.

- [ ] **Step 1: Write the failing test**

Config changes are tested through a full load cycle, not a successful write — a config that serialises fine and fails to load is the exact failure this gate exists for.

```python
"""Tests for the [loops] config section."""

from __future__ import annotations

from pathlib import Path

from lazy_harness.core.config import load_config


def test_defaults_to_injection_off(tmp_path: Path) -> None:
    cfg_file = tmp_path / "config.toml"
    cfg_file.write_text("")

    cfg = load_config(cfg_file)

    assert cfg.loops.inject_goal_prompt is False


def test_loads_an_explicit_true_through_a_full_cycle(tmp_path: Path) -> None:
    cfg_file = tmp_path / "config.toml"
    cfg_file.write_text("[loops]\ninject_goal_prompt = true\n")

    cfg = load_config(cfg_file)

    assert cfg.loops.inject_goal_prompt is True
```

And, in the hook test file:

```python
def test_injects_only_when_the_flag_is_on(monkeypatch, tmp_path, capsys) -> None:
    from lazy_harness.hooks.builtins import user_prompt_goal as mod

    monkeypatch.setattr(mod, "_db_path", lambda: tmp_path / "m.db")
    monkeypatch.setattr(mod, "_injection_enabled", lambda: True)

    out = _run(
        monkeypatch,
        {"session_id": "s1", "prompt": "implementá el hook y agregá el test", "cwd": "/tmp"},
        capsys,
    )

    payload = json.loads(out)
    assert payload["hookSpecificOutput"]["hookEventName"] == "UserPromptSubmit"
    assert "criterio" in payload["hookSpecificOutput"]["additionalContext"].lower()


def test_stays_silent_when_the_flag_is_off(monkeypatch, tmp_path, capsys) -> None:
    from lazy_harness.hooks.builtins import user_prompt_goal as mod

    monkeypatch.setattr(mod, "_db_path", lambda: tmp_path / "m.db")
    monkeypatch.setattr(mod, "_injection_enabled", lambda: False)

    out = _run(
        monkeypatch,
        {"session_id": "s1", "prompt": "implementá el hook y agregá el test", "cwd": "/tmp"},
        capsys,
    )

    assert out == ""
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/core/test_config_loops.py tests/unit/hooks/builtins/test_user_prompt_goal.py -v`
Expected: FAIL — `AttributeError: 'Config' object has no attribute 'loops'`

- [ ] **Step 3: Write minimal implementation**

Follow the dataclass-plus-default pattern the neighbouring sections in `config.py` already use:

```python
@dataclass
class LoopsConfig:
    inject_goal_prompt: bool = False
```

Register it on the top-level `Config` dataclass as `loops: LoopsConfig = field(default_factory=LoopsConfig)`, and parse it in the same place the other sections are parsed.

In the hook:

```python
def _injection_enabled() -> bool:
    try:
        from lazy_harness.core.config import load_config
        from lazy_harness.core.paths import config_file

        return bool(load_config(config_file()).loops.inject_goal_prompt)
    except Exception:  # noqa: BLE001 - an unreadable config means stay silent
        return False


_INJECTION_TEXT = (
    "Antes de ejecutar: declará el criterio de éxito verificable de esta tarea "
    "(qué comando o comprobación demuestra que está hecha), o usá /goal para fijarlo."
)


def _emit_injection() -> None:
    print(
        json.dumps(
            {
                "hookSpecificOutput": {
                    "hookEventName": "UserPromptSubmit",
                    "additionalContext": _INJECTION_TEXT,
                }
            }
        )
    )
```

In `main`, after recording the event and before `sys.exit(0)`:

```python
        if _injection_enabled():
            _emit_injection()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/core/ tests/unit/hooks/ -v`
Expected: all pass

- [ ] **Step 5: Commit**

```bash
git add src/lazy_harness/core/config.py src/lazy_harness/hooks/builtins/user_prompt_goal.py tests/unit/core/test_config_loops.py tests/unit/hooks/builtins/test_user_prompt_goal.py
git commit -m "feat: gate goal-prompt injection behind a config flag"
```

---

### Task 7: Record the closing side of the loop

**Files:**
- Modify: `src/lazy_harness/hooks/builtins/session_end.py`
- Test: `tests/unit/hooks/builtins/test_session_end.py` (existing file — add cases)

**Interfaces:**
- Consumes: `MetricsDB.record_loop_event` (Task 1).
- Produces: a `session_closed` event per session, giving `lh metrics loops` its session denominator.

- [ ] **Step 1: Write the failing test**

```python
def test_records_session_closed(monkeypatch, tmp_path, capsys) -> None:
    from lazy_harness.hooks.builtins import session_end as mod
    from lazy_harness.monitoring.db import MetricsDB

    db_path = tmp_path / "m.db"
    monkeypatch.setattr(mod, "_loop_db_path", lambda: db_path, raising=False)
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps({"session_id": "s1"})))

    with pytest.raises(SystemExit) as exc:
        mod.main()
    assert exc.value.code == 0

    assert MetricsDB(db_path).loop_event_counts() == {"session_closed": 1}


def test_still_exits_zero_when_recording_fails(monkeypatch, tmp_path, capsys) -> None:
    from lazy_harness.hooks.builtins import session_end as mod

    blocked = tmp_path / "not-a-dir"
    blocked.write_text("x")
    monkeypatch.setattr(mod, "_loop_db_path", lambda: blocked / "m.db", raising=False)
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps({"session_id": "s1"})))

    with pytest.raises(SystemExit) as exc:
        mod.main()
    assert exc.value.code == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/hooks/builtins/test_session_end.py -v`
Expected: FAIL — the recorded counts are empty

- [ ] **Step 3: Write minimal implementation**

Add to `session_end.py`:

```python
def _loop_db_path() -> Path:
    from lazy_harness.core.paths import data_dir

    return data_dir() / "metrics.db"


def _record_session_closed(payload: object) -> None:
    """Never raises: the compound-loop enqueue below must run regardless."""
    try:
        session = payload.get("session_id") if isinstance(payload, dict) else None
        from lazy_harness.monitoring.db import MetricsDB

        MetricsDB(_loop_db_path()).record_loop_event(
            session=session if isinstance(session, str) else "",
            kind="session_closed",
        )
    except Exception:  # noqa: BLE001
        pass
```

Call `_record_session_closed(payload)` in `main()` immediately after the payload is parsed, before the existing compound-loop enqueue. Ordering matters: the new call must not be able to skip the existing behaviour, which is why it swallows everything.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/hooks/builtins/test_session_end.py -v`
Expected: all pass

- [ ] **Step 5: Run the full gate and commit**

```bash
uv run pytest
uv run ruff check src tests
uv run --group docs mkdocs build --strict
git add src/lazy_harness/hooks/builtins/session_end.py tests/unit/hooks/builtins/test_session_end.py
git commit -m "feat: record session_closed loop events"
```

---

## After the plan: the two-week hold

Phase 0 is not complete when the code merges. It is complete when two weeks of data exist.

- [ ] Deploy with the installed `lh` and confirm the sensor fires (Task 5, Step 5).
- [ ] Leave `inject_goal_prompt = false` for two weeks.
- [ ] Run `lh metrics loops --days 14` and record the declared rate as the baseline.
- [ ] Only then flip the flag, and start the four-week clock against the kill criteria in the spec: remove the injection if adoption is zero or signal-to-noise falls below 50%.

"""Byte goldens for `user_prompt_goal`, one per branch, captured pre-migration.

Unlike the four session-lifecycle hooks, this one *has* a channel a golden can
see: with `[loops] inject_goal_prompt` on it writes `additionalContext` on
stdout. That covers exactly one of its branches. Every other branch is silent
on all three channels, so freezing them alone would be satisfied by a `main()`
whose whole body is `return HookDecision()`.

So each case carries a second expectation, `rows`: the `loop_events` this hook
inserted, as `(kind, project, profile)`. That is the only thing the silent
branches say, and it is where both of this migration's real substitutions land
— `payload["cwd"]` becoming `event.cwd`, and `profile_name()` becoming
`event.profile`. Both halves were recorded from the **unmigrated** `main()`.

Branches, read off `main()`:

* the classification gate — a non-trivial prompt, a trivial one, an absent
  prompt and a prompt of the wrong type (the last two share `isinstance`);
* the injection gate — the same non-trivial prompt with `inject_goal_prompt`
  off and on, which is the only pair the wire channels can tell apart;
* the cwd column — a payload naming no `cwd`, which records an *empty* project
  rather than the hook's own process directory;
* the fail-soft path — an unwritable metrics store, which must stay silent and
  record nothing;
* the unusable payload, which decision 3 moves off the "degrade to `{}`" path.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from tests.unit.hooks.builtins._goldens import (
    assert_golden,
    pinned_env,
    run_through_runner,
)

HOOK = "user-prompt-goal"

SESSION = "0193b0de-1111-2222-3333-444455556666"

#: Long enough to clear `_MIN_CHARS` and carrying an action verb, so it is
#: non-trivial through the verb branch rather than the file-reference one.
WORK_PROMPT = "implementá el hook y agregá el test"

#: The profile `[profiles.goldens]` names, which `CLAUDE_CONFIG_DIR` points at.
#: Pre-migration `profile_name()` derives it from that variable; post-migration
#: `resolve_profile(None)` reaches the same helper, so the column is stable
#: across the migration and a change in it is a regression rather than noise.
PROFILE = "goldens"


def _config(*, db: Path, agent_dir: Path, inject: bool) -> str:
    return (
        '[harness]\nversion = "1"\n\n'
        '[agent]\ntype = "claude-code"\n\n'
        f'[monitoring]\nenabled = true\ndb = "{db}"\n\n'
        f'[profiles]\ndefault = "{PROFILE}"\n\n'
        f'[profiles.{PROFILE}]\nconfig_dir = "{agent_dir}"\n\n'
        f"[loops]\ninject_goal_prompt = {str(inject).lower()}\n"
    )


@dataclass(frozen=True)
class Case:
    """One branch of the hook."""

    id: str
    #: `None` omits `prompt` from the payload entirely.
    prompt: object = WORK_PROMPT
    #: `False` omits `prompt` rather than sending the value above.
    declare_prompt: bool = True
    #: `[loops] inject_goal_prompt`.
    inject: bool = False
    #: `False` omits `cwd` from the payload — the empty-project column.
    declare_cwd: bool = True
    #: `True` puts the metrics store behind a regular file, so opening it fails.
    unwritable_db: bool = False
    #: Raw stdin, for the payloads that are not valid JSON objects.
    raw_stdin: str | None = None
    #: `(kind, project, profile)` per recorded row, in insertion order.
    rows: tuple[tuple[str, str, str], ...] = field(default_factory=tuple)


CASES: list[Case] = [
    # --- the classification gate ------------------------------------------- #
    Case(
        id="nontrivial-prompt-records-a-row",
        rows=(("nontrivial_prompt", "<CWD>", PROFILE),),
    ),
    Case(id="trivial-prompt-records-nothing", prompt="gracias"),
    Case(id="prompt-absent-records-nothing", declare_prompt=False),
    Case(id="prompt-wrong-type-records-nothing", prompt=42),
    # --- the injection gate ------------------------------------------------ #
    Case(
        id="injection-enabled-emits-additional-context",
        inject=True,
        rows=(("nontrivial_prompt", "<CWD>", PROFILE),),
    ),
    Case(
        id="injection-enabled-stays-silent-for-a-trivial-prompt",
        prompt="gracias",
        inject=True,
    ),
    # --- the cwd column ----------------------------------------------------- #
    # The project is recorded empty, not resolved against the hook's own
    # process directory: this column is a metrics label, and an unattributed
    # row beats one attributed to whatever directory the agent happened to
    # spawn the hook in.
    Case(
        id="nontrivial-prompt-without-a-cwd-records-an-empty-project",
        declare_cwd=False,
        rows=(("nontrivial_prompt", "", PROFILE),),
    ),
    # --- the fail-soft path -------------------------------------------------- #
    Case(id="unwritable-metrics-store-stays-silent", unwritable_db=True),
    # --- the unusable payload ------------------------------------------------ #
    Case(id="stdin-empty", raw_stdin=""),
    Case(id="stdin-malformed-json", raw_stdin="not json"),
    Case(id="stdin-json-null", raw_stdin="null"),
    Case(id="stdin-json-int", raw_stdin="42"),
    Case(id="stdin-json-list", raw_stdin='["a"]'),
    Case(id="stdin-json-string", raw_stdin='"a string"'),
]

#: The payloads the runner cannot use. Decision 3's right-hand column: exit 0
#: and a warning on stderr, with the builtin never reached.
UNUSABLE_PAYLOAD_CASE_IDS: frozenset[str] = frozenset(
    c.id for c in CASES if c.raw_stdin is not None
)

#: What those six branches wrote on the wire *before* the migration, measured by
#: capturing these goldens against the unmigrated `main()`. Kept as a value
#: rather than as a sentence so that a runner which quietly went back to
#: degrading an unparseable payload to `{}` fails a test instead of a review.
PRE_MIGRATION_UNUSABLE_GOLDEN = {"exit_code": 0, "stderr": "", "stdout": ""}


def _prepare(tmp_path: Path, case: Case) -> tuple[str, dict[str, str], Path, Path]:
    home = tmp_path / "home"
    config_dir = tmp_path / "config"
    data_dir = tmp_path / "data"
    work = tmp_path / "work"
    agent_dir = tmp_path / "claude"
    for d in (home, config_dir, data_dir, work, agent_dir):
        d.mkdir(parents=True, exist_ok=True)

    if case.unwritable_db:
        blocked = tmp_path / "not-a-directory"
        blocked.write_text("x")
        db = blocked / "metrics.db"
    else:
        db = tmp_path / "metrics.db"

    (config_dir / "config.toml").write_text(_config(db=db, agent_dir=agent_dir, inject=case.inject))

    if case.raw_stdin is not None:
        stdin = case.raw_stdin
    else:
        payload: dict[str, object] = {
            "hook_event_name": "UserPromptSubmit",
            "session_id": SESSION,
        }
        if case.declare_prompt:
            payload["prompt"] = case.prompt
        if case.declare_cwd:
            payload["cwd"] = str(work)
        stdin = json.dumps(payload)

    env = pinned_env(
        home=home,
        config_dir=config_dir,
        data_dir=data_dir,
        agent_config_dir=agent_dir,
    )
    return stdin, env, work, db


def _rows(db: Path) -> list[tuple[str, str, str]]:
    if not db.is_file():
        return []
    with sqlite3.connect(db) as conn:
        return conn.execute(
            "SELECT kind, project, profile FROM loop_events ORDER BY rowid"
        ).fetchall()


def _normalise_rows(rows: list[tuple[str, str, str]], *, cwd: Path) -> list[tuple[str, str, str]]:
    """`<CWD>` stands in for the working directory the case ran under.

    `project_key` resolves symlinks, and pytest's `tmp_path` is under
    `/private/var` on macOS while the payload names `/var`, so the literal is
    not stable across platforms. The substitution is against the *resolved*
    path, which is what makes the case below pin that resolution rather than
    hide it.
    """
    resolved = str(cwd.resolve())
    return [
        (kind, "<CWD>" if project == resolved else project, profile)
        for kind, project, profile in rows
    ]


@pytest.mark.parametrize("case", CASES, ids=lambda c: c.id)
def test_golden(case: Case, tmp_path: Path) -> None:
    stdin, env, work, _db = _prepare(tmp_path, case)

    run = run_through_runner(HOOK, stdin_text=stdin, cwd=work, env=env)

    assert_golden(HOOK, case.id, run)


@pytest.mark.parametrize("case", CASES, ids=lambda c: c.id)
def test_the_recorded_rows_are_what_the_silent_branches_say(case: Case, tmp_path: Path) -> None:
    """Twelve of the fourteen wire goldens are empty, so the rows carry the proof.

    Without this a `main()` that returned `HookDecision()` and recorded nothing
    would reproduce every golden file but the two injection ones.
    """
    stdin, env, work, db = _prepare(tmp_path, case)

    run_through_runner(HOOK, stdin_text=stdin, cwd=work, env=env)

    assert _normalise_rows(_rows(db), cwd=work) == list(case.rows)


def test_case_ids_are_unique() -> None:
    ids = [c.id for c in CASES]
    assert len(ids) == len(set(ids))


@pytest.mark.parametrize(
    "case_id",
    [c.id for c in CASES if c.id not in UNUSABLE_PAYLOAD_CASE_IDS and not c.inject],
)
def test_every_usable_branch_with_injection_off_is_silent(case_id: str) -> None:
    """The sensor phase is silent by construction, not by accident.

    `[loops] inject_goal_prompt` defaults to off and stays off until a baseline
    exists (`specs/backlog.md:175`), so a branch that started writing to stdout
    with the flag down would change what every session sees.
    """
    from tests.unit.hooks.builtins._goldens import golden_path

    golden = json.loads(golden_path(HOOK, case_id).read_text())

    assert golden == {"exit_code": 0, "stderr": "", "stdout": ""}


def test_the_injected_context_is_the_only_thing_this_hook_ever_writes() -> None:
    """The one channel a golden can see, pinned to its exact wire shape.

    `hookSpecificOutput.additionalContext` under `hookEventName` is what Claude
    Code's UserPromptSubmit variant accepts; a payload shaped any other way
    fails schema validation and is discarded with the hook marked failed, which
    no exit code would show.
    """
    from tests.unit.hooks.builtins._goldens import golden_path

    golden = json.loads(golden_path(HOOK, "injection-enabled-emits-additional-context").read_text())
    body = json.loads(golden["stdout"])

    assert golden["exit_code"] == 0
    assert golden["stderr"] == ""
    assert set(body) == {"hookSpecificOutput"}
    assert body["hookSpecificOutput"]["hookEventName"] == "UserPromptSubmit"
    assert "criterio de éxito verificable" in body["hookSpecificOutput"]["additionalContext"]


@pytest.mark.parametrize("case_id", sorted(UNUSABLE_PAYLOAD_CASE_IDS))
def test_an_unusable_payload_warns_instead_of_running(case_id: str) -> None:
    """Decision 3's declared divergence, and the only one this migration licenses.

    What it costs here is smaller than for `session-end`, and worth stating
    rather than assuming: before the migration `_read_stdin_json` returned `{}`,
    `payload.get("prompt")` was `None`, the `isinstance` guard refused it and
    the hook exited 0 having recorded nothing. Every one of these six branches
    was already a no-op, so the runner refusing earlier loses no behaviour — it
    changes only the stderr text.
    """
    from tests.unit.hooks.builtins._goldens import golden_path

    golden = json.loads(golden_path(HOOK, case_id).read_text())

    assert golden != PRE_MIGRATION_UNUSABLE_GOLDEN
    assert golden["exit_code"] == 0
    assert golden["stdout"] == ""
    assert "unparseable payload" in golden["stderr"]

"""Byte goldens for `stop_verify_guard`, one per branch, captured pre-migration.

The second hook the design's gate names: this one refuses through *stdout*, by
printing `{"decision": "block", ...}` while still exiting 0. A golden that only
watched stderr and the exit code would see nothing at all here, and a migration
that dropped the JSON would look identical to a migration that kept it.

Branches, read off `main()`, `_injection_enabled()` and `_goal_declared()`:

* the flag gate — no config, flag off, unparseable config (all abstain);
* the session id — absent, empty, not a string;
* the transcript — key absent, file missing, present but carrying no
  `goal_status` attachment, and present with the marker buried behind lines
  `_goal_declared` has to skip past;
* the once-per-session ladder — first Stop blocks, a session with `verify_block`
  already recorded closes silently, a session with `verify_ran` never blocks;
* the swallowed-exception path, reached with a metrics store that cannot open;
* the blocking branch with no usable `cwd`, which takes the other side of the
  project-key guard and must still block.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import pytest

from tests.unit.hooks.builtins._goldens import (
    assert_golden,
    golden_path,
    normalise_run,
    pinned_env,
    run_through_runner,
)

HOOK = "stop-verify-guard"

SESSION = "0193b0de-1111-2222-3333-444455556666"

_CONFIG_ON = '[harness]\nversion = "1"\n\n[loops]\ninject_goal_prompt = true\n'
_CONFIG_OFF = '[harness]\nversion = "1"\n\n[loops]\ninject_goal_prompt = false\n'
_CONFIG_BROKEN = "[loops\ninject_goal_prompt = true"

#: A `/goal` declaration as Claude Code writes it into the transcript.
_GOAL_LINE = json.dumps({"type": "attachment", "attachment": {"type": "goal_status"}})
#: Lines `_goal_declared` must walk past without raising: blank, unparseable,
#: a JSON scalar where a dict is expected, the wrong entry type, and an
#: attachment whose payload is not a mapping.
_NOISE_LINES = [
    "",
    "   ",
    "{not json",
    "42",
    '"a string"',
    json.dumps({"type": "user", "message": "hi"}),
    json.dumps({"type": "attachment", "attachment": "not-a-dict"}),
    json.dumps({"type": "attachment", "attachment": {"type": "something-else"}}),
]


@dataclass(frozen=True)
class Case:
    """One branch of the guard."""

    id: str
    payload: object
    config: str | None = _CONFIG_ON
    #: Lines written to the declared transcript; `None` writes no file at all.
    transcript: list[str] | None = None
    #: Loop events pre-recorded for the session before the hook runs.
    prior_events: tuple[str, ...] = ()
    #: `True` points `[monitoring] db` at a directory, so the store cannot open.
    break_metrics_db: bool = False
    #: Raw stdin, for the payloads that are not valid JSON objects.
    raw_stdin: str | None = None


def _stop_payload(**extra: object) -> dict[str, object]:
    return {"hook_event_name": "Stop", "session_id": SESSION, **extra}


CASES: list[Case] = [
    # --- the flag gate ---------------------------------------------------- #
    Case(id="flag-no-config-at-all", payload=_stop_payload(), config=None),
    Case(id="flag-off", payload=_stop_payload(), config=_CONFIG_OFF),
    Case(id="flag-unparseable-config", payload=_stop_payload(), config=_CONFIG_BROKEN),
    # --- the session id --------------------------------------------------- #
    Case(id="session-id-absent", payload={"hook_event_name": "Stop"}),
    Case(id="session-id-empty", payload={"hook_event_name": "Stop", "session_id": ""}),
    Case(id="session-id-not-a-string", payload={"hook_event_name": "Stop", "session_id": 7}),
    Case(id="stdin-malformed-json", payload=None, raw_stdin="not json"),
    Case(id="stdin-empty", payload=None, raw_stdin=""),
    # --- the transcript --------------------------------------------------- #
    Case(id="transcript-key-absent", payload=_stop_payload()),
    Case(id="transcript-file-missing", payload=None, transcript=None),
    Case(id="transcript-without-goal-marker", payload=None, transcript=_NOISE_LINES),
    # --- the once-per-session ladder -------------------------------------- #
    Case(id="goal-declared-first-stop-blocks", payload=None, transcript=[_GOAL_LINE]),
    Case(
        id="goal-declared-marker-behind-noise",
        payload=None,
        transcript=[*_NOISE_LINES, _GOAL_LINE],
    ),
    Case(
        id="goal-declared-second-stop-closes",
        payload=None,
        transcript=[_GOAL_LINE],
        prior_events=("verify_block",),
    ),
    Case(
        id="goal-declared-verification-already-ran",
        payload=None,
        transcript=[_GOAL_LINE],
        prior_events=("verify_ran",),
    ),
    Case(
        id="goal-declared-verify-ran-outranks-verify-block",
        payload=None,
        transcript=[_GOAL_LINE],
        prior_events=("verify_block", "verify_ran"),
    ),
    # --- the other side of the project-key guard -------------------------- #
    Case(id="goal-declared-blocks-without-cwd", payload=None, transcript=[_GOAL_LINE]),
    # --- the swallowed exception ------------------------------------------ #
    Case(
        id="metrics-store-cannot-open",
        payload=None,
        transcript=[_GOAL_LINE],
        break_metrics_db=True,
    ),
]

#: The payloads the runner cannot use. `stop_verify_guard` is informational —
#: it blocks through stdout with exit 0, not through exit 2 — so decision 3's
#: table gives it the right-hand column: exit 0, a warning on stderr, and no
#: stdout at all, because the hook never ran and has no verdict to report.
UNUSABLE_PAYLOAD_CASE_IDS: frozenset[str] = frozenset(
    {"stdin-empty", "stdin-malformed-json"}
)

#: The branches that actually refuse. Everything else must stay silent.
BLOCKING_CASE_IDS: frozenset[str] = frozenset(
    {
        "goal-declared-first-stop-blocks",
        "goal-declared-marker-behind-noise",
        "goal-declared-blocks-without-cwd",
    }
)

#: Cases whose payload is built during the run because it names a transcript.
_NEEDS_TRANSCRIPT = frozenset(
    c.id for c in CASES if c.payload is None and c.raw_stdin is None
)


def _prepare(tmp_path: Path, case: Case) -> tuple[str, dict[str, str], Path]:
    home = tmp_path / "home"
    config_dir = tmp_path / "config"
    data_dir = tmp_path / "data"
    work = tmp_path / "work"
    sessions = tmp_path / "claude" / "projects" / "-work"
    for d in (home, config_dir, data_dir, work, sessions):
        d.mkdir(parents=True, exist_ok=True)

    db_path = data_dir / "metrics.db"
    config = case.config
    if case.break_metrics_db and config is not None:
        broken = data_dir / "not-a-file.db"
        broken.mkdir()
        config = f'{config}\n[monitoring]\ndb = "{broken}"\n'
    if config is not None:
        (config_dir / "config.toml").write_text(config)

    transcript = sessions / f"{SESSION}.jsonl"
    if case.transcript is not None:
        transcript.write_text("\n".join(case.transcript) + "\n")

    if case.prior_events:
        from lazy_harness.monitoring.db import MetricsDB

        db = MetricsDB(db_path)
        for kind in case.prior_events:
            db.record_loop_event(session=SESSION, kind=kind, project=str(work), profile="")
        db.close()

    if case.raw_stdin is not None:
        stdin = case.raw_stdin
    elif case.payload is not None:
        stdin = json.dumps(case.payload)
    else:
        extra: dict[str, object] = {"transcript_path": str(transcript)}
        if case.id != "goal-declared-blocks-without-cwd":
            extra["cwd"] = str(work)
        stdin = json.dumps(_stop_payload(**extra))

    env = pinned_env(
        home=home,
        config_dir=config_dir,
        data_dir=data_dir,
        agent_config_dir=tmp_path / "claude",
    )
    return stdin, env, work


@pytest.mark.parametrize("case", CASES, ids=lambda c: c.id)
def test_golden(case: Case, tmp_path: Path) -> None:
    stdin, env, work = _prepare(tmp_path, case)

    run = run_through_runner(HOOK, stdin_text=stdin, cwd=work, env=env)

    # The tmp tree never reaches the output, so nothing is normalised here —
    # a rule that fires would mean the hook started leaking a path.
    assert_golden(HOOK, case.id, normalise_run(run, ()))


def test_case_ids_are_unique() -> None:
    ids = [c.id for c in CASES]
    assert len(ids) == len(set(ids))


def test_every_case_that_needs_a_transcript_declares_one() -> None:
    for case in CASES:
        if case.id in _NEEDS_TRANSCRIPT and case.id != "transcript-file-missing":
            assert case.transcript is not None, case.id


@pytest.mark.parametrize("case_id", sorted(BLOCKING_CASE_IDS))
def test_the_block_goes_out_on_stdout_with_exit_0(case_id: str) -> None:
    """This hook blocks by printing, not by exiting non-zero.

    Claude Code reads a Stop hook's verdict off stdout; the exit code stays 0
    because a non-zero Stop hook is a crashed hook, not a refusal.
    """
    golden = json.loads(golden_path(HOOK, case_id).read_text())

    assert golden["exit_code"] == 0
    assert golden["stderr"] == ""
    assert json.loads(golden["stdout"])["decision"] == "block"


@pytest.mark.parametrize(
    "case_id",
    [
        c.id
        for c in CASES
        if c.id not in BLOCKING_CASE_IDS and c.id not in UNUSABLE_PAYLOAD_CASE_IDS
    ],
)
def test_abstention_emits_nothing_at_all(case_id: str) -> None:
    """Every non-blocking branch says nothing — including the second Stop.

    The design's abstention gate: the no-objection branch must not emit an
    explicit `approve`, which would read as a verdict the hook never formed.
    """
    golden = json.loads(golden_path(HOOK, case_id).read_text())

    assert golden == {"exit_code": 0, "stderr": "", "stdout": ""}


@pytest.mark.parametrize("case_id", sorted(UNUSABLE_PAYLOAD_CASE_IDS))
def test_an_unusable_payload_warns_instead_of_abstaining(case_id: str) -> None:
    """Decision 3's table, informational column: exit 0, warning, no stdout.

    The distinction that keeps the flag at `blocking=False`: this hook's refusal
    travels on stdout, so an exit 2 here would change its wire contract rather
    than express the table. What the table does buy is that a payload the runner
    could not read leaves a trace on stderr instead of passing as a clean run.
    """
    golden = json.loads(golden_path(HOOK, case_id).read_text())

    assert golden["exit_code"] == 0
    assert golden["stdout"] == ""
    assert "unparseable payload" in golden["stderr"]


def test_the_block_reason_is_the_hooks_own_constant() -> None:
    """The golden carries the real message, not a paraphrase written by hand."""
    from lazy_harness.hooks.builtins.stop_verify_guard import _BLOCK_REASON

    golden = json.loads(golden_path(HOOK, "goal-declared-first-stop-blocks").read_text())

    assert json.loads(golden["stdout"])["reason"] == _BLOCK_REASON

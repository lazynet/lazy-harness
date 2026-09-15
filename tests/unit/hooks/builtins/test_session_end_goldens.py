"""Byte goldens for `session_end`, one per branch, captured pre-migration.

This hook has no output channel at all: every branch exits 0 with both wire
channels empty. Freezing only those three would therefore freeze nothing — the
same file would be produced by a `main()` that returned immediately. So each
case carries a second expectation, `log`: the `session-end:` lines the hook
appended to the profile's `hooks.log`, which is the only place this hook says
anything. Both halves were recorded from the **unmigrated** `main()`.

Branches, read off `main()` and `_enqueue_compound_loop()`:

* the config gate — no config file, a config without the section, an
  unparseable config, and the section explicitly off (all four skip);
* the transcript search — nothing declared and no session dir, a declared
  transcript that exists, and a declared transcript that does not exist with a
  session JSONL found under the cwd-derived project dir instead;
* the cwd fallback — a payload naming no `cwd` at all, which must still log the
  process directory rather than `.`;
* the unusable payload, which decision 3 moves off the "degrade to `{}`" path.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from tests.unit.hooks.builtins._goldens import (
    assert_golden,
    pinned_env,
    run_through_runner,
)

HOOK = "session-end"

SESSION = "0193b0de-aaaa-bbbb-cccc-ddddeeeeffff"

_HEADER = '[harness]\nversion = "1"\n\n[agent]\ntype = "claude-code"\n'
_CONFIG_ON = f"{_HEADER}\n[compound_loop]\nenabled = true\n"
_CONFIG_OFF = f"{_HEADER}\n[compound_loop]\nenabled = false\n"
_CONFIG_NO_SECTION = _HEADER
_CONFIG_BROKEN = "[compound_loop\nenabled = true"

#: `create_task` names the file after `int(time.time())`, so the queued line
#: carries a clock reading. Only that number is normalised; the rest of the
#: line — the short session id, the `(force)` marker — is compared literally.
_QUEUED = re.compile(r"^queued \d+-(?P<short>[0-9a-f]{8})\.task \(force\)$")


@dataclass(frozen=True)
class Case:
    """One branch of the hook."""

    id: str
    config: str | None = _CONFIG_ON
    #: `True` writes the declared transcript to disk before the hook runs.
    transcript_on_disk: bool = True
    #: `True` names the transcript in the payload.
    declare_transcript: bool = True
    #: `True` drops a session JSONL into the cwd-derived project dir.
    seed_project_dir: bool = False
    #: `False` omits `cwd` from the payload — trap 1 of the migration plan.
    declare_cwd: bool = True
    #: Raw stdin, for the payloads that are not valid JSON objects.
    raw_stdin: str | None = None
    #: `session-end:` log messages, in order, with the timestamp stripped.
    log: tuple[str, ...] = field(default_factory=tuple)


CASES: list[Case] = [
    # --- the config gate --------------------------------------------------- #
    Case(
        id="no-config-at-all",
        config=None,
        log=("fired cwd=<CWD>", "disabled in config, skipping"),
    ),
    Case(
        id="config-without-the-section",
        config=_CONFIG_NO_SECTION,
        log=("fired cwd=<CWD>", "disabled in config, skipping"),
    ),
    Case(
        id="config-unparseable",
        config=_CONFIG_BROKEN,
        log=("fired cwd=<CWD>", "disabled in config, skipping"),
    ),
    Case(
        id="compound-loop-disabled",
        config=_CONFIG_OFF,
        log=("fired cwd=<CWD>", "disabled in config, skipping"),
    ),
    # --- the transcript search --------------------------------------------- #
    Case(
        id="enabled-no-session-jsonl-anywhere",
        transcript_on_disk=False,
        declare_transcript=False,
        log=("fired cwd=<CWD>", "no session JSONL found"),
    ),
    Case(
        id="enabled-declared-transcript-is-queued",
        log=("fired cwd=<CWD>", "<QUEUED>"),
    ),
    Case(
        id="enabled-declared-transcript-missing-falls-back-to-latest",
        transcript_on_disk=False,
        seed_project_dir=True,
        log=("fired cwd=<CWD>", "<QUEUED>"),
    ),
    # --- the cwd fallback (trap 1) ----------------------------------------- #
    Case(
        id="enabled-payload-names-no-cwd",
        declare_cwd=False,
        log=("fired cwd=<CWD>", "<QUEUED>"),
    ),
    # --- the unusable payload ---------------------------------------------- #
    Case(id="stdin-empty", raw_stdin="", log=()),
    Case(id="stdin-malformed-json", raw_stdin="not json", log=()),
    # Valid JSON that is not an object. The old `main()` reached
    # `_record_session_closed` with a `None`/`int`/`list`/`str` and had to guard
    # every `.get()`; `_parse_payload` now refuses the whole class, so the guard
    # moved rather than disappeared and these cases move with it.
    Case(id="stdin-json-null", raw_stdin="null", log=()),
    Case(id="stdin-json-int", raw_stdin="42", log=()),
    Case(id="stdin-json-list", raw_stdin='["a"]', log=()),
    Case(id="stdin-json-string", raw_stdin='"a string"', log=()),
]

#: The payloads the runner cannot use. Decision 3's right-hand column: exit 0
#: and a warning on stderr. Because the hook is never reached it also writes no
#: log line and queues no task — see the test below for what that costs.
UNUSABLE_PAYLOAD_CASE_IDS: frozenset[str] = frozenset(
    c.id for c in CASES if c.raw_stdin is not None
)

#: What those two branches wrote on the wire *before* the migration, measured by
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
    encoded = "-" + str(work).replace("/", "-").lstrip("-")
    sessions = agent_dir / "projects" / encoded
    for d in (home, config_dir, data_dir, work, sessions):
        d.mkdir(parents=True, exist_ok=True)

    if case.config is not None:
        (config_dir / "config.toml").write_text(case.config)

    transcript = sessions / f"{SESSION}.jsonl"
    if case.transcript_on_disk:
        transcript.write_text(json.dumps({"type": "user"}) + "\n")
    if case.seed_project_dir:
        (sessions / "0193b0de-9999-8888-7777-666655554444.jsonl").write_text("{}\n")

    if case.raw_stdin is not None:
        stdin = case.raw_stdin
    else:
        payload: dict[str, object] = {"hook_event_name": "SessionEnd", "session_id": SESSION}
        if case.declare_cwd:
            payload["cwd"] = str(work)
        if case.declare_transcript:
            payload["transcript_path"] = str(transcript)
        stdin = json.dumps(payload)

    env = pinned_env(
        home=home,
        config_dir=config_dir,
        data_dir=data_dir,
        agent_config_dir=agent_dir,
    )
    return stdin, env, work, agent_dir


def _log_messages(agent_dir: Path) -> list[str]:
    """The hook's own lines, timestamp stripped, in the order it wrote them."""
    log_file = agent_dir / "logs" / "hooks.log"
    if not log_file.is_file():
        return []
    out: list[str] = []
    for line in log_file.read_text().splitlines():
        _, sep, msg = line.partition(" session-end: ")
        if sep:
            out.append(msg)
    return out


def _normalise_log(messages: list[str], *, cwd: Path) -> list[str]:
    out: list[str] = []
    for msg in messages:
        if msg == f"fired cwd={cwd}":
            out.append("fired cwd=<CWD>")
            continue
        m = _QUEUED.match(msg)
        if m is not None and m.group("short") == SESSION[:8]:
            out.append("<QUEUED>")
            continue
        out.append(msg)
    return out


@pytest.mark.parametrize("case", CASES, ids=lambda c: c.id)
def test_golden(case: Case, tmp_path: Path) -> None:
    stdin, env, work, _agent_dir = _prepare(tmp_path, case)

    run = run_through_runner(HOOK, stdin_text=stdin, cwd=work, env=env)

    assert_golden(HOOK, case.id, run)


@pytest.mark.parametrize("case", CASES, ids=lambda c: c.id)
def test_the_log_is_the_only_thing_this_hook_says(case: Case, tmp_path: Path) -> None:
    """The wire goldens are empty on every branch, so the log carries the proof.

    Without this a `main()` that returned `HookDecision()` and did nothing else
    would reproduce all ten golden files exactly.
    """
    stdin, env, work, agent_dir = _prepare(tmp_path, case)

    run_through_runner(HOOK, stdin_text=stdin, cwd=work, env=env)

    assert _normalise_log(_log_messages(agent_dir), cwd=work) == list(case.log)


def test_case_ids_are_unique() -> None:
    ids = [c.id for c in CASES]
    assert len(ids) == len(set(ids))


@pytest.mark.parametrize("case_id", [c.id for c in CASES if c.id not in UNUSABLE_PAYLOAD_CASE_IDS])
def test_every_usable_branch_is_silent_on_both_wire_channels(case_id: str) -> None:
    """`session-end` has no output channel: it must never write one by accident."""
    from tests.unit.hooks.builtins._goldens import golden_path

    golden = json.loads(golden_path(HOOK, case_id).read_text())

    assert golden == {"exit_code": 0, "stderr": "", "stdout": ""}


@pytest.mark.parametrize("case_id", sorted(UNUSABLE_PAYLOAD_CASE_IDS))
def test_an_unusable_payload_warns_instead_of_running(case_id: str) -> None:
    """Decision 3's declared divergence, and the only one this migration licenses.

    It costs more here than a log line, which is worth stating because the plan
    does not. Before the migration an unparseable payload still reached
    `main()`: `_declared_transcript(None)` returned `None`, `find_latest_session`
    picked the newest JSONL under the cwd-derived project dir, and the hook
    **enqueued a compound-loop task for it**. Both `stdin-*` cases were measured
    logging `fired` and `queued ... (force)` before the migration. Now the runner
    refuses before the module is imported, so that enqueue is gone.

    Deliberate: the transcript it guessed at was never named by the payload, and
    a SessionEnd hook that cannot read its payload has no session to close.
    """
    from tests.unit.hooks.builtins._goldens import golden_path

    golden = json.loads(golden_path(HOOK, case_id).read_text())

    assert golden != PRE_MIGRATION_UNUSABLE_GOLDEN
    assert golden["exit_code"] == 0
    assert golden["stdout"] == ""
    assert "unparseable payload" in golden["stderr"]


def test_a_payload_cwd_decides_the_logged_directory(tmp_path: Path) -> None:
    """Trap 1's other half: when the payload names a `cwd`, that one wins.

    Before the migration this hook called `Path.cwd()` and never read the
    payload's `cwd` at all, so the two could disagree and the hook would not
    notice. Paired with `enabled-payload-names-no-cwd` above, which holds the
    fallback: together they pin `event.cwd if event.cwd != Path(".") else
    Path.cwd()` and neither half alone does.
    """
    stdin, env, work, agent_dir = _prepare(tmp_path, Case(id="cwd-probe"))
    declared_cwd = tmp_path / "elsewhere"
    declared_cwd.mkdir()
    payload = json.loads(stdin)
    payload["cwd"] = str(declared_cwd)

    run_through_runner(HOOK, stdin_text=json.dumps(payload), cwd=work, env=env)

    assert f"fired cwd={declared_cwd}" in _log_messages(agent_dir)

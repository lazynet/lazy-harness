"""Byte goldens for `compound_loop`, one per branch, captured pre-migration.

This hook has no output channel at all: it drops a task file and spawns a
detached worker, and everything it says it says into `hooks.log`. So the three
channels are empty on every branch, and that emptiness is exactly what the
golden is for — a migration that started printing the queued task's name, or
that let an exception reach stderr, would be invisible to a test that only
looked at the queue.

**An all-empty golden table cannot tell its own branches apart**, which is the
failure mode of a golden over a silent hook: every case would still pass if all
ten took the same early return. So each case also names the `hooks.log` line
its branch writes, and that is asserted beside the bytes. The golden freezes
what the agent sees; the log assertion is what makes the case list honest.

Branches, read off `main()`:

* the config gate — absent, unparseable, and `enabled = false` (all no-op);
* the session lookup — nothing to find, the transcript the payload declares,
  and the one derived from `cwd` when it declares none;
* the two skip ladders — the debounce window, and a session with no new
  activity since the last processed task;
* the payloads the runner cannot parse.

The queued branches spawn the real worker, deliberately: the hook's last act is
a `Popen`, and a golden that mocked it would not cover the only line that can
write to a channel after the task file lands. The staged transcript is one line
long, so the worker skips it long before any inference.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from tests.unit.hooks.builtins._goldens import (
    assert_golden,
    golden_path,
    normalise_run,
    pinned_env,
    run_through_runner,
)

HOOK = "compound-loop"

SESSION = "0197f0de-cafe-4bad-9001-000000000001"

_CONFIG_ON = """\
[harness]
version = "1"

[agent]
type = "claude-code"

[compound_loop]
enabled = true
debounce_seconds = 0
reprocess_min_growth_seconds = 0
"""
_CONFIG_OFF = _CONFIG_ON.replace("enabled = true", "enabled = false")
_CONFIG_DEBOUNCING = _CONFIG_ON.replace("debounce_seconds = 0", "debounce_seconds = 3600")
_CONFIG_NO_REPROCESS = _CONFIG_ON.replace(
    "reprocess_min_growth_seconds = 0", "reprocess_min_growth_seconds = 86400"
)
_CONFIG_BROKEN = "[compound_loop\nenabled = true"


@dataclass(frozen=True)
class Case:
    """One branch of the hook."""

    id: str
    #: Lines this branch is expected to append to `hooks.log`, in order. Empty
    #: means the hook never ran at all — the runner refused before it.
    log: tuple[str, ...]
    config: str | None = _CONFIG_ON
    #: Stage a transcript under the project dir the agent would name.
    transcript: bool = False
    #: Name that transcript in the payload; `False` leaves the cwd-derived
    #: lookup to find it.
    declare_transcript: bool = True
    #: Pre-stage a queued task for `SESSION`, which is what debounce reads.
    queued_task: bool = False
    #: Pre-stage a processed task, which is what the growth check reads.
    done_task: bool = False
    #: Raw stdin, for the payloads that are not valid JSON objects.
    raw_stdin: str | None = None


_FIRED = "fired cwd="
_DISABLED = "disabled in config, skipping"
_NO_SESSION = "no session JSONL found"
_QUEUED = "queued "

CASES: list[Case] = [
    # --- the config gate --------------------------------------------------- #
    Case(id="config-absent", config=None, transcript=True, log=(_FIRED, _DISABLED)),
    Case(id="config-unparseable", config=_CONFIG_BROKEN, transcript=True, log=(_FIRED, _DISABLED)),
    Case(id="disabled-in-config", config=_CONFIG_OFF, transcript=True, log=(_FIRED, _DISABLED)),
    # --- the session lookup ------------------------------------------------ #
    Case(id="no-session-found", transcript=False, log=(_FIRED, _NO_SESSION)),
    Case(id="declared-transcript-queues", transcript=True, log=(_FIRED, _QUEUED)),
    Case(
        id="cwd-derived-transcript-queues",
        transcript=True,
        declare_transcript=False,
        log=(_FIRED, _QUEUED),
    ),
    # --- the skip ladders -------------------------------------------------- #
    Case(
        id="debounced",
        config=_CONFIG_DEBOUNCING,
        transcript=True,
        queued_task=True,
        log=(_FIRED, f"debounce, task already queued for {SESSION[:8]}"),
    ),
    Case(
        id="no-new-activity",
        config=_CONFIG_NO_REPROCESS,
        transcript=True,
        done_task=True,
        log=(_FIRED, f"no new activity since last process for {SESSION[:8]}"),
    ),
    # --- the payloads the runner cannot use -------------------------------- #
    Case(id="stdin-empty", raw_stdin="", log=()),
    Case(id="stdin-malformed-json", raw_stdin="not json", log=()),
]

#: Decision 3's declared divergence: before the migration every builtin
#: degraded an unreadable payload to `{}` and ran anyway; after it the runner
#: refuses before the builtin is reached. This hook is informational, so the
#: refusal is exit 0 plus a warning on stderr rather than exit 2.
UNUSABLE_PAYLOAD_CASE_IDS: frozenset[str] = frozenset({"stdin-empty", "stdin-malformed-json"})

#: The branches that reach `create_task`. Named here so the silence assertion
#: below cannot quietly become a test that every branch bails out early.
QUEUEING_CASE_IDS: frozenset[str] = frozenset(
    {"declared-transcript-queues", "cwd-derived-transcript-queues"}
)


@dataclass(frozen=True)
class Staged:
    """Where the run's artifacts landed, for the assertions after it."""

    stdin: str
    env: dict[str, str]
    work: Path
    agent_dir: Path
    queue: Path = field(default_factory=Path)


def _prepare(tmp_path: Path, case: Case) -> Staged:
    home = tmp_path / "home"
    config_dir = tmp_path / "config"
    data_dir = tmp_path / "data"
    agent_dir = tmp_path / "claude"
    work = tmp_path / "work"
    for d in (home, config_dir, data_dir, work):
        d.mkdir(parents=True, exist_ok=True)
    # Resolved, because the cwd-derived lookup encodes a path into a directory
    # name and the two sides of the comparison must be spelled the same way:
    # `getcwd()` hands the child `/private/var/...` where `tmp_path` says
    # `/var/...`, and the golden would then record a symlink of the test
    # machine's rather than the hook's branch.
    work = work.resolve()

    if case.config is not None:
        (config_dir / "config.toml").write_text(case.config)

    # The agent's own encoding for `work`, which is also the one the hook
    # derives when the payload declares no transcript.
    sessions = agent_dir / "projects" / ("-" + str(work).replace("/", "-").lstrip("-"))
    transcript = sessions / f"{SESSION}.jsonl"
    if case.transcript:
        sessions.mkdir(parents=True, exist_ok=True)
        transcript.write_text('{"type":"user"}\n')

    queue = agent_dir / "queue"
    if case.queued_task:
        queue.mkdir(parents=True, exist_ok=True)
        (queue / f"{int(time.time())}-{SESSION[:8]}.task").write_text("staged\n")
    if case.done_task:
        (queue / "done").mkdir(parents=True, exist_ok=True)
        (queue / "done" / f"{int(time.time())}-{SESSION[:8]}.task").write_text("staged\n")

    if case.raw_stdin is not None:
        stdin = case.raw_stdin
    else:
        payload: dict[str, object] = {
            "hook_event_name": "Stop",
            "session_id": SESSION,
            "cwd": str(work),
        }
        if case.transcript and case.declare_transcript:
            payload["transcript_path"] = str(transcript)
        stdin = json.dumps(payload)

    env = pinned_env(
        home=home,
        config_dir=config_dir,
        data_dir=data_dir,
        agent_config_dir=agent_dir,
    )
    return Staged(stdin=stdin, env=env, work=work, agent_dir=agent_dir, queue=queue)


def _hook_lines(agent_dir: Path) -> list[str]:
    log = agent_dir / "logs" / "hooks.log"
    if not log.is_file():
        return []
    return [line for line in log.read_text().splitlines() if f" {HOOK}: " in line]


@pytest.mark.parametrize("case", CASES, ids=lambda c: c.id)
def test_golden(case: Case, tmp_path: Path) -> None:
    staged = _prepare(tmp_path, case)

    run = run_through_runner(HOOK, stdin_text=staged.stdin, cwd=staged.work, env=staged.env)

    # Nothing is normalised: this hook writes no paths to any channel, so a
    # rule that fired would mean it started leaking one.
    assert_golden(HOOK, case.id, normalise_run(run, ()))


@pytest.mark.parametrize("case", CASES, ids=lambda c: c.id)
def test_the_branch_this_case_names_is_the_branch_it_takes(case: Case, tmp_path: Path) -> None:
    """The discriminating half: the golden is silent, the log is not."""
    staged = _prepare(tmp_path, case)

    run_through_runner(HOOK, stdin_text=staged.stdin, cwd=staged.work, env=staged.env)

    lines = _hook_lines(staged.agent_dir)
    assert len(lines) == len(case.log), f"{case.id}: {lines}"
    for line, expected in zip(lines, case.log, strict=True):
        assert expected in line, case.id


def test_case_ids_are_unique() -> None:
    ids = [c.id for c in CASES]
    assert len(ids) == len(set(ids))


def test_the_queueing_cases_are_the_ones_that_log_a_queued_task() -> None:
    """The two tables agree, so neither can drift into describing nothing."""
    assert QUEUEING_CASE_IDS == frozenset(c.id for c in CASES if _QUEUED in c.log)


@pytest.mark.parametrize("case_id", [c.id for c in CASES if c.id not in UNUSABLE_PAYLOAD_CASE_IDS])
def test_every_usable_branch_is_completely_silent(case_id: str) -> None:
    """The hook's whole contract on the wire: it says nothing, ever.

    Including the branches that queue a task and spawn a worker — the Stop
    payload has no channel for "I queued something", so a line on stdout here
    would reach Claude Code as an unparseable hook response.
    """
    golden = json.loads(golden_path(HOOK, case_id).read_text())

    assert golden == {"exit_code": 0, "stderr": "", "stdout": ""}


@pytest.mark.parametrize("case_id", sorted(UNUSABLE_PAYLOAD_CASE_IDS))
def test_an_unusable_payload_warns_instead_of_running(case_id: str) -> None:
    """Decision 3's informational column: exit 0, a warning, no stdout.

    The one divergence the plan licenses. Before the migration this hook read
    stdin itself, swallowed the `JSONDecodeError` and queued whatever the
    cwd-derived lookup found — the two goldens here were captured showing
    exactly that, and re-captured in the migration commit. Now the runner
    refuses first and says so, and the hook never runs: the `log=()` rows above
    are the other half of that assertion.
    """
    golden = json.loads(golden_path(HOOK, case_id).read_text())

    assert golden["exit_code"] == 0
    assert golden["stdout"] == ""
    assert "unparseable payload" in golden["stderr"]

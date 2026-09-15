"""Byte goldens for `herdr-context-gauge`, one per branch, captured pre-migration.

This hook writes nothing to either wire channel on any branch — `grep -n log
src/lazy_harness/hooks/builtins/herdr_context_gauge.py` returns nothing, and
every path ends at `sys.exit(0)`. Freezing only stdout, stderr and the exit code
would therefore freeze a file that a `main()` returning immediately reproduces
exactly. `session-end` hit the same wall and answered it with a second
expectation; this module does the same, and the second expectation here is the
**`herdr` command line the hook emitted**, recorded by a shim on the pinned PATH.

That second half is the whole point, because of trap 2 of the migration plan:

    `herdr_context_gauge.py:166` reads `hook_event_name` and compares against
    `"PostToolUse"` (`:172`) and `"SessionEnd"` (`:175`). `HookEvent.event`
    holds `post_tool_use` and `session_end`. A direct swap leaves both
    comparisons permanently false.

A swap that leaves the wire-name literals in place turns `session-end-clears`
from `--clear-display-agent` into `--display-agent 🟢 94k` and
`post-tool-use-throttled` from silence into a publish. Neither shows up in an
exit code, in stdout, or in stderr. Both show up here. Both halves were recorded
from the **unmigrated** `main()`.

Branches, read off `main()` (`:158-191`):

* the two ambient gates — `HERDR_ENV != "1"` (`:159`) and an absent
  `HERDR_PANE_ID` (`:161`), which emit no command at all;
* the throttle (`:172`), which applies to `PostToolUse` and to nothing else,
  both sides;
* the `SessionEnd` short-circuit (`:175`), which reaches `clear_command`
  without opening the transcript;
* the publish path at each of `gauge_label`'s three thresholds (`:90-97`);
* an absent transcript, which is the ordinary state at `SessionStart` and
  clears rather than failing.
"""

from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import pytest

from tests.unit.hooks.builtins._goldens import (
    assert_golden,
    pinned_env,
    run_through_runner,
)

HOOK = "herdr-context-gauge"

SESSION = "0193b0de-1111-2222-3333-444455556666"

#: What the shim records when the hook emitted no command at all.
NO_COMMAND: tuple[tuple[str, ...], ...] = ()


def _transcript_line(tokens: int) -> str:
    """One assistant entry whose three input channels sum to `tokens`.

    Split across all three keys rather than loaded onto `input_tokens` alone:
    `_USAGE_INPUT_KEYS` (`:39-43`) sums exactly three, and a fixture that
    exercised one would pass just as happily against a hook that had stopped
    reading the other two.
    """
    cache_read = tokens // 2
    cache_creation = tokens // 4
    return json.dumps(
        {
            "type": "assistant",
            "message": {
                "usage": {
                    "input_tokens": tokens - cache_read - cache_creation,
                    "cache_read_input_tokens": cache_read,
                    "cache_creation_input_tokens": cache_creation,
                }
            },
        }
    )


@dataclass(frozen=True)
class Case:
    """One branch of the hook."""

    id: str
    #: Native wire event name, as the payload carries it.
    event: str
    #: `None` declares no transcript at all; otherwise the window to write.
    tokens: int | None = 94_000
    #: `False` names a transcript in the payload without writing it to disk.
    transcript_on_disk: bool = True
    #: `False` drops `HERDR_ENV=1` from the child's environment.
    in_herdr: bool = True
    #: `False` drops `HERDR_PANE_ID`.
    has_pane: bool = True
    #: `True` writes a fresh stamp for this pane before the hook runs.
    stamped: bool = False
    #: The `herdr` argv the hook is expected to emit, minus the binary name.
    argv: tuple[tuple[str, ...], ...] = NO_COMMAND


_PANE = "w10:p1"

_PUBLISH = ("pane", "report-metadata", _PANE, "--source", "lh:ctx", "--display-agent")
_CLEAR = ("pane", "report-metadata", _PANE, "--source", "lh:ctx", "--clear-display-agent")


CASES: list[Case] = [
    # --- the ambient gates, which emit nothing ----------------------------- #
    Case(id="not-in-herdr", event="Stop", in_herdr=False),
    Case(id="no-pane-id", event="Stop", has_pane=False),
    # --- trap 2's guard: SessionEnd must reach the clear, not the publish --- #
    Case(
        id="session-end-clears",
        event="SessionEnd",
        argv=(_CLEAR,),
    ),
    Case(
        id="session-end-clears-even-with-a-full-transcript",
        event="SessionEnd",
        tokens=673_000,
        argv=(_CLEAR,),
    ),
    # --- the publish path, at each threshold ------------------------------- #
    Case(id="stop-publishes-green", event="Stop", argv=((*_PUBLISH, "🟢 94k"),)),
    Case(id="stop-publishes-amber", event="Stop", tokens=340_000, argv=((*_PUBLISH, "🟡 340k"),)),
    Case(
        id="stop-publishes-red-with-the-verb",
        event="Stop",
        tokens=673_000,
        argv=((*_PUBLISH, "🔴 673k rotar"),),
    ),
    # --- the throttle, which is PostToolUse's and nothing else's ------------ #
    Case(id="post-tool-use-unthrottled", event="PostToolUse", argv=((*_PUBLISH, "🟢 94k"),)),
    Case(id="post-tool-use-throttled", event="PostToolUse", stamped=True),
    Case(
        id="stop-ignores-a-fresh-stamp",
        event="Stop",
        stamped=True,
        argv=((*_PUBLISH, "🟢 94k"),),
    ),
    Case(
        id="session-end-ignores-a-fresh-stamp",
        event="SessionEnd",
        stamped=True,
        argv=(_CLEAR,),
    ),
    # --- SessionStart: publish on resume, clear on a fresh window ---------- #
    Case(id="session-start-resume-publishes", event="SessionStart", argv=((*_PUBLISH, "🟢 94k"),)),
    Case(
        id="session-start-fresh-clears",
        event="SessionStart",
        transcript_on_disk=False,
        argv=(_CLEAR,),
    ),
    # --- an absent or silent transcript clears rather than failing --------- #
    Case(id="no-transcript-declared", event="Stop", tokens=None, argv=(_CLEAR,)),
    Case(
        id="transcript-declared-but-absent",
        event="Stop",
        transcript_on_disk=False,
        argv=(_CLEAR,),
    ),
]


#: Where the shim appends one JSON array per invocation.
_ARGV_LOG = "LH_TEST_HERDR_ARGV_LOG"

_SHIM = """\
import json
import os
import sys

with open(os.environ[{log!r}], "a", encoding="utf-8") as fh:
    fh.write(json.dumps(sys.argv[1:], ensure_ascii=False) + "\\n")
"""


def _install_herdr_shim(bin_dir: Path, log: Path) -> None:
    """A `herdr` on PATH that records its argv instead of talking to a pane.

    Without this the pinned PATH holds git alone, `subprocess.run` raises
    `FileNotFoundError`, `:189` swallows it and every branch produces the same
    three empty channels — a golden that passes against a hook which decided
    nothing. The shim is what makes the decision observable.
    """
    shim = bin_dir / "herdr"
    shim.write_text(
        f"#!{sys.executable}\n" + _SHIM.format(log=_ARGV_LOG),
        encoding="utf-8",
    )
    shim.chmod(shim.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def _recorded(log: Path) -> tuple[tuple[str, ...], ...]:
    if not log.is_file():
        return ()
    return tuple(
        tuple(json.loads(line)) for line in log.read_text(encoding="utf-8").splitlines() if line
    )


def _prepare(tmp_path: Path, case: Case) -> tuple[str, dict[str, str], Path, Path]:
    home = tmp_path / "home"
    config_dir = tmp_path / "config"
    data_dir = tmp_path / "data"
    work = tmp_path / "work"
    agent_dir = tmp_path / "claude"
    bin_dir = tmp_path / "bin"
    # `stamp_path` resolves `tempfile.gettempdir()`, which reads TMPDIR. Left
    # unpinned it lands in the machine's real temp dir, where a stamp from a
    # previous run of this suite decides whether `post-tool-use-unthrottled`
    # publishes — the golden would encode what ran before it.
    tmp_dir = tmp_path / "tmp"
    encoded = "-" + str(work).replace("/", "-").lstrip("-")
    sessions = agent_dir / "projects" / encoded
    for d in (home, config_dir, data_dir, work, sessions, bin_dir, tmp_dir):
        d.mkdir(parents=True, exist_ok=True)

    argv_log = tmp_path / "herdr-argv.log"
    _install_herdr_shim(bin_dir, argv_log)

    transcript = sessions / f"{SESSION}.jsonl"
    if case.transcript_on_disk and case.tokens is not None:
        transcript.write_text(_transcript_line(case.tokens) + "\n", encoding="utf-8")

    if case.stamped:
        # Written through the hook's own helper: a literal path here would keep
        # passing if `stamp_path`'s naming scheme changed under it.
        from lazy_harness.hooks.builtins.herdr_context_gauge import stamp_path

        # Only the file name is reused: `stamp_path` resolves the temp dir in
        # *this* process, whose TMPDIR is not the child's.
        (tmp_dir / stamp_path(_PANE).name).write_text(str(_frozen_now()), encoding="utf-8")

    payload: dict[str, object] = {
        "hook_event_name": case.event,
        "session_id": SESSION,
        "cwd": str(work),
    }
    if case.tokens is not None or not case.transcript_on_disk:
        payload["transcript_path"] = str(transcript)

    git = shutil.which("git")
    assert git is not None, "git is required to capture hook goldens"
    extra = {
        "PATH": os.pathsep.join([str(bin_dir), str(Path(git).parent)]),
        "TMPDIR": str(tmp_dir),
        _ARGV_LOG: str(argv_log),
    }
    if case.in_herdr:
        extra["HERDR_ENV"] = "1"
    if case.has_pane:
        extra["HERDR_PANE_ID"] = _PANE

    env = pinned_env(
        home=home,
        config_dir=config_dir,
        data_dir=data_dir,
        agent_config_dir=agent_dir,
        extra=extra,
    )
    return json.dumps(payload), env, work, argv_log


def _frozen_now() -> float:
    """A stamp reading the hook will always consider current.

    `throttled` (`:119-129`) accepts `0 <= now - last < THROTTLE_SECS`, so a
    stamp dated in the future fails *open* and would un-throttle the case that
    exists to be throttled. `time.time()` at prepare time is a few milliseconds
    before the hook's own reading, which is the only side of that window that
    is stable.
    """
    return time.time()


@pytest.mark.parametrize("case", CASES, ids=lambda c: c.id)
def test_golden(case: Case, tmp_path: Path) -> None:
    stdin, env, work, _log = _prepare(tmp_path, case)

    run = run_through_runner(HOOK, stdin_text=stdin, cwd=work, env=env)

    assert_golden(HOOK, case.id, run)


@pytest.mark.parametrize("case", CASES, ids=lambda c: c.id)
def test_the_emitted_command_is_the_only_thing_this_hook_says(case: Case, tmp_path: Path) -> None:
    """The wire goldens are empty on every branch, so the argv carries the proof.

    This is the assertion trap 2 fails against. A migration that swapped
    `payload.get("hook_event_name")` for `event.event` and left the
    `"SessionEnd"` literal at `:175` in place keeps all sixteen golden files
    byte-identical and turns this list from `--clear-display-agent` into
    `--display-agent 🟢 94k`.
    """
    stdin, env, work, log = _prepare(tmp_path, case)

    run_through_runner(HOOK, stdin_text=stdin, cwd=work, env=env)

    assert _recorded(log) == case.argv


def test_case_ids_are_unique() -> None:
    ids = [c.id for c in CASES]
    assert len(ids) == len(set(ids))


@pytest.mark.parametrize("case_id", [c.id for c in CASES])
def test_every_branch_is_silent_on_both_wire_channels(case_id: str) -> None:
    """This hook has no output channel: it must never grow one by accident.

    A gauge that wrote to stdout would reach the agent as a hook decision; one
    that wrote to stderr would surface in the transcript on every tool call.
    """
    from tests.unit.hooks.builtins._goldens import golden_path

    golden = json.loads(golden_path(HOOK, case_id).read_text())

    assert golden == {"exit_code": 0, "stderr": "", "stdout": ""}


def test_the_shim_is_what_makes_the_argv_observable(tmp_path: Path) -> None:
    """Guard on the fixture itself, not on the hook.

    Every `argv` expectation above is worthless if the shim silently stops
    being found — the hook swallows `FileNotFoundError` at `:189` and exits 0,
    so a broken shim turns all sixteen cases into `()` and only the cases that
    expect `()` would keep passing. This asserts the recording mechanism works
    before any of them are believed.
    """
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log = tmp_path / "argv.log"
    _install_herdr_shim(bin_dir, log)

    subprocess.run(
        [str(bin_dir / "herdr"), "pane", "--display-agent", "🔴 673k rotar"],
        check=True,
        env={**os.environ, _ARGV_LOG: str(log)},
    )

    assert _recorded(log) == (("pane", "--display-agent", "🔴 673k rotar"),)

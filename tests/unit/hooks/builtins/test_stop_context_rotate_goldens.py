"""Byte goldens and effect assertions for `stop-context-rotate`, captured pre-migration.

This hook has a channel the golden can actually see: `{"systemMessage": ...}`
on stdout, top level and never nested. So unlike rows 4-7 of the migration plan
— whose every branch froze to the same empty triple — the emitting branches here
are real evidence, and the silent ones are discriminated by the case beside them
rather than by the filesystem.

One effect still lives off the streams and is asserted separately: the
once-per-session stamp. It is keyed on `session_id` alone and lives in the
system temp dir, so `TMPDIR` is pinned into the child's environment — without
it a stamp left by one case silences the next, and the suite would pass alone
and fail in full.

**The stamp is deliberately not profile-scoped, and that is a conclusion rather
than a copy.** `herdr-context-gauge` keys its throttle on `HERDR_PANE_ID`
because the pane is the resource being rate-limited and two profiles running
sequentially in one pane share it. A once-per-session notice is a different
thing: its key is the session id, which is a uuid the agent mints per session,
so two profiles cannot collide on one and there is nothing for a profile
component to disambiguate. Scoping it per profile would only make the same
session warn twice if it were somehow re-entered under another profile — which
is the noise the stamp exists to prevent.

`cwd` is absent from every payload on purpose: this hook never reads it, so
trap 1 cannot apply to it, and a declared `cwd` would suggest otherwise.
"""

from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest

from lazy_harness.hooks.builtins import stop_context_rotate as hook
from lazy_harness.hooks.builtins.herdr_context_gauge import ROTATE_TOKENS
from lazy_harness.hooks.engine import CLI_BOOTSTRAP
from tests.unit.hooks.builtins._goldens import (
    HookRun,
    assert_golden,
    golden_path,
    normalise_run,
    pinned_env,
    run_through_runner,
)

HOOK = "stop-context-rotate"

SESSION = "0193b0de-1111-2222-3333-444455556666"

_CONFIG_MIN = '[harness]\nversion = "1"\n'

#: Lines `context_tokens` has to walk past without producing a total: blank,
#: unparseable, a JSON scalar where a mapping is expected, a user turn, an
#: assistant turn with no `message`, and one whose `usage` is not a mapping.
_NOISE_LINES = (
    "",
    "{not json",
    "42",
    json.dumps({"type": "user", "message": {"content": "hi"}}),
    json.dumps({"type": "assistant"}),
    json.dumps({"type": "assistant", "message": {"usage": "not-a-mapping"}}),
)


def _usage_line(total: int) -> str:
    return json.dumps(
        {
            "type": "assistant",
            "message": {
                "usage": {
                    "input_tokens": total,
                    "cache_read_input_tokens": 0,
                    "cache_creation_input_tokens": 0,
                }
            },
        }
    )


@dataclass(frozen=True)
class Case:
    """One branch of `stop_context_rotate.main()`."""

    id: str
    #: Lines written to the declared transcript, in order.
    transcript: tuple[str, ...] = ()
    #: Name a `transcript_path` in the payload.
    declare_transcript: bool = True
    #: Write that transcript to disk. Only read when declaring one.
    write_transcript: bool = True
    #: Value for `transcript_path` when it is not the real path.
    transcript_override: object | None = None
    #: `session_id` as the payload carries it; `None` omits the key.
    session_id: object | None = SESSION
    #: Write the stamp for this session before the hook runs.
    pre_stamp: bool = False
    #: Raw stdin, for the payloads that are not JSON objects.
    raw_stdin: str | None = None


_UNDER = (_usage_line(150_000), _usage_line(380_000))
_OVER = (_usage_line(150_000), _usage_line(437_000))
_AT = (_usage_line(ROTATE_TOKENS),)

CASES: list[Case] = [
    # --- the threshold ---------------------------------------------------- #
    Case(id="below-the-threshold", transcript=_UNDER),
    Case(id="at-the-threshold", transcript=_AT),
    Case(id="above-the-threshold", transcript=_OVER),
    # --- the once-per-session ladder -------------------------------------- #
    Case(id="already-warned-this-session", transcript=_OVER, pre_stamp=True),
    # --- the transcript --------------------------------------------------- #
    Case(id="transcript-key-absent", declare_transcript=False),
    Case(id="transcript-declared-but-not-written", transcript=_OVER, write_transcript=False),
    Case(id="transcript-path-not-a-string", transcript_override=7),
    Case(id="transcript-path-empty-string", transcript_override=""),
    Case(id="transcript-without-usage-entries", transcript=_NOISE_LINES),
    Case(id="transcript-with-noise-above-the-usage", transcript=(*_NOISE_LINES, *_OVER)),
    # --- the session id, which only the stamp reads ------------------------ #
    Case(id="session-id-absent", transcript=_OVER, session_id=None),
    Case(id="session-id-not-a-string", transcript=_OVER, session_id=7),
    Case(id="session-id-with-path-separators", transcript=_OVER, session_id="../../escape"),
    # --- stdin the runner cannot use -------------------------------------- #
    Case(id="stdin-empty", raw_stdin=""),
    Case(id="stdin-malformed-json", raw_stdin="not json"),
]

#: The payloads the runner refuses once this hook is migrated. Decision 3's
#: informational column: exit 0, a warning on stderr, no stdout. Before the
#: migration the hook read stdin itself and exited 0 in silence.
UNUSABLE_PAYLOAD_CASE_IDS: frozenset[str] = frozenset({"stdin-empty", "stdin-malformed-json"})

#: The branches that actually emit. Everything else must stay silent.
EMITTING_CASE_IDS: frozenset[str] = frozenset(
    {
        "at-the-threshold",
        "above-the-threshold",
        "transcript-with-noise-above-the-usage",
        "session-id-absent",
        "session-id-not-a-string",
        "session-id-with-path-separators",
    }
)


@dataclass
class World:
    """The tmp tree one case runs in, and where its artifacts should land."""

    work: Path
    tmpdir: Path
    agent_dir: Path
    global_agent_dir: Path
    env: dict[str, str]
    stdin: str

    def stamps(self) -> list[Path]:
        return sorted(p for p in self.tmpdir.iterdir() if p.is_file())


def _stamp_path(tmpdir: Path, session: object) -> Path:
    """The stamp the hook would write, named by the hook's own rule.

    `_stamp_for` is asked rather than the name spelled out again here: the
    sanitisation is the thing under test in one of the cases, and a second
    spelling of it would agree with itself while disagreeing with the hook.
    """
    key = session if isinstance(session, str) else ""
    original = hook.stamp_dir
    try:
        hook.stamp_dir = lambda: tmpdir  # type: ignore[assignment]
        return hook._stamp_for(key)
    finally:
        hook.stamp_dir = original  # type: ignore[assignment]


def _build(tmp_path: Path, case: Case, *, profile: str | None = None) -> World:
    """Lay out one case's tree and return the probes for it.

    `profile` writes a `[profiles.<name>] config_dir` **and clears
    `CLAUDE_CONFIG_DIR`**: `agent_runtime_dir` resolves the adapter's env var
    above the profile's `config_dir` (ADR-032 L3), so leaving it set makes the
    global answer and the per-profile answer the same path and an absence
    assertion could never fail.
    """
    home = tmp_path / "home"
    config_dir = tmp_path / "config"
    data_dir = tmp_path / "data"
    work = tmp_path / "work"
    tmpdir = tmp_path / "tmp"
    env_agent_dir = tmp_path / "claude-global"
    global_agent_dir = home / ".claude" if profile else env_agent_dir
    agent_dir = tmp_path / f"claude-{profile}" if profile else env_agent_dir
    for d in (home, config_dir, data_dir, work, tmpdir, agent_dir, env_agent_dir):
        d.mkdir(parents=True, exist_ok=True)

    config = _CONFIG_MIN
    if profile is not None:
        config += f'\n[profiles.{profile}]\nconfig_dir = "{agent_dir}"\nroots = ["~"]\n'
    (config_dir / "config.toml").write_text(config)

    transcript = work / "transcript.jsonl"
    if case.declare_transcript and case.write_transcript and case.transcript_override is None:
        transcript.write_text("\n".join(case.transcript) + "\n", encoding="utf-8")

    if case.pre_stamp:
        _stamp_path(tmpdir, case.session_id).write_text("1", encoding="utf-8")

    env = pinned_env(
        home=home,
        config_dir=config_dir,
        data_dir=data_dir,
        agent_config_dir=env_agent_dir,
        extra={"TMPDIR": str(tmpdir)},
    )
    if profile is not None:
        env["CLAUDE_CONFIG_DIR"] = ""

    if case.raw_stdin is not None:
        stdin = case.raw_stdin
    else:
        payload: dict[str, object] = {"hook_event_name": "Stop"}
        if case.session_id is not None:
            payload["session_id"] = case.session_id
        if case.transcript_override is not None:
            payload["transcript_path"] = case.transcript_override
        elif case.declare_transcript:
            payload["transcript_path"] = str(transcript)
        stdin = json.dumps(payload)

    return World(
        work=work,
        tmpdir=tmpdir,
        agent_dir=agent_dir,
        global_agent_dir=global_agent_dir,
        env=env,
        stdin=stdin,
    )


def _run(world: World, *, profile: str | None = None) -> HookRun:
    if profile is None:
        return run_through_runner(HOOK, stdin_text=world.stdin, cwd=world.work, env=world.env)
    proc = subprocess.run(
        [sys.executable, "-c", CLI_BOOTSTRAP, "hook", HOOK, "--profile", profile],
        input=world.stdin,
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=str(world.work),
        env=world.env,
        timeout=60,
        check=False,
    )
    return HookRun(stdout=proc.stdout, stderr=proc.stderr, exit_code=proc.returncode)


def _files_under(root: Path) -> set[Path]:
    return {p.relative_to(root) for p in root.rglob("*") if p.is_file()}


@pytest.mark.parametrize("case", CASES, ids=lambda c: c.id)
def test_golden(case: Case, tmp_path: Path) -> None:
    world = _build(tmp_path, case)

    run = _run(world)

    # Nothing in the tmp tree may reach either stream; a normalisation rule
    # that fired would mean this hook had started leaking a path.
    assert_golden(HOOK, case.id, normalise_run(run, ()))


def test_case_ids_are_unique() -> None:
    ids = [c.id for c in CASES]
    assert len(ids) == len(set(ids))


def test_every_emitting_case_is_declared_over_the_threshold() -> None:
    """The two sets above must not drift apart from the fixtures they describe.

    A case that names `_OVER` but is left out of `EMITTING_CASE_IDS` would be
    asserted silent, and the golden would agree with it — which is how a broken
    threshold reads as a passing suite.
    """
    for case in CASES:
        carries_a_qualifying_turn = any(
            str(ROTATE_TOKENS) in line or str(437_000) in line for line in case.transcript
        )
        expected = carries_a_qualifying_turn and not case.pre_stamp and case.write_transcript
        assert (case.id in EMITTING_CASE_IDS) is expected, case.id


@pytest.mark.parametrize("case_id", sorted(EMITTING_CASE_IDS))
def test_an_emitting_branch_puts_a_top_level_system_message_on_stdout(case_id: str) -> None:
    """The channel the operator actually reads, asserted on the frozen bytes.

    `systemMessage` is top level, sibling to `hookSpecificOutput` and never
    inside it: `hookSpecificOutput` takes exactly four keys (verified against
    the 2.1.269 binary) and discards the rest, so a nested one would parse,
    stamp, and display nothing.
    """
    golden = json.loads(golden_path(HOOK, case_id).read_text())

    assert golden["exit_code"] == 0
    assert golden["stderr"] == ""
    body = json.loads(golden["stdout"])
    assert set(body) == {"systemMessage"}
    assert "decision" not in body
    assert "hookSpecificOutput" not in body


@pytest.mark.parametrize(
    "case_id",
    [
        c.id
        for c in CASES
        if c.id not in EMITTING_CASE_IDS and c.id not in UNUSABLE_PAYLOAD_CASE_IDS
    ],
)
def test_a_silent_branch_writes_on_neither_stream(case_id: str) -> None:
    golden = json.loads(golden_path(HOOK, case_id).read_text())

    assert golden == {"exit_code": 0, "stderr": "", "stdout": ""}


@pytest.mark.parametrize("case_id", sorted(UNUSABLE_PAYLOAD_CASE_IDS))
def test_an_unusable_payload_warns_instead_of_running_silently(case_id: str) -> None:
    """The one licensed golden divergence, named rather than re-captured quietly.

    Decision 3's informational column: the runner refuses a payload it cannot
    parse before the builtin is reached, so these two goldens carry a warning
    on stderr where the pre-runner path read stdin itself and exited 0 without
    a word. Nothing is lost — the hook had no transcript to measure either way.
    """
    golden = json.loads(golden_path(HOOK, case_id).read_text())

    assert golden["exit_code"] == 0
    assert golden["stdout"] == ""
    assert golden["stderr"].startswith(f"{HOOK}: unparseable payload")


def test_the_golden_carries_the_hooks_own_notice(tmp_path: Path) -> None:
    """The frozen message is the hook's, not a paraphrase written by hand."""
    golden = json.loads(golden_path(HOOK, "above-the-threshold").read_text())

    body = json.loads(golden["stdout"])

    assert body["systemMessage"] == hook.notice(437_000)
    assert "437k" in body["systemMessage"]


def test_the_threshold_branch_fires_at_the_threshold_itself() -> None:
    """`>= ROTATE_TOKENS`, not `>`. The boundary is the whole point of the hook."""
    golden = json.loads(golden_path(HOOK, "at-the-threshold").read_text())

    assert json.loads(golden["stdout"])["systemMessage"] == hook.notice(ROTATE_TOKENS)


def test_the_notice_writes_the_stamp_and_a_second_stop_stays_silent(tmp_path: Path) -> None:
    """The effect the golden cannot see, on the ladder it gates.

    Two runs of one case rather than two cases: the stamp is what makes the
    second run silent, so asserting it from the outside would only restate the
    fixture the `already-warned` case sets up by hand.
    """
    case = next(c for c in CASES if c.id == "above-the-threshold")
    world = _build(tmp_path, case)

    first = _run(world)
    stamp = _stamp_path(world.tmpdir, SESSION)
    assert first.exit_code == 0, first.stderr
    assert "systemMessage" in first.stdout
    assert stamp.is_file()

    second = _run(world)

    assert second.exit_code == 0, second.stderr
    assert second.stdout == ""
    assert world.stamps() == [stamp]


def test_a_session_id_carrying_separators_cannot_escape_the_stamp_dir(tmp_path: Path) -> None:
    """`_stamp_for` sanitises, so a payload cannot name a path outside the dir.

    The golden only shows that the notice went out; where the stamp landed is
    invisible to it, and a session id is agent-supplied input.
    """
    case = next(c for c in CASES if c.id == "session-id-with-path-separators")
    world = _build(tmp_path, case)

    run = _run(world)

    assert run.exit_code == 0, run.stderr
    stamps = world.stamps()
    assert len(stamps) == 1
    assert stamps[0].parent == world.tmpdir
    assert "/" not in stamps[0].name


def test_the_notice_writes_nothing_into_any_agent_directory(tmp_path: Path) -> None:
    """This hook resolves no agent dir at all, and must keep not resolving one.

    Recipe step 7 asserts a `hooks.log` line lands in the invoked profile's
    directory and nowhere else. `stop-context-rotate` writes no log, loads no
    config and never calls `agent_dir_for`, so there is no line to place — the
    assertion that carries meaning here is the other half: running under
    `--profile gate` must leave both the profile's directory and the global one
    exactly as they were. Stated as a fence, not as evidence of a fix: it
    passes against the unmigrated hook too, because the unmigrated hook also
    wrote nothing there.
    """
    case = next(c for c in CASES if c.id == "above-the-threshold")
    world = _build(tmp_path, case, profile="gate")
    before_profile = _files_under(world.agent_dir)
    before_global = (
        _files_under(world.global_agent_dir) if world.global_agent_dir.exists() else set()
    )

    run = _run(world, profile="gate")

    # Without this the absence assertions below pass on a hook that never ran.
    assert run.exit_code == 0, run.stderr
    assert "systemMessage" in run.stdout
    assert _files_under(world.agent_dir) == before_profile
    assert (
        _files_under(world.global_agent_dir) if world.global_agent_dir.exists() else set()
    ) == before_global

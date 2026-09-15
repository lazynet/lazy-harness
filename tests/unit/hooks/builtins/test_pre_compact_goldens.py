"""Byte goldens and effect assertions for `pre-compact`, captured pre-migration.

This hook is the only one in step 5 whose channel is **plain text**: Claude
Code's `hookSpecificOutput` union has no PreCompact variant, so the executor
joins each successful hook's raw stdout into `newCustomInstructions`. When a
summary exists the golden is real evidence — the bytes the summariser receives.

**When no summary exists it degenerates**, and that is the trap this file is
built around: an empty memory dir makes every channel `{"exit_code": 0,
"stderr": "", "stdout": ""}`, which a `main()` whose whole body is `return
HookDecision()` reproduces. For those cases the evidence lives off the
filesystem instead, in the three things this hook writes and nothing else does:

* `<agent dir>/logs/hooks.log` — `fired`, then one of `summary written`,
  `no summary extracted` or `backed up transcript to …`;
* `<memory dir>/pre-compact-summary.md` — the summary `context-inject` reads
  back at the next SessionStart;
* `<agent dir>/compact-backups/<ts>-<project>.jsonl` — the raw transcript copy.

Two of the three are keyed by the agent runtime dir, which is what makes them
the probe for profile isolation as well: a hook that resolves the agent globally
writes them into the global directory no matter which `--profile` invoked it.
"""

from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from lazy_harness.hooks.engine import CLI_BOOTSTRAP
from tests.unit.hooks.builtins._goldens import (
    HookRun,
    assert_golden,
    golden_path,
    normalise_run,
    pinned_env,
    run_through_runner,
)

HOOK = "pre-compact"

SESSION = "0193b0de-1111-2222-3333-444455556666"

_CONFIG_MIN = '[harness]\nversion = "1"\n'
_CONFIG_BROKEN = "[memory.engram\nbinary = 1"

#: Entries in the shape `compound_loop` appends to the two memory JSONLs.
_DECISIONS = (
    {"ts": "2026-09-01T00:00:00Z", "summary": "resolve the profile in the writer"},
    {"ts": "2026-09-02T00:00:00Z", "summary": "keep the plain-text channel"},
)
_FAILURES = ({"ts": "2026-09-03T00:00:00Z", "summary": "the reader stayed global"},)

#: A transcript line in the shape `parse_transcript` was written against:
#: `role` and `content` at the *top level*. No Claude Code release emits this
#: (`specs/backlog.md:125`), so this fixture is the only thing on the machine
#: that makes those two loops produce anything at all. Literal paths, never
#: `tmp_path`: `parse_transcript` puts `file_path` on stdout, and a temp path
#: there would encode the capturing machine into the golden.
_LEGACY_TRANSCRIPT = (
    {"role": "user", "content": "migrate the pre-compact hook onto the event contract"},
    {
        "role": "assistant",
        "content": [
            {"type": "tool_use", "input": {"file_path": "/srv/app/pre_compact.py"}},
            {"type": "tool_use", "input": {"path": "/srv/app/loader.py"}},
        ],
    },
)

#: The same content in the shape Claude Code actually emits — both keys nested
#: under `message`. `parse_transcript` reads the top level, so this yields
#: nothing, and the golden for it is the measurement rather than an assertion
#: about it. Repairing the parser is out of scope (`specs/backlog.md:125`).
_REAL_TRANSCRIPT = (
    {"type": "user", "message": {"role": "user", "content": "migrate the pre-compact hook"}},
    {
        "type": "assistant",
        "message": {
            "role": "assistant",
            "content": [{"type": "tool_use", "input": {"file_path": "/srv/app/pre_compact.py"}}],
        },
    },
)


@dataclass(frozen=True)
class Case:
    """One branch of `pre_compact.main()`."""

    id: str
    config: str | None = _CONFIG_MIN
    #: Entries pre-written to the resolved memory dir.
    decisions: tuple[dict, ...] = ()
    failures: tuple[dict, ...] = ()
    #: Lines to write into the declared transcript, if any.
    transcript: tuple[dict, ...] = ()
    #: Name a `transcript_path` in the payload.
    declare_transcript: bool = False
    #: Write that transcript to disk. Only read when declaring one.
    write_transcript: bool = True
    #: Name `cwd` in the payload. `False` is trap 1's input.
    declare_cwd: bool = True
    #: Raw stdin, for the payloads that are not JSON objects.
    raw_stdin: str | None = None


CASES: list[Case] = [
    Case(id="empty-memory-dir"),
    # Both degradation branches carry tails, so they measure *where* the hook
    # resolved its memory dir without a config rather than only that it exited
    # 0. With no entries every branch of this hook produces the same empty
    # golden, and a case that cannot tell the two apart is not a case.
    Case(id="no-config-at-all", config=None, decisions=_DECISIONS),
    Case(id="config-unparseable", config=_CONFIG_BROKEN, decisions=_DECISIONS),
    Case(id="memory-tails-only", decisions=_DECISIONS, failures=_FAILURES),
    Case(id="decisions-without-failures", decisions=_DECISIONS),
    Case(
        id="transcript-in-the-legacy-shape",
        decisions=_DECISIONS,
        failures=_FAILURES,
        declare_transcript=True,
        transcript=_LEGACY_TRANSCRIPT,
    ),
    Case(
        id="transcript-in-the-shape-claude-code-emits",
        decisions=_DECISIONS,
        declare_transcript=True,
        transcript=_REAL_TRANSCRIPT,
    ),
    Case(
        id="transcript-declared-but-not-written",
        decisions=_DECISIONS,
        declare_transcript=True,
        transcript=_LEGACY_TRANSCRIPT,
        write_transcript=False,
    ),
    Case(id="cwd-absent-from-the-payload", decisions=_DECISIONS, declare_cwd=False),
    Case(id="stdin-empty", raw_stdin=""),
    Case(id="stdin-malformed-json", raw_stdin="not json"),
]

#: The payloads the runner refuses once this hook is migrated. Decision 3's
#: informational column: exit 0, a warning on stderr, no stdout. Before the
#: migration the pre-runner path degraded them to `{}` and ran the hook.
UNUSABLE_PAYLOAD_CASE_IDS: frozenset[str] = frozenset({"stdin-empty", "stdin-malformed-json"})

#: Cases whose stdout is empty, so the golden alone discriminates nothing and
#: the evidence has to come off the filesystem.
SILENT_CASE_IDS: frozenset[str] = frozenset({"empty-memory-dir", *UNUSABLE_PAYLOAD_CASE_IDS})


@dataclass
class World:
    """The tmp tree one case runs in, and where its artifacts should land."""

    work: Path
    agent_dir: Path
    global_agent_dir: Path
    env: dict[str, str] = field(default_factory=dict)
    stdin: str = "{}"

    @property
    def log_file(self) -> Path:
        return self.agent_dir / "logs" / "hooks.log"

    @property
    def memory_dir(self) -> Path:
        return self.agent_dir / "projects" / _encoded(self.work) / "memory"

    @property
    def summary_file(self) -> Path:
        return self.memory_dir / "pre-compact-summary.md"

    @property
    def backup_dir(self) -> Path:
        return self.agent_dir / "compact-backups"

    def log_lines(self) -> list[str]:
        if not self.log_file.is_file():
            return []
        return [ln for ln in self.log_file.read_text(encoding="utf-8").splitlines() if ln.strip()]

    def logged(self, needle: str) -> bool:
        return any(needle in line for line in self.log_lines())

    def backups(self) -> list[Path]:
        if not self.backup_dir.is_dir():
            return []
        return sorted(self.backup_dir.glob("*.jsonl"))


def _encoded(path: Path) -> str:
    return "-" + str(path).replace("/", "-").lstrip("-")


def _jsonl(entries: tuple[dict, ...]) -> str:
    return "".join(json.dumps(e, sort_keys=True) + "\n" for e in entries)


def _build(tmp_path: Path, case: Case, *, profile: str | None = None) -> World:
    """Lay out one case's tree and return the probes for it.

    `work` is realpath'd. `Path.cwd()` is symlink-resolved and a payload's
    `cwd` is not, and this hook encodes that string into a *directory name* —
    so a `tmp_path` left unresolved would make the pre-migration run (which
    reads `Path.cwd()`) and the migrated one (which reads `event.cwd`) pick
    different project dirs while every frozen channel stayed byte-identical.
    Resolving here stops the fixture from hiding that; it is not a fix to the
    hook, which is right to name the directory the way the agent saw it.

    `profile` writes a `[profiles.<name>] config_dir` **and clears
    `CLAUDE_CONFIG_DIR`**: `agent_runtime_dir` resolves the adapter's env var
    above the profile's `config_dir` (ADR-032 L3), so leaving it set makes both
    answers the same path and the absence half of the isolation assertion can
    never fail.
    """
    home = tmp_path / "home"
    config_dir = tmp_path / "config"
    data_dir = tmp_path / "data"
    work = tmp_path / "work"
    env_agent_dir = tmp_path / "claude-global"
    global_agent_dir = home / ".claude" if profile else env_agent_dir
    agent_dir = tmp_path / f"claude-{profile}" if profile else env_agent_dir
    for d in (home, config_dir, data_dir, work, agent_dir, env_agent_dir):
        d.mkdir(parents=True, exist_ok=True)
    work = work.resolve()

    config = case.config
    if config is not None and config != _CONFIG_BROKEN and profile is not None:
        config += f'\n[profiles.{profile}]\nconfig_dir = "{agent_dir}"\nroots = ["~"]\n'
    if config is not None:
        (config_dir / "config.toml").write_text(config)

    # Written where the hook will look for them rather than the other way
    # round: the memory dir is the agent's project dir for this cwd.
    memory = agent_dir / "projects" / _encoded(work) / "memory"
    if case.decisions or case.failures:
        memory.mkdir(parents=True, exist_ok=True)
        if case.decisions:
            (memory / "decisions.jsonl").write_text(_jsonl(case.decisions))
        if case.failures:
            (memory / "failures.jsonl").write_text(_jsonl(case.failures))

    transcript = agent_dir / "projects" / _encoded(work) / f"{SESSION}.jsonl"
    if case.declare_transcript and case.write_transcript:
        transcript.parent.mkdir(parents=True, exist_ok=True)
        transcript.write_text(_jsonl(case.transcript))

    env = pinned_env(
        home=home,
        config_dir=config_dir,
        data_dir=data_dir,
        agent_config_dir=env_agent_dir,
    )
    if profile is not None:
        env["CLAUDE_CONFIG_DIR"] = ""

    if case.raw_stdin is not None:
        stdin = case.raw_stdin
    else:
        payload: dict[str, object] = {"hook_event_name": "PreCompact", "session_id": SESSION}
        if case.declare_cwd:
            payload["cwd"] = str(work)
        if case.declare_transcript:
            payload["transcript_path"] = str(transcript)
        stdin = json.dumps(payload)

    return World(
        work=work,
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


@pytest.mark.parametrize("case_id", sorted(SILENT_CASE_IDS))
def test_a_branch_with_no_summary_writes_nothing_on_either_stream(case_id: str) -> None:
    """Named rather than left implicit in the golden files.

    These are the cases where the golden proves only that nothing reached
    stdout — true of a deleted hook too. Stated here so a migration that
    started emitting on them shows up as one broken contract rather than as
    four one-line golden diffs a reviewer re-captures without reading.
    """
    golden = json.loads(golden_path(HOOK, case_id).read_text())

    assert golden["exit_code"] == 0
    assert golden["stdout"] == ""


@pytest.mark.parametrize("case_id", [c.id for c in CASES if c.id not in SILENT_CASE_IDS])
def test_a_branch_with_a_summary_puts_the_preamble_on_stdout(case_id: str) -> None:
    """The channel the compaction summariser actually reads.

    Plain text, never JSON: a JSON payload on PreCompact fails Claude Code's
    schema validation, which marks the hook failed and discards its output
    (ADR-036 D2). Asserting it does not parse is what pins that.
    """
    from lazy_harness.hooks.builtins.pre_compact import SUMMARY_PREAMBLE

    golden = json.loads(golden_path(HOOK, case_id).read_text())

    assert golden["exit_code"] == 0
    assert golden["stderr"] == ""
    assert golden["stdout"].startswith(SUMMARY_PREAMBLE)
    with pytest.raises(json.JSONDecodeError):
        json.loads(golden["stdout"])


@pytest.mark.parametrize("case_id", sorted(UNUSABLE_PAYLOAD_CASE_IDS))
def test_an_unusable_payload_warns_instead_of_running_silently(case_id: str) -> None:
    """The one licensed golden divergence, named rather than re-captured quietly.

    Decision 3's informational column: the runner refuses a payload it cannot
    parse before the builtin is reached, so these two goldens carry a warning
    on stderr where the pre-runner path degraded the payload to `{}` and let
    the hook run against `Path.cwd()`. Everything that run would have written —
    a memory dir, a `fired` line — was keyed by whatever directory the agent
    happened to spawn it from, which is what makes the refusal an improvement
    rather than a loss.
    """
    golden = json.loads(golden_path(HOOK, case_id).read_text())

    assert golden["exit_code"] == 0
    assert golden["stdout"] == ""
    assert golden["stderr"].startswith(f"{HOOK}: unparseable payload")


def test_the_memory_tails_reach_both_stdout_and_the_summary_file(tmp_path: Path) -> None:
    """The part of this hook that has always worked, on both its outputs.

    `build_memory_tails` is the only producer the transcript parser does not
    gate, so it is what the plain-text channel actually carries in production.
    The file half is what `context-inject` reads back at the next SessionStart.
    """
    case = next(c for c in CASES if c.id == "memory-tails-only")
    world = _build(tmp_path, case)

    run = _run(world)

    assert run.exit_code == 0, run.stderr
    assert "## Recent decisions" in run.stdout
    assert "keep the plain-text channel" in run.stdout
    assert "## Recent failures" in run.stdout
    assert "the reader stayed global" in run.stdout

    body = world.summary_file.read_text(encoding="utf-8")
    assert body.startswith("<!-- auto-generated by pre-compact hook at ")
    assert "keep the plain-text channel" in body
    assert world.logged("pre-compact: summary written (")


def test_an_empty_memory_dir_produces_the_directory_and_a_log_line_and_nothing_else(
    tmp_path: Path,
) -> None:
    """The degenerate golden's real evidence.

    `{exit 0, "", ""}` is reproduced by a `main()` that does nothing at all, so
    the assertion has to be on what reached disk: the memory dir exists, the
    hook logged why it stayed silent, and it wrote no summary.
    """
    case = next(c for c in CASES if c.id == "empty-memory-dir")
    world = _build(tmp_path, case)

    run = _run(world)

    assert run.exit_code == 0, run.stderr
    assert run.stdout == ""
    assert world.memory_dir.is_dir()
    assert world.logged(f"pre-compact: fired cwd={world.work}")
    assert world.logged("pre-compact: no summary extracted")
    assert not world.summary_file.exists()


def test_a_written_transcript_is_copied_into_compact_backups(tmp_path: Path) -> None:
    """The second filesystem effect, and the one no channel shows.

    Named after the cwd's basename, which is why the fixture's `work` directory
    has one rather than being `tmp_path` itself.
    """
    case = next(c for c in CASES if c.id == "transcript-in-the-legacy-shape")
    world = _build(tmp_path, case)

    _run(world)

    backups = world.backups()
    assert len(backups) == 1, backups
    assert backups[0].name.endswith(f"-{world.work.name}.jsonl")
    assert json.loads(backups[0].read_text().splitlines()[0])["role"] == "user"
    assert world.logged("pre-compact: backed up transcript to ")


def test_a_declared_transcript_that_is_not_on_disk_is_not_backed_up(tmp_path: Path) -> None:
    """`existing_transcript`'s half of the contract, pinned.

    `HookEvent.transcript_path` is what the payload *named*, not what exists.
    The pre-runner code stat'd it as part of reading the payload
    (`pre_compact.py:218`), so without the explicit filter the check would
    disappear silently and `shutil.copy2` would start raising into the
    `except OSError` instead — logging `backup failed` on every compaction of
    a session whose transcript the agent had not written yet.
    """
    case = next(c for c in CASES if c.id == "transcript-declared-but-not-written")
    world = _build(tmp_path, case)

    run = _run(world)

    assert run.exit_code == 0, run.stderr
    assert world.backups() == []
    assert not world.logged("backup failed")
    assert not world.logged("backed up transcript to ")
    # The memory tails still reach stdout, so the hook was not merely skipped:
    # only the transcript half of the summary is missing.
    assert "## Recent decisions" in run.stdout
    assert "## Tasks in progress" not in run.stdout


def test_the_parser_reads_nothing_from_the_shape_claude_code_emits(tmp_path: Path) -> None:
    """The dead-code measurement, executable rather than asserted in prose.

    `parse_transcript` reads `role` and `content` at the top level of each
    JSONL line; Claude Code nests both under `message`. This is the branch the
    hook takes in production, and it is why row 8 of the migration plan
    declares **no** signals — a `MESSAGES` declaration would name a read that
    does not happen and let `deploy` omit the hook, losing the memory tails
    over a transcript read that never worked. The repair is out of scope and
    owned by `specs/backlog.md:125`; this test pins the current behaviour so
    that repair cannot land silently.
    """
    case = next(c for c in CASES if c.id == "transcript-in-the-shape-claude-code-emits")
    world = _build(tmp_path, case)

    run = _run(world)

    assert run.exit_code == 0, run.stderr
    # Backed up, so the transcript was found and read — the parser is what
    # yields nothing, not the file handling.
    assert len(world.backups()) == 1
    assert "## Tasks in progress" not in run.stdout
    assert "## Files worked on" not in run.stdout
    assert "/srv/app/pre_compact.py" not in run.stdout
    assert "## Recent decisions" in run.stdout


def test_the_legacy_shape_is_the_only_one_that_reaches_the_summary(tmp_path: Path) -> None:
    """The contrast that makes the test above a measurement rather than a tautology.

    Without it, `parse_transcript` returning nothing would be indistinguishable
    from a fixture the hook never opened.
    """
    case = next(c for c in CASES if c.id == "transcript-in-the-legacy-shape")
    world = _build(tmp_path, case)

    run = _run(world)

    assert "## Tasks in progress" in run.stdout
    assert "migrate the pre-compact hook onto the event contract" in run.stdout
    assert "## Files worked on" in run.stdout
    assert "/srv/app/pre_compact.py" in run.stdout
    assert "/srv/app/loader.py" in run.stdout


def test_a_payload_without_cwd_falls_back_to_the_hooks_own_directory(tmp_path: Path) -> None:
    """Trap 1: an absent `cwd` must not resolve to `.`.

    `parse_hook_input` yields `Path("")`, which is `Path(".")` — truthy, so an
    `or Path.cwd()` would not fire. This hook encodes the cwd into a directory
    *name*, so `Path(".")` would make the memory dir `projects/-.` and every
    checkout on the machine would share one, reading tails written by another
    project. Measured through the directory the summary lands in.
    """
    case = next(c for c in CASES if c.id == "cwd-absent-from-the-payload")
    world = _build(tmp_path, case)

    run = _run(world)

    assert run.exit_code == 0, run.stderr
    assert world.summary_file.is_file()
    assert not (world.agent_dir / "projects" / "-.").exists()


def test_the_run_lands_in_the_invoked_profile_and_not_in_the_global_dir(
    tmp_path: Path,
) -> None:
    """Recipe step 7, asserted as a pair: present under `<profile>`, absent globally.

    `CLAUDE_CONFIG_DIR` is cleared, so the two answers to "where does this hook
    write" are distinguishable: the profile's own `config_dir`, and `~/.claude`
    which is `agent_runtime_dir`'s last resort. A hook resolving the agent
    globally — `get_agent(...)` plus `agent_runtime_dir(agent)` with no profile,
    which is what `pre_compact._resolve_agent_dirs` did — writes its log, its
    memory dir and its backup into `~/.claude` for every profile.

    The absence half is what makes it a test. PR #300 measured a presence
    assertion passing against a broken hook, because a hook that writes into
    both directories satisfies it.
    """
    case = next(c for c in CASES if c.id == "transcript-in-the-legacy-shape")
    world = _build(tmp_path, case, profile="p")

    run = _run(world, profile="p")

    assert run.exit_code == 0, run.stderr
    assert world.logged("pre-compact: fired cwd=")
    assert world.summary_file.is_file()
    assert len(world.backups()) == 1
    assert not world.global_agent_dir.exists(), sorted(world.global_agent_dir.rglob("*"))

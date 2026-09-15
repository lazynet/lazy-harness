"""Byte goldens and effect assertions for `engram-persist`, captured pre-migration.

This hook's declared output channel is **none**: every branch exits 0 with
nothing on either stream, so a golden alone would pass against a hook that had
been deleted. The goldens are still captured — they are what pins "still
silent" once `format_hook_output` starts serialising a `HookDecision` — but the
evidence that the hook did its job lives in `EffectProbe`, read off the
filesystem after the same run.

Three things this hook writes and nothing else does:

* `<agent dir>/logs/engram_persist_metrics.jsonl` — one `run` or `skip` record;
* `<agent dir>/logs/engram_persist.log` — the error trail;
* `<agent dir>/engram-cursors/<identity>/engram_cursor.json` — the byte offsets.

Each is keyed by the agent runtime dir, which is what makes them the probe for
profile isolation as well: a hook that resolves the agent globally writes all
three into the global directory no matter which `--profile` invoked it.
"""

from __future__ import annotations

import json
import os
import stat
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

HOOK = "engram-persist"

SESSION = "0193b0de-aaaa-bbbb-cccc-ddddeeeeffff"

_CONFIG_MIN = '[harness]\nversion = "1"\n'
_CONFIG_BROKEN = "[memory.engram\nbinary = 1"

#: One entry in the shape `compound_loop` appends to `decisions.jsonl`.
_DECISION = {"ts": "2026-09-15T00:00:00Z", "type": "decision", "summary": "chose-a-over-b"}


def _write_engram_shim(shim_dir: Path, *, exit_code: int) -> Path:
    """A POSIX-sh stand-in for `engram` that records its argv.

    `sh` rather than the `python3` shebang the older subprocess tests used: the
    pinned PATH carries git and this directory and nothing else, so a shebang
    resolved through `env` would find no interpreter and the run would fail for
    a reason that has nothing to do with the hook.
    """
    shim_dir.mkdir(parents=True, exist_ok=True)
    shim = shim_dir / "engram"
    log = shim_dir / "invocations.log"
    shim.write_text(
        "#!/bin/sh\n"
        f'printf "%s\\n" "$*" >> {str(log)!r}\n'
        'if [ "$1" = "version" ]; then echo "engram v0.0.0-shim"; exit 0; fi\n'
        f"exit {exit_code}\n"
    )
    shim.chmod(shim.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    return shim


@dataclass(frozen=True)
class Case:
    """One branch of `engram_persist.main()`."""

    id: str
    config: str | None = _CONFIG_MIN
    #: Entries pre-written to `decisions.jsonl` in the resolved memory dir.
    decisions: tuple[dict, ...] = ()
    #: Put an `engram` shim on the child's PATH.
    shim: bool = False
    #: Exit code that shim returns for `save`.
    shim_exit: int = 0
    #: Point `[memory.engram] binary` at a path that does not exist.
    configured_binary_missing: bool = False
    #: Name `cwd` in the payload. `False` is trap 1's input.
    declare_cwd: bool = True
    #: Name a `transcript_path` inside the agent's own sessions root.
    declare_transcript: bool = False
    #: Write that transcript file to disk. Only read when declaring one.
    write_transcript: bool = True
    #: Project dir the declared transcript sits in, under the sessions root.
    #: `None` uses the cwd encoding, which is what the fallback would also
    #: produce; a literal name is what makes the two spellings disagree.
    transcript_dir_name: str | None = None
    #: Raw stdin, for the payloads that are not JSON objects.
    raw_stdin: str | None = None


CASES: list[Case] = [
    Case(id="no-config-at-all", config=None),
    Case(id="config-unparseable", config=_CONFIG_BROKEN),
    Case(id="configured-binary-missing", configured_binary_missing=True),
    Case(id="binary-not-on-path"),
    Case(id="binary-on-path-with-nothing-to-save", shim=True),
    Case(id="binary-on-path-saves-a-decision", shim=True, decisions=(_DECISION,)),
    Case(id="engram-save-fails", shim=True, shim_exit=1, decisions=(_DECISION,)),
    Case(id="cwd-absent-from-the-payload", shim=True, declare_cwd=False),
    Case(id="transcript-declares-the-project-dir", shim=True, declare_transcript=True),
    Case(
        id="transcript-declared-but-not-written",
        shim=True,
        declare_transcript=True,
        write_transcript=False,
        transcript_dir_name="-a-name-only-the-agent-knows",
    ),
    Case(id="stdin-empty", raw_stdin=""),
    Case(id="stdin-malformed-json", raw_stdin="not json"),
]

#: The payloads the runner refuses once this hook is migrated. Decision 3's
#: informational column: exit 0, a warning on stderr, no stdout. Before the
#: migration the pre-runner path degraded them to `{}` and ran the hook.
UNUSABLE_PAYLOAD_CASE_IDS: frozenset[str] = frozenset({"stdin-empty", "stdin-malformed-json"})


@dataclass
class World:
    """The tmp tree one case runs in, and where its three artifacts should land."""

    work: Path
    agent_dir: Path
    global_agent_dir: Path
    config_dir: Path
    env: dict[str, str] = field(default_factory=dict)
    stdin: str = "{}"
    shim_dir: Path | None = None
    #: Project dir the payload's transcript path sits in.
    transcript_dir: Path = Path(".")

    @property
    def logs_dir(self) -> Path:
        return self.agent_dir / "logs"

    @property
    def metrics_file(self) -> Path:
        return self.logs_dir / "engram_persist_metrics.jsonl"

    @property
    def error_log(self) -> Path:
        return self.logs_dir / "engram_persist.log"

    @property
    def cursors_root(self) -> Path:
        return self.agent_dir / "engram-cursors"

    def metrics_records(self, event: str | None = None) -> list[dict]:
        """Records in `engram_persist_metrics.jsonl`, optionally one event only.

        Filtering matters: `slow_save` is emitted whenever one `engram save`
        crosses 500ms, which for a shell shim is a stopwatch on the machine
        running the suite. Asserting on the full sequence would make these
        tests fail on a loaded CI box for a reason the hook does not own.
        """
        if not self.metrics_file.is_file():
            return []
        records = [
            json.loads(line)
            for line in self.metrics_file.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        return [r for r in records if event is None or r.get("event") == event]

    def engram_invocations(self) -> list[str]:
        if self.shim_dir is None:
            return []
        log = self.shim_dir / "invocations.log"
        if not log.is_file():
            return []
        return [line for line in log.read_text(encoding="utf-8").splitlines() if line.strip()]


def _encoded(path: Path) -> str:
    return "-" + str(path).replace("/", "-").lstrip("-")


def _build(tmp_path: Path, case: Case, *, profile: str | None = None) -> World:
    """Lay out one case's tree and return the probes for it.

    `profile` writes a `[profiles.<name>] config_dir` **and clears
    `CLAUDE_CONFIG_DIR`**, which together reproduce what a deployed hook sees.
    `agent_runtime_dir` resolves the adapter's env var first by design, so
    leaving it set would make both the global resolution and the per-profile
    one agree and the isolation assertion would prove nothing. A hook
    subprocess does not inherit the interactive shell's `CLAUDE_CONFIG_DIR` —
    that absence is exactly why the profile step exists — and without it the
    global fall-through lands in `~/.claude`, which is what `global_agent_dir`
    points at here.
    """
    home = tmp_path / "home"
    config_dir = tmp_path / "config"
    data_dir = tmp_path / "data"
    work = tmp_path / "work"
    env_agent_dir = tmp_path / "claude-global"
    # With no `CLAUDE_CONFIG_DIR`, the adapter's global link is where a hook
    # that ignores its profile ends up.
    global_agent_dir = home / ".claude" if profile else env_agent_dir
    agent_dir = tmp_path / f"claude-{profile}" if profile else env_agent_dir
    for d in (home, config_dir, data_dir, work, agent_dir, env_agent_dir):
        d.mkdir(parents=True, exist_ok=True)

    shim_dir: Path | None = None
    extra: dict[str, str] = {}
    if case.shim:
        shim_dir = tmp_path / "shimbin"
        _write_engram_shim(shim_dir, exit_code=case.shim_exit)

    config = case.config
    if config is not None and config != _CONFIG_BROKEN:
        if case.configured_binary_missing:
            missing = tmp_path / "nowhere" / "engram"
            config += f'\n[memory.engram]\nbinary = "{missing}"\n'
        if profile is not None:
            config += f'\n[profiles.{profile}]\nconfig_dir = "{agent_dir}"\nroots = ["~"]\n'
    if config is not None:
        (config_dir / "config.toml").write_text(config)

    # The memory dir the hook is expected to resolve, so the fixture writes the
    # entries where the hook will look for them rather than the other way round.
    sessions_root = agent_dir / "projects"
    cwd_project_dir = sessions_root / _encoded(work)
    transcript_dir = sessions_root / (case.transcript_dir_name or _encoded(work))
    transcript = transcript_dir / f"{SESSION}.jsonl"
    if case.declare_transcript:
        transcript_dir.mkdir(parents=True, exist_ok=True)
        if case.write_transcript:
            transcript.write_text("{}\n")
    if case.decisions:
        memory = cwd_project_dir / "memory"
        memory.mkdir(parents=True, exist_ok=True)
        (memory / "decisions.jsonl").write_text(
            "".join(json.dumps(e, sort_keys=True) + "\n" for e in case.decisions)
        )

    env = pinned_env(
        home=home,
        config_dir=config_dir,
        data_dir=data_dir,
        agent_config_dir=env_agent_dir,
        extra=extra,
    )
    if profile is not None:
        env["CLAUDE_CONFIG_DIR"] = ""
    if shim_dir is not None:
        env["PATH"] = f"{shim_dir}{os.pathsep}{env['PATH']}"

    if case.raw_stdin is not None:
        stdin = case.raw_stdin
    else:
        payload: dict[str, object] = {"hook_event_name": "Stop", "session_id": SESSION}
        if case.declare_cwd:
            payload["cwd"] = str(work)
        if case.declare_transcript:
            payload["transcript_path"] = str(transcript)
        stdin = json.dumps(payload)

    return World(
        work=work,
        agent_dir=agent_dir,
        global_agent_dir=global_agent_dir,
        config_dir=config_dir,
        env=env,
        stdin=stdin,
        shim_dir=shim_dir,
        transcript_dir=transcript_dir,
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


@pytest.mark.parametrize("case_id", [c.id for c in CASES if c.id not in UNUSABLE_PAYLOAD_CASE_IDS])
def test_every_usable_branch_stays_silent_on_both_streams(case_id: str) -> None:
    """The declared output channel is none, and the golden is what holds it.

    Written as its own assertion rather than left implicit in the golden files:
    a migration that started returning `HookDecision(system_message=...)` would
    rewrite twelve goldens at once, and a reviewer re-capturing them would see
    twelve one-line diffs rather than one broken contract.
    """
    golden = json.loads(golden_path(HOOK, case_id).read_text())

    assert golden == {"exit_code": 0, "stderr": "", "stdout": ""}


@pytest.mark.parametrize("case_id", sorted(UNUSABLE_PAYLOAD_CASE_IDS))
def test_an_unusable_payload_warns_instead_of_running_silently(case_id: str) -> None:
    """The one licensed golden divergence, named rather than re-captured quietly.

    Decision 3's informational column: the runner refuses a payload it cannot
    parse before the builtin is reached, so these two goldens carry a warning
    on stderr where the pre-runner path degraded the payload to `{}` and let
    the hook run against `Path.cwd()`. Everything the hook would have written
    on that run — a cursor, a metrics record — was keyed by whatever directory
    the agent happened to spawn it from, which is what makes the refusal an
    improvement rather than a loss.

    The other ten goldens in this directory are the pre-migration captures,
    unchanged.
    """
    golden = json.loads(golden_path(HOOK, case_id).read_text())

    assert golden["exit_code"] == 0
    assert golden["stdout"] == ""
    assert golden["stderr"].startswith(f"{HOOK}: unparseable payload")


def test_a_run_with_the_binary_present_records_a_run_metric(tmp_path: Path) -> None:
    """The effect the golden cannot see: the hook reached the persister."""
    case = next(c for c in CASES if c.id == "binary-on-path-saves-a-decision")
    world = _build(tmp_path, case)

    _run(world)

    records = world.metrics_records("run")
    assert len(records) == 1, world.metrics_records()
    assert records[0]["saved_ok"] == 1
    assert any(line.startswith("save chose-a-over-b ") for line in world.engram_invocations())


def test_a_run_without_the_binary_records_a_skip_rather_than_a_clean_run(
    tmp_path: Path,
) -> None:
    """A skip that counted as a run is why a no-op hook reported 0% failures."""
    case = next(c for c in CASES if c.id == "binary-not-on-path")
    world = _build(tmp_path, case)

    _run(world)

    records = world.metrics_records()
    assert [r["event"] for r in records] == ["skip"]
    assert records[0]["reason"] == "binary_not_found"
    assert "engram binary not on PATH" in world.error_log.read_text(encoding="utf-8")


def test_the_cursor_lands_under_the_agent_dir_and_never_beside_the_jsonl(
    tmp_path: Path,
) -> None:
    """The offsets index files that travel between machines; they must not.

    Asserted as a pair: the cursor is present under the agent runtime dir *and*
    absent from the memory dir. Presence alone passes against a hook that
    writes both.
    """
    case = next(c for c in CASES if c.id == "binary-on-path-saves-a-decision")
    world = _build(tmp_path, case)

    _run(world)

    cursors = sorted(world.cursors_root.rglob("engram_cursor.json"))
    assert len(cursors) == 1, cursors
    memory = world.agent_dir / "projects" / _encoded(world.work) / "memory"
    assert not (memory / "engram_cursor.json").exists()


def test_a_declared_transcript_that_is_not_written_yet_still_names_the_project_dir(
    tmp_path: Path,
) -> None:
    """The call site this migration touches, pinned against `existing_transcript`.

    `memory_dir` takes the *declared* transcript because `resolve_project_dir`
    stats only its parent — filtering it through `existing_transcript` first
    would drop back to encoding the cwd. Here both spellings resolve to the
    same directory, so the disagreement is forced by leaving the transcript
    unwritten while its project dir exists and holds the entries.

    Without this, `engram_persist`'s transcript argument had no test at all and
    a swap to the filtering helper would have been invisible.
    """
    case = next(c for c in CASES if c.id == "transcript-declared-but-not-written")
    world = _build(tmp_path, case)
    # The entries live *only* under the dir the transcript names, which is not
    # the cwd encoding — so a run that falls back finds an empty directory and
    # saves nothing. Both halves are asserted: the save happened, and the
    # fallback dir was never even created.
    memory = world.transcript_dir / "memory"
    memory.mkdir(parents=True, exist_ok=True)
    (memory / "decisions.jsonl").write_text(json.dumps(_DECISION, sort_keys=True) + "\n")
    fallback = world.agent_dir / "projects" / _encoded(world.work)

    _run(world)

    assert any(line.startswith("save chose-a-over-b ") for line in world.engram_invocations())
    assert not (fallback / "memory" / "decisions.jsonl").exists()


def test_a_payload_without_cwd_falls_back_to_the_hooks_own_directory(
    tmp_path: Path,
) -> None:
    """Trap 1: an absent `cwd` must not resolve to `.`.

    `parse_hook_input` yields `Path("")`, which is `Path(".")` — truthy, and so
    not caught by the `or Path.cwd()` this hook used to rely on. The project
    key would become the empty basename and the encoded project dir `-.`,
    pointing every checkout at one shared directory.

    Measured through the metrics record's `project_key`, which is the field a
    dashboard groups on.
    """
    case = next(c for c in CASES if c.id == "cwd-absent-from-the-payload")
    world = _build(tmp_path, case)

    _run(world)

    records = world.metrics_records("run")
    assert len(records) == 1, world.metrics_records()
    assert records[0]["project_key"] == world.work.name


def test_the_run_lands_in_the_invoked_profile_and_not_in_the_global_dir(
    tmp_path: Path,
) -> None:
    """Recipe step 7, asserted as a pair: present under `<profile>`, absent globally.

    `CLAUDE_CONFIG_DIR` names one directory and `[profiles.p] config_dir`
    names another, so the two answers to "where does this hook write" are
    distinguishable. A hook resolving the agent globally — `get_agent(...)` plus
    `agent_runtime_dir(agent)` with no profile — writes into the environment's
    directory for every profile, which is the defect PR #300 measured.

    The absence half is what makes it a test. PR #300 also measured a presence
    assertion passing against a broken hook, because a hook that writes into
    both directories satisfies it.
    """
    case = next(c for c in CASES if c.id == "binary-on-path-saves-a-decision")
    world = _build(tmp_path, case, profile="p")

    run = _run(world, profile="p")

    assert run.exit_code == 0, run.stderr
    assert any(line.startswith("save chose-a-over-b ") for line in world.engram_invocations())
    assert world.metrics_records("run"), world.metrics_file
    assert sorted(world.cursors_root.rglob("engram_cursor.json"))
    assert not world.global_agent_dir.exists(), sorted(world.global_agent_dir.rglob("*"))

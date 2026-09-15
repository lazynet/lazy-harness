"""Byte goldens for `session_export`, one per branch, captured pre-migration.

This hook writes nothing on any channel: no verdict, no `systemMessage`, no
`additionalContext`. Every branch is `stdout=""`, `stderr=""`, `exit_code=0`,
and freezing that is the point rather than a weakness of the golden — it is a
Stop hook, and Claude Code parses a Stop hook's stdout. A migration that let
one line of diagnostics reach stdout would be invisible to any test asserting
on the hook's own return value, and fatal on the wire.

The three frozen channels therefore cannot tell the branches apart, so each
case also names the `hooks.log` line it must produce. That log is this hook's
only output, which makes it the only place a branch is observable at all:

* config — absent, unparseable, valid;
* knowledge store — no marker file, usable;
* session — none found, one exported, one skipped as too short;
* transcript — declared on stdin and on disk, so the project dir is never
  derived from the cwd at all.

Determinism comes from `pinned_env`: `qmd` is off the child's `PATH`, so the
`qmd update` tail never runs, and `HOME`, `LH_CONFIG_DIR`, `LH_DATA_DIR` and
`CLAUDE_CONFIG_DIR` all land inside the test's tmp tree.

The payload's `cwd` is the child's *real* cwd (`os.path.realpath`), not
`tmp_path` as pytest spells it. Pre-migration the hook reads `Path.cwd()`,
which is already symlink-resolved; post-migration it reads `event.cwd`, which
is whatever the payload said. On macOS `/var` is a symlink to `/private/var`,
so passing the unresolved path would make the two eras disagree about the
project directory while every frozen channel stayed identical.
"""

from __future__ import annotations

import json
import os
import shutil
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import pytest

from tests.unit.hooks.builtins._goldens import (
    assert_golden,
    golden_path,
    pinned_env,
    run_through_runner,
)

HOOK = "session-export"

SESSION = "0193c0de-aaaa-bbbb-cccc-ddddeeeeffff"

BASE_CONFIG = '[harness]\nversion = "1"\n\n[agent]\ntype = "claude-code"\n'

MARKER = '[knowledge]\nversion = 1\nsessions = "sessions"\nlearnings = "learnings"\n'


def _transcript(cwd: str, *, turns: int) -> str:
    """A session JSONL the exporter accepts, with `turns` user/assistant pairs.

    `permission-mode` is what sets `is_interactive`; without it `export_session`
    skips every session as non-interactive and the exported branch is
    unreachable.
    """
    lines: list[dict[str, object]] = [
        {"type": "permission-mode", "timestamp": "2026-04-12T10:00:00"},
        {"type": "system", "cwd": cwd, "timestamp": "2026-04-12T10:00:00"},
    ]
    for i in range(turns):
        lines.append(
            {
                "type": "user",
                "message": {"content": f"question {i}"},
                "timestamp": f"2026-04-12T10:00:{i * 2 + 1:02d}",
            }
        )
        lines.append(
            {
                "type": "assistant",
                "message": {"content": f"answer {i}"},
                "timestamp": f"2026-04-12T10:00:{i * 2 + 2:02d}",
            }
        )
    return "\n".join(json.dumps(line) for line in lines) + "\n"


@dataclass
class World:
    """The pinned machine one case runs against."""

    tmp: Path
    home: Path
    config_dir: Path
    data_dir: Path
    agent_dir: Path
    work: Path
    project_dir: Path
    knowledge_root: Path

    @property
    def real_cwd(self) -> str:
        return os.path.realpath(self.work)

    def config(self, extra: str = "") -> None:
        (self.config_dir / "config.toml").write_text(BASE_CONFIG + extra)

    def raw_config(self, text: str) -> None:
        (self.config_dir / "config.toml").write_text(text)

    def knowledge_config(self) -> None:
        self.config(f'\n[knowledge]\nroot = "{self.knowledge_root}"\n')

    def marker(self) -> None:
        self.knowledge_root.mkdir(parents=True, exist_ok=True)
        (self.knowledge_root / "knowledge.toml").write_text(MARKER)

    def session(self, directory: Path, name: str, *, turns: int) -> Path:
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / name
        path.write_text(_transcript(self.real_cwd, turns=turns))
        return path

    @property
    def exported(self) -> list[Path]:
        return sorted((self.knowledge_root / "sessions").rglob("*.md"))

    @property
    def log(self) -> str:
        path = self.agent_dir / "logs" / "hooks.log"
        return path.read_text(encoding="utf-8") if path.is_file() else ""


Build = Callable[[World], None]


@dataclass(frozen=True)
class Case:
    id: str
    build: Build
    #: Substring the hook must append to `hooks.log`. The only channel it uses.
    log: str
    #: How many markdown files the knowledge store must hold afterwards.
    exports: int = 0
    #: Overrides the ordinary Stop payload. `None` sends it.
    raw_stdin: str | None = None
    #: Declares this case's transcript on stdin instead of leaving it to the cwd.
    declare_transcript: str | None = None


def _no_config(world: World) -> None:
    """`config_file()` does not exist: the hook stops before anything else."""


def _unparseable_config(world: World) -> None:
    world.raw_config("[agent\ntype = claude-code")


def _no_marker(world: World) -> None:
    """A configured knowledge root with no `knowledge.toml` in it."""
    world.knowledge_root.mkdir(parents=True, exist_ok=True)
    world.knowledge_config()


def _no_session(world: World) -> None:
    world.knowledge_config()
    world.marker()
    world.project_dir.mkdir(parents=True, exist_ok=True)


def _exported(world: World) -> None:
    world.knowledge_config()
    world.marker()
    world.session(world.project_dir, f"{SESSION}.jsonl", turns=3)


def _too_short(world: World) -> None:
    world.knowledge_config()
    world.marker()
    world.session(world.project_dir, f"{SESSION}.jsonl", turns=1)


def _declared_elsewhere(world: World) -> None:
    """The agent names a project dir that encoding the cwd would never produce."""
    world.knowledge_config()
    world.marker()
    world.session(world.agent_dir / "projects" / "-agent-chose-this", "declared.jsonl", turns=3)
    world.project_dir.mkdir(parents=True, exist_ok=True)


CASES: list[Case] = [
    Case(id="no-config-file", build=_no_config, log="no config file, skipping"),
    Case(id="config-unparseable", build=_unparseable_config, log="config error:"),
    Case(id="knowledge-store-without-marker", build=_no_marker, log="knowledge store unusable"),
    Case(id="no-session-jsonl", build=_no_session, log="no session JSONL found"),
    Case(id="session-exported", build=_exported, log="exported to ", exports=1),
    Case(id="session-too-short", build=_too_short, log="(short)"),
    Case(
        id="transcript-declared-on-stdin",
        build=_declared_elsewhere,
        log="exported to ",
        exports=1,
        declare_transcript="-agent-chose-this/declared.jsonl",
    ),
]


def _world(tmp_path: Path) -> World:
    home = tmp_path / "home"
    agent_dir = tmp_path / "claude"
    work = tmp_path / "repos" / "work"
    world = World(
        tmp=tmp_path,
        home=home,
        config_dir=tmp_path / "config",
        data_dir=tmp_path / "data",
        agent_dir=agent_dir,
        work=work,
        project_dir=agent_dir / "projects" / "unset",
        knowledge_root=tmp_path / "knowledge",
    )
    for d in (home, world.config_dir, world.data_dir, work):
        d.mkdir(parents=True, exist_ok=True)
    # The project dir the hook derives from the cwd, spelled the way the hook
    # spells it — `resolve_project_dir` encodes the *resolved* cwd.
    encoded = "-" + world.real_cwd.replace("/", "-").lstrip("-")
    world.project_dir = agent_dir / "projects" / encoded
    return world


def _payload(world: World, case: Case) -> str:
    body: dict[str, object] = {
        "hook_event_name": "Stop",
        "session_id": SESSION,
        "cwd": world.real_cwd,
    }
    if case.declare_transcript:
        body["transcript_path"] = str(world.agent_dir / "projects" / case.declare_transcript)
    return json.dumps(body)


def _run(world: World, case: Case):  # noqa: ANN202 - HookRun, imported for typing only
    env = pinned_env(
        home=world.home,
        config_dir=world.config_dir,
        data_dir=world.data_dir,
        agent_config_dir=world.agent_dir,
    )
    # `main` shells out to `qmd update` after a successful export. A machine
    # with qmd installed would otherwise spend 60s of timeout inside a golden.
    assert shutil.which("qmd", path=env["PATH"]) is None

    stdin = case.raw_stdin if case.raw_stdin is not None else _payload(world, case)
    return run_through_runner(HOOK, stdin_text=stdin, cwd=world.work, env=env)


@pytest.mark.parametrize("case", CASES, ids=lambda c: c.id)
def test_golden(case: Case, tmp_path: Path) -> None:
    world = _world(tmp_path)
    case.build(world)

    assert_golden(HOOK, case.id, _run(world, case))


@pytest.mark.parametrize("case", CASES, ids=lambda c: c.id)
def test_each_branch_reaches_its_own_log_line_and_export(case: Case, tmp_path: Path) -> None:
    """What the frozen channels cannot see, asserted against the real effects.

    Split from `test_golden` on purpose: the goldens are identical across every
    branch, so a case that silently stopped taking the branch it is named after
    would keep matching its golden forever.
    """
    world = _world(tmp_path)
    case.build(world)

    _run(world, case)

    assert case.log in world.log
    assert len(world.exported) == case.exports


def test_case_ids_are_unique() -> None:
    ids = [c.id for c in CASES]
    assert len(ids) == len(set(ids))


@pytest.mark.parametrize("case_id", [c.id for c in CASES])
def test_every_branch_is_silent_on_both_channels_and_exits_0(case_id: str) -> None:
    """A Stop hook's stdout is parsed by the agent; this hook has nothing to say.

    Asserted against the committed golden rather than against a fresh run, so
    it is a statement about what was frozen and not a second copy of it.
    """
    golden = json.loads(golden_path(HOOK, case_id).read_text())

    assert golden == {"exit_code": 0, "stderr": "", "stdout": ""}


def test_no_golden_carries_an_unnormalised_temp_path() -> None:
    """A leaked tmp path would make the golden pass only on the machine that
    captured it — the failure mode this whole harness exists to prevent."""
    for case in CASES:
        raw = golden_path(HOOK, case.id).read_text()
        assert "/pytest-of-" not in raw, case.id
        assert "/var/folders/" not in raw, case.id


def test_the_exported_session_carries_the_transcript_the_agent_declared(tmp_path: Path) -> None:
    """The declared path wins over the one encoding the cwd would produce.

    Both directories exist and only one holds a session, so an implementation
    that dropped `event.transcript_path` would export nothing at all rather
    than exporting the wrong thing.
    """
    world = _world(tmp_path)
    case = next(c for c in CASES if c.id == "transcript-declared-on-stdin")
    case.build(world)

    _run(world, case)

    assert len(world.exported) == 1
    assert "answer 0" in world.exported[0].read_text()


def test_a_payload_naming_no_cwd_falls_back_to_the_process_directory(tmp_path: Path) -> None:
    """Trap 1: `event.cwd` is `Path("")` when the payload names no cwd.

    `Path("")` is `Path(".")`, and `resolve_project_dir` encodes it as the
    directory `-.` -- which holds nobody's sessions, so the export silently
    stops happening. Nothing on any frozen channel would show that: this hook
    exits 0 and prints nothing whether it exported or not.

    Discriminable by construction: the session lives only in the directory
    encoding the *process* cwd, and the payload never names it.
    """
    world = _world(tmp_path)
    world.knowledge_config()
    world.marker()
    world.session(world.project_dir, f"{SESSION}.jsonl", turns=3)

    case = Case(id="unused", build=lambda w: None, log="", raw_stdin=json.dumps({}))
    _run(world, case)

    assert len(world.exported) == 1
    assert "exported to " in world.log

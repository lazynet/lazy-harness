"""Byte goldens for `post_tool_use_format`, one per branch, captured pre-migration.

**The wire goldens discriminate nothing here and it is worth saying why once.**
This hook's output channel is "none": it never prints, and `ruff format`'s own
output is captured and discarded (`post_tool_use_format.py:52`). So every case
below freezes to `{"exit_code": 0, "stderr": "", "stdout": ""}` on the branches
the runner reaches, and a `main()` whose whole body is `return HookDecision()`
would reproduce all of them. Wave A measured that four times over.

The evidence is therefore the filesystem, recorded per case beside the golden:

* `formatted` — the edited file came back reformatted. That is the whole point
  of the hook and the one thing an empty `main()` cannot fake.
* `logged` — a `hooks.log` line under the agent runtime dir. This hook writes
  one on exactly one branch, `ruff` being unreachable, and that branch is also
  where the profile resolution lives.

Both halves were recorded from the **unmigrated** `main()`.

Branches, read off `main()`:

* the tool gate — `Edit`, `Write`, a tool that is neither, and no `tool_name`
  at all;
* **`NotebookEdit` naming a `.py` path**, in both of Claude Code's spellings.
  `_TOOL_OPERATIONS` maps it to `MODIFY_FILE` beside `Edit` and `Write`
  (`claude_code.py:97`), so a migration that swapped the tool gate for the
  operation gate would start running Ruff on it — and the `.py` suffix re-check
  would not stop it, because nothing in `ToolCall` makes a notebook's path end
  in `.ipynb`. Pre-migration these two are skipped; the goldens freeze that;
* the suffix gate — a `.md` and a `.txt` path;
* the shape guards — `tool_input` null, and `file_path` absent;
* the fail-soft path — `ruff` off `PATH`, which is the only branch that logs;
* the unusable payload, which decision 3 moves off the "degrade to `{}`" path.
"""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from pathlib import Path

import pytest

from tests.unit.hooks.builtins._goldens import (
    assert_golden,
    pinned_env,
    run_through_runner,
)

HOOK = "post-tool-use-format"

SESSION = "0193b0de-aaaa-bbbb-cccc-ddddeeeeffff"

#: The profile `[profiles.goldens]` names, which `CLAUDE_CONFIG_DIR` points at.
PROFILE = "goldens"

#: Badly formatted on purpose, and in a way `ruff format` fixes deterministically
#: with no configuration: the extra spaces around `=` come out as one each.
UNFORMATTED = "x  =  1\n"
FORMATTED = "x = 1\n"


def _config(*, agent_dir: Path) -> str:
    return (
        '[harness]\nversion = "1"\n\n'
        '[agent]\ntype = "claude-code"\n\n'
        f'[profiles]\ndefault = "{PROFILE}"\n\n'
        f'[profiles.{PROFILE}]\nconfig_dir = "{agent_dir}"\n'
    )


@dataclass(frozen=True)
class Case:
    """One branch of the hook."""

    id: str
    #: Native tool name. `None` omits `tool_name` from the payload entirely.
    tool: str | None = "Edit"
    #: Suffix of the edited file, which is what the hook's own gate reads.
    suffix: str = ".py"
    #: Claude Code names the file differently per tool; both are one path.
    path_key: str = "file_path"
    #: `False` sends `"tool_input": null` rather than a mapping.
    declare_tool_input: bool = True
    #: `False` sends a `tool_input` that names no path.
    declare_path: bool = True
    #: `False` hides `ruff` from the child's `PATH`.
    ruff_on_path: bool = True
    #: Raw stdin, for the payloads that are not valid JSON objects.
    raw_stdin: str | None = None
    #: The edited file came back reformatted.
    formatted: bool = False
    #: A `hooks.log` line was written under the agent runtime dir.
    logged: bool = False


CASES: list[Case] = [
    # --- the tool gate ------------------------------------------------------ #
    Case(id="edit-of-a-python-file-is-reformatted", formatted=True),
    Case(id="write-of-a-python-file-is-reformatted", tool="Write", formatted=True),
    Case(id="read-of-a-python-file-is-left-alone", tool="Read"),
    Case(id="tool-name-absent-is-left-alone", tool=None),
    # --- the NotebookEdit widening, in both spellings ----------------------- #
    # `MODIFY_FILE` covers these; `INSPECTED_TOOLS` does not. The goldens freeze
    # the narrower answer, so a migration that widened to the operation fails
    # here rather than in production.
    Case(id="notebook-edit-naming-a-python-path-is-left-alone", tool="NotebookEdit"),
    Case(
        id="notebook-edit-under-its-own-path-key-is-left-alone",
        tool="NotebookEdit",
        path_key="notebook_path",
    ),
    # --- the suffix gate ---------------------------------------------------- #
    Case(id="markdown-is-left-alone", suffix=".md"),
    Case(id="plain-text-is-left-alone", suffix=".txt"),
    # --- the shape guards --------------------------------------------------- #
    Case(id="tool-input-null-is-left-alone", declare_tool_input=False),
    Case(id="file-path-absent-is-left-alone", declare_path=False),
    # --- the fail-soft path ------------------------------------------------- #
    Case(id="ruff-unreachable-is-logged", ruff_on_path=False, logged=True),
    # --- the unusable payload ----------------------------------------------- #
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
#: capturing these goldens against the unmigrated `main()`.
PRE_MIGRATION_UNUSABLE_GOLDEN = {"exit_code": 0, "stderr": "", "stdout": ""}


def _prepare(tmp_path: Path, case: Case) -> tuple[str, dict[str, str], Path, Path, Path]:
    home = tmp_path / "home"
    config_dir = tmp_path / "config"
    data_dir = tmp_path / "data"
    work = tmp_path / "work"
    agent_dir = tmp_path / "claude"
    for d in (home, config_dir, data_dir, work, agent_dir):
        d.mkdir(parents=True, exist_ok=True)

    (config_dir / "config.toml").write_text(_config(agent_dir=agent_dir))

    edited = work / f"edited{case.suffix}"
    edited.write_text(UNFORMATTED)

    if case.raw_stdin is not None:
        stdin = case.raw_stdin
    else:
        payload: dict[str, object] = {
            "hook_event_name": "PostToolUse",
            "session_id": SESSION,
            "cwd": str(work),
        }
        if case.tool is not None:
            payload["tool_name"] = case.tool
        if case.declare_tool_input:
            payload["tool_input"] = {case.path_key: str(edited)} if case.declare_path else {}
        else:
            payload["tool_input"] = None
        stdin = json.dumps(payload)

    env = pinned_env(
        home=home,
        config_dir=config_dir,
        data_dir=data_dir,
        agent_config_dir=agent_dir,
        extra={"PATH": _path_with_ruff()} if case.ruff_on_path else None,
    )
    return stdin, env, work, edited, agent_dir


def _ruff() -> str | None:
    return shutil.which("ruff")


def _path_with_ruff() -> str:
    """`pinned_env`'s PATH plus the directory `ruff` lives in.

    The pinned PATH holds git and nothing else on purpose, which is exactly the
    state that drives this hook down its binary-missing branch. Every case but
    one wants the other state, so the directory is added back rather than the
    ambient PATH inherited: what gets added is one entry this test names.
    """
    ruff = _ruff()
    git = shutil.which("git")
    assert git is not None
    return f"{Path(git).parent}:{Path(ruff).parent}" if ruff else str(Path(git).parent)


requires_ruff = pytest.mark.skipif(
    shutil.which("ruff") is None,
    reason="ruff is not installed; the formatting half of these cases cannot run",
)


@pytest.mark.parametrize("case", CASES, ids=lambda c: c.id)
def test_golden(case: Case, tmp_path: Path) -> None:
    stdin, env, work, _edited, _agent_dir = _prepare(tmp_path, case)

    run = run_through_runner(HOOK, stdin_text=stdin, cwd=work, env=env)

    assert_golden(HOOK, case.id, run)


@requires_ruff
@pytest.mark.parametrize("case", CASES, ids=lambda c: c.id)
def test_the_edited_file_is_what_the_silent_branches_say(case: Case, tmp_path: Path) -> None:
    """Every wire golden is empty, so the file on disk carries the proof.

    Without this a `main()` that returned `HookDecision()` and ran nothing would
    reproduce all seventeen golden files.
    """
    stdin, env, work, edited, _agent_dir = _prepare(tmp_path, case)

    run_through_runner(HOOK, stdin_text=stdin, cwd=work, env=env)

    assert edited.read_text() == (FORMATTED if case.formatted else UNFORMATTED)


@pytest.mark.parametrize("case", CASES, ids=lambda c: c.id)
def test_the_hook_log_is_what_the_fail_soft_branch_says(case: Case, tmp_path: Path) -> None:
    """The second silent channel, and the one the profile resolution lands in.

    `ruff` off `PATH` is the only branch this hook writes a line on, so it is
    also the only branch on which `agent_dir_for(cfg, event.profile)` can be
    caught resolving the wrong directory.
    """
    stdin, env, work, edited, agent_dir = _prepare(tmp_path, case)

    run_through_runner(HOOK, stdin_text=stdin, cwd=work, env=env)

    log = agent_dir / "logs" / "hooks.log"
    if not case.logged:
        assert not log.exists()
        return
    body = log.read_text()
    assert f"{HOOK}: ruff unavailable" in body
    assert f"left {edited} unformatted" in body


def test_case_ids_are_unique() -> None:
    ids = [c.id for c in CASES]
    assert len(ids) == len(set(ids))


@pytest.mark.parametrize("case_id", [c.id for c in CASES if c.id not in UNUSABLE_PAYLOAD_CASE_IDS])
def test_every_usable_branch_is_silent_on_the_wire(case_id: str) -> None:
    """The channel this hook declares is "none", pinned rather than described.

    A branch that started printing would change what every session sees on
    every tool call — this hook carries no matcher, so it runs on all of them.
    """
    from tests.unit.hooks.builtins._goldens import golden_path

    golden = json.loads(golden_path(HOOK, case_id).read_text())

    assert golden == {"exit_code": 0, "stderr": "", "stdout": ""}


@pytest.mark.parametrize("case_id", sorted(UNUSABLE_PAYLOAD_CASE_IDS))
def test_an_unusable_payload_warns_instead_of_running(case_id: str) -> None:
    """Decision 3's declared divergence, and the only one this migration licenses.

    What it costs here is nothing: before the migration `_read_stdin_json`
    returned `{}`, `payload.get("tool_name")` was `None`, the `INSPECTED_TOOLS`
    gate refused it and the hook exited 0 having run nothing. All six branches
    were already no-ops, so the runner refusing earlier changes only the stderr
    text.
    """
    from tests.unit.hooks.builtins._goldens import golden_path

    golden = json.loads(golden_path(HOOK, case_id).read_text())

    assert golden != PRE_MIGRATION_UNUSABLE_GOLDEN
    assert golden["exit_code"] == 0
    assert golden["stdout"] == ""
    assert "unparseable payload" in golden["stderr"]

"""Byte goldens for `pre-tool-use-memory-size`, captured before its migration.

This hook has a channel a golden can see — a top-level `systemMessage` — so the
cases here discriminate rather than all freezing to the same empty triple. That
matters: wave A measured that a hook writing on no channel produces goldens a
`main()` whose whole body is `return HookDecision()` reproduces exactly. Here a
migration that lost the warning turns eight cases red on the bytes alone.

**The projection is the part a careless migration breaks.** `_projected_text`
computes what the file *would* hold after the edit, and the two `replace_all`
cases below are the same file, the same `old_string` and the same `new_string`
differing only in that flag: 300 projected lines against 151, a warning against
silence. A migration that read `FileEdit.replacements` and dropped
`FileEdit.replace_all` passes every other case in this file.

**Trap 3 is frozen as a case.** `_TOOL_OPERATIONS` maps `NotebookEdit` to
`MODIFY_FILE` beside `Edit` and `Write`, and `_FILE_PATH_KEYS` reads
`notebook_path` into the same `FileEdit.path`. This hook's re-check is a
*filename* — `/memory/MEMORY.md`, `CLAUDE.md` — so unlike a suffix check it
cannot narrow a notebook back out: nothing in `ToolCall` makes a notebook path
end `.ipynb`, and a notebook named `CLAUDE.md` clears it. Replacing the
`INSPECTED_TOOLS` gate with `event.tool.operation is Operation.MODIFY_FILE`
therefore widens the hook, and `notebook-edit-naming-memory-md-is-not-inspected`
is what turns red when it does.

**Paths are machine-independent or normalised, never both left alone.** The
warning names the file, so a case whose payload points at `tmp_path` would
freeze the capturing machine's temp root into the golden. The `Write` branch
never touches the filesystem, so those cases name a synthetic absolute path; the
`Edit` branch has to read a real file, so those runs go through `normalise_run`
with one rule this module declares and `test_no_golden_leaks_a_path_from_the_
machine_that_captured_it` enforces in both directions.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from tests.unit.hooks.builtins._goldens import (
    HookRun,
    assert_golden,
    golden_path,
    normalise_run,
    pinned_env,
    run_through_runner,
)

HOOK = "pre-tool-use-memory-size"

SESSION = "0193b0de-5555-6666-7777-888899990000"

_CONFIG_MIN = '[harness]\nversion = "1"\n'

#: Absolute and synthetic. `Write` projects from `content` alone and never opens
#: the file, so these cases need nothing on disk and leak nothing.
MEMORY_PATH = "/home/user/.claude/projects/foo/memory/MEMORY.md"
CLAUDE_PATH = "/repo/CLAUDE.md"

#: 250 lines, 1250 bytes: over the line ceiling, under the byte one.
_OVER_LINES = "line\n" * 250

#: 50 lines, 250 bytes: under both.
_UNDER_BOTH = "line\n" * 50

#: The shape the byte ceiling exists for — the real backstage-poc index was 67
#: lines and 20KB, far under 200 lines while dominating the session prefix.
_FAT_INDEX = "\n".join(f"- [note {i}]({i}.md) - {'detail ' * 40}" for i in range(67))

#: Both ceilings at once, so the golden carries the " and " join.
_OVER_BOTH = ("x" * 100 + "\n") * 250


@dataclass(frozen=True)
class Case:
    """One branch of the hook's decision."""

    id: str
    tool_name: str = "Write"
    #: The payload key carrying the path. Claude Code uses `notebook_path` for
    #: `NotebookEdit` and `file_path` for everything else.
    path_key: str = "file_path"
    #: The absolute path the payload names, when nothing needs to exist.
    file_path: str = MEMORY_PATH
    content: str | None = None
    old_string: str | None = None
    new_string: str | None = None
    replace_all: bool = False
    #: Body written under `<tmp>/<on_disk_name>` before the run; when set, it is
    #: that file the payload names rather than `file_path`.
    on_disk: str | None = None
    on_disk_name: str = "memory/MEMORY.md"
    #: Appended to the minimal `config.toml`.
    config_extra: str = ""
    #: Replaces `config.toml` wholesale, for the malformed-TOML branch.
    config_raw: str | None = None
    env_extra: dict[str, str] = field(default_factory=dict)
    #: Raw stdin, for the payloads that are not the shape the agent sends.
    raw_stdin: str | None = None


CASES: list[Case] = [
    # --- the branches that warn -----------------------------------------
    Case(id="write-over-the-line-ceiling-warns", content=_OVER_LINES),
    Case(id="write-over-the-byte-ceiling-warns", content=_FAT_INDEX),
    Case(id="write-over-both-ceilings-names-both", content=_OVER_BOTH),
    # CLAUDE.md carries its own threshold pair and its own hint. A migration
    # that collapsed the two kinds would keep exit 0 and change these bytes.
    Case(id="claude-md-over-the-ceiling-warns", file_path=CLAUDE_PATH, content=_OVER_LINES),
    Case(
        id="claude-md-ceiling-comes-from-the-profile-config",
        file_path=CLAUDE_PATH,
        content="line\n" * 20,
        config_extra="\n[hooks.pre_tool_use]\nclaude_md_max_lines = 10\n",
    ),
    Case(
        id="claude-md-ceiling-falls-back-when-the-config-is-malformed",
        file_path=CLAUDE_PATH,
        content=_OVER_LINES,
        config_raw="this is not [ valid toml",
    ),
    # The projection: the file on disk plus what the edit would do to it.
    Case(
        id="edit-projects-the-post-edit-file-and-warns",
        tool_name="Edit",
        on_disk="existing\n" * 195,
        old_string="existing\n",
        new_string="existing\n" + "new line\n" * 30,
    ),
    # `replace_all` decides between 300 projected lines and 151 -- the pair
    # below is the same edit twice, differing only in that flag.
    Case(
        id="edit-with-replace-all-projects-every-occurrence-and-warns",
        tool_name="Edit",
        on_disk="a\n" * 150,
        old_string="a\n",
        new_string="a\na\n",
        replace_all=True,
    ),
    # --- the branches that stay silent -----------------------------------
    Case(
        id="edit-without-replace-all-projects-one-occurrence-and-stays-silent",
        tool_name="Edit",
        on_disk="a\n" * 150,
        old_string="a\n",
        new_string="a\na\n",
    ),
    Case(id="write-under-both-ceilings-is-silent", content=_UNDER_BOTH),
    Case(id="claude-md-under-the-ceiling-is-silent", file_path=CLAUDE_PATH, content=_UNDER_BOTH),
    # An `Edit` whose target does not exist has nothing to project from.
    Case(
        id="edit-on-a-file-that-does-not-exist-is-silent",
        tool_name="Edit",
        file_path="/nowhere/memory/MEMORY.md",
        old_string="x",
        new_string="y" * 20000,
    ),
    Case(
        id="a-path-that-is-neither-memory-md-nor-claude-md-is-silent",
        file_path="/repo/notes.md",
        content=_OVER_LINES,
    ),
    # The filename match is exact, not a loose suffix: `NOTCLAUDE.md` ends in
    # `CLAUDE.md` as a string and must not be swept in.
    Case(
        id="a-file-merely-ending-in-claude-md-is-silent",
        file_path="/repo/NOTCLAUDE.md",
        content=_OVER_LINES,
    ),
    Case(
        id="a-tool-this-hook-does-not-inspect-is-silent",
        tool_name="Bash",
        file_path=MEMORY_PATH,
        content=_OVER_LINES,
    ),
    # Trap 3, frozen as bytes. See the module docstring: this is the case that
    # turns red if the tool-name gate is replaced by the operation.
    Case(
        id="notebook-edit-naming-memory-md-is-not-inspected",
        tool_name="NotebookEdit",
        path_key="notebook_path",
        content=_OVER_LINES,
    ),
    # The consolidator pathway rewrites MEMORY.md wholesale on purpose.
    Case(
        id="the-bypass-env-var-silences-the-warning",
        content=_OVER_LINES,
        env_extra={"LH_MEMORY_SIZE_BYPASS": "1"},
    ),
    # --- payloads that are not the shape the agent sends -------------------
    Case(
        id="a-tool-input-that-is-not-a-dict-is-silent",
        raw_stdin=json.dumps(
            {
                "hook_event_name": "PreToolUse",
                "session_id": SESSION,
                "tool_name": "Write",
                "tool_input": ["not", "a", "dict"],
            }
        ),
    ),
    Case(
        id="a-file-path-that-is-not-a-string-is-silent",
        raw_stdin=json.dumps(
            {
                "hook_event_name": "PreToolUse",
                "session_id": SESSION,
                "tool_name": "Write",
                "tool_input": {"file_path": 12345, "content": "line\n" * 250},
            }
        ),
    ),
    Case(id="stdin-empty", raw_stdin=""),
    Case(id="stdin-malformed-json", raw_stdin="not json"),
    Case(id="stdin-valid-json-that-is-not-an-object", raw_stdin="null"),
]

#: The payloads the runner refuses once this hook is migrated. Decision 3's
#: informational column: exit 0, a warning on stderr, no stdout. Before the
#: migration `_read_stdin_json` degraded them to `{}`, the tool-name gate saw
#: nothing and the hook exited 0 silently -- so these are the licensed
#: divergence, and the only ones.
UNUSABLE_PAYLOAD_CASE_IDS: frozenset[str] = frozenset(
    {"stdin-empty", "stdin-malformed-json", "stdin-valid-json-that-is-not-an-object"}
)


@dataclass
class World:
    """The tmp tree one case runs in."""

    work: Path
    agent_dir: Path
    payload_path: str
    env: dict[str, str] = field(default_factory=dict)
    stdin: str = "{}"
    rules: tuple[tuple[str, str], ...] = ()


def _build(tmp_path: Path, case: Case) -> World:
    home = tmp_path / "home"
    config_dir = tmp_path / "config"
    data_dir = tmp_path / "data"
    work = tmp_path / "work"
    agent_dir = tmp_path / "claude"
    for d in (home, config_dir, data_dir, work, agent_dir):
        d.mkdir(parents=True, exist_ok=True)

    config = case.config_raw if case.config_raw is not None else _CONFIG_MIN + case.config_extra
    (config_dir / "config.toml").write_text(config)

    payload_path = case.file_path
    if case.on_disk is not None:
        target = work / case.on_disk_name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(case.on_disk)
        payload_path = str(target)

    env = pinned_env(
        home=home,
        config_dir=config_dir,
        data_dir=data_dir,
        agent_config_dir=agent_dir,
        extra=case.env_extra,
    )

    if case.raw_stdin is not None:
        stdin = case.raw_stdin
    else:
        tool_input: dict[str, object] = {case.path_key: payload_path}
        if case.content is not None:
            tool_input["content"] = case.content
        if case.old_string is not None:
            tool_input["old_string"] = case.old_string
        if case.new_string is not None:
            tool_input["new_string"] = case.new_string
        if case.replace_all:
            tool_input["replace_all"] = True
        stdin = json.dumps(
            {
                "hook_event_name": "PreToolUse",
                "session_id": SESSION,
                "cwd": str(work),
                "tool_name": case.tool_name,
                "tool_input": tool_input,
            }
        )

    return World(
        work=work,
        agent_dir=agent_dir,
        payload_path=payload_path,
        env=env,
        stdin=stdin,
        # One rule, named here rather than applied silently: the `Edit` cases
        # must point at a real file, and the warning echoes the path back.
        rules=((str(tmp_path), "<tmp>"),),
    )


def _run(world: World) -> HookRun:
    run = run_through_runner(HOOK, stdin_text=world.stdin, cwd=world.work, env=world.env)
    return normalise_run(run, world.rules)


@pytest.mark.parametrize("case", CASES, ids=lambda c: c.id)
def test_golden(case: Case, tmp_path: Path) -> None:
    world = _build(tmp_path, case)

    assert_golden(HOOK, case.id, _run(world))


def test_case_ids_are_unique() -> None:
    ids = [c.id for c in CASES]
    assert len(ids) == len(set(ids))


def test_no_golden_leaks_a_path_from_the_machine_that_captured_it() -> None:
    """Every case's bytes are reproducible off this repo alone."""
    for case in CASES:
        golden = json.loads(golden_path(HOOK, case.id).read_text())
        blob = golden["stdout"] + golden["stderr"]
        assert "/Users/" not in blob, case.id
        assert "/private/" not in blob, case.id
        assert "/var/folders/" not in blob, case.id


def _system_message(case_id: str) -> str:
    golden = json.loads(golden_path(HOOK, case_id).read_text())
    assert golden["exit_code"] == 0
    body = json.loads(golden["stdout"])
    assert "hookSpecificOutput" not in body, (
        "the warning is the only output; a hookSpecificOutput carrying nothing "
        "Claude Code reads is noise"
    )
    return str(body["systemMessage"])


def test_the_line_ceiling_breach_names_the_file_and_the_threshold() -> None:
    assert _system_message("write-over-the-line-ceiling-warns") == (
        f"WARN: MEMORY.md at {MEMORY_PATH} would be 250 lines (threshold 200). "
        "Consider running `lh memory consolidate` to distill recent JSONL entries, "
        "or move detail out of the index into the linked note, before adding more."
    )


def test_a_file_small_in_lines_and_large_in_bytes_still_warns() -> None:
    """67 lines and ~20KB — the shape the line ceiling alone waves through."""
    message = _system_message("write-over-the-byte-ceiling-warns")

    assert "lines (threshold" not in message
    assert f"{len(_FAT_INDEX.encode('utf-8')) / 1000:.1f}KB (threshold 12KB)" in message


def test_both_breaches_are_reported_together() -> None:
    message = _system_message("write-over-both-ceilings-names-both")

    assert "250 lines (threshold 200) and 25.2KB (threshold 12KB)" in message


def test_claude_md_gets_its_own_kind_and_its_own_hint() -> None:
    """The two files have different jobs, and the remedy differs with them."""
    message = _system_message("claude-md-over-the-ceiling-warns")

    assert message.startswith(f"WARN: CLAUDE.md at {CLAUDE_PATH} would be 250 lines")
    assert "`lh memory rightsize`" in message
    assert "consolidate" not in message


def test_the_claude_md_ceiling_is_read_from_the_config() -> None:
    message = _system_message("claude-md-ceiling-comes-from-the-profile-config")

    assert "20 lines (threshold 10)" in message


def test_a_malformed_config_falls_back_to_the_default_ceiling() -> None:
    """Fail-soft: an unparseable config must not silence the warning."""
    message = _system_message("claude-md-ceiling-falls-back-when-the-config-is-malformed")

    assert "250 lines (threshold 200)" in message


def test_the_projection_applies_the_edit_rather_than_measuring_the_file() -> None:
    """195 lines on disk, 225 after the edit — only the projection breaches."""
    message = _system_message("edit-projects-the-post-edit-file-and-warns")

    assert "225 lines (threshold 200)" in message


def test_replace_all_is_part_of_the_projection() -> None:
    """The same edit twice. Dropping the flag makes 300 lines read as 151."""
    with_flag = _system_message("edit-with-replace-all-projects-every-occurrence-and-warns")
    without = json.loads(
        golden_path(
            HOOK, "edit-without-replace-all-projects-one-occurrence-and-stays-silent"
        ).read_text()
    )

    assert "300 lines (threshold 200)" in with_flag
    assert without == {"exit_code": 0, "stderr": "", "stdout": ""}


@pytest.mark.parametrize(
    "case_id",
    [
        "write-under-both-ceilings-is-silent",
        "claude-md-under-the-ceiling-is-silent",
        "edit-without-replace-all-projects-one-occurrence-and-stays-silent",
        "edit-on-a-file-that-does-not-exist-is-silent",
        "a-path-that-is-neither-memory-md-nor-claude-md-is-silent",
        "a-file-merely-ending-in-claude-md-is-silent",
        "a-tool-this-hook-does-not-inspect-is-silent",
        "notebook-edit-naming-memory-md-is-not-inspected",
        "the-bypass-env-var-silences-the-warning",
        "a-tool-input-that-is-not-a-dict-is-silent",
        "a-file-path-that-is-not-a-string-is-silent",
    ],
)
def test_the_silent_branches_write_nothing_on_any_channel(case_id: str) -> None:
    golden = json.loads(golden_path(HOOK, case_id).read_text())

    assert golden == {"exit_code": 0, "stderr": "", "stdout": ""}


def test_a_notebook_named_memory_md_is_refused_by_the_tool_gate_alone(tmp_path: Path) -> None:
    """The narrowing trap 3 asks for, asserted where the golden cannot see it.

    `notebook-edit-naming-memory-md-is-not-inspected` freezes to the same bytes
    as every other silent branch, so on its own it cannot say *why* the hook
    stayed quiet. This is the contrast: the identical payload under `Write`
    warns, which means the silence above comes from the tool name and from
    nothing else — the filename re-check passes a notebook just as happily.
    """
    notebook = next(c for c in CASES if c.id == "notebook-edit-naming-memory-md-is-not-inspected")
    as_write = Case(id=notebook.id, tool_name="Write", content=notebook.content)

    silent = _run(_build(tmp_path / "notebook", notebook))
    warned = _run(_build(tmp_path / "write", as_write))

    assert silent.stdout == ""
    assert "MEMORY.md" in warned.stdout


def test_the_warning_is_also_recorded_in_hooks_log(tmp_path: Path) -> None:
    """The audit line, which no golden channel carries.

    The warning reaches the agent on stdout; the log is what makes its frequency
    auditable afterwards, and it is the effect
    `tests/integration/test_hook_log_profile_isolation.py` holds to a profile.
    """
    case = next(c for c in CASES if c.id == "write-over-the-line-ceiling-warns")
    world = _build(tmp_path, case)

    run = _run(world)

    assert run.exit_code == 0
    log = (world.agent_dir / "logs" / "hooks.log").read_text()
    assert HOOK in log
    assert f"over threshold: {MEMORY_PATH} would be 250 lines (threshold 200)" in log


def test_a_silent_branch_writes_no_audit_line(tmp_path: Path) -> None:
    """The contrast, without which the assertion above passes on a hook that
    logged every tool call it ever saw."""
    case = next(c for c in CASES if c.id == "write-under-both-ceilings-is-silent")
    world = _build(tmp_path, case)

    _run(world)

    assert not (world.agent_dir / "logs" / "hooks.log").exists()


@pytest.mark.parametrize("case_id", sorted(UNUSABLE_PAYLOAD_CASE_IDS))
def test_an_unusable_payload_warns_instead_of_running_silently(case_id: str) -> None:
    """The only goldens this migration did not keep byte-identical, named.

    What the pre-migration bytes carried, recorded here because the files no
    longer do:

        {"exit_code": 0, "stderr": "", "stdout": ""}

    Nothing is lost: on `{}` this hook had no tool call, no path and no file to
    project, so the refusal replaces a silent no-op with a named one.
    """
    golden = json.loads(golden_path(HOOK, case_id).read_text())

    assert golden["exit_code"] == 0
    assert golden["stdout"] == ""
    assert golden["stderr"].startswith(f"{HOOK}: unparseable payload")

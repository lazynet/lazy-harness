"""Byte goldens for `post-tool-use-sync-system-doc`, one per branch, captured pre-migration.

This hook has no output channel. Every branch ends at `sys.exit(0)` having
written nothing to stdout or stderr, so the three frozen channels collapse to
the same `{"exit_code": 0, "stderr": "", "stdout": ""}` on all of them — a file
that a `main()` whose whole body is `return HookDecision()` reproduces exactly.
Wave A measured that four times over; the migration plan's step 1 says so.

So the evidence here is the **filesystem effect**: which profiles' system doc
the hook regenerated. `SEGMENT_FILES` (`:27`) is the gate, and regeneration is
the only thing this hook has ever done, so `_regenerated()` below is the real
assertion and the goldens are the smaller half.

Two branches carry the traps this wave was warned about:

* `a-notebook-edit-named-as-a-segment-regenerates-the-tree` is **trap 3**,
  resolved by accepting it. `_TOOL_OPERATIONS` maps `NotebookEdit` to
  `Operation.MODIFY_FILE` alongside `Edit` and `Write` (`claude_code.py:97`),
  and `_FILE_PATH_KEYS` folds `notebook_path` into the same `FileEdit.path`.
  This hook's second gate is a *filename* match, not an extension, so a
  `NotebookEdit` whose path is named `CLAUDE.head.md` clears it once the
  tool-name gate becomes the operation — an accepted, documented cost of the
  widening, not a real path any agent produces: Claude Code's `NotebookEdit`
  only ever carries a `.ipynb` path, which is
  `a-notebook-edit-on-a-realistic-ipynb-path-regenerates-nothing` below.
* `a-head-edit-regenerates-every-profile-in-the-tree` records what
  `sync_profiles` actually does: it walks the whole `profiles/` tree
  (`sync_agent_md.py:73`) rather than the one profile whose segment was
  touched. The tree is chosen by the *edited path*, never by `event.profile`.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from tests.unit.hooks.builtins._goldens import (
    assert_golden,
    golden_path,
    pinned_env,
    run_through_runner,
)

HOOK = "post-tool-use-sync-system-doc"

SESSION = "0193b0de-5555-6666-7777-888899990000"

#: What each profile's generated doc holds before the hook runs. Anything the
#: hook writes differs from it, so "regenerated" is observable without
#: re-deriving the generator's output here.
STALE = "STALE — written by the fixture, not by the hook\n"

#: Profiles the fixture tree carries. Two, because `sync_profiles` regenerates
#: every profile under the tree and a single-profile fixture could not show it.
PROFILES = ("alpha", "beta")

_CONFIG = """\
[harness]
version = "1"

[agent]
type = "claude-code"

[profiles]
default = "p"

[profiles.p]
config_dir = "{agent_dir}"
"""


@dataclass(frozen=True)
class Case:
    """One branch of `main()`."""

    id: str
    #: Native tool name the payload carries. `None` names no tool at all.
    tool: str | None = "Edit"
    #: Path relative to the fixture root, as the payload declares it.
    #: `None` declares a tool call carrying no path.
    path: str | None = "profiles/alpha/CLAUDE.head.md"
    #: The payload key the path goes under, which is the tool's own spelling.
    path_key: str = "file_path"
    #: `True` removes `_common/CLAUDE.common.md` before the hook runs.
    drop_common: bool = False
    #: Raw stdin, bypassing the payload builder entirely.
    raw_stdin: str | None = None
    #: Profiles whose generated doc the hook is expected to have rewritten.
    regenerates: tuple[str, ...] = ()
    #: Extra files to create under the fixture root before the run.
    extra_files: tuple[str, ...] = ()


CASES: list[Case] = [
    # --- the three segment names, each reaching the generator --------------- #
    Case(
        id="a-head-edit-regenerates-every-profile-in-the-tree",
        regenerates=PROFILES,
    ),
    Case(
        id="a-tail-write-regenerates-every-profile-in-the-tree",
        tool="Write",
        path="profiles/beta/CLAUDE.tail.md",
        regenerates=PROFILES,
    ),
    Case(
        id="a-common-edit-regenerates-every-profile-in-the-tree",
        path="profiles/_common/CLAUDE.common.md",
        regenerates=PROFILES,
    ),
    # --- the filename gate, which is this hook's whole discriminator -------- #
    Case(
        id="a-non-segment-file-regenerates-nothing",
        path="profiles/alpha/settings.json",
        extra_files=("profiles/alpha/settings.json",),
    ),
    # The generated doc is not one of its own inputs. Without this the gate
    # could be "any CLAUDE*.md" and every case above would still pass.
    Case(id="the-generated-doc-is-not-a-segment", path="profiles/alpha/CLAUDE.md"),
    Case(
        id="a-segment-outside-a-profiles-tree-regenerates-nothing",
        path="elsewhere/CLAUDE.head.md",
        extra_files=("elsewhere/CLAUDE.head.md",),
    ),
    # --- the tool gate ------------------------------------------------------ #
    Case(id="a-read-regenerates-nothing", tool="Read"),
    # Trap 3, accepted. `NotebookEdit` is `MODIFY_FILE` too, and this path is
    # named like a segment, so the filename re-check does not save the
    # operation gate here -- a synthetic case, not a real one.
    Case(
        id="a-notebook-edit-named-as-a-segment-regenerates-the-tree",
        tool="NotebookEdit",
        path_key="notebook_path",
        regenerates=PROFILES,
    ),
    # What actually happens: `NotebookEdit` only ever carries a `.ipynb` path,
    # which never collides with a segment name.
    Case(
        id="a-notebook-edit-on-a-realistic-ipynb-path-regenerates-nothing",
        tool="NotebookEdit",
        path="profiles/alpha/notes.ipynb",
        path_key="notebook_path",
    ),
    Case(id="a-payload-naming-no-tool-regenerates-nothing", tool=None, path=None),
    Case(id="an-edit-with-no-file-path-regenerates-nothing", path=None),
    # --- the generator refusing, swallowed ---------------------------------- #
    Case(
        id="a-tree-without-the-common-segment-regenerates-nothing",
        drop_common=True,
    ),
    # --- an unusable payload ------------------------------------------------ #
    Case(id="stdin-malformed-json", raw_stdin="not json"),
    Case(id="stdin-empty", raw_stdin=""),
]

#: The payloads the runner refuses once this hook is migrated — decision 3's
#: informational column: exit 0, a warning on stderr, no stdout. Before the
#: migration `_read_stdin_json` degraded them to `{}` and the hook ran its gates
#: against it, finding no tool name and returning. Both states regenerate
#: nothing, so only the stderr byte differs; these are the licensed divergence.
UNUSABLE_PAYLOAD_CASE_IDS: frozenset[str] = frozenset({"stdin-empty", "stdin-malformed-json"})


@dataclass
class World:
    """The tmp tree one case runs in."""

    root: Path
    work: Path
    env: dict[str, str] = field(default_factory=dict)
    stdin: str = "{}"


def _build(tmp_path: Path, case: Case) -> World:
    home = tmp_path / "home"
    config_dir = tmp_path / "config"
    data_dir = tmp_path / "data"
    agent_dir = tmp_path / "agent"
    root = tmp_path / "root"
    work = tmp_path / "work"
    for d in (home, config_dir, data_dir, agent_dir, root, work):
        d.mkdir(parents=True, exist_ok=True)

    profiles = root / "profiles"
    common = profiles / "_common" / "CLAUDE.common.md"
    common.parent.mkdir(parents=True, exist_ok=True)
    if not case.drop_common:
        common.write_text("SHARED RULES\n", encoding="utf-8")
    for name in PROFILES:
        (profiles / name).mkdir(parents=True, exist_ok=True)
        (profiles / name / "CLAUDE.head.md").write_text(f"{name} HEAD\n", encoding="utf-8")
        (profiles / name / "CLAUDE.tail.md").write_text(f"{name} TAIL\n", encoding="utf-8")
        (profiles / name / "CLAUDE.md").write_text(STALE, encoding="utf-8")
    for extra in case.extra_files:
        target = root / extra
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("unrelated\n", encoding="utf-8")

    (config_dir / "config.toml").write_text(_CONFIG.format(agent_dir=agent_dir), encoding="utf-8")

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
            payload["tool_input"] = (
                {case.path_key: str(root / case.path)} if case.path is not None else {}
            )
        stdin = json.dumps(payload)

    env = pinned_env(
        home=home,
        config_dir=config_dir,
        data_dir=data_dir,
        agent_config_dir=agent_dir,
    )
    return World(root=root, work=work, env=env, stdin=stdin)


def _regenerated(root: Path) -> tuple[str, ...]:
    """Profiles whose generated doc no longer holds the fixture's sentinel."""
    profiles = root / "profiles"
    return tuple(
        name
        for name in PROFILES
        if (profiles / name / "CLAUDE.md").read_text(encoding="utf-8") != STALE
    )


@pytest.mark.parametrize("case", CASES, ids=lambda c: c.id)
def test_golden(case: Case, tmp_path: Path) -> None:
    world = _build(tmp_path, case)

    run = run_through_runner(HOOK, stdin_text=world.stdin, cwd=world.work, env=world.env)

    assert_golden(HOOK, case.id, run)


@pytest.mark.parametrize("case", CASES, ids=lambda c: c.id)
def test_the_regeneration_is_the_only_thing_this_hook_does(case: Case, tmp_path: Path) -> None:
    """The wire goldens are empty on every branch, so the filesystem carries the proof.

    This is the assertion trap 3 fails against: swapping the `INSPECTED_TOOLS`
    gate for `event.tool.operation is Operation.MODIFY_FILE` keeps every golden
    file byte-identical and turns
    `a-notebook-edit-named-as-a-segment-regenerates-nothing` into a full
    regeneration of the tree.
    """
    world = _build(tmp_path, case)

    run_through_runner(HOOK, stdin_text=world.stdin, cwd=world.work, env=world.env)

    assert _regenerated(world.root) == case.regenerates


def test_what_it_writes_is_the_segments_joined_by_the_shipped_generator(tmp_path: Path) -> None:
    """`_regenerated` only says the file changed; this says what it changed into.

    Without it every positive case above would pass against a hook that
    truncated the doc, and the gate tests would read as green.
    """
    from lazy_harness.core.sync_agent_md import legacy_segment_names, render_agent_md

    case = next(c for c in CASES if c.id == "a-head-edit-regenerates-every-profile-in-the-tree")
    world = _build(tmp_path, case)

    run_through_runner(HOOK, stdin_text=world.stdin, cwd=world.work, env=world.env)

    for name in PROFILES:
        expected = render_agent_md(
            f"{name} HEAD\n",
            "SHARED RULES\n",
            f"{name} TAIL\n",
            names=legacy_segment_names("CLAUDE"),
        )
        assert (world.root / "profiles" / name / "CLAUDE.md").read_text(
            encoding="utf-8"
        ) == expected


def test_case_ids_are_unique() -> None:
    ids = [c.id for c in CASES]
    assert len(ids) == len(set(ids))


@pytest.mark.parametrize("case_id", [c.id for c in CASES if c.id not in UNUSABLE_PAYLOAD_CASE_IDS])
def test_every_usable_branch_is_silent_on_both_wire_channels(case_id: str) -> None:
    """This hook has no output channel: it must never grow one by accident.

    A PostToolUse hook that wrote to stdout would reach the agent as a hook
    decision on every file edit; one that wrote to stderr would surface in the
    transcript just as often.
    """
    golden = json.loads(golden_path(HOOK, case_id).read_text(encoding="utf-8"))

    assert golden == {"exit_code": 0, "stderr": "", "stdout": ""}


@pytest.mark.parametrize("case_id", sorted(UNUSABLE_PAYLOAD_CASE_IDS))
def test_an_unusable_payload_warns_instead_of_running_silently(case_id: str) -> None:
    """The only two goldens this migration did not keep byte-identical, named.

    Eleven of the thirteen cases matched their pre-migration capture exactly.
    These two are decision 3's informational column: the runner refuses a
    payload it cannot parse *before* the builtin is reached, where
    `_read_stdin_json` used to degrade it to `{}`. What the pre-migration bytes
    carried, recorded here because the files no longer do:

        {"exit_code": 0, "stderr": "", "stdout": ""}

    Nothing observable was traded away. The old hook ran its gates against
    `{}`, found no `tool_name`, and exited — so the filesystem effect is
    unchanged and `test_the_regeneration_is_the_only_thing_this_hook_does`
    covers both cases and still expects `()`. What is new is that a payload the
    runner could not read now says so on stderr instead of being
    indistinguishable from a tool call this hook was not interested in.
    """
    golden = json.loads(golden_path(HOOK, case_id).read_text(encoding="utf-8"))

    assert golden["exit_code"] == 0
    assert golden["stdout"] == ""
    assert golden["stderr"].startswith(f"{HOOK}: unparseable payload: ")


def test_the_trigger_set_is_derived_from_the_segment_roles() -> None:
    """Decision 5 — `SEGMENT_FILES` is computed, not listed.

    A static list is how renaming the segments stops firing the hook that
    regenerates the document from them: the rename lands, the hook keeps
    watching three filenames nobody edits any more, and the deployed contract
    file quietly goes stale.
    """
    from lazy_harness.core.sync_agent_md import segment_filenames
    from lazy_harness.hooks.builtins.post_tool_use_sync_system_doc import SEGMENT_FILES

    assert SEGMENT_FILES == segment_filenames()


def test_an_edit_to_a_role_named_segment_regenerates_the_tree(tmp_path: Path) -> None:
    """The hook fires on the role names, not only on the legacy ones."""
    from lazy_harness.hooks.builtins.post_tool_use_sync_system_doc import _trees_touched

    tree = tmp_path / "profiles"
    assert _trees_touched((tree / "lazy" / "head.md",)) == [tree]
    assert _trees_touched((tree / "_common" / "common.md",)) == [tree]
    assert _trees_touched((tree / "_common" / "claude-code.md",)) == [tree]

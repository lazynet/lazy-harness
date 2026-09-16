"""Byte goldens for `pre-tool-use-read-size`, captured before its migration.

This hook has a channel a golden can see — a top-level `systemMessage` — so the
cases here discriminate instead of all freezing to the same empty triple, which
is what wave A measured for the channel-less hooks. The warning text carries the
line count and the token estimate, so a `main()` that mis-measured or stopped
emitting shows up as a byte difference rather than as a green run.

**The path is normalised, and it is the only thing that is.** The warning quotes
the file path the payload named, which is inside `tmp_path` and therefore differs
per machine and per run. `_goldens.py` licenses exactly this — "what genuinely
cannot be pinned is normalised by an explicit rule the calling test names and
justifies" — so the work directory is replaced by `<work>` and nothing else is
touched. Using a *relative* `file_path` would have made the bytes deterministic
without a rule, and was rejected: Claude Code sends an absolute path, and a
golden captured on a shape the agent never sends freezes a branch nobody runs.

**`cwd` is not a variable here.** Trap 1 is about builtins that encode the
working directory into a path they write; this one never reads `cwd`, before or
after the migration. The cases declare it because a payload without one is not
the shape the agent sends, and `work` is realpath'd because `os.getcwd()` is
symlink-resolved on macOS while the payload is not.
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

HOOK = "pre-tool-use-read-size"

SESSION = "0193b0de-7777-8888-9999-aaaabbbbcccc"

_CONFIG_MIN = '[harness]\nversion = "1"\n'

#: Stands in for the work directory in every captured channel. See the module
#: docstring: the warning quotes the path, and `tmp_path` is not reproducible.
_WORK = "<work>"


@dataclass(frozen=True)
class Case:
    """One branch of the hook's decision."""

    id: str
    #: Path relative to the work directory. The payload carries it absolute.
    target: str = "big.md"
    #: Lines written to the target. `None` leaves the file absent.
    lines: int | None = 3000
    #: `tool_input` keys beyond the path, exactly as the payload carries them.
    bounds: dict[str, object] = field(default_factory=dict)
    #: The tool the payload names.
    tool_name: str = "Read"
    #: Send no path at all, for the shape a malformed `tool_input` produces.
    omit_path: bool = False
    #: Extra environment for the child, on top of `pinned_env`.
    extra_env: dict[str, str] = field(default_factory=dict)
    #: Raw stdin, for the payloads that are not JSON objects.
    raw_stdin: str | None = None


CASES: list[Case] = [
    # The branch the hook exists for.
    Case(id="unbounded-read-of-a-large-file-warns"),
    # `MAX_LINES` is a promise about where the warning starts. Only a pair
    # either side of it says the comparison is `>` and not `>=` or `<`.
    Case(id="a-file-at-the-ceiling-is-silent", lines=500),
    Case(id="a-file-one-line-over-the-ceiling-warns", lines=501),
    # --- the bounds -------------------------------------------------------
    Case(id="a-read-bounded-by-limit-is-silent", bounds={"limit": 200}),
    # `offset` of 0 is a legitimate bound and the adapter's `_as_int` keeps it
    # as 0 rather than collapsing it to None. A migrated `main` that wrote
    # `if event.tool.offset:` instead of `is not None` turns this case red;
    # nothing else in the set would notice.
    Case(id="a-read-bounded-by-offset-zero-is-silent", bounds={"offset": 0}),
    Case(id="a-read-bounded-by-both-is-silent", bounds={"offset": 100, "limit": 200}),
    # --- the sizes --------------------------------------------------------
    Case(id="a-small-file-is-silent", target="notes.md", lines=50),
    # `_measure` returns None on an empty file rather than (0, 0), so this is a
    # different branch from the small file above.
    Case(id="an-empty-file-is-silent", target="empty.md", lines=0),
    Case(id="a-missing-file-is-silent", target="nope.md", lines=None),
    # --- the gates --------------------------------------------------------
    Case(id="another-tool-is-not-inspected", tool_name="Grep"),
    # Trap 3 from the other side. `_TOOL_OPERATIONS` maps only `Read` to
    # `READ_FILE`, so this hook's operation gate is not a widening the way
    # `MODIFY_FILE` is — but `NotebookEdit` is the tool that made that trap, and
    # freezing it here is what turns red if a later adapter maps a second tool
    # into `READ_FILE` while this hook's native-name narrowing is gone.
    Case(id="notebook-edit-is-not-inspected", tool_name="NotebookEdit"),
    Case(id="a-tool-input-naming-no-path-is-silent", omit_path=True),
    Case(
        id="the-bypass-env-var-silences-the-warning",
        extra_env={"LH_READ_SIZE_BYPASS": "1"},
    ),
    # --- malformed bounds -------------------------------------------------
    # The one behavioural golden this migration does not preserve. See
    # `test_a_non_integer_bound_no_longer_counts_as_bounded`.
    Case(id="a-string-offset-is-not-a-bound", bounds={"offset": "0"}),
    # --- unusable payloads ------------------------------------------------
    Case(id="stdin-empty", raw_stdin=""),
    Case(id="stdin-malformed-json", raw_stdin="not json"),
]

#: The payloads the runner refuses once this hook is migrated. Decision 3's
#: informational column: exit 0, a warning on stderr, no stdout. Before the
#: migration `_read_stdin_json` degraded them to `{}`, the tool-name gate saw
#: nothing and the hook exited 0 silently.
UNUSABLE_PAYLOAD_CASE_IDS: frozenset[str] = frozenset({"stdin-empty", "stdin-malformed-json"})


@dataclass
class World:
    """The tmp tree one case runs in."""

    work: Path
    target: Path
    agent_dir: Path
    global_agent_dir: Path
    env: dict[str, str] = field(default_factory=dict)
    stdin: str = "{}"


def _build(tmp_path: Path, case: Case, *, profile: str | None = None) -> World:
    """Lay out one case's tree.

    `profile` writes a `[profiles.<name>] config_dir` **and clears
    `CLAUDE_CONFIG_DIR`**: `agent_runtime_dir` resolves the adapter's env var
    above the profile's `config_dir`, so leaving it set makes the global answer
    and the per-profile answer the same path and no isolation assertion can fail.
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

    config = _CONFIG_MIN
    if profile is not None:
        config += f'\n[profiles.{profile}]\nconfig_dir = "{agent_dir}"\nroots = ["~"]\n'
    (config_dir / "config.toml").write_text(config)

    target = work / case.target
    if case.lines is not None:
        target.write_text("key: value\n" * case.lines)

    env = pinned_env(
        home=home,
        config_dir=config_dir,
        data_dir=data_dir,
        agent_config_dir=env_agent_dir,
        extra=case.extra_env,
    )
    if profile is not None:
        env["CLAUDE_CONFIG_DIR"] = ""

    if case.raw_stdin is not None:
        stdin = case.raw_stdin
    else:
        tool_input: dict[str, object] = dict(case.bounds)
        if not case.omit_path:
            tool_input["file_path"] = str(target)
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
        target=target,
        agent_dir=agent_dir,
        global_agent_dir=global_agent_dir,
        env=env,
        stdin=stdin,
    )


def _run(world: World) -> HookRun:
    run = run_through_runner(HOOK, stdin_text=world.stdin, cwd=world.work, env=world.env)
    return normalise_run(run, ((str(world.work), _WORK),))


@pytest.mark.parametrize("case", CASES, ids=lambda c: c.id)
def test_golden(case: Case, tmp_path: Path) -> None:
    world = _build(tmp_path, case)

    assert_golden(HOOK, case.id, _run(world))


def test_case_ids_are_unique() -> None:
    ids = [c.id for c in CASES]
    assert len(ids) == len(set(ids))


def test_no_golden_leaks_a_path_from_the_machine_that_captured_it() -> None:
    """Every case's bytes are reproducible off this repo alone.

    The normalisation rule above is what makes that true for the warning text;
    this is the assertion that the rule covered every path it had to.
    """
    for case in CASES:
        golden = json.loads(golden_path(HOOK, case.id).read_text())
        blob = golden["stdout"] + golden["stderr"]
        assert "/Users/" not in blob, case.id
        assert "/private/" not in blob, case.id
        assert "/var/folders" not in blob, case.id


def test_the_warning_reaches_the_agent_on_the_system_message_channel() -> None:
    """The bytes the agent actually reads, named rather than left in a file.

    `systemMessage` is top level on purpose: `hookSpecificOutput` accepts four
    keys and discards the rest, and nested there this warning parsed without
    error and displayed nothing. A migration that moved it inside would keep
    exit code 0 and a non-empty stdout, which reads as a working hook.
    """
    golden = json.loads(golden_path(HOOK, "unbounded-read-of-a-large-file-warns").read_text())
    body = json.loads(golden["stdout"])

    assert golden["exit_code"] == 0
    assert golden["stderr"] == ""
    assert body == {
        "systemMessage": (
            f"WARN: {_WORK}/big.md is 3000 lines (~8250 tokens) and this Read "
            "is unbounded. Pass offset/limit for the region you need, or use Grep "
            "to locate it first."
        )
    }
    assert "hookSpecificOutput" not in body


def test_the_warning_carries_no_permission_decision() -> None:
    """Non-blocking on a blockable event: `pre_tool_use` honours `DENY`.

    `HookDecision.verdict` defaults to `None` so that a hook which merely has
    something to say does not thereby approve or refuse the call. This is that
    default asserted on the bytes; `test_pre_tool_use_read_size.py` asserts it
    on the returned decision, which is the half a re-captured golden cannot lie
    about.
    """
    golden = json.loads(golden_path(HOOK, "unbounded-read-of-a-large-file-warns").read_text())

    assert "permissionDecision" not in golden["stdout"]
    assert "decision" not in json.loads(golden["stdout"])


def test_the_ceiling_is_where_the_warning_starts() -> None:
    """`MAX_LINES` bounds what this hook is willing to stay quiet about."""
    from lazy_harness.hooks.builtins.pre_tool_use_read_size import MAX_LINES

    at = json.loads(golden_path(HOOK, "a-file-at-the-ceiling-is-silent").read_text())
    over = json.loads(golden_path(HOOK, "a-file-one-line-over-the-ceiling-warns").read_text())

    assert MAX_LINES == 500
    assert at == {"exit_code": 0, "stderr": "", "stdout": ""}
    assert f"is {MAX_LINES + 1} lines" in json.loads(over["stdout"])["systemMessage"]


@pytest.mark.parametrize(
    "case_id",
    [
        "a-file-at-the-ceiling-is-silent",
        "a-read-bounded-by-limit-is-silent",
        "a-read-bounded-by-offset-zero-is-silent",
        "a-read-bounded-by-both-is-silent",
        "a-small-file-is-silent",
        "an-empty-file-is-silent",
        "a-missing-file-is-silent",
        "another-tool-is-not-inspected",
        "notebook-edit-is-not-inspected",
        "a-tool-input-naming-no-path-is-silent",
        "the-bypass-env-var-silences-the-warning",
    ],
)
def test_the_silent_branches_write_nothing_on_any_channel(case_id: str) -> None:
    golden = json.loads(golden_path(HOOK, case_id).read_text())

    assert golden == {"exit_code": 0, "stderr": "", "stdout": ""}


def test_a_non_integer_bound_no_longer_counts_as_bounded() -> None:
    """The one behavioural divergence, named rather than left in a re-capture.

    `:89` read `tool_input.get("offset") is not None`, so any JSON value at all
    — including the string `"0"` — silenced the hook. The adapter's `_as_int`
    admits only a real int (`claude_code.py:59-64`), so `event.tool.offset` is
    `None` for that payload and the read is treated as unbounded. What the
    pre-migration bytes carried, recorded here because the file no longer does:

        {"exit_code": 0, "stderr": "", "stdout": ""}

    Kept rather than papered over with `event.tool.raw_input`, which the
    contract reserves for adapters: a bound the tool will not honour as a number
    is not a bound, and the cost of being wrong here is one extra advisory line
    on a payload shape Claude Code does not send. The same reasoning covers a
    bool, which `_as_int` also excludes.
    """
    golden = json.loads(golden_path(HOOK, "a-string-offset-is-not-a-bound").read_text())

    assert golden["exit_code"] == 0
    assert golden["stderr"] == ""
    assert "is unbounded" in json.loads(golden["stdout"])["systemMessage"]


@pytest.mark.parametrize("case_id", sorted(UNUSABLE_PAYLOAD_CASE_IDS))
def test_an_unusable_payload_warns_instead_of_running_silently(case_id: str) -> None:
    """The goldens this migration did not keep byte-identical, named.

    Decision 3's informational column: the runner refuses a payload it cannot
    parse *before* the builtin is reached, where `_read_stdin_json` used to
    degrade it to `{}` and let the tool-name gate exit 0 on it. What the
    pre-migration bytes carried, recorded here because the files no longer do:

        {"exit_code": 0, "stderr": "", "stdout": ""}

    Nothing is lost: on `{}` this hook had no tool name, no path and no file to
    measure, so the refusal replaces a silent no-op with a named one.
    """
    golden = json.loads(golden_path(HOOK, case_id).read_text())

    assert golden["exit_code"] == 0
    assert golden["stdout"] == ""
    assert golden["stderr"].startswith(f"{HOOK}: unparseable payload")

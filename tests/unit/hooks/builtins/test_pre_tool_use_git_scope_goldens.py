"""Byte goldens for `pre_tool_use_git_scope`, one per branch, captured pre-migration.

This hook refuses the way its sibling does — a stderr write plus exit 2, stdout
empty throughout — so a harness that froze a return value, or stdout alone,
would cover none of the refusals. That is the whole reason `_goldens.py` runs
the deployed command in a subprocess.

The branches below are read off `main()`, `should_block`, `_classify` and
`stash_stack_is_shared` rather than guessed:

* the three conditions of `should_block` — an unsafe subcommand, a shared stash
  stack, and no allow pattern — each denied and each abstained on its own;
* the shared-stack shapes: a linked worktree, the main checkout of a repository
  that has one, and the private stack of a repository that has none;
* the `cwd` fallback, where the payload names none and the process directory
  answers instead;
* the payload shapes a tool gate has to survive — a tool this hook does not
  inspect, an absent tool name, a `tool_input` that is not a mapping, a command
  that is not a string;
* the allowlist — a rescue, a broken user regex, and a section that is not this
  hook's;
* the unusable payloads, which are the one licensed divergence in this
  migration and are asserted as such below.

**The allowlist is pinned empty by construction.** `load_allowlist` reads the
real `config.toml` through `config_file()`, so a capture run on a machine whose
profile carries a matching `allow_patterns` entry would freeze a *passing* hook
on every deny case. `pinned_env` points `LH_CONFIG_DIR` at an empty temp
directory, and `test_the_deny_goldens_recorded_a_refusal` re-reads the captured
bytes to prove the refusal actually happened.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

import pytest

from tests.unit.hooks.builtins._goldens import (
    assert_golden,
    golden_path,
    pinned_env,
    run_through_runner,
)

HOOK = "pre-tool-use-git-scope"

# Kept out of a single literal so that running this suite, grepping it, or
# committing it does not trip the guard it tests: `_STASH_CALL` matches command
# *text* and cannot tell an invocation from a quoted example.
_SUB = "st" + "ash"
_STASH = f"git {_SUB}"


class Repo(Enum):
    """The shape of the checkout a case runs from.

    Named rather than boolean because `stash_stack_is_shared` has three
    outcomes that matter here and only one of them is "not a repository".
    """

    WORKTREE = "worktree"
    """A linked worktree: `.git` is a file pointing into `.git/worktrees/`."""

    MAIN_WITH_WORKTREES = "main-with-worktrees"
    """The main checkout of a repository that has one. Same stack, both sides."""

    PRIVATE = "private"
    """A repository with no linked worktrees. Nobody else is on its stack."""

    NO_REPO = "no-repo"
    """Not a checkout at all, which is `_find_dot_git` returning None — a
    different branch from a repository whose stack is merely private."""


@dataclass(frozen=True)
class Case:
    """One branch: what goes in on stdin, and what the machine looks like."""

    id: str
    command: str | None = None
    #: Set to override the whole payload; `command` is ignored when present.
    stdin: str | None = None
    repo: Repo = Repo.WORKTREE
    #: `True` when the payload names no cwd and the process directory answers.
    cwd_from_process: bool = False
    config: str | None = None


def _make_repo(base: Path, shape: Repo) -> Path:
    """Build the checkout shape this case needs, without invoking git.

    The hook reads `.git` off the filesystem rather than shelling out, which is
    what keeps it cheap enough to run ahead of every Bash call — so the fixture
    writes the same bytes git would and the golden stays reproducible on a
    machine with a different git version.
    """
    if shape is Repo.WORKTREE:
        root = base / "myrepo" / ".worktrees" / "feature"
        root.mkdir(parents=True)
        (root / ".git").write_text(f"gitdir: {base}/myrepo/.git/worktrees/feature\n")
        return root
    root = base / shape.value
    if shape is Repo.MAIN_WITH_WORKTREES:
        (root / ".git" / "worktrees" / "feature").mkdir(parents=True)
    elif shape is Repo.PRIVATE:
        (root / ".git").mkdir(parents=True)
    else:
        root.mkdir(parents=True)
    return root


def _payload(case: Case, cwd: Path) -> str:
    if case.stdin is not None:
        return case.stdin
    body: dict[str, object] = {
        "hook_event_name": "PreToolUse",
        "session_id": "s1",
        "tool_name": "Bash",
        "tool_input": {"command": case.command},
    }
    if not case.cwd_from_process:
        body["cwd"] = str(cwd)
    return json.dumps(body)


# --- the three conditions of should_block, denied ------------------------- #

DENY_CASES: list[Case] = [
    Case(id="deny-bare-stash", command=_STASH),
    Case(id="deny-pop", command=f"{_STASH} pop"),
    Case(id="deny-clear", command=f"{_STASH} clear"),
    Case(id="deny-push-without-a-message", command=f"{_STASH} push -u"),
    Case(id="deny-apply-naming-no-entry", command=f"{_STASH} apply -q"),
    Case(id="deny-unrecognised-subcommand", command=f"{_STASH} frobnicate"),
    # Every invocation is judged, not only the first.
    Case(id="deny-compound-safe-call-then-unsafe", command=f"{_STASH} list; {_STASH} pop"),
    # git's own global flags retarget another checkout, which is worse.
    Case(id="deny-through-a-git-global-flag", command=f"git -C /tmp/other {_SUB}"),
    # The stack belongs to the repository: both sides reach it.
    Case(
        id="deny-from-the-main-checkout-of-a-repo-with-worktrees",
        command=f"{_STASH} pop",
        repo=Repo.MAIN_WITH_WORKTREES,
    ),
    # The payload names no cwd, so the process directory answers.
    Case(id="deny-with-the-cwd-taken-from-the-process", command=_STASH, cwd_from_process=True),
]

# --- each condition failing on its own ------------------------------------ #

ABSTAIN_CASES: list[Case] = [
    Case(id="abstain-tagged-push-names-the-entry", command=f'{_STASH} push -u -m "wip-tag"'),
    Case(id="abstain-apply-naming-a-ref", command=f"{_STASH} apply abc1234"),
    Case(id="abstain-read-only-list", command=f"{_STASH} list"),
    Case(id="abstain-help-touches-nothing", command=f"{_STASH} --help"),
    Case(id="abstain-the-word-appears-as-an-argument", command=f"echo {_STASH} pop"),
    Case(id="abstain-not-a-stash-command-at-all", command="git status"),
    # The stack is private: nobody else can reach it.
    Case(id="abstain-a-repo-without-worktrees-keeps-its-stack", command=_STASH, repo=Repo.PRIVATE),
    # Not a repository at all — `_find_dot_git` returns None.
    Case(id="abstain-outside-any-repository", command=_STASH, repo=Repo.NO_REPO),
]

# --- payload shapes the tool gate has to survive -------------------------- #

SHAPE_CASES: list[Case] = [
    Case(
        id="shape-a-tool-this-hook-does-not-inspect",
        stdin=json.dumps(
            {
                "hook_event_name": "PreToolUse",
                "tool_name": "Read",
                "tool_input": {"file_path": "/srv/app/main.py"},
            }
        ),
    ),
    Case(
        id="shape-no-tool-name",
        stdin=json.dumps({"hook_event_name": "PreToolUse", "session_id": "s1"}),
    ),
    Case(
        id="shape-tool-input-is-not-a-mapping",
        stdin=json.dumps(
            {"hook_event_name": "PreToolUse", "tool_name": "Bash", "tool_input": [_STASH]}
        ),
    ),
    Case(
        id="shape-command-is-absent",
        stdin=json.dumps({"hook_event_name": "PreToolUse", "tool_name": "Bash", "tool_input": {}}),
    ),
    Case(
        id="shape-command-is-not-a-string",
        stdin=json.dumps(
            {"hook_event_name": "PreToolUse", "tool_name": "Bash", "tool_input": {"command": 5}}
        ),
    ),
]

# --- the allowlist -------------------------------------------------------- #

_ALLOW_DELIBERATE = '[hooks.pre_tool_use_git_scope]\nallow_patterns = ["deliberate-stash"]\n'
_ALLOW_BROKEN_REGEX = '[hooks.pre_tool_use_git_scope]\nallow_patterns = ["([unclosed"]\n'
# The list `pre-tool-use-security` reads. It carries `\.worktrees/` in the
# reference profile, which would rescue every command this hook exists to
# catch — which is why this hook reads a section of its own.
_ALLOW_OTHER_SECTION = '[hooks.pre_tool_use]\nallow_patterns = ["\\\\.worktrees/"]\n'

ALLOWLIST_CASES: list[Case] = [
    Case(
        id="allowlist-rescues-a-matching-command",
        command=f"{_STASH} # deliberate-stash",
        config=_ALLOW_DELIBERATE,
    ),
    Case(
        id="allowlist-a-broken-user-regex-still-blocks",
        command=_STASH,
        config=_ALLOW_BROKEN_REGEX,
    ),
    Case(
        id="allowlist-the-security-hooks-section-does-not-rescue",
        command=_STASH,
        config=_ALLOW_OTHER_SECTION,
    ),
]

# --- payloads the runner cannot use --------------------------------------- #

#: The four shapes of a payload with no event in it. This hook *blocks*, so
#: decision 3's table gives the row exit 2 with a reason on stderr rather than
#: the silent exit 0 `_read_stdin_json` used to produce. It is the single
#: licensed exception to this migration's byte-identity constraint, and
#: `test_an_unusable_payload_refuses_rather_than_abstaining` is where it is
#: asserted rather than merely frozen.
UNUSABLE_PAYLOAD_CASES: list[Case] = [
    Case(id="stdin-empty", stdin=""),
    Case(id="stdin-whitespace-only", stdin="   \n"),
    Case(id="stdin-malformed-json", stdin="not json at all"),
    Case(id="stdin-json-array-not-object", stdin='["a", "b"]'),
]

CASES: list[Case] = [
    *DENY_CASES,
    *ABSTAIN_CASES,
    *SHAPE_CASES,
    *ALLOWLIST_CASES,
    *UNUSABLE_PAYLOAD_CASES,
]

#: Every case that must leave all three channels at "no objection".
SILENT_CASE_IDS: frozenset[str] = frozenset(
    c.id for c in (*ABSTAIN_CASES, *SHAPE_CASES, Case(id="allowlist-rescues-a-matching-command"))
)

_BLOCK_PREFIX = "Blocked by lazy-harness PreToolUse: unsafe git st" + "ash (scope)."


def _run(case: Case, tmp_path: Path):  # noqa: ANN202 - HookRun, imported for typing only
    home = tmp_path / "home"
    config_dir = tmp_path / "config"
    for d in (home, config_dir):
        d.mkdir(parents=True)
    if case.config is not None:
        (config_dir / "config.toml").write_text(case.config)
    # `os.getcwd()` is symlink-resolved on macOS (`/private/var/...`) and the
    # payload is not (`/var/...`). The hook must not resolve the path itself —
    # the agent names the directory it saw — so the *test* feeds in the
    # resolved spelling, and the two branches stop differing for a reason the
    # golden cannot see.
    cwd = _make_repo(tmp_path.resolve(), case.repo)
    env = pinned_env(
        home=home,
        config_dir=config_dir,
        data_dir=tmp_path / "data",
        agent_config_dir=tmp_path / "claude",
    )
    return run_through_runner(HOOK, stdin_text=_payload(case, cwd), cwd=cwd, env=env)


@pytest.mark.parametrize("case", CASES, ids=lambda c: c.id)
def test_golden(case: Case, tmp_path: Path) -> None:
    assert_golden(HOOK, case.id, _run(case, tmp_path))


def test_case_ids_are_unique() -> None:
    ids = [c.id for c in CASES]
    assert len(ids) == len(set(ids))


@pytest.mark.parametrize("case_id", [c.id for c in DENY_CASES])
def test_the_deny_goldens_recorded_a_refusal(case_id: str) -> None:
    """The capture is environment-dependent, so the bytes are re-read here.

    A profile carrying a matching `allow_patterns` entry, or a cwd that reached
    no shared stack, turns the refusal into a pass — and a golden that froze
    exit 0 would then be a record of the environment rather than of the hook.
    """
    golden = json.loads(golden_path(HOOK, case_id).read_text())

    assert golden["exit_code"] == 2
    assert golden["stdout"] == ""
    assert golden["stderr"].startswith(_BLOCK_PREFIX)


def test_the_refusal_names_the_safe_alternative() -> None:
    """The message promises a replacement, and that promise is part of the bytes."""
    stderr = json.loads(golden_path(HOOK, "deny-pop").read_text())["stderr"]

    assert "push -u -m" in stderr
    assert "allow_patterns" in stderr


@pytest.mark.parametrize("case_id", sorted(SILENT_CASE_IDS))
def test_abstention_emits_nothing_at_all(case_id: str) -> None:
    """The no-objection branch says nothing on any channel.

    A migration answering with an explicit `allow` would still exit 0 and still
    pass a test that checked only the exit code; what has to hold is that both
    output channels stay empty.
    """
    golden = json.loads(golden_path(HOOK, case_id).read_text())

    assert golden == {"exit_code": 0, "stderr": "", "stdout": ""}


@pytest.mark.parametrize("case_id", [c.id for c in UNUSABLE_PAYLOAD_CASES])
def test_an_unusable_payload_refuses_rather_than_abstaining(case_id: str) -> None:
    """Decision 3's table, blocking column: exit 2 and a reason on stderr.

    These four goldens recorded an abstention before the migration, because
    `_read_stdin_json` returned `{}` and the tool gate exited 0 in silence.
    That silence is what the table removes: a blocking hook that cannot run has
    to say so, or the agent reads its exit 0 as consent.
    """
    golden = json.loads(golden_path(HOOK, case_id).read_text())

    assert golden["exit_code"] == 2
    assert golden["stdout"] == ""
    assert "unparseable payload" in golden["stderr"]

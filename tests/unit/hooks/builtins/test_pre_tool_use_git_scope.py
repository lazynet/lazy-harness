"""Unit tests for the pre_tool_use_git_scope hook.

The hook blocks the `git stash` forms that reach into a shared stash stack
without naming what they touch, and only when the command runs from inside a
git worktree. The safe forms the harness itself recommends — a tagged
`git stash push -m`, an `apply` naming its entry — stay allowed, as do the
read-only subcommands.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Final

import pytest

from lazy_harness.agents.base import HookDecision, HookEvent, Operation, ToolCall, Verdict

_UNSET: Final = object()
"""Distinguishes "build the default tool call" from "hand `main` no tool call".

`None` is a value this hook has to survive, so it cannot double as the
"argument not given" marker."""

# Format: (command, human_label)
UNSAFE_STASH_CASES: list[tuple[str, str]] = [
    ("git stash", "bare stash creates an anonymous entry"),
    ("git stash push", "push without a message is equally anonymous"),
    ("git stash push -u", "untracked flag does not name the entry"),
    ("git stash push --include-untracked", "long untracked flag, still unnamed"),
    ("git stash save", "deprecated save, also unnamed"),
    ("git stash pop", "pop takes the top entry, which may be another session's"),
    ("git stash pop stash@{0}", "pop removes the entry even when named"),
    ("git stash clear", "clear destroys every session's entries"),
    ("git stash apply", "apply without a ref takes the top entry"),
    ("git stash drop", "drop without a ref discards the top entry"),
    ("cd src && git stash", "stash after a cd is still a stash"),
    ("git  stash   pop", "extra whitespace does not evade the rule"),
]

# Shapes that reached the shared stack while an earlier version of this hook
# waved them through. Each one was found by running the hook, not by reading it.
BYPASS_CASES: list[tuple[str, str]] = [
    # A single search() only ever saw the first `git stash` in the command.
    ("git stash list; git stash pop", "unsafe call after a safe one, semicolon"),
    ("git stash list && git stash pop", "unsafe call after a safe one, &&"),
    ('git stash push -m "tag"; git stash pop', "tagged push then a blind pop"),
    ("git stash show; git stash clear", "read-only then clear"),
    # The anchor was `^` without MULTILINE, and its separator class had no \n.
    ("  git stash", "leading whitespace"),
    ("\tgit stash pop", "leading tab"),
    ("cd src\ngit stash pop", "newline-separated, as a multiline script arrives"),
    ("set -e\ngit stash clear", "newline after a shell option"),
    # `if args:` counted a flag as though it named an entry.
    ("git stash drop -q", "short flag is not a ref"),
    ("git stash drop --quiet", "long flag is not a ref"),
    ("git stash apply --index", "--index is not a ref"),
    ("git stash apply -q", "short flag is not a ref"),
    # Wrappers and git's own global flags were never considered.
    ("env git stash pop", "env wrapper"),
    ("sudo git stash", "sudo wrapper"),
    ("command git stash pop", "command wrapper"),
    ("git -C /tmp/other stash", "git -C reaches another checkout entirely"),
    ("git --git-dir=.git stash pop", "global --git-dir flag"),
    ("git --no-pager stash pop", "global --no-pager flag"),
    ("git -c core.editor=true stash", "global -c flag"),
    # Punctuation glued to the subcommand fell through to a silent return None.
    ("(git stash pop)", "subshell parentheses"),
    ("{ git stash; }", "brace group"),
    ("if true; then git stash; fi", "inside an if"),
    ("for f in a; do git stash; done", "inside a for"),
    ("git stash > /dev/null", "redirect straight after a bare stash"),
    ("git stash 2>&1", "stderr redirect after a bare stash"),
]

# `--help` prints documentation and touches nothing.
HELP_CASES: list[tuple[str, str]] = [
    ("git stash --help", "bare stash help"),
    ("git stash push --help", "subcommand help"),
    ("git stash -h", "short help flag"),
]

# Format: (command, human_label)
SAFE_COMMAND_CASES: list[tuple[str, str]] = [
    ('git stash push -u -m "wip-tag"', "the form the harness recommends"),
    ("git stash push -m wip-tag", "message without quotes still names it"),
    ('git stash push --message "wip-tag"', "long message flag"),
    ("git stash apply abc1234", "apply naming a sha"),
    ("git stash apply stash@{0}", "apply naming a stash ref"),
    ("git stash drop stash@{1}", "drop naming a stash ref"),
    ("git stash list", "read-only"),
    ("git stash show", "read-only"),
    ("git stash show stash@{0}", "read-only with a ref"),
    ("git status", "not a stash command at all"),
    ("git commit -m 'stash the docs'", "the word stash inside a message"),
    ("echo 'git stash pop'", "stash named inside a quoted string"),
    # The case that actually exercises the command-position anchor: `git` here
    # is an argument to echo, not a command. Without the anchor this blocks.
    ("echo git stash pop", "stash named as an unquoted argument to echo"),
    ("printf 'git stash clear\\n'", "stash named in a printf format"),
]


def _make_worktree(tmp_path: Path) -> Path:
    """Build a directory that looks like a git worktree checkout.

    A worktree's `.git` is a file pointing into the main repo's
    `.git/worktrees/<name>`, which is the signal the hook keys on.
    """
    wt = tmp_path / "myrepo" / ".worktrees" / "feature"
    wt.mkdir(parents=True)
    (wt / ".git").write_text(f"gitdir: {tmp_path}/myrepo/.git/worktrees/feature\n")
    return wt


def _make_main_checkout(tmp_path: Path) -> Path:
    """Build a directory that looks like an ordinary (non-worktree) checkout."""
    root = tmp_path / "plainrepo"
    (root / ".git").mkdir(parents=True)
    return root


def _make_main_checkout_with_worktrees(tmp_path: Path) -> Path:
    """The main checkout of a repository that has linked worktrees.

    Its `.git` is a directory like any plain checkout, but `.git/worktrees/`
    holds one administrative directory per linked worktree — and the stash
    stack under it is reachable from here too.
    """
    root = tmp_path / "shared"
    (root / ".git" / "worktrees" / "feature").mkdir(parents=True)
    return root


def _make_submodule(tmp_path: Path) -> Path:
    """A submodule also has a `.git` file, but points into `.git/modules/`."""
    sub = tmp_path / "parent" / "vendor" / "lib"
    sub.mkdir(parents=True)
    (sub / ".git").write_text(f"gitdir: {tmp_path}/parent/.git/modules/lib\n")
    return sub


class TestIsUnsafeStash:
    @pytest.mark.parametrize("command,label", UNSAFE_STASH_CASES, ids=lambda v: v)
    def test_flags_unsafe_stash_forms(self, command: str, label: str) -> None:
        from lazy_harness.hooks.builtins.pre_tool_use_git_scope import is_unsafe_stash

        assert is_unsafe_stash(command) is not None, label

    @pytest.mark.parametrize("command,label", SAFE_COMMAND_CASES, ids=lambda v: v)
    def test_leaves_safe_commands_alone(self, command: str, label: str) -> None:
        from lazy_harness.hooks.builtins.pre_tool_use_git_scope import is_unsafe_stash

        assert is_unsafe_stash(command) is None, label

    def test_reason_names_the_subcommand_that_fired(self) -> None:
        from lazy_harness.hooks.builtins.pre_tool_use_git_scope import is_unsafe_stash

        verdict = is_unsafe_stash("git stash clear")
        assert verdict is not None
        assert "clear" in verdict.reason

    @pytest.mark.parametrize("command,label", BYPASS_CASES, ids=lambda v: v)
    def test_closes_known_bypasses(self, command: str, label: str) -> None:
        from lazy_harness.hooks.builtins.pre_tool_use_git_scope import is_unsafe_stash

        assert is_unsafe_stash(command) is not None, label

    @pytest.mark.parametrize("command,label", HELP_CASES, ids=lambda v: v)
    def test_help_touches_nothing_and_is_allowed(self, command: str, label: str) -> None:
        from lazy_harness.hooks.builtins.pre_tool_use_git_scope import is_unsafe_stash

        assert is_unsafe_stash(command) is None, label

    def test_a_pathspec_after_the_double_dash_is_not_a_message(self) -> None:
        """`--` ends the options; what follows names paths, not the entry."""
        from lazy_harness.hooks.builtins.pre_tool_use_git_scope import is_unsafe_stash

        assert is_unsafe_stash("git stash push -- -m") is not None

    def test_an_unknown_subcommand_is_treated_as_unsafe(self) -> None:
        """The allowlist decides. A subcommand nobody recognised still touches
        the stack, so it must not fall through to a silent pass."""
        from lazy_harness.hooks.builtins.pre_tool_use_git_scope import is_unsafe_stash

        assert is_unsafe_stash("git stash frobnicate") is not None

    def test_the_command_position_anchor_is_load_bearing(self) -> None:
        """Names the anchor's job directly, so deleting it fails a test.

        `echo git stash pop` runs echo, not stash. Without the anchor the
        substring alone would match and this would block.
        """
        from lazy_harness.hooks.builtins.pre_tool_use_git_scope import is_unsafe_stash

        assert is_unsafe_stash("echo git stash pop") is None
        assert is_unsafe_stash("git stash pop") is not None

    def test_read_only_subcommands_are_recognised_as_such(self) -> None:
        """Pins _READ_ONLY to observable behaviour: emptying it must break this.

        Asserted against `push`, which is unsafe without -m, so the difference
        between "recognised as read-only" and "fell through" is visible.
        """
        from lazy_harness.hooks.builtins.pre_tool_use_git_scope import is_unsafe_stash

        assert is_unsafe_stash("git stash list") is None
        assert is_unsafe_stash("git stash show") is None
        assert is_unsafe_stash("git stash push") is not None


class TestInWorktree:
    def test_detects_a_worktree_checkout(self, tmp_path: Path) -> None:
        from lazy_harness.hooks.builtins.pre_tool_use_git_scope import in_worktree

        assert in_worktree(str(_make_worktree(tmp_path))) is True

    def test_a_plain_checkout_is_not_a_worktree(self, tmp_path: Path) -> None:
        from lazy_harness.hooks.builtins.pre_tool_use_git_scope import in_worktree

        assert in_worktree(str(_make_main_checkout(tmp_path))) is False

    def test_a_submodule_is_not_a_worktree(self, tmp_path: Path) -> None:
        from lazy_harness.hooks.builtins.pre_tool_use_git_scope import in_worktree

        assert in_worktree(str(_make_submodule(tmp_path))) is False

    def test_finds_the_worktree_from_a_nested_subdirectory(self, tmp_path: Path) -> None:
        from lazy_harness.hooks.builtins.pre_tool_use_git_scope import in_worktree

        nested = _make_worktree(tmp_path) / "src" / "deep"
        nested.mkdir(parents=True)
        assert in_worktree(str(nested)) is True

    def test_a_directory_outside_any_repo_is_not_a_worktree(self, tmp_path: Path) -> None:
        from lazy_harness.hooks.builtins.pre_tool_use_git_scope import in_worktree

        assert in_worktree(str(tmp_path)) is False

    def test_a_git_file_of_undecodable_bytes_is_not_a_worktree(self, tmp_path: Path) -> None:
        from lazy_harness.hooks.builtins.pre_tool_use_git_scope import in_worktree

        root = tmp_path / "weird"
        root.mkdir()
        (root / ".git").write_bytes(b"\xff\xfe\x00binary garbage")
        assert in_worktree(str(root)) is False

    def test_an_unreadable_git_file_is_not_a_worktree(self, tmp_path: Path) -> None:
        """The real OSError path: readable name, unreadable content (EACCES)."""
        from lazy_harness.hooks.builtins.pre_tool_use_git_scope import in_worktree

        root = tmp_path / "locked"
        root.mkdir()
        dot_git = root / ".git"
        dot_git.write_text("gitdir: /somewhere/.git/worktrees/x\n")
        dot_git.chmod(0o000)
        try:
            assert in_worktree(str(root)) is False
        finally:
            dot_git.chmod(0o644)

    def test_separate_git_dir_under_a_worktrees_folder_is_not_a_worktree(
        self, tmp_path: Path
    ) -> None:
        """A substring match on the whole path is not enough.

        `git init --separate-git-dir` can put the real git dir anywhere,
        including a directory a user happens to call `worktrees`. That is a
        plain checkout, not a linked worktree.
        """
        from lazy_harness.hooks.builtins.pre_tool_use_git_scope import in_worktree

        root = tmp_path / "plain"
        root.mkdir()
        (root / ".git").write_text(f"gitdir: {tmp_path}/worktrees/proj.git\n")
        assert in_worktree(str(root)) is False

    def test_a_missing_directory_is_not_a_worktree(self, tmp_path: Path) -> None:
        from lazy_harness.hooks.builtins.pre_tool_use_git_scope import in_worktree

        assert in_worktree(str(tmp_path / "does" / "not" / "exist")) is False


class TestStashStackIsShared:
    """The stack belongs to the repository, so being inside a worktree is not
    the question — whether anyone else can reach the same stack is."""

    def test_a_worktree_shares_the_stack(self, tmp_path: Path) -> None:
        from lazy_harness.hooks.builtins.pre_tool_use_git_scope import stash_stack_is_shared

        assert stash_stack_is_shared(str(_make_worktree(tmp_path))) is True

    def test_the_main_checkout_of_a_repo_with_worktrees_shares_it(self, tmp_path: Path) -> None:
        """The gap this closes: same stack, reachable from the main checkout."""
        from lazy_harness.hooks.builtins.pre_tool_use_git_scope import stash_stack_is_shared

        assert stash_stack_is_shared(str(_make_main_checkout_with_worktrees(tmp_path))) is True

    def test_a_repo_without_worktrees_keeps_its_stack_private(self, tmp_path: Path) -> None:
        """The negative control. Without it the hook would block every stash
        everywhere, which is a different tool than the one we wanted."""
        from lazy_harness.hooks.builtins.pre_tool_use_git_scope import stash_stack_is_shared

        assert stash_stack_is_shared(str(_make_main_checkout(tmp_path))) is False

    def test_an_emptied_worktrees_directory_is_not_shared(self, tmp_path: Path) -> None:
        """git leaves `.git/worktrees/` behind after the last one is removed."""
        from lazy_harness.hooks.builtins.pre_tool_use_git_scope import stash_stack_is_shared

        root = tmp_path / "emptied"
        (root / ".git" / "worktrees").mkdir(parents=True)
        assert stash_stack_is_shared(str(root)) is False

    def test_finds_it_from_a_nested_subdirectory_of_the_main_checkout(self, tmp_path: Path) -> None:
        from lazy_harness.hooks.builtins.pre_tool_use_git_scope import stash_stack_is_shared

        nested = _make_main_checkout_with_worktrees(tmp_path) / "src" / "deep"
        nested.mkdir(parents=True)
        assert stash_stack_is_shared(str(nested)) is True

    def test_a_submodule_of_a_repo_with_worktrees_is_not_shared(self, tmp_path: Path) -> None:
        from lazy_harness.hooks.builtins.pre_tool_use_git_scope import stash_stack_is_shared

        assert stash_stack_is_shared(str(_make_submodule(tmp_path))) is False

    def test_a_directory_outside_any_repo_is_not_shared(self, tmp_path: Path) -> None:
        from lazy_harness.hooks.builtins.pre_tool_use_git_scope import stash_stack_is_shared

        assert stash_stack_is_shared(str(tmp_path)) is False

    def test_an_unreadable_worktrees_directory_is_not_shared(self, tmp_path: Path) -> None:
        from lazy_harness.hooks.builtins.pre_tool_use_git_scope import stash_stack_is_shared

        root = _make_main_checkout_with_worktrees(tmp_path)
        wt_dir = root / ".git" / "worktrees"
        wt_dir.chmod(0o000)
        try:
            assert stash_stack_is_shared(str(root)) is False
        finally:
            wt_dir.chmod(0o755)


class TestShouldBlock:
    def test_blocks_unsafe_stash_inside_a_worktree(self, tmp_path: Path) -> None:
        from lazy_harness.hooks.builtins.pre_tool_use_git_scope import should_block

        assert should_block("git stash", str(_make_worktree(tmp_path))) is not None

    def test_blocks_unsafe_stash_from_the_main_checkout_of_a_shared_repo(
        self, tmp_path: Path
    ) -> None:
        """Reaching the shared stack from the main checkout is the same hazard."""
        from lazy_harness.hooks.builtins.pre_tool_use_git_scope import should_block

        shared = str(_make_main_checkout_with_worktrees(tmp_path))
        assert should_block("git stash pop", shared) is not None

    def test_allows_unsafe_stash_where_the_stack_is_private(self, tmp_path: Path) -> None:
        """A repo with no worktrees has nobody else on its stack."""
        from lazy_harness.hooks.builtins.pre_tool_use_git_scope import should_block

        assert should_block("git stash", str(_make_main_checkout(tmp_path))) is None

    def test_allows_safe_stash_inside_a_worktree(self, tmp_path: Path) -> None:
        from lazy_harness.hooks.builtins.pre_tool_use_git_scope import should_block

        wt = str(_make_worktree(tmp_path))
        assert should_block('git stash push -u -m "tag"', wt) is None


_POP = "git st" + "ash pop"
"""Kept out of one literal so the guard does not refuse the run that tests it.

`_STASH_CALL` matches command *text*, so a `Bash` call whose argument merely
quotes an unsafe invocation is refused — which is the cheapest evidence that
the evasion suite below has real surface to work on.
"""

_BARE = "git st" + "ash"


def _event(command: str, cwd: Path, *, tool: object = _UNSET) -> HookEvent:
    """A `PreToolUse` event carrying one Bash call, the way the adapter builds it."""
    return HookEvent(
        event="pre_tool_use",
        profile="p",
        session_id="s",
        cwd=cwd,
        transcript_path=None,
        tool=ToolCall(native_name="Bash", operation=Operation.RUN_COMMAND, command=command)
        if tool is _UNSET
        else tool,
    )


class TestTheVerdictItReturns:
    """`main` decides through `HookDecision`; the adapter owns the exit code."""

    def test_refuses_an_unsafe_stash_through_the_verdict(self, tmp_path: Path) -> None:
        """All three conditions of `should_block` supplied at once.

        The unsafe subcommand, a cwd whose stash stack is shared, and no allow
        pattern — take any one away and the other two tests below hold instead.
        """
        from lazy_harness.hooks.builtins.pre_tool_use_git_scope import main

        decision = main(_event(_POP, _make_worktree(tmp_path)))

        assert decision.verdict is Verdict.DENY
        assert "unsafe git st" + "ash" in decision.reason

    def test_abstains_where_no_one_else_reaches_the_stack(self, tmp_path: Path) -> None:
        """A real checkout with no linked worktrees, not a bare `tmp_path`.

        A directory with no `.git` at all exercises `_find_dot_git` returning
        None, which is a different branch — and would let this pass against a
        guard that had lost the shared-stack check entirely.
        """
        from lazy_harness.hooks.builtins.pre_tool_use_git_scope import main

        assert main(_event(_POP, _make_main_checkout(tmp_path))).verdict is None

    def test_still_refuses_from_the_main_checkout_of_a_repo_with_worktrees(
        self, tmp_path: Path
    ) -> None:
        """The stack belongs to the repository, so both sides are guarded.

        Without this, the pair above passes against a guard narrowed to linked
        worktrees only — which is what an earlier draft of the migration plan
        described three times.
        """
        from lazy_harness.hooks.builtins.pre_tool_use_git_scope import main

        cwd = _make_main_checkout_with_worktrees(tmp_path)

        assert main(_event(_POP, cwd)).verdict is Verdict.DENY

    def test_the_reason_is_the_whole_message_the_agent_reads(self, tmp_path: Path) -> None:
        """`reason` *is* the stderr bytes: the adapter writes it and exits 2.

        Asserted against `_format_block_message` rather than against a
        substring, because a migration that put a summary in `reason` and left
        the detail behind would still pass an "unsafe" check and would silently
        shorten what Claude Code shows.
        """
        from lazy_harness.hooks.builtins.pre_tool_use_git_scope import (
            _format_block_message,
            is_unsafe_stash,
            main,
        )

        verdict = is_unsafe_stash(_POP)
        assert verdict is not None

        assert main(_event(_POP, _make_worktree(tmp_path))).reason == _format_block_message(verdict)

    def test_an_allow_pattern_from_the_config_rescues_the_command(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The escape hatch the block message promises, through `main`.

        `should_block` is tested with the list passed in; this is the only path
        that proves `main` still consults `load_allowlist` at all.
        """
        from lazy_harness.hooks.builtins import pre_tool_use_git_scope as hook

        cfg = tmp_path / "config.toml"
        cfg.write_text('[hooks.pre_tool_use_git_scope]\nallow_patterns = ["deliberate"]\n')
        monkeypatch.setattr(hook, "config_file", lambda: cfg)
        cwd = _make_worktree(tmp_path)

        assert hook.main(_event(f"{_POP} # deliberate", cwd)).verdict is None
        assert hook.main(_event(_POP, cwd)).verdict is Verdict.DENY

    def test_abstention_is_a_bare_decision_and_never_an_approval(self, tmp_path: Path) -> None:
        """Exit 0 with no output is how a hook says "no objection".

        `Verdict.ALLOW` says something else entirely: it skips the permission
        prompt. A guard that merely failed to recognise a command must not
        thereby approve it.
        """
        from lazy_harness.hooks.builtins.pre_tool_use_git_scope import main

        decision = main(_event(f"{_BARE} list", _make_worktree(tmp_path)))

        assert decision == HookDecision()


class TestWhatItIsHandedInsteadOfAToolCall:
    def test_an_event_with_no_tool_call_abstains(self, tmp_path: Path) -> None:
        from lazy_harness.hooks.builtins.pre_tool_use_git_scope import main

        assert main(_event("", _make_worktree(tmp_path), tool=None)).verdict is None

    @pytest.mark.parametrize(
        "operation",
        [Operation.READ_FILE, Operation.MODIFY_FILE, None],
        ids=lambda v: f"operation={v}",
    )
    def test_an_operation_this_hook_does_not_guard_abstains(
        self, operation: Operation | None, tmp_path: Path
    ) -> None:
        from lazy_harness.hooks.builtins.pre_tool_use_git_scope import main

        tool = ToolCall(native_name="Read", operation=operation, command=_POP)

        assert main(_event(_POP, _make_worktree(tmp_path), tool=tool)).verdict is None

    def test_a_tool_call_carrying_no_command_abstains(self, tmp_path: Path) -> None:
        """`Operation.RUN_COMMAND` with `command=None` is a normalisation that
        found no command, not an empty one to judge."""
        from lazy_harness.hooks.builtins.pre_tool_use_git_scope import main

        tool = ToolCall(native_name="Bash", operation=Operation.RUN_COMMAND, command=None)

        assert main(_event("", _make_worktree(tmp_path), tool=tool)).verdict is None

    def test_the_operation_gate_is_not_wider_than_the_tools_it_inspects(self) -> None:
        """Trap 3, asserted rather than assumed.

        This hook gates on `Operation.RUN_COMMAND` and not on the native tool
        name, which is only safe while the two answer the same question. Four
        of the fifteen migrations could not do that: `MODIFY_FILE` also carries
        `NotebookEdit`, so the operation gate there is a widening. Here it is
        not — and this test is what makes that a fact rather than a reading of
        today's table. Map a second tool onto `RUN_COMMAND` and it goes red.
        """
        from lazy_harness.agents.claude_code import _TOOL_OPERATIONS
        from lazy_harness.hooks.builtins.pre_tool_use_git_scope import INSPECTED_TOOLS

        run_command_tools = {
            tool for tool, op in _TOOL_OPERATIONS.items() if op is Operation.RUN_COMMAND
        }

        assert run_command_tools == set(INSPECTED_TOOLS)


class TestTheWorkingDirectoryItJudgesAgainst:
    def test_an_empty_cwd_falls_back_to_the_process_directory(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """`parse_hook_input` yields `Path("")` when the payload names no cwd.

        `Path("")` is `Path(".")` and is truthy, so a bare `if not event.cwd`
        never fires — and judging a shared stack against the string `.` would
        wave every unsafe stash through on a payload missing one optional
        field.
        """
        from lazy_harness.hooks.builtins.pre_tool_use_git_scope import main

        monkeypatch.chdir(_make_worktree(tmp_path))

        assert main(_event(_POP, Path(""))).verdict is Verdict.DENY

    def test_the_process_directory_is_not_consulted_when_the_payload_names_one(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The negative half: the fallback must not override a stated cwd.

        Without it, a fallback written as "always prefer the process directory"
        passes the test above and judges every event against wherever the hook
        happens to run.
        """
        from lazy_harness.hooks.builtins.pre_tool_use_git_scope import main

        monkeypatch.chdir(_make_worktree(tmp_path))

        assert main(_event(_POP, _make_main_checkout(tmp_path))).verdict is None


class TestFailsOpenOnInternalError:
    def test_an_unexpected_error_abstains_instead_of_escaping(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Proves the broad except is not dead code, and that it still abstains.

        Two failure policies meet in this module and must not collapse into
        one. The Global Constraints of the migration say a *blocking* builtin
        refuses when it cannot run, and `run_hook` does exactly that when it
        cannot even construct the event. This handler is one layer down and
        does the opposite on purpose: a bug inside the guard's own logic must
        not block honest work.
        """
        from lazy_harness.hooks.builtins import pre_tool_use_git_scope as hook

        def explode(command: str, cwd: str, allow_patterns: list[str] | None = None) -> None:
            raise RuntimeError("boom")

        monkeypatch.setattr(hook, "should_block", explode)

        assert hook.main(_event(_POP, _make_worktree(tmp_path))) == HookDecision()


class TestThroughTheRunner:
    """The bytes the deployed command writes, which is what the agent reads."""

    def _isolated(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("LH_CONFIG_DIR", str(tmp_path / "config"))
        monkeypatch.setenv("LH_DATA_DIR", str(tmp_path / "data"))

    def test_refuses_rather_than_abstains_when_it_cannot_run(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Decision 3's table, blocking column, and the one licensed divergence.

        `_read_stdin_json` used to degrade an unparseable payload to `{}`, and
        a guard handed `{}` abstains — which on the wire is indistinguishable
        from having looked. The runner refuses before the builtin is reached.
        """
        from lazy_harness.hooks.runner import run_hook

        self._isolated(tmp_path, monkeypatch)

        output = run_hook("pre-tool-use-git-scope", profile="p", stdin_text="not json")

        assert output.exit_code == 2
        assert "unparseable payload" in output.stderr

    def test_a_refusal_reaches_stderr_with_exit_2_and_an_empty_stdout(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The refusal channel, end to end: `reason` on stderr, nothing on stdout."""
        from lazy_harness.hooks.runner import run_hook

        self._isolated(tmp_path, monkeypatch)
        payload = {
            "hook_event_name": "PreToolUse",
            "tool_name": "Bash",
            "tool_input": {"command": _POP},
            "cwd": str(_make_worktree(tmp_path)),
        }

        output = run_hook("pre-tool-use-git-scope", profile="p", stdin_text=json.dumps(payload))

        assert output.exit_code == 2
        assert output.stdout is None
        assert output.stderr.startswith("Blocked by lazy-harness PreToolUse:")

    def test_it_writes_nothing_under_either_agent_directory(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Step 7 of the migration recipe has no witness here, and this says so.

        Every other migration asserts its `hooks.log` line lands in the
        profile's runtime directory and not in the global one. This hook writes
        no log, no metric and no queue entry — `load_allowlist` reads
        `config_file()`, which is not profile-scoped — so there is nothing for
        that assertion to stand on. What is asserted instead is the property
        that makes it inapplicable: a refusal leaves no trace on disk at all.

        `CLAUDE_CONFIG_DIR` is cleared rather than pinned. `agent_runtime_dir`
        resolves it above the profile's `config_dir`, so pinning it makes both
        answers the same path and the absence half could never fail.
        """
        from lazy_harness.hooks.runner import run_hook

        self._isolated(tmp_path, monkeypatch)
        monkeypatch.delenv("CLAUDE_CONFIG_DIR", raising=False)
        agent_dir = tmp_path / "agent"
        agent_dir.mkdir()
        monkeypatch.setattr(Path, "home", classmethod(lambda cls: agent_dir))
        payload = {
            "hook_event_name": "PreToolUse",
            "tool_name": "Bash",
            "tool_input": {"command": _POP},
            "cwd": str(_make_worktree(tmp_path)),
        }

        output = run_hook("pre-tool-use-git-scope", profile="p", stdin_text=json.dumps(payload))

        assert output.exit_code == 2
        assert list(agent_dir.rglob("*")) == []


# --- step 6 of the migration plan: attack the denylist with its own shapes -- #
#
# Split out of one literal for the same reason as `_POP` above.
_S = "st" + "ash"

#: Evasions of what `_STASH_CALL` declares it covers. Every one is refused, and
#: each names the clause that refuses it — delete that clause and one of these
#: turns red rather than the whole suite staying green on a narrower guard.
DECLARED_COVERAGE_CASES: list[tuple[str, str]] = [
    (f"git   {_S}    pop", "repeated whitespace between the words"),
    (f"git -c core.pager=cat {_S} pop", "a git global option between them"),
    (f"GIT_DIR=. git {_S} pop", "an assignment prefix"),
    (f"env git {_S} pop", "a wrapper"),
    (f"sudo env git {_S} pop", "two nested wrappers"),
    (f"git {_S} list && git {_S} pop", "a compound whose unsafe call is second"),
    (f"ls; git {_S} list; git {_S} clear", "a compound whose unsafe call is third"),
    (f"cd src\ngit {_S} pop", "a newline separator"),
    (f"if true; then git {_S} pop; fi", "an invocation after a shell keyword"),
    (f'git {_S} "pop"', "a quoted argument"),
    (f"$(git {_S} pop)", "command substitution"),
    (f"`git {_S} pop`", "backticks"),
]

#: What got through, measured 2026-09-15. Every one is past `_COMMAND_START`
#: rather than past the stash pattern, and none is closed — see the docstring on
#: `_STASH_CALL` for why. Pinned so that closing one goes red here instead of
#: leaving that record quietly wrong.
KNOWN_EVASION_CASES: list[tuple[str, str]] = [
    (f'sh -c "git {_S} pop"', "the invocation is an argument to another shell"),
    (f"bash -c 'git {_S} pop'", "same, single-quoted"),
    (f'eval "git {_S} pop"', "eval defers the parse past this regex"),
    (f'C="git {_S} pop"; $C', "the command is built in a variable"),
    (f"\\git {_S} pop", "a backslash-escaped command name"),
    (f'git "{_S}" pop', "a quoted subcommand"),
    (f"> /dev/null git {_S} pop", "a redirect before the command"),
    (f"2>/dev/null git {_S} pop", "a numbered redirect before the command"),
    (f"/usr/bin/git {_S} pop", "git spelled as an absolute path"),
]


class TestKnownEvasions:
    """Both halves of the attack, so neither can go stale in silence.

    A denylist that was only ever tested on the shapes it was written for
    reports coverage it does not have. These two lists are the output of
    running the guard against evasions of its own patterns, not of reading it.
    """

    @pytest.mark.parametrize("command,label", DECLARED_COVERAGE_CASES, ids=lambda v: v)
    def test_the_regex_covers_what_it_declares(self, command: str, label: str) -> None:
        from lazy_harness.hooks.builtins.pre_tool_use_git_scope import is_unsafe_stash

        assert is_unsafe_stash(command) is not None, label

    def test_a_quoted_compound_is_still_caught(self) -> None:
        """The `sh -c` gap is narrower than it looks, and that matters.

        `_COMMAND_START` treats the `&&` inside the quotes as a separator, so
        only a stash that is the *first* word inside them escapes. Recorded
        because "quoting defeats this hook" would be the wrong summary.
        """
        from lazy_harness.hooks.builtins.pre_tool_use_git_scope import is_unsafe_stash

        assert is_unsafe_stash(f"sh -c 'cd /tmp && git {_S}'") is not None

    @pytest.mark.parametrize("command,label", KNOWN_EVASION_CASES, ids=lambda v: v)
    def test_the_measured_gaps_are_still_the_gaps(self, command: str, label: str) -> None:
        """Pins the gap rather than the fix.

        This asserts what the guard does *not* catch, which is only useful
        while the record beside it says so. Closing one of these is a welcome
        change and has to update the docstring on `_STASH_CALL` in the same
        commit — which is what turning this red is for.
        """
        from lazy_harness.hooks.builtins.pre_tool_use_git_scope import is_unsafe_stash

        assert is_unsafe_stash(command) is None, (
            f"{label}: this evasion is now caught -- update the gap list on "
            f"`_STASH_CALL` and move this case into DECLARED_COVERAGE_CASES"
        )


class TestRegistration:
    def test_is_registered_as_a_builtin_hook(self) -> None:
        from lazy_harness.hooks.loader import _BUILTIN_HOOKS

        assert "pre-tool-use-git-scope" in _BUILTIN_HOOKS

    def test_is_scoped_to_bash_by_its_matcher(self) -> None:
        from lazy_harness.hooks.loader import _BUILTIN_HOOKS

        assert _BUILTIN_HOOKS["pre-tool-use-git-scope"].matcher == "Bash"

    def test_declares_the_operation_it_guards(self) -> None:
        """Declared, not inferred from the `Bash` matcher, which names Claude
        Code's own tool. Another agent's translated matcher still has to be
        asked whether the operation exists there."""
        from lazy_harness.hooks.loader import _BUILTIN_HOOKS

        spec = _BUILTIN_HOOKS["pre-tool-use-git-scope"]

        assert spec.operations == frozenset({Operation.RUN_COMMAND})
        assert spec.blocking is True
        assert spec.event == "pre_tool_use"

    def test_declares_no_transcript_signal(self) -> None:
        """This hook reads a command string and the filesystem, never a
        transcript. Declaring a signal would make `deploy` omit a working guard
        on any agent whose reader cannot supply one it never touches."""
        from lazy_harness.hooks.loader import builtin_signals

        assert builtin_signals("pre-tool-use-git-scope") == frozenset()

    def test_runs_through_the_runner_rather_than_owning_stdin(self) -> None:
        """`main(event)` is the contract the single dispatch calls, not a flag.

        The registry marker this used to read is gone; the signature is what
        both entry points now depend on, and it is what a module reverting to
        an stdin-owning `main()` would break.
        """
        import inspect

        from lazy_harness.hooks.builtins import pre_tool_use_git_scope

        assert list(inspect.signature(pre_tool_use_git_scope.main).parameters) == ["event"]

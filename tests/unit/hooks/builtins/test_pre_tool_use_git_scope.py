"""Unit tests for the pre_tool_use_git_scope hook.

The hook blocks the `git stash` forms that reach into a shared stash stack
without naming what they touch, and only when the command runs from inside a
git worktree. The safe forms the harness itself recommends — a tagged
`git stash push -m`, an `apply` naming its entry — stay allowed, as do the
read-only subcommands.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

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


def _run_hook(payload: object, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    """Invoke the hook as the agent does: a subprocess fed JSON on stdin."""
    return subprocess.run(
        [sys.executable, "-m", "lazy_harness.hooks.builtins.pre_tool_use_git_scope"],
        input=payload if isinstance(payload, str) else json.dumps(payload),
        capture_output=True,
        text=True,
        cwd=cwd,
    )


class TestHookEntrypoint:
    def test_exits_2_and_explains_when_blocking(self, tmp_path: Path) -> None:
        wt = _make_worktree(tmp_path)
        result = _run_hook(
            {
                "hook_event_name": "PreToolUse",
                "tool_name": "Bash",
                "tool_input": {"command": "git stash"},
                "cwd": str(wt),
            }
        )
        assert result.returncode == 2
        assert "stash" in result.stderr.lower()

    def test_the_block_message_names_the_safe_alternative(self, tmp_path: Path) -> None:
        wt = _make_worktree(tmp_path)
        result = _run_hook(
            {
                "tool_name": "Bash",
                "tool_input": {"command": "git stash pop"},
                "cwd": str(wt),
            }
        )
        assert result.returncode == 2
        assert "git stash push" in result.stderr

    def test_exits_0_for_a_safe_command(self, tmp_path: Path) -> None:
        wt = _make_worktree(tmp_path)
        result = _run_hook(
            {
                "tool_name": "Bash",
                "tool_input": {"command": "git stash list"},
                "cwd": str(wt),
            }
        )
        assert result.returncode == 0

    def test_falls_back_to_process_cwd_when_the_payload_omits_it(self, tmp_path: Path) -> None:
        wt = _make_worktree(tmp_path)
        result = _run_hook(
            {"tool_name": "Bash", "tool_input": {"command": "git stash"}},
            cwd=wt,
        )
        assert result.returncode == 2

    @pytest.mark.parametrize("bad_cwd", [3, None, [], {}], ids=lambda v: f"cwd={v!r}")
    def test_falls_back_to_process_cwd_when_the_payload_cwd_is_not_a_string(
        self, bad_cwd: object, tmp_path: Path
    ) -> None:
        """A malformed `cwd` must not wave the command through.

        Unlike a broken `tool_input`, a broken `cwd` still leaves the command
        legible — and `os.getcwd()` answers the only question left. Degrading
        to exit 0 here would let an unsafe stash past on a bad optional field.
        """
        wt = _make_worktree(tmp_path)
        result = _run_hook(
            {"tool_name": "Bash", "tool_input": {"command": "git stash"}, "cwd": bad_cwd},
            cwd=wt,
        )
        assert result.returncode == 2

    @pytest.mark.parametrize(
        "tool_name",
        ["Read", "Edit", "Write", "Glob", "Task"],
        ids=lambda v: f"tool={v}",
    )
    def test_ignores_every_tool_except_bash(self, tool_name: str, tmp_path: Path) -> None:
        result = _run_hook(
            {
                "tool_name": tool_name,
                "tool_input": {"command": "git stash"},
                "cwd": str(_make_worktree(tmp_path)),
            }
        )
        assert result.returncode == 0

    @pytest.mark.parametrize(
        "payload,label",
        [
            ("", "empty stdin"),
            ("   \n  ", "whitespace only"),
            ("not json at all", "malformed json"),
            ("null", "valid json, null"),
            ("42", "valid json, int"),
            ('["a", "b"]', "valid json, list"),
            ('{"tool_name": "Bash", "tool_input": null}', "tool_input is null"),
            ('{"tool_name": "Bash", "tool_input": 7}', "tool_input is an int"),
            ('{"tool_name": "Bash", "tool_input": ["x"]}', "tool_input is a list"),
            ('{"tool_name": "Bash", "tool_input": {"command": null}}', "command is null"),
            ('{"tool_name": "Bash", "tool_input": {"command": 5}}', "command is an int"),
            ('{"tool_name": "Bash", "tool_input": {}}', "command missing"),
            ('{"tool_name": 99, "tool_input": {"command": "git stash"}}', "tool_name is an int"),
        ],
        ids=lambda v: v if isinstance(v, str) and " " in v else "",
    )
    def test_degrades_to_exit_0_on_malformed_input(self, payload: str, label: str) -> None:
        result = _run_hook(payload)
        assert result.returncode == 0, f"{label}: {result.stderr}"


class TestAllowlist:
    """The block message promises `allow_patterns`, so it has to work."""

    def _write_config(self, tmp_path: Path, body: str) -> Path:
        cfg = tmp_path / "config.toml"
        cfg.write_text(body)
        return cfg

    def test_an_allow_pattern_rescues_a_matching_command(self, tmp_path: Path) -> None:
        from lazy_harness.hooks.builtins.pre_tool_use_git_scope import should_block

        wt = str(_make_worktree(tmp_path))
        assert should_block("git stash", wt, ["deliberate-stash"]) is not None
        assert should_block("git stash # deliberate-stash", wt, ["deliberate-stash"]) is None

    def test_a_broken_user_regex_is_skipped_not_raised(self, tmp_path: Path) -> None:
        from lazy_harness.hooks.builtins.pre_tool_use_git_scope import should_block

        wt = str(_make_worktree(tmp_path))
        assert should_block("git stash", wt, ["([unclosed"]) is not None

    def test_reads_its_own_config_section(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from lazy_harness.hooks.builtins import pre_tool_use_git_scope as hook

        cfg = self._write_config(
            tmp_path,
            '[hooks.pre_tool_use_git_scope]\nallow_patterns = ["escape-hatch"]\n',
        )
        monkeypatch.setattr(hook, "config_file", lambda: cfg)
        assert hook.load_allowlist() == ["escape-hatch"]

    def test_does_not_read_the_security_hooks_allowlist(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The separation is the whole reason this hook is its own module.

        `[hooks.pre_tool_use] allow_patterns` carries `\\.worktrees/` in the
        reference profile, which would rescue every command this hook exists
        to catch.
        """
        from lazy_harness.hooks.builtins import pre_tool_use_git_scope as hook

        cfg = self._write_config(
            tmp_path,
            '[hooks.pre_tool_use]\nallow_patterns = ["\\\\.worktrees/"]\n',
        )
        monkeypatch.setattr(hook, "config_file", lambda: cfg)
        assert hook.load_allowlist() == []

    @pytest.mark.parametrize(
        "body,label",
        [
            ("", "empty file"),
            ("not [ valid toml", "malformed toml"),
            ("[hooks]\n", "no section"),
            ('[hooks.pre_tool_use_git_scope]\nallow_patterns = "nope"\n', "patterns not a list"),
            ("[hooks.pre_tool_use_git_scope]\nallow_patterns = [1, 2]\n", "patterns not strings"),
            ("hooks = 5\n", "hooks is not a table"),
            ('[hooks]\npre_tool_use_git_scope = "nope"\n', "section is not a table"),
        ],
        ids=lambda v: v if " " in str(v) else "",
    )
    def test_degrades_to_an_empty_allowlist(
        self, body: str, label: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from lazy_harness.hooks.builtins import pre_tool_use_git_scope as hook

        cfg = self._write_config(tmp_path, body)
        monkeypatch.setattr(hook, "config_file", lambda: cfg)
        assert hook.load_allowlist() == [], label

    def test_a_missing_config_file_yields_an_empty_allowlist(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from lazy_harness.hooks.builtins import pre_tool_use_git_scope as hook

        monkeypatch.setattr(hook, "config_file", lambda: tmp_path / "absent.toml")
        assert hook.load_allowlist() == []


class TestFailsOpenOnInternalError:
    def test_an_unexpected_error_exits_0_instead_of_escaping(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Proves the broad except is not dead code.

        A bug inside the hook must not block honest work, and must not escape
        to crash the rest of the PreToolUse chain.
        """
        import io

        from lazy_harness.hooks.builtins import pre_tool_use_git_scope as hook

        def explode(command: str, cwd: str) -> None:
            raise RuntimeError("boom")

        monkeypatch.setattr(hook, "should_block", explode)
        monkeypatch.setattr(
            "sys.stdin",
            io.StringIO(json.dumps({"tool_name": "Bash", "tool_input": {"command": "git stash"}})),
        )
        with pytest.raises(SystemExit) as excinfo:
            hook.main()
        assert excinfo.value.code == 0


class TestRunsTheWayTheLoaderInvokesIt:
    def test_blocks_when_invoked_by_file_path(self, tmp_path: Path) -> None:
        """The loader runs `python <path>.py`, not `python -m <module>`.

        Every other entrypoint test uses -m, so this is the one that proves the
        form the deployed system actually uses still works.
        """
        from lazy_harness.hooks.builtins import pre_tool_use_git_scope as hook

        wt = _make_worktree(tmp_path)
        result = subprocess.run(
            [sys.executable, str(Path(hook.__file__))],
            input=json.dumps(
                {
                    "tool_name": "Bash",
                    "tool_input": {"command": "git stash"},
                    "cwd": str(wt),
                }
            ),
            capture_output=True,
            text=True,
        )
        assert result.returncode == 2, result.stderr


class TestRegistration:
    def test_is_registered_as_a_builtin_hook(self) -> None:
        from lazy_harness.hooks.loader import _BUILTIN_HOOKS

        assert "pre-tool-use-git-scope" in _BUILTIN_HOOKS

    def test_is_scoped_to_bash_by_its_matcher(self) -> None:
        from lazy_harness.hooks.loader import _BUILTIN_HOOKS

        assert _BUILTIN_HOOKS["pre-tool-use-git-scope"].matcher == "Bash"

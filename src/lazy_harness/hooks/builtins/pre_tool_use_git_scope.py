"""PreToolUse git-scope hook — blocks unsafe `git stash` on a shared stack.

The stash stack belongs to the repository, not the checkout: every linked
worktree, the main checkout, and every concurrent agent session in any of them
push onto the same stack. A `git stash pop` takes whatever sits on top, which
may belong to somebody else; a bare `git stash` pushes an entry nobody can
later identify. Four such incidents were recorded before this hook existed.

A repository with no linked worktrees keeps its stack private and is left
alone — the hazard is other people reaching it, not stashing as such.

Deliberately separate from `pre_tool_use_security`: that hook rescues a whole
command when any `allow_patterns` entry matches it, and this profile's config
carries `\\.worktrees/` as one of those entries — which would exempt precisely
the commands this hook exists to catch. It also blocks a different kind of
thing. `pre_tool_use_security` blocks the destructive; this blocks the
out-of-scope, and the two are worth turning off independently.

**The safe list decides, not the unsafe one.** Anything touching the stash that
is not recognised as safe blocks. An earlier denylist version ended in a silent
`return None` for unrecognised input, and `(git stash pop)`, `git stash drop -q`
and `git stash > /dev/null` all walked straight through it.

Diverges from ADR-006's "exit 0 always" contract the same way its sibling does:
exits 2 on block, per Claude Code PreToolUse semantics. Every other path,
including every unexpected error, exits 0 — a hook that fails closed would
block honest work on its own bugs.
"""

from __future__ import annotations

import json
import os
import re
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from lazy_harness.core.paths import config_file


@dataclass(frozen=True)
class UnsafeStash:
    """A `git stash` invocation that reaches into the shared stack blindly."""

    subcommand: str
    reason: str


# A command word starts a line or follows a shell separator. Anchoring here is
# what keeps `echo git stash pop` out of scope: there `git` is an argument, not
# a command. Newline is a separator like any other — multi-line scripts are how
# long commands actually arrive.
# The tool names this hook inspects. `tests/unit/test_hook_matcher_coverage.py`
# asserts the matcher the registry deploys covers every one of them, so the gate
# below and the subscription declared outside cannot drift apart.
INSPECTED_TOOLS = frozenset({"Bash"})

_COMMAND_START = r"(?:(?<=^)|(?<=[;&|(){}`\n]))\s*"

# Shell keywords introduce a command without being a separator themselves:
# in `if true; then git stash; fi` the stash follows `then`, not `;`.
_SHELL_KEYWORDS = r"(?:(?:then|else|elif|do|while|until)\s+)*"

# Wrappers that exec their argument, optionally preceded by variable
# assignments (`FOO=bar git stash`).
_WRAPPERS = r"(?:(?:sudo|doas|env|command|time|nohup|xargs|exec|builtin)\s+)*"
_ASSIGNMENTS = r"(?:\w+=\S*\s+)*"

# git's own global flags sit between `git` and the subcommand. `git -C <path>`
# is the important one: it retargets another checkout entirely, which makes it
# more dangerous than a plain stash, not less.
_GIT_GLOBALS = (
    r"(?:"
    r"(?:-[cC]|--git-dir|--work-tree|--namespace|--exec-path)(?:=\S*|\s+\S+)"
    r"|--no-pager|--paginate|--bare|--literal-pathspecs|--no-replace-objects"
    r")\s+"
)

# Group 1 captures the arguments up to the next shell separator or redirect,
# so a compound command is split the way the shell would split it.
_STASH_CALL = re.compile(
    _COMMAND_START
    + _SHELL_KEYWORDS
    + _ASSIGNMENTS
    + _WRAPPERS
    + r"git\s+(?:"
    + _GIT_GLOBALS
    + r")*stash\b([^;&|(){}\n]*)",
    re.MULTILINE,
)

# Subcommands that only read the stack.
_READ_ONLY = frozenset({"list", "show"})

# Subcommands that mutate the stack and cannot name a single entry safely.
_ALWAYS_UNSAFE = {
    "pop": "`git stash pop` removes the entry it applies, and the one on top "
    "may belong to another session",
    "clear": "`git stash clear` destroys every entry on the shared stack, "
    "including other sessions'",
    "branch": "`git stash branch` consumes a stash entry",
    "store": "`git stash store` writes to the shared stack",
    "create": "`git stash create` writes to the shared stack",
}

_HELP_FLAGS = frozenset({"--help", "-h"})

_SAFE_PUSH = 'git stash push -u -m "<unique-tag>"'


def _has_message(parts: list[str]) -> bool:
    """True when the argument list names the entry with -m / --message.

    A short-flag cluster counts (`-um`). Scanning stops at `--`, after which
    the words are pathspecs — a file literally named `-m` is not a message.
    """
    for part in parts:
        if part == "--":
            return False
        if part in ("-m", "--message") or part.startswith("--message="):
            return True
        if part.startswith("-") and not part.startswith("--") and "m" in part[1:]:
            return True
    return False


def _names_an_entry(args: list[str]) -> bool:
    """True when at least one argument is a stash ref rather than a flag.

    `git stash drop -q` names nothing: it drops whatever is on top.
    """
    return any(not arg.startswith("-") for arg in args)


def _classify(rest: str) -> UnsafeStash | None:
    """Judge one `git stash` invocation from its argument string."""
    parts = rest.split()

    if not parts:
        return UnsafeStash(
            "stash",
            "a bare `git stash` pushes an entry nobody can identify later",
        )

    # Help prints documentation and touches nothing.
    if any(part in _HELP_FLAGS for part in parts):
        return None

    subcommand, args = parts[0], parts[1:]

    if subcommand in _READ_ONLY:
        return None

    if subcommand in _ALWAYS_UNSAFE:
        return UnsafeStash(subcommand, _ALWAYS_UNSAFE[subcommand])

    if subcommand in ("push", "save"):
        if _has_message(parts):
            return None
        return UnsafeStash(
            subcommand,
            f"`git stash {subcommand}` without -m leaves an entry nobody can identify",
        )

    if subcommand in ("apply", "drop"):
        if _names_an_entry(args):
            return None
        return UnsafeStash(
            subcommand,
            f"`git stash {subcommand}` without a ref takes the top entry, "
            "which may belong to another session",
        )

    # A flag rather than a subcommand: `git stash -u`, `git stash > /dev/null`.
    if subcommand.startswith("-"):
        if _has_message(parts):
            return None
        return UnsafeStash(
            "stash",
            "a bare `git stash` pushes an entry nobody can identify later",
        )

    # The safe list decided, and this was not on it.
    return UnsafeStash(
        subcommand,
        f"`git stash {subcommand}` was not recognised as a safe, entry-naming form of stash",
    )


def is_unsafe_stash(command: str) -> UnsafeStash | None:
    """Return an UnsafeStash when `command` touches the stash stack blindly.

    Every `git stash` in the command is judged, not just the first: a compound
    like `git stash list; git stash pop` is unsafe on account of its second
    invocation.
    """
    for match in _STASH_CALL.finditer(command):
        verdict = _classify(match.group(1).strip())
        if verdict is not None:
            return verdict
    return None


# What git writes into a linked worktree's `.git` file, as a path fragment.
# Anchored on `.git/worktrees/` rather than bare `worktrees/`, so a repo whose
# separate git dir merely lives under a folder called `worktrees` is not
# mistaken for one.
_WORKTREE_MARKERS = ("/.git/worktrees/", "\\.git\\worktrees\\")


def _find_dot_git(cwd: str) -> Path | None:
    """Walk up from `cwd` to the nearest `.git`, or None.

    Reading the filesystem directly is what keeps this cheap enough to run
    ahead of every Bash call — a `git rev-parse` subprocess would not be.
    """
    try:
        current = Path(cwd).resolve()
    except (OSError, ValueError, TypeError):
        return None

    for directory in (current, *current.parents):
        dot_git = directory / ".git"
        try:
            if dot_git.exists():
                return dot_git
        except OSError:
            return None
    return None


def in_worktree(cwd: str) -> bool:
    """True when `cwd` sits inside a linked worktree checkout.

    A worktree's `.git` is a file pointing into `<main>/.git/worktrees/<name>`;
    a plain checkout has a `.git` directory, and a submodule's `.git` file
    points into `.git/modules/` instead.
    """
    dot_git = _find_dot_git(cwd)
    if dot_git is None:
        return False
    try:
        if not dot_git.is_file():
            return False
        content = dot_git.read_text(encoding="utf-8")
    except (OSError, ValueError, UnicodeDecodeError):
        return False
    return any(marker in content for marker in _WORKTREE_MARKERS)


def stash_stack_is_shared(cwd: str) -> bool:
    """True when somebody other than this checkout can reach the same stash stack.

    The stack belongs to the repository, not the checkout, so "am I inside a
    worktree" is the wrong question — the main checkout of a repository that
    has worktrees reaches exactly the same stack. Both sides count; a
    repository with no linked worktrees keeps its stack private and is left
    alone.
    """
    if in_worktree(cwd):
        return True

    dot_git = _find_dot_git(cwd)
    if dot_git is None:
        return False
    try:
        if not dot_git.is_dir():
            # A `.git` file that is not a worktree marker is a submodule.
            return False
        worktrees = dot_git / "worktrees"
        # git leaves the directory behind after the last worktree is removed,
        # so its mere existence is not enough.
        return worktrees.is_dir() and any(worktrees.iterdir())
    except (OSError, ValueError):
        return False


def _safe_search(pattern: str, text: str) -> bool:
    """Compile-and-search; broken user regexes are skipped, never raised."""
    try:
        return re.search(pattern, text) is not None
    except re.error:
        return False


def load_allowlist() -> list[str]:
    """Load `[hooks.pre_tool_use_git_scope] allow_patterns` from config.toml.

    Returns an empty list on any failure — missing file, malformed TOML,
    missing section. Empty means stricter blocking: fail-safe by design.

    Deliberately its own section rather than the one `pre_tool_use_security`
    reads. That list carries `\\.worktrees/` in this profile, which would
    rescue every command this hook exists to catch.
    """
    try:
        cfg_path: Path = config_file()
    except Exception:
        return []
    if not cfg_path.is_file():
        return []
    try:
        data = tomllib.loads(cfg_path.read_text())
    except (OSError, tomllib.TOMLDecodeError):
        return []
    section = data.get("hooks", {})
    if not isinstance(section, dict):
        return []
    scope = section.get("pre_tool_use_git_scope", {})
    if not isinstance(scope, dict):
        return []
    patterns = scope.get("allow_patterns", [])
    if not isinstance(patterns, list):
        return []
    return [p for p in patterns if isinstance(p, str)]


def should_block(
    command: str, cwd: str, allow_patterns: list[str] | None = None
) -> UnsafeStash | None:
    """Return the verdict when `command` is an unsafe stash run from a worktree."""
    verdict = is_unsafe_stash(command)
    if verdict is None:
        return None
    if not stash_stack_is_shared(cwd):
        return None
    if allow_patterns and any(_safe_search(ap, command) for ap in allow_patterns):
        return None
    return verdict


def _format_block_message(verdict: UnsafeStash) -> str:
    """Format the stderr message Claude Code surfaces back to the agent."""
    return (
        f"Blocked by lazy-harness PreToolUse: unsafe git stash (scope).\n"
        f"Why: {verdict.reason}.\n"
        f"The stash stack is shared across every worktree of this repository "
        f"and across concurrent sessions.\n"
        f"Instead: prefer a temporary WIP commit. If you must stash, use\n"
        f"  {_SAFE_PUSH}\n"
        f"then restore with `git stash apply <sha>` and drop that entry by ref.\n"
        f"If this is intentional, add a regex to [hooks.pre_tool_use_git_scope] "
        f"allow_patterns in your profile config.toml.\n"
    )


def _read_stdin_json() -> dict[str, Any]:
    """Read and parse stdin as JSON; return {} on any parse error or empty input."""
    try:
        data = sys.stdin.read()
    except (OSError, ValueError):
        return {}
    if not data.strip():
        return {}
    try:
        parsed = json.loads(data)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def main() -> None:
    """Block an unsafe stash from a worktree; exit 0 on every other path."""
    try:
        payload = _read_stdin_json()

        if payload.get("tool_name") not in INSPECTED_TOOLS:
            sys.exit(0)

        tool_input = payload.get("tool_input")
        if not isinstance(tool_input, dict):
            sys.exit(0)

        command = tool_input.get("command")
        if not isinstance(command, str):
            sys.exit(0)

        cwd = payload.get("cwd")
        if not isinstance(cwd, str) or not cwd:
            cwd = os.getcwd()

        verdict = should_block(command, cwd, load_allowlist())
        if verdict is None:
            sys.exit(0)

        sys.stderr.write(_format_block_message(verdict))
        sys.exit(2)
    except SystemExit:
        raise
    except Exception:
        # Fail open: a bug here must not block honest work.
        sys.exit(0)


if __name__ == "__main__":
    main()

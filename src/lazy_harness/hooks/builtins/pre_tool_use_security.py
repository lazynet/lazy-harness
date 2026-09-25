"""PreToolUse security hook — blocks destructive / exfiltration commands.

Deliberately diverges from ADR-006's "exit 0 always" contract: refuses with
`Verdict.DENY`, which Claude Code's adapter serialises as stderr plus exit 2.
See spec `specs/designs/2026-04-17-security-hooks-cluster-design.md`.
"""

from __future__ import annotations

import fnmatch
import os
import re
import shlex
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from lazy_harness.agents.base import HookDecision, HookEvent, Operation, Verdict
from lazy_harness.core.config import ConfigError
from lazy_harness.core.paths import config_file

Category = Literal["filesystem", "sql", "terraform", "credentials", "git", "policy"]


@dataclass(frozen=True)
class BlockRule:
    category: Category
    pattern: re.Pattern[str]
    reason: str


@dataclass(frozen=True)
class BlockDecision:
    rule: BlockRule
    matched_text: str


# A command word starts the line, follows a shell operator, or follows a wrapper
# that execs its argument. Anchoring here keeps the rules from firing on command
# names that merely *mention* a dangerous command inside a quoted argument.
#
# `(?m)` makes `^` mean start-of-line rather than start-of-string, which is what
# keeps a command on the second line of a multi-line script -- or of a heredoc
# body piped into a shell -- in command position. It has to stay at index 0:
# Python accepts a global inline flag only at the start of the whole expression,
# and every rule below is built by prefixing this constant.
_COMMAND_START = (
    r"(?m)"
    # Start of a line, indentation included: a command nested in an `if` or a
    # `for` block is still the command being run.
    r"(?:^[ \t]*"
    # After a shell operator. The optional quote is what reaches a command
    # inside an interpreter's own string, as in `os.system("...")`.
    r"|[;&|(`]\s*['\"]?"
    # After a wrapper that execs its argument.
    r"|\b(?:sudo|doas|xargs|time|env|nohup|eval)\s+['\"]?"
    # After a shell asked to run a string. `-[a-z]*c` covers `-c`, `-lc`, `-ec`
    # and the rest of the cluster spellings, not `-c` alone.
    r"|\b(?:ba|z|k)?sh\s+-[a-z]*c\s+['\"]?"
    r")(?:\S*/)?"
)
# Short flags cluster (-r, -rf, -fr, -rfv, -R) or the long spelling. RECURSION
# ALONE IS THE TRIGGER; force is not required and is not matched at all.
#
# It used to require both, so `rm -r dir` stayed allowed. Probe 6 (2026-09-17
# 16:41, `codex-evidence.md` §4.2) measured what that costs: F9 phase B asks for
# "a single recursive shell delete" and the model answered `rm -rf` twice and
# `rm -r -- doomed` once, so the same prompt produced a block or a deletion
# depending on the spelling the model happened to pick. A guard whose verdict
# turns on phrasing guards nothing.
#
# `rm -f file` and `rm -fv file` stay allowed: force without recursion deletes
# exactly what was named. `rm -ri dir` now blocks even though it prompts —
# accepted, because the rule's subject is recursion and an interactive
# confirmation is not something the pattern can read.
_RM_RECURSIVE_FLAG = r"(?:-[a-zA-Z]*[rR][a-zA-Z]*|--recursive)\b"
# A command's arguments end at the line break. The classes below exclude the
# shell separators *and* the newline: without it a `cat` opening a heredoc on
# the first line reaches a secrets filename written in the body three lines
# down, which is the second half of the same false positive the anchor fixes.
_RM_OPTION = r"(?:-[a-zA-Z]+|--[a-z][a-z-]*)"

BLOCK_RULES: tuple[BlockRule, ...] = (
    BlockRule(
        category="filesystem",
        pattern=re.compile(
            _COMMAND_START + r"rm\s+"
            rf"(?=(?:{_RM_OPTION}\s+)*{_RM_RECURSIVE_FLAG})"
            r"\S+.*"
        ),
        reason="Recursive delete",
    ),
    BlockRule(
        category="filesystem",
        pattern=re.compile(_COMMAND_START + r"truncate\s+(-s\s+\d+\s+)?[^\s-]"),
        reason="File truncation",
    ),
    BlockRule(
        category="git",
        pattern=re.compile(_COMMAND_START + r"git\s+push\s+(--force(?!-with-lease)\b|-f\b)"),
        reason="Force-push without lease",
    ),
    BlockRule(
        category="git",
        pattern=re.compile(_COMMAND_START + r"git\s+reset\s+--hard\b"),
        reason="Hard reset discards work",
    ),
    BlockRule(
        category="git",
        pattern=re.compile(
            _COMMAND_START + r"git\s+add\s+(-f\b|--force\b)[^|;&\n]*"
            r"(\.env|\.pem|\.key|\.p12|credentials|id_rsa|id_ed25519)"
        ),
        reason="Forced add of secret",
    ),
    # The one rule deliberately left unanchored: `DROP TABLE` is never the
    # executable, it is the argument of one (`psql -c "DROP TABLE users"`), so
    # anchoring it on command position would delete the rule rather than narrow
    # it. The cost is that prose naming `DROP TABLE` still trips this rule.
    BlockRule(
        category="sql",
        pattern=re.compile(r"\b(drop|truncate)\s+(table|database)\b", re.IGNORECASE),
        reason="SQL destruction",
    ),
    BlockRule(
        category="terraform",
        pattern=re.compile(_COMMAND_START + r"terraform\s+destroy\b"),
        reason="Infra destruction",
    ),
    BlockRule(
        category="terraform",
        pattern=re.compile(_COMMAND_START + r"terraform\s+apply\s+[^|;&\n]*-auto-approve\b"),
        reason="Skips plan review",
    ),
    BlockRule(
        category="terraform",
        pattern=re.compile(_COMMAND_START + r"terraform\s+apply\s+[^|;&\n]*-replace=\S+"),
        reason="Forces resource recreation",
    ),
    BlockRule(
        category="terraform",
        pattern=re.compile(_COMMAND_START + r"terraform\s+state\s+(rm|push)\b"),
        reason="State mutation",
    ),
    BlockRule(
        category="credentials",
        pattern=re.compile(
            _COMMAND_START + r"(cat|bat|less|more|head|tail|grep|rg|awk|sed)\b[^|;&\n]*"
            # Keep the dotenv file distinct from an identifier ending in `.env`:
            # `process.env` and `import.meta.env` are APIs, and grepping for them
            # reads source, not credentials. The second lookbehind sees through a
            # regex-escaped dot, since that is how such a grep is usually written
            # (`grep -rn "process\.env"`).
            r"(?<!\w)(?<!\w\\)\\?\.env\b(?!\.(example|sample|template))"
        ),
        reason="Read of .env",
    ),
    BlockRule(
        category="credentials",
        pattern=re.compile(
            _COMMAND_START + r"(cat|bat|less|more|head|tail)\b[^|;&\n]*\.ssh/id_(?!.*\.pub)\S+"
        ),
        reason="Read of SSH private key",
    ),
    BlockRule(
        category="credentials",
        pattern=re.compile(
            _COMMAND_START
            + r"(cat|bat|less|more|head|tail|grep|rg|awk|sed)\b"
            + r"[^|;&\n]*\.aws/(credentials|config)\b"
        ),
        reason="Read of AWS credentials",
    ),
    BlockRule(
        category="credentials",
        pattern=re.compile(
            _COMMAND_START + r"(cat|bat|less|more|head|tail)\b[^|;&\n]*\.(pem|key|p12)\b"
        ),
        reason="Read of cert/key file",
    ),
)


# Path globs that must never be reached through the file tools. These used to
# live in `permissions.deny` as `Read(...)` / `Edit(...)` entries, and moved here
# because a single Read() deny rule makes the auto-mode classifier escalate any
# compound `cd <dir> && <reader> <relative-file>` command to a permission prompt:
# it cannot resolve the relative path statically, so it refuses to auto-approve.
# Enforcing the same globs from the hook keeps the coverage without that cost --
# and extends it to Bash, which the deny rules never reached.
SECRET_PATH_GLOBS: tuple[str, ...] = (
    "**/.env",
    "**/.env.*",
    "**/.dev.vars",
    "**/.dev.vars.*",
    "**/*.pem",
    "**/*.key",
    "**/id_rsa*",
    "**/id_ed25519*",
    "**/secrets/**",
    "**/credentials/**",
    "**/.aws/**",
    "**/.ssh/**",
    "**/.gnupg/**",
    "**/config/database.yml",
    "**/config/credentials.json",
    "**/.npmrc",
    "**/.pypirc",
    "**/.netrc",
)

# Globs whose match is a false positive: a public key is not a secret, and the
# checked-in samples exist precisely to be read.
SECRET_PATH_EXCEPTIONS: tuple[str, ...] = (
    "**/*.pub",
    "**/.env.example",
    "**/.env.sample",
    "**/.env.template",
)

# Tools that take a filesystem path instead of a command. NotebookEdit names its
# path field differently, so both keys are read. `apply_patch` is Codex's
# native edit tool (`agents/codex.py:_APPLY_PATCH`) — its own matcher has
# nothing to widen (Codex omits one and fires this hook on every tool call
# regardless), but leaving it out of this set still understated what the hook
# is supposed to be subscribed to.
FILE_TOOLS = frozenset({"Read", "Edit", "Write", "NotebookEdit", "apply_patch"})
COMMAND_TOOLS = frozenset({"Bash"})

# The tool names this hook inspects. `tests/unit/test_hook_matcher_coverage.py`
# asserts the matcher the registry deploys covers every one of them, so the gate
# below and the subscription declared outside cannot drift apart.
INSPECTED_TOOLS = COMMAND_TOOLS | FILE_TOOLS
FILE_PATH_KEYS = ("file_path", "notebook_path")

MAX_MATCH_LEN = 120


def _format_block_message(decision: BlockDecision) -> str:
    """Format the stderr message surfaced back to the agent by Claude Code."""
    matched = decision.matched_text
    if len(matched) > MAX_MATCH_LEN:
        matched = matched[:MAX_MATCH_LEN] + "…"
    return (
        f"Blocked by lazy-harness PreToolUse: {decision.rule.reason} "
        f"({decision.rule.category}).\n"
        f"Matched: {matched}\n"
        f"Review [hooks.pre_tool_use] in config.toml. Only "
        f"recursive_delete_roots can exempt a literal cleanup; legacy "
        f"allow_patterns no longer bypass security rules.\n"
        f"See specs/designs/2026-04-17-security-hooks-cluster-design.md "
        f"for the full rule list.\n"
    )


@dataclass(frozen=True)
class SecurityPolicy:
    recursive_delete_roots: tuple[Path, ...] = ()
    denied_commands: tuple[str, ...] = ()


def _load_policy() -> SecurityPolicy:
    """Read hook-local options; malformed explicit policy must not disable a ban."""
    from lazy_harness.core.config import parse_security_policy

    try:
        data = tomllib.loads(config_file().read_text())
    except FileNotFoundError:
        return SecurityPolicy()
    except (OSError, UnicodeError, tomllib.TOMLDecodeError) as exc:
        raise ValueError("Cannot read security policy from config.toml") from exc
    hooks = data.get("hooks", {})
    if not isinstance(hooks, dict):
        raise ValueError("hooks must be a table")
    section = hooks.get("pre_tool_use", {})
    values = parse_security_policy(section)
    return SecurityPolicy(
        tuple(Path(p) for p in values["recursive_delete_roots"]),
        tuple(values["denied_commands"]),
    )


def _invocations(command: str) -> list[list[str]]:
    """Inspect literal shell words without evaluating expansions or running a shell."""
    command = command.replace("\\\n", "")
    lexer = shlex.shlex(command, posix=True, punctuation_chars=";&|()\n")
    lexer.whitespace = " \t\r"
    lexer.whitespace_split = True
    lexer.commenters = ""
    groups: list[list[str]] = [[]]
    for word in lexer:
        if word and all(c in ";&|()\n" for c in word):
            groups.append([])
        else:
            groups[-1].append(word)
    invocations: list[list[str]] = []
    wrappers = {"sudo", "doas", "env", "command", "exec", "time", "nohup", "xargs"}
    value_options = {"-u", "-g", "-h", "-p", "-C", "-n", "-P", "-I", "-s", "--chdir", "--unset"}
    for words in groups:
        while words:
            if re.match(r"[A-Za-z_][A-Za-z_0-9]*=", words[0]):
                words = words[1:]
                continue
            name = Path(words[0]).name
            invocations.append(words)
            if name == "eval":
                invocations.extend(_invocations(" ".join(words[1:])))
            if name in {"sh", "bash", "zsh", "ksh", "dash"}:
                for index, word in enumerate(words[1:], 1):
                    if re.fullmatch(r"-[a-z]*c[a-z]*", word) and index + 1 < len(words):
                        invocations.extend(_invocations(words[index + 1]))
                        break
            if name not in wrappers:
                break
            words = words[1:]
            while words and words[0].startswith("-"):
                flag = words.pop(0)
                if flag == "--":
                    break
                if flag in value_options and words:
                    words = words[1:]
    return invocations


def _recursive(words: list[str]) -> bool:
    for word in words[1:]:
        if word == "--":
            break
        if re.fullmatch(r"-[A-Za-z]*[rR][A-Za-z]*|--recursive", word):
            return True
    return False


def _safe_cleanup(command: str, roots: list[Path] | tuple[Path, ...], cwd: Path) -> bool:
    # Do not infer shell expansion, wrapper behaviour, redirections, or a cwd
    # changed by an earlier command. Even quoted metacharacters fail closed.
    if not roots or any(c in command for c in "\n\r;&|<>()$`*?[]{}~\\"):
        return False
    try:
        words = shlex.split(command)
        if not words or words[0] not in {"rm", "/bin/rm", "/usr/bin/rm"} or not _recursive(words):
            return False
        operands: list[str] = []
        options = True
        for word in words[1:]:
            if options and word == "--":
                options = False
            elif options and word.startswith("-"):
                if not re.fullmatch(r"-[fFirRdv]+|--(?:force|recursive|verbose|dir)", word):
                    return False
            else:
                operands.append(word)
        if not operands:
            return False
        resolved_roots = [root.resolve() for root in roots if root.is_absolute()]
        for operand in operands:
            path = Path(operand)
            if not operand or ".." in path.parts:
                return False
            resolved = (cwd / path).resolve()
            if not any(
                resolved != root and resolved.is_relative_to(root) for root in resolved_roots
            ):
                return False
        return True
    except (OSError, RuntimeError, ValueError):
        return False


def _token_rule(words: list[str]) -> BlockRule | None:
    """Cover quoting and flag ordering that the legacy regex rules cannot see."""
    name = Path(words[0]).name
    if name == "rm" and _recursive(words):
        return BLOCK_RULES[0]
    if name == "find":
        return _find_rule(words)
    if name != "git":
        return None
    args = words[1:]
    while args and args[0].startswith("-"):
        option = args.pop(0)
        if option in _GIT_GLOBAL_OPTIONS_WITH_ARG and args:
            args = args[1:]
        elif option in _GIT_GLOBAL_OPTIONS_BARE or any(
            option.startswith(flag + "=") or (flag in {"-C", "-c"} and option.startswith(flag))
            for flag in _GIT_GLOBAL_OPTIONS_WITH_ARG
        ):
            continue
        else:
            # An option this hook cannot parse may take a value, so the
            # subcommand's position is unknown: judge every later word as a
            # candidate rather than abstain.
            return next(
                (
                    rule
                    for index in range(len(args))
                    if (rule := _git_subcommand_rule(args[index], args[index + 1 :]))
                ),
                None,
            )
    if not args:
        return None
    return _git_subcommand_rule(args[0], args[1:])


def _is_long_prefix(flag: str, option: str) -> bool:
    # git's parse-options accepts any unambiguous prefix of a long option.
    return len(flag) > 2 and option.startswith(flag)


def _git_subcommand_rule(subcommand: str, operands: list[str]) -> BlockRule | None:
    flags = operands[: operands.index("--")] if "--" in operands else operands
    if subcommand == "push" and (
        any(
            _is_long_prefix(flag, "--force") or re.fullmatch(r"-[a-zA-Z]*f[a-zA-Z]*", flag)
            for flag in flags
        )
        or any(operand.startswith("+") for operand in operands)
    ):
        return BLOCK_RULES[2]
    if subcommand == "reset" and any(_is_long_prefix(flag, "--hard") for flag in flags):
        return BLOCK_RULES[3]
    return None


def _find_rule(words: list[str]) -> BlockRule | None:
    if "-delete" in words:
        return BLOCK_RULES[0]
    for index, word in enumerate(words):
        if word in {"-exec", "-execdir", "-ok", "-okdir"} and index + 1 < len(words):
            action = words[index + 1 :]
            end = next((i for i, w in enumerate(action) if w in {";", "+"}), len(action))
            if action[:end] and _token_rule(action[:end]) is not None:
                return BLOCK_RULES[0]
    return None


# Preserve the legacy regex segmentation for credential/infra matches. Cleanup
# exceptions are checked against the entire command, never these text fragments.
_CHAIN_OPERATORS = re.compile(r"&&|\|\||;|\n|(?<![<>])&(?![&>])")


def _segments(command: str) -> list[str]:
    return _CHAIN_OPERATORS.split(command)


# Global git options this hook recognises between `git` and its subcommand.
# Options that take a value are listed with the flag alone; both the `=`-joined
# and space-separated spellings are matched. Anything not named here (e.g.
# `--namespace=`, `--exec-path`) still makes the git rules abstain, same as
# before this normalisation existed.
_GIT_GLOBAL_OPTIONS_WITH_ARG = ("-C", "-c", "--git-dir", "--work-tree")
_GIT_GLOBAL_OPTIONS_BARE = ("--no-pager",)
_GIT_GLOBAL_OPTION_AFTER_GIT = re.compile(
    r"\bgit\s+(?:"
    + "|".join(re.escape(opt) + r"(?:=\S+|\s+\S+)" for opt in _GIT_GLOBAL_OPTIONS_WITH_ARG)
    + "|"
    + "|".join(re.escape(opt) for opt in _GIT_GLOBAL_OPTIONS_BARE)
    + r")"
)


def _normalise_git_globals(segment: str) -> str:
    """Collapse `git <global-opts> <subcommand>` to `git <subcommand>`.

    The git rules match `git\\s+<subcommand>` right after `git`; a global
    option in between (`-C <path>`, `-c k=v`, `--git-dir=...`) otherwise makes
    them abstain. Repeated substitution handles several stacked options. Text
    before `git` is never touched, so `_COMMAND_START`'s position check still
    applies to the same offset it would have without normalisation.
    """
    normalised = segment
    while True:
        rewritten = _GIT_GLOBAL_OPTION_AFTER_GIT.sub("git", normalised, count=1)
        if rewritten == normalised:
            return normalised
        normalised = rewritten


def should_block(
    command: str,
    allow_patterns: list[str],
    *,
    recursive_delete_roots: list[Path] | tuple[Path, ...] = (),
    denied_commands: list[str] | tuple[str, ...] = (),
    cwd: Path | None = None,
) -> BlockDecision | None:
    """Judge operations; legacy allow_patterns is accepted but never grants an exception."""
    try:
        invocations = _invocations(command)
    except (ValueError, RecursionError):
        invocations = []
        if denied_commands:
            return BlockDecision(
                BlockRule("policy", re.compile(""), "Cannot parse command under denied_commands"),
                command,
            )
    for words in invocations:
        if Path(words[0]).name in denied_commands:
            return BlockDecision(
                BlockRule("policy", re.compile(""), f"Denied command: {Path(words[0]).name}"),
                command,
            )
    cleanup = _safe_cleanup(command, recursive_delete_roots, cwd or Path.cwd())
    for segment in _segments(command):
        for rule in BLOCK_RULES:
            subject = _normalise_git_globals(segment) if rule.category == "git" else segment
            match = rule.pattern.search(subject)
            if match is None:
                continue
            if cleanup and rule is BLOCK_RULES[0]:
                continue
            return BlockDecision(rule=rule, matched_text=match.group(0))
    for words in invocations:
        rule = _token_rule(words)
        if rule is not None and not (cleanup and rule is BLOCK_RULES[0]):
            return BlockDecision(rule, " ".join(words))
    return None


def should_block_path(path: str) -> BlockDecision | None:
    """Return BlockDecision if `path` resolves onto a secret glob.

    The path is made absolute first: the globs are anchored with `**/`, and
    fnmatch treats `*` as crossing `/`, so an absolute path is what makes
    `**/secrets/**` match a nested file the way the deny rule used to.

    Cleanup roots and legacy allow_patterns never exempt secret paths. Paths
    are exempted only by SECRET_PATH_EXCEPTIONS.
    """
    if not path:
        return None
    resolved = os.path.abspath(os.path.expanduser(path))
    if any(fnmatch.fnmatch(resolved, exc) for exc in SECRET_PATH_EXCEPTIONS):
        return None
    for glob in SECRET_PATH_GLOBS:
        if not fnmatch.fnmatch(resolved, glob):
            continue
        return BlockDecision(
            rule=BlockRule(
                category="credentials",
                pattern=re.compile(re.escape(glob)),
                reason=f"Secret path ({glob})",
            ),
            matched_text=resolved,
        )
    return None


def _log_block(decision: BlockDecision, command: str, profile: str) -> None:
    """Record a block so the guardrail leaves an auditable trace.

    Only blocks are logged: this hook runs on every Bash call, so logging
    allowed commands would bury the events that matter.

    Per profile, not per machine. Resolving the directory from a hardcoded
    `get_agent("claude-code")` appended this line to whichever directory the
    global agent named, so a block raised under one profile was auditable only
    from another. The `load_config` this costs is paid on the deny path alone.
    """
    try:
        from lazy_harness.core.config import ConfigError, load_config
        from lazy_harness.core.paths import config_file
        from lazy_harness.hooks.builtins._shared import agent_dir_for, make_log

        try:
            cfg = load_config(config_file())
        except ConfigError:
            cfg = None
        _, agent_dir = agent_dir_for(cfg, profile)
        log = make_log("pre-tool-use-security")
        log(agent_dir / "logs" / "hooks.log", f"blocked {decision.rule.category}: {command[:200]}")
    except Exception:
        # Auditing must never keep the guardrail from firing.
        pass


def main(event: HookEvent) -> HookDecision:
    """Judge one tool call, in the operations the adapter normalised it into.

    Dispatching on `Operation` rather than on Claude Code's tool names is what
    makes the guard portable: a renamed tool on another agent still runs a
    command or still touches a path, and the names this hook used to compare
    against are only one agent's spelling of that.

    Abstention is a bare `HookDecision()`, never `Verdict.ALLOW`: exit 0 with
    no output is how a hook says "no objection", and approving every command
    this guard merely fails to recognise would be the opposite statement.
    """
    tool = event.tool
    if tool is None:
        return HookDecision()
    if tool.operation is Operation.RUN_COMMAND:
        subject = tool.command or ""
        try:
            policy = _load_policy()
        except (ConfigError, ValueError, OSError, RuntimeError) as exc:
            return HookDecision(verdict=Verdict.DENY, reason=f"Invalid security policy: {exc}\n")
        decision = should_block(
            subject,
            [],
            recursive_delete_roots=policy.recursive_delete_roots,
            denied_commands=policy.denied_commands,
            cwd=event.cwd,
        )
    elif tool.operation in (Operation.READ_FILE, Operation.MODIFY_FILE):
        # Every path, not `paths[0]`. Under Claude Code the two are the same —
        # `reads` and `edits` are never both populated and `edits` never holds
        # more than one entry — but Codex's `apply_patch` delivers a multi-file
        # blob as one call (probe 5), so since the native edit path landed,
        # every path after the first went unexamined. ADR-046 D5: a delete
        # joins `paths` last, which makes it the entry most likely to be the
        # one skipped, and deleting a protected file is worse than editing it.
        #
        # First match wins, so one call still yields one block message.
        subject, decision = "", None
        for path in tool.paths:
            subject = str(path)
            decision = should_block_path(subject)
            if decision is not None:
                break
    else:
        return HookDecision()
    if decision is None:
        return HookDecision()
    _log_block(decision, subject, event.profile)
    return HookDecision(verdict=Verdict.DENY, reason=_format_block_message(decision))

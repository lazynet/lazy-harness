"""PreToolUse security hook — blocks destructive / exfiltration commands.

Deliberately diverges from ADR-006's "exit 0 always" contract: refuses with
`Verdict.DENY`, which Claude Code's adapter serialises as stderr plus exit 2.
See spec `specs/designs/2026-04-17-security-hooks-cluster-design.md`.
"""

from __future__ import annotations

import fnmatch
import os
import re
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from lazy_harness.agents.base import HookDecision, HookEvent, Operation, Verdict
from lazy_harness.core.paths import config_file

Category = Literal["filesystem", "sql", "terraform", "credentials", "git"]


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
# Short flags cluster (-rf, -fr, -rfv) or the long spelling, never both letters
# assumed from a single one: recursion and force are matched independently so
# `rm -f file` and `rm -r dir` both stay allowed.
_RM_RECURSIVE_FLAG = r"(?:-[a-zA-Z]*[rR][a-zA-Z]*|--recursive)\b"
_RM_FORCE_FLAG = r"(?:-[a-zA-Z]*f[a-zA-Z]*|--force)\b"
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
            rf"(?=(?:{_RM_OPTION}\s+)*{_RM_FORCE_FLAG})"
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
# path field differently, so both keys are read.
FILE_TOOLS = frozenset({"Read", "Edit", "Write", "NotebookEdit"})
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
        f"If this is intentional, add a regex pattern to "
        f"[hooks.pre_tool_use] allow_patterns in your profile config.toml.\n"
        f"See specs/designs/2026-04-17-security-hooks-cluster-design.md "
        f"for the full rule list.\n"
    )


def _load_allowlist() -> list[str]:
    """Load pre_tool_use.allow_patterns from the harness config.toml.

    Returns empty list on any failure (missing file, malformed TOML, missing
    section). Empty list means stricter blocking — fail-safe by design.
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
    section = data.get("hooks", {}).get("pre_tool_use", {})
    patterns = section.get("allow_patterns", [])
    if not isinstance(patterns, list):
        return []
    return [p for p in patterns if isinstance(p, str)]


def _safe_search(pattern: str, text: str) -> bool:
    """Compile-and-search; broken user regexes are skipped, never raised."""
    try:
        return re.search(pattern, text) is not None
    except re.error:
        return False


# `;`, `&&`, `||`, a bare `&` (background) and a newline chain independent
# commands; `|` does not, since a pipe composes one command out of two, so it
# is deliberately left out. This split is unquoted: a chain operator inside a
# quoted string or heredoc body still splits here, which can over-segment.
# Rule anchoring (`_COMMAND_START`) already tolerates that -- a mid-segment
# split lands the tail at what the regex treats as a fresh line/command start
# -- so over-segmenting narrows the allow_pattern rescue scope without
# changing which commands the rules match. A redirection spelling (`2>&1`,
# `>&2`, `&>file`, `<&3`) is excluded by the lookaround rather than relied on
# for that tolerance, since its `&` never starts a new command.
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


def should_block(command: str, allow_patterns: list[str]) -> BlockDecision | None:
    """Return BlockDecision if a shell segment matches a rule and is not rescued.

    Evaluated per segment (split on `;`, `&&`, `||`, bare `&`, newline -- see
    `_segments`): an allow_pattern rescues a match only if it also matches
    within that match's own segment, so a pattern meant for one operation
    cannot rescue a different, destructive one chained after it. Within a
    segment, first rule match wins; later rules are not evaluated even if more
    specific. Segments are checked in order and the first unrescued block
    returns. Git rules match against a normalised copy of the segment (see
    `_normalise_git_globals`) so a global option before the subcommand cannot
    make them abstain; every other category matches the segment as given.
    """
    for segment in _segments(command):
        for rule in BLOCK_RULES:
            subject = _normalise_git_globals(segment) if rule.category == "git" else segment
            match = rule.pattern.search(subject)
            if match is None:
                continue
            if any(_safe_search(ap, segment) for ap in allow_patterns):
                break
            return BlockDecision(rule=rule, matched_text=match.group(0))
    return None


def should_block_path(path: str) -> BlockDecision | None:
    """Return BlockDecision if `path` resolves onto a secret glob.

    The path is made absolute first: the globs are anchored with `**/`, and
    fnmatch treats `*` as crossing `/`, so an absolute path is what makes
    `**/secrets/**` match a nested file the way the deny rule used to.

    `allow_patterns` deliberately does not apply here. It rescues commands, and
    a pattern wide enough to be useful for one — `\\.worktrees/` is real in this
    repo's own config — would silently exempt every secret underneath it. Paths
    are rescued only by SECRET_PATH_EXCEPTIONS.
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
        decision = should_block(subject, _load_allowlist())
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

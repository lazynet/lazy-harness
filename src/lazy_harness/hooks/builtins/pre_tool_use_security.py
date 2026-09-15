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
_COMMAND_START = (
    r"(?:^|[;&|(`]\s*|\b(?:sudo|doas|xargs|time|env|nohup)\s+"
    r"|\b(?:ba|z|k)?sh\s+-c\s+['\"]?)(?:\S*/)?"
)
# Short flags cluster (-rf, -fr, -rfv) or the long spelling, never both letters
# assumed from a single one: recursion and force are matched independently so
# `rm -f file` and `rm -r dir` both stay allowed.
_RM_RECURSIVE_FLAG = r"(?:-[a-zA-Z]*[rR][a-zA-Z]*|--recursive)\b"
_RM_FORCE_FLAG = r"(?:-[a-zA-Z]*f[a-zA-Z]*|--force)\b"
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
        pattern=re.compile(r"\btruncate\s+(-s\s+\d+\s+)?[^\s-]"),
        reason="File truncation",
    ),
    BlockRule(
        category="git",
        pattern=re.compile(r"\bgit\s+push\s+(--force(?!-with-lease)\b|-f\b)"),
        reason="Force-push without lease",
    ),
    BlockRule(
        category="git",
        pattern=re.compile(r"\bgit\s+reset\s+--hard\b"),
        reason="Hard reset discards work",
    ),
    BlockRule(
        category="git",
        pattern=re.compile(
            r"\bgit\s+add\s+(-f\b|--force\b)[^|;&]*"
            r"(\.env|\.pem|\.key|\.p12|credentials|id_rsa|id_ed25519)"
        ),
        reason="Forced add of secret",
    ),
    BlockRule(
        category="sql",
        pattern=re.compile(r"\b(drop|truncate)\s+(table|database)\b", re.IGNORECASE),
        reason="SQL destruction",
    ),
    BlockRule(
        category="terraform",
        pattern=re.compile(r"\bterraform\s+destroy\b"),
        reason="Infra destruction",
    ),
    BlockRule(
        category="terraform",
        pattern=re.compile(r"\bterraform\s+apply\s+[^|;&]*-auto-approve\b"),
        reason="Skips plan review",
    ),
    BlockRule(
        category="terraform",
        pattern=re.compile(r"\bterraform\s+apply\s+[^|;&]*-replace=\S+"),
        reason="Forces resource recreation",
    ),
    BlockRule(
        category="terraform",
        pattern=re.compile(r"\bterraform\s+state\s+(rm|push)\b"),
        reason="State mutation",
    ),
    BlockRule(
        category="credentials",
        pattern=re.compile(
            r"\b(cat|bat|less|more|head|tail|grep|rg|awk|sed)\b[^|;&]*"
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
        pattern=re.compile(r"\b(cat|bat|less|more|head|tail)\b[^|;&]*\.ssh/id_(?!.*\.pub)\S+"),
        reason="Read of SSH private key",
    ),
    BlockRule(
        category="credentials",
        pattern=re.compile(
            r"\b(cat|bat|less|more|head|tail|grep|rg|awk|sed)\b[^|;&]*\.aws/(credentials|config)\b"
        ),
        reason="Read of AWS credentials",
    ),
    BlockRule(
        category="credentials",
        pattern=re.compile(r"\b(cat|bat|less|more|head|tail)\b[^|;&]*\.(pem|key|p12)\b"),
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


def should_block(command: str, allow_patterns: list[str]) -> BlockDecision | None:
    """Return BlockDecision if command matches a rule and no allow_pattern rescues it.

    First match wins; later rules are not evaluated even if more specific.
    """
    for rule in BLOCK_RULES:
        match = rule.pattern.search(command)
        if match is None:
            continue
        if any(_safe_search(ap, command) for ap in allow_patterns):
            return None
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
        paths = tool.paths
        subject = str(paths[0]) if paths else ""
        decision = should_block_path(subject)
    else:
        return HookDecision()
    if decision is None:
        return HookDecision()
    _log_block(decision, subject, event.profile)
    return HookDecision(verdict=Verdict.DENY, reason=_format_block_message(decision))

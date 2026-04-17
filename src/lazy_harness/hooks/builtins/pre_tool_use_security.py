"""PreToolUse security hook — blocks destructive / exfiltration commands.

Deliberately diverges from ADR-006's "exit 0 always" contract: exits 2 on
block per Claude Code PreToolUse semantics. See spec
`specs/designs/2026-04-17-security-hooks-cluster-design.md`.
"""

from __future__ import annotations

import json
import re
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

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


BLOCK_RULES: tuple[BlockRule, ...] = (
    BlockRule(
        category="filesystem",
        pattern=re.compile(r"\brm\s+-\S*f\S*\b.+"),
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
            r"\.env\b(?!\.(example|sample|template))"
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


MAX_MATCH_LEN = 120


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


def main() -> None:
    """Entry point invoked by Claude Code as a PreToolUse hook command."""
    payload = _read_stdin_json()
    if payload.get("tool_name") != "Bash":
        sys.exit(0)
    command = str(payload.get("tool_input", {}).get("command", ""))
    allow = _load_allowlist()
    decision = should_block(command, allow)
    if decision is None:
        sys.exit(0)
    sys.stderr.write(_format_block_message(decision))
    sys.exit(2)


if __name__ == "__main__":
    main()

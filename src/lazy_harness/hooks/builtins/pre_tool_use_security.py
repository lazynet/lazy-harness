"""PreToolUse security hook — blocks destructive / exfiltration commands.

Deliberately diverges from ADR-006's "exit 0 always" contract: exits 2 on
block per Claude Code PreToolUse semantics. See spec
`specs/designs/2026-04-17-security-hooks-cluster-design.md`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

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

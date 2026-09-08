"""Parsing of the claude-md proposal ledgers.

Three call sites answer the question "what is pending?": the CLI that drains
the queue, the session-start hook that reports on it, and the compound loop
that must not re-propose it. They disagreed — the hook's regex accepted a
leading-whitespace bullet the CLI's parser skipped — so the rules live here,
in one importable place, and every reader imports them.
"""

from __future__ import annotations

from dataclasses import dataclass

_RULE_PREFIX = "- **Rule:**"
_RATIONALE_PREFIX = "- **Rationale:**"


@dataclass(frozen=True)
class PendingProposal:
    """One `- **Rule:**` bullet from claude-md.proposal.md, with line spans."""

    timestamp: str
    rule: str
    rationale: str
    start_line: int
    end_line: int  # exclusive
    header_line: int  # line index of the owning `## <timestamp>` header, -1 if none


def parse_proposals(text: str) -> list[PendingProposal]:
    """Parse pending proposal bullets out of claude-md.proposal.md content.

    Tolerates the archived-comments-only file state: HTML comments and
    anything outside `- **Rule:**` bullets are ignored.
    """
    lines = text.splitlines()
    proposals: list[PendingProposal] = []
    in_comment = False
    header_ts = ""
    header_line = -1
    current: dict[str, object] | None = None

    def close(end: int) -> None:
        nonlocal current
        if current is None:
            return
        start = int(current["start"])
        while end - 1 > start and not lines[end - 1].strip():
            end -= 1
        proposals.append(
            PendingProposal(
                timestamp=str(current["timestamp"]),
                rule=str(current["rule"]),
                rationale=str(current["rationale"]),
                start_line=start,
                end_line=end,
                header_line=int(current["header_line"]),
            )
        )
        current = None

    for i, line in enumerate(lines):
        stripped = line.strip()
        if in_comment:
            if "-->" in stripped:
                in_comment = False
            continue
        if stripped.startswith("<!--"):
            close(i)
            if "-->" not in stripped:
                in_comment = True
            continue
        if stripped.startswith("## "):
            close(i)
            header_ts = stripped[3:].strip()
            header_line = i
            continue
        if stripped.startswith(_RULE_PREFIX) and not line.startswith(" "):
            close(i)
            current = {
                "timestamp": header_ts,
                "rule": stripped[len(_RULE_PREFIX) :].strip(),
                "rationale": "",
                "start": i,
                "header_line": header_line,
            }
            continue
        if current is not None and stripped.startswith(_RATIONALE_PREFIX):
            current["rationale"] = stripped[len(_RATIONALE_PREFIX) :].strip()
    close(len(lines))
    return proposals


def _remove_proposal(text: str, proposals: list[PendingProposal], index: int) -> str:
    """Return `text` without proposal `index` (0-based), dropping its section
    header when no sibling rule remains under it."""
    target = proposals[index]
    drop = set(range(target.start_line, target.end_line))
    header_shared = any(
        p.header_line == target.header_line for i, p in enumerate(proposals) if i != index
    )
    lines = text.splitlines()
    if target.header_line >= 0 and not header_shared:
        drop.add(target.header_line)
        j = target.header_line + 1
        while j < len(lines) and not lines[j].strip():
            drop.add(j)
            j += 1
    kept = [line for i, line in enumerate(lines) if i not in drop]
    out = "\n".join(kept).rstrip("\n")
    return out + "\n" if out else ""


def rule_lines(text: str) -> list[str]:
    """Rule text of every pending proposal, in document order.

    Built on `parse_proposals` rather than a regex of its own, so a document
    the CLI declines to number cannot be counted here as if it were queued.
    """
    return [p.rule for p in parse_proposals(text)]

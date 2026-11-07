"""Parsing of the claude-md proposal ledgers.

Three call sites answer the question "what is pending?": the CLI that drains
the queue, the session-start hook that reports on it, and the compound loop
that must not re-propose it. They disagreed — the hook's regex accepted a
leading-whitespace bullet the CLI's parser skipped — so the rules live here,
in one importable place, and every reader imports them.
"""

from __future__ import annotations

import os
import re
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

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


EXPIRED_PROPOSALS_FILE = "claude-md.expired.md"
_PENDING_FILE = "claude-md.proposal.md"
_EXPIRED_HEADER = (
    "<!-- expired claude-md proposals (append-only; NOT an immunity registry). -->\n\n"
)


def format_entry_block(proposal: PendingProposal, status_lines: list[str]) -> str:
    lines = [f"## {proposal.timestamp}"]
    lines.extend(status_lines)
    lines.append("")
    lines.append(f"{_RULE_PREFIX} {proposal.rule}")
    if proposal.rationale:
        lines.append(f"  {_RATIONALE_PREFIX} {proposal.rationale}")
    lines.append("")
    return "\n".join(lines)


def _replace_file(path: Path, content: str) -> None:
    """Atomic replace through a uniquely named temp file in the same directory."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            f.write(content)
        os.replace(tmp_name, path)
    except BaseException:
        Path(tmp_name).unlink(missing_ok=True)
        raise


def append_block(
    path: Path,
    header_comment: str,
    block: str,
    write: Callable[[Path, str], None] = _replace_file,
) -> None:
    if path.exists():
        write(path, path.read_text().rstrip("\n") + "\n\n" + block)
    else:
        write(path, header_comment + block)


def _proposal_age(timestamp: str, now: datetime) -> timedelta | None:
    """Age of a `## <ts>` header, or None when it cannot be told.

    A header that does not parse is never expired: dropping a proposal on a
    guess is the failure this guard exists to avoid. A naive timestamp is read
    as UTC.
    """
    try:
        stamp = datetime.fromisoformat(timestamp)
    except ValueError:
        return None
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=UTC)
    return now - stamp


def expire_pending(
    memory_dir: Path, max_age_days: int | None, now: datetime
) -> list[PendingProposal]:
    """Move pending proposals older than `max_age_days` to `claude-md.expired.md`.

    The registry is deliberately not the rejected one: a rejection teaches the
    grader never to propose the rule again, while an expired rule was only never
    reviewed and may be proposed afresh. The caller holds `memory_dir_lock`.
    `None` or `0` disables expiry.
    """
    if not max_age_days:
        return []
    pending_file = memory_dir / _PENDING_FILE
    try:
        text = pending_file.read_text()
    except OSError:
        return []
    limit = timedelta(days=max_age_days)
    expired: list[PendingProposal] = []
    while True:
        # Re-parsed after each removal: spans shift, and a header shared with a
        # rule already removed must be judged on what is left under it.
        proposals = parse_proposals(text)
        index = next(
            (
                i
                for i, p in enumerate(proposals)
                if (age := _proposal_age(p.timestamp, now)) is not None and age > limit
            ),
            None,
        )
        if index is None:
            break
        expired.append(proposals[index])
        text = _remove_proposal(text, proposals, index)
    if not expired:
        return []
    today = now.date().isoformat()
    registry = memory_dir / EXPIRED_PROPOSALS_FILE
    # Registry first, so a crash between the two writes never loses a rule; the
    # re-run skips what the registry already holds under the same header.
    try:
        registered = {(p.timestamp, p.rule) for p in parse_proposals(registry.read_text())}
    except OSError:
        registered = set()
    for proposal in expired:
        if (proposal.timestamp, proposal.rule) in registered:
            continue
        append_block(
            memory_dir / EXPIRED_PROPOSALS_FILE,
            _EXPIRED_HEADER,
            format_entry_block(
                proposal, [f"expired: {today}", f"reason: age > {max_age_days} days"]
            ),
        )
    _replace_file(pending_file, text)
    return expired


_EXPIRED_STAMP = re.compile(r"^expired: (\d{4}-\d{2}-\d{2})\s*$", re.MULTILINE)


def count_expired_since(memory_dir: Path, since: date) -> int:
    """Entries of the expired registry stamped `expired: <date>` on or after `since`."""
    try:
        text = (memory_dir / EXPIRED_PROPOSALS_FILE).read_text()
    except OSError:
        return 0
    return sum(1 for m in _EXPIRED_STAMP.finditer(text) if date.fromisoformat(m.group(1)) >= since)

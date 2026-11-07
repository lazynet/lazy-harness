"""Every reader of the proposal queue must return the same count.

Three places answer "how many proposals are pending?": the CLI that numbers
them for `accept`/`reject`, the session-start hook that warns about them, and
the compound loop that must not re-propose them. A reader that counts a bullet
the CLI declines to number reports a queue the user cannot drain — the warning
never clears and the number never matches the list.
"""

from __future__ import annotations

from pathlib import Path

from lazy_harness.core.proposals import parse_proposals
from lazy_harness.hooks.builtins.context_inject import proposals_summary_line
from lazy_harness.knowledge.compound_loop import collect_pending_proposals

# An indented `- **Rule:**` bullet: legal markdown the evaluator can emit, and
# the exact shape on which the hook's regex and the CLI's parser disagreed.
INDENTED_RULE = """\
<!-- claude-md proposals (append-only). -->

## 2026-09-01T22:21:21-03:00

- **Rule:** a top-level rule the CLI numbers
  - **Rationale:** why
  - **Rule:** an indented bullet the CLI does not number
"""


def _write(tmp_path: Path, text: str) -> Path:
    memory = tmp_path / "memory"
    memory.mkdir()
    (memory / "claude-md.proposal.md").write_text(text)
    return memory


def test_hook_summary_counts_what_the_cli_would_number(tmp_path: Path) -> None:
    memory = _write(tmp_path, INDENTED_RULE)

    numbered = len(parse_proposals((memory / "claude-md.proposal.md").read_text()))
    line = proposals_summary_line(memory)

    assert numbered == 1
    assert f"{numbered} claude-md proposal(s) pending" in line


def test_compound_loop_sees_what_the_cli_would_number(tmp_path: Path) -> None:
    memory = _write(tmp_path, INDENTED_RULE)

    numbered = [p.rule for p in parse_proposals((memory / "claude-md.proposal.md").read_text())]

    assert collect_pending_proposals(memory) == numbered


def test_every_reader_agrees_after_an_expiry(tmp_path: Path) -> None:
    from datetime import UTC, datetime

    from lazy_harness.core.proposals import expire_pending

    memory = _write(
        tmp_path,
        "## 2020-01-01T10:00:00-03:00\n\n- **Rule:** long gone\n\n"
        "## 2026-11-06T10:00:00-03:00\n\n- **Rule:** still fresh\n",
    )

    expire_pending(memory, 30, datetime(2026, 11, 7, tzinfo=UTC))

    numbered = [p.rule for p in parse_proposals((memory / "claude-md.proposal.md").read_text())]
    assert numbered == ["still fresh"]
    assert collect_pending_proposals(memory) == numbered
    assert "1 claude-md proposal(s) pending" in proposals_summary_line(memory)
    assert _doctor_lines(memory) == ["1 pending proposal(s), oldest", "1 expired in the last 30d"]
    assert "1 pending · 0 rejected" in _status_output(memory)


def _doctor_lines(memory: Path) -> list[str]:
    """The pending and expired fragments `lh doctor` prints for this memory dir."""
    import io
    import re
    from datetime import UTC, datetime

    from rich.console import Console

    from lazy_harness.cli.doctor_cmd import _render_memory_hygiene

    buf = io.StringIO()
    console = Console(file=buf, width=200, color_system=None)
    _render_memory_hygiene(console, memory, now=datetime(2026, 11, 7, tzinfo=UTC))
    found = re.findall(
        r"\d+ pending proposal\(s\), oldest|\d+ expired in the last 30d", buf.getvalue()
    )
    return found


def _status_output(memory: Path) -> str:
    from click.testing import CliRunner

    from lazy_harness.cli.memory_cmd import memory as memory_group

    result = CliRunner().invoke(memory_group, ["status", "--memory-dir", str(memory)])
    assert result.exit_code == 0, result.output
    return result.output

"""Expired proposal review and revival through the shipped CLI."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from click.testing import CliRunner

from lazy_harness.cli.memory_cmd import memory
from lazy_harness.core.proposals import expire_pending, parse_proposals
from lazy_harness.knowledge.compound_loop import collect_pending_proposals

_NOW = datetime(2026, 11, 7, 12, 0, tzinfo=UTC)


def _expired(memory_dir: Path, rules: list[str]) -> None:
    memory_dir.mkdir(parents=True, exist_ok=True)
    body = "\n\n".join(
        f"## 2026-09-0{i + 1}T10:00:00-03:00\n\n- **Rule:** {r}" for i, r in enumerate(rules)
    )
    (memory_dir / "claude-md.proposal.md").write_text(body + "\n")
    expire_pending(memory_dir, 30, _NOW)


def _run(memory_dir: Path, *args: str):
    return CliRunner().invoke(
        memory, ["proposals", "expired", *args, "--memory-dir", str(memory_dir)]
    )


def test_expired_default_listing_is_read_only(tmp_path: Path) -> None:
    memory_dir = tmp_path / "memory"
    _expired(memory_dir, ["first rule", "second rule"])
    registry = memory_dir / "claude-md.expired.md"
    before = registry.read_bytes()

    result = _run(memory_dir)

    assert result.exit_code == 0, result.output
    assert "first rule" in result.output and "second rule" in result.output
    assert registry.read_bytes() == before


def test_expired_list_reports_an_empty_registry(tmp_path: Path) -> None:
    memory_dir = tmp_path / "memory"
    memory_dir.mkdir()

    result = _run(memory_dir, "list")

    assert result.exit_code == 0, result.output
    assert "No expired claude-md proposals" in result.output


def test_expired_requeue_revives_the_rule_with_a_fresh_timestamp(tmp_path: Path) -> None:
    memory_dir = tmp_path / "memory"
    _expired(memory_dir, ["first rule", "second rule"])

    result = _run(memory_dir, "requeue", "2")

    assert result.exit_code == 0, result.output
    assert collect_pending_proposals(memory_dir) == ["second rule"]
    pending = parse_proposals((memory_dir / "claude-md.proposal.md").read_text())
    # Keeping the original header would expire the rule again on the next run.
    assert pending[0].timestamp[:4] == str(datetime.now(UTC).year)
    assert expire_pending(memory_dir, 30, datetime.now(UTC)) == []
    remaining = parse_proposals((memory_dir / "claude-md.expired.md").read_text())
    assert [p.rule for p in remaining] == ["first rule"]
    log = (memory_dir / "claude-md.expired-requeued.jsonl").read_text().splitlines()
    assert [json.loads(line)["rule"] for line in log] == ["second rule"]


def test_expired_requeue_refuses_a_full_queue(tmp_path: Path) -> None:
    memory_dir = tmp_path / "memory"
    _expired(memory_dir, ["old rule"])
    (memory_dir / "claude-md.proposal.md").write_text("## now\n\n- **Rule:** queued\n")

    result = _run(memory_dir, "requeue", "1", "--max-pending", "1")

    assert result.exit_code != 0
    assert "1 pending >= cap 1" in result.output
    assert collect_pending_proposals(memory_dir) == ["queued"]
    assert not (memory_dir / "claude-md.expired-requeued.jsonl").exists()
    assert len(parse_proposals((memory_dir / "claude-md.expired.md").read_text())) == 1


def test_expired_requeue_rejects_an_index_out_of_range(tmp_path: Path) -> None:
    memory_dir = tmp_path / "memory"
    _expired(memory_dir, ["only rule"])

    result = _run(memory_dir, "requeue", "5")

    assert result.exit_code != 0
    assert "No expired proposal 5" in result.output

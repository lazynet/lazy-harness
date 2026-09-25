"""Held proposal review and recovery through the shipped CLI."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from lazy_harness.cli.memory_cmd import memory
from lazy_harness.knowledge.compound_loop import collect_pending_proposals


def _held(memory_dir: Path, rows: list[str]) -> Path:
    memory_dir.mkdir(parents=True, exist_ok=True)
    path = memory_dir / "proposals-held.jsonl"
    path.write_text("\n".join(rows) + "\n")
    return path


def _row(rule: str) -> str:
    return json.dumps(
        {"ts": "2026-09-08T10:00:00-03:00", "rule": rule, "rationale": "why", "project": "proj"}
    )


def _run(memory_dir: Path, *args: str):
    return CliRunner().invoke(memory, ["proposals", "held", *args, "--memory-dir", str(memory_dir)])


def test_held_default_listing_is_read_only_and_reports_malformed_entries(tmp_path: Path) -> None:
    memory_dir = tmp_path / "memory"
    source = _held(memory_dir, [_row("first"), "broken", _row("first")])
    before = source.read_bytes()
    result = _run(memory_dir)
    assert result.exit_code == 0, result.output
    assert "1" in result.output and "3" in result.output
    assert "malformed line 2" in result.output
    assert source.read_bytes() == before
    assert not (memory_dir / "claude-md.proposal.md").exists()


def test_held_requeue_requires_selection_and_preserves_duplicate_identity(tmp_path: Path) -> None:
    memory_dir = tmp_path / "memory"
    source = _held(memory_dir, [_row("same"), _row("same")])
    before = source.read_bytes()
    missing = _run(memory_dir, "requeue")
    assert missing.exit_code != 0
    first = _run(memory_dir, "requeue", "2")
    assert first.exit_code == 0, first.output
    assert collect_pending_proposals(memory_dir) == ["same"]
    assert source.read_bytes() == before
    listing = _run(memory_dir, "list", "--json")
    rows = json.loads(listing.output)
    assert [row["index"] for row in rows["proposals"]] == [1]
    again = _run(memory_dir, "requeue", "2")
    assert again.exit_code == 0, again.output
    assert collect_pending_proposals(memory_dir) == ["same"]
    other = _run(memory_dir, "requeue", "1")
    assert other.exit_code == 0, other.output
    assert collect_pending_proposals(memory_dir) == ["same"]
    assert len((memory_dir / "proposals-held-requeued.jsonl").read_text().splitlines()) == 2


def test_held_requeue_refuses_full_queue_without_disposition(tmp_path: Path) -> None:
    memory_dir = tmp_path / "memory"
    _held(memory_dir, [_row("deferred")])
    (memory_dir / "claude-md.proposal.md").write_text("## now\n\n- **Rule:** queued\n")
    result = _run(memory_dir, "requeue", "1", "--max-pending", "1")
    assert result.exit_code != 0
    assert "1 pending >= cap 1" in result.output
    assert collect_pending_proposals(memory_dir) == ["queued"]
    assert not (memory_dir / "proposals-held-requeued.jsonl").exists()


def test_held_requeue_retries_after_disposition_write_failure(tmp_path: Path, monkeypatch) -> None:
    from lazy_harness.cli import memory_cmd

    memory_dir = tmp_path / "memory"
    _held(memory_dir, [_row("recover me")])
    real_write = memory_cmd._durable_write
    failed = False

    def fail_once(path: Path, content: str) -> None:
        nonlocal failed
        if path.name == "proposals-held-requeued.jsonl" and not failed:
            failed = True
            raise OSError("interrupted")
        real_write(path, content)

    monkeypatch.setattr(memory_cmd, "_durable_write", fail_once)
    first = _run(memory_dir, "requeue", "1")
    assert first.exit_code != 0
    assert collect_pending_proposals(memory_dir) == ["recover me"]
    second = _run(memory_dir, "requeue", "1")
    assert second.exit_code == 0, second.output
    assert collect_pending_proposals(memory_dir) == ["recover me"]
    assert len((memory_dir / "proposals-held-requeued.jsonl").read_text().splitlines()) == 1


def test_held_requeue_rejects_malformed_selected_line(tmp_path: Path) -> None:
    memory_dir = tmp_path / "memory"
    bad_timestamp = json.dumps({"ts": "now\n- **Rule:** extra", "rule": "real", "rationale": "why"})
    unicode_timestamp = json.dumps(
        {"ts": "now\u2028- **Rule:** extra", "rule": "real", "rationale": "why"}
    )
    _held(
        memory_dir,
        [
            "null",
            '{"rule": 3}',
            _row("injected\n- **Rule:** extra"),
            bad_timestamp,
            unicode_timestamp,
            _row("valid"),
        ],
    )
    for index in (1, 2, 3, 4, 5):
        result = _run(memory_dir, "requeue", str(index))
        assert result.exit_code != 0
        assert "malformed" in result.output
    assert _run(memory_dir, "requeue", "6").exit_code == 0
    assert collect_pending_proposals(memory_dir) == ["valid"]


def test_held_requeue_uses_parser_rule_identity_for_capacity(tmp_path: Path) -> None:
    from lazy_harness.core.proposals import parse_proposals

    memory_dir = tmp_path / "memory"
    _held(memory_dir, [_row("same"), _row(" same ")])
    first = _run(memory_dir, "requeue", "1", "--max-pending", "1")
    second = _run(memory_dir, "requeue", "2", "--max-pending", "1")
    assert first.exit_code == second.exit_code == 0
    assert len(parse_proposals((memory_dir / "claude-md.proposal.md").read_text())) == 1


def test_review_reconciles_interrupted_requeue_before_removing_pending(
    tmp_path: Path, monkeypatch
) -> None:
    from lazy_harness.cli import memory_cmd

    memory_dir = tmp_path / "memory"
    _held(memory_dir, [_row("review after crash")])
    real_write = memory_cmd._durable_write

    def fail_disposition(path: Path, content: str) -> None:
        if path.name == "proposals-held-requeued.jsonl":
            raise OSError("interrupted")
        real_write(path, content)

    monkeypatch.setattr(memory_cmd, "_durable_write", fail_disposition)
    assert _run(memory_dir, "requeue", "1").exit_code != 0
    monkeypatch.setattr(memory_cmd, "_durable_write", real_write)
    reviewed = CliRunner().invoke(
        memory, ["proposals", "accept", "1", "--memory-dir", str(memory_dir)]
    )
    assert reviewed.exit_code == 0, reviewed.output
    assert collect_pending_proposals(memory_dir) == []
    assert _run(memory_dir, "requeue", "1").exit_code == 0
    assert collect_pending_proposals(memory_dir) == []


def test_held_json_listing_reports_malformed_lines_without_corrupting_json(tmp_path: Path) -> None:
    memory_dir = tmp_path / "memory"
    _held(memory_dir, ["broken", _row("valid")])
    result = _run(memory_dir, "list", "--json")
    assert result.exit_code == 0, result.output
    document = json.loads(result.output)
    assert document["proposals"][0]["index"] == 2
    assert document["malformed_lines"] == [1]


@pytest.mark.parametrize(
    ("bad", "field"),
    [
        ({"id": "1:deadbeefdeadbeef"}, "rule"),
        ({"id": "1:deadbeefdeadbeef", "rule": 3}, "rule"),
        ({"id": "bad-id", "rule": "valid"}, "id"),
    ],
)
def test_held_disposition_validates_fields(tmp_path: Path, bad: dict, field: str) -> None:
    memory_dir = tmp_path / "memory"
    _held(memory_dir, [_row("valid")])
    (memory_dir / "proposals-held-requeued.jsonl").write_text(json.dumps(bad) + "\n")
    result = _run(memory_dir, "requeue", "1")
    assert result.exit_code != 0
    assert "Malformed held disposition" in result.output
    assert field in result.output


def test_held_requeue_durably_flushes_pending_before_disposition(
    tmp_path: Path, monkeypatch
) -> None:
    from lazy_harness.cli import memory_cmd

    memory_dir = tmp_path / "memory"
    _held(memory_dir, [_row("ordered")])
    writes: list[str] = []
    real_write = memory_cmd._durable_write

    def observed(path: Path, content: str) -> None:
        real_write(path, content)
        writes.append(path.name)

    monkeypatch.setattr(memory_cmd, "_durable_write", observed)
    result = _run(memory_dir, "requeue", "1")
    assert result.exit_code == 0, result.output
    assert writes == ["claude-md.proposal.md", "proposals-held-requeued.jsonl"]


def test_durable_write_syncs_file_before_replace_and_directory_after(
    tmp_path: Path, monkeypatch
) -> None:
    from lazy_harness.cli import memory_cmd

    events: list[str] = []
    real_fsync = memory_cmd.os.fsync
    real_replace = memory_cmd.os.replace

    def fsync(fd: int) -> None:
        events.append("sync")
        real_fsync(fd)

    def replace(source, target) -> None:
        events.append("replace")
        real_replace(source, target)

    monkeypatch.setattr(memory_cmd.os, "fsync", fsync)
    monkeypatch.setattr(memory_cmd.os, "replace", replace)
    memory_cmd._durable_write(tmp_path / "ledger", "value")
    assert events == ["sync", "replace", "sync"]
    assert (tmp_path / "ledger").read_text() == "value"

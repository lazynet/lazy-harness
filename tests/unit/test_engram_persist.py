"""Tests for knowledge.engram_persist — EngramPersister core logic."""

from __future__ import annotations

import json
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

from lazy_harness.knowledge.engram_persist import EngramPersister, PersistResult


def test_persister_can_be_instantiated_with_required_args(tmp_path: Path) -> None:
    memory_dir = tmp_path / "memory"
    logs_dir = tmp_path / "logs"
    memory_dir.mkdir()
    logs_dir.mkdir()

    persister = EngramPersister(
        memory_dir=memory_dir,
        logs_dir=logs_dir,
        project_key="lazy-harness",
        engram_bin="/usr/bin/false",  # never invoked in this test
    )

    assert persister.memory_dir == memory_dir
    assert persister.logs_dir == logs_dir
    assert persister.project_key == "lazy-harness"


def test_persist_returns_zero_counts_when_no_jsonl_files_present(tmp_path: Path) -> None:
    memory_dir = tmp_path / "memory"
    logs_dir = tmp_path / "logs"
    memory_dir.mkdir()
    logs_dir.mkdir()

    persister = EngramPersister(
        memory_dir=memory_dir,
        logs_dir=logs_dir,
        project_key="lazy-harness",
        engram_bin="/usr/bin/false",
    )

    result: PersistResult = persister.persist_new_entries()

    assert result.saved_ok == 0
    assert result.saved_failed == 0
    assert result.skipped_malformed == 0
    assert result.entries_seen == {"decision": 0, "failure": 0}


def test_load_cursor_returns_zero_offsets_when_file_missing(tmp_path: Path) -> None:
    from lazy_harness.knowledge.engram_persist import _load_cursor

    cursor = _load_cursor(tmp_path / "engram_cursor.json")

    assert cursor == {"decisions_offset": 0, "failures_offset": 0}


def test_load_cursor_reads_valid_json(tmp_path: Path) -> None:
    from lazy_harness.knowledge.engram_persist import _load_cursor

    cursor_path = tmp_path / "engram_cursor.json"
    cursor_path.write_text(
        '{"version": 1, "decisions_offset": 4523, "failures_offset": 1820, '
        '"updated_at": "2026-05-04T11:25:00Z"}'
    )

    cursor = _load_cursor(cursor_path)

    assert cursor["decisions_offset"] == 4523
    assert cursor["failures_offset"] == 1820


def test_load_cursor_resets_on_corrupt_json(tmp_path: Path) -> None:
    from lazy_harness.knowledge.engram_persist import _load_cursor

    cursor_path = tmp_path / "engram_cursor.json"
    cursor_path.write_text("not valid json {{{")

    cursor = _load_cursor(cursor_path)

    assert cursor == {"decisions_offset": 0, "failures_offset": 0}


def test_load_cursor_resets_on_missing_keys(tmp_path: Path) -> None:
    from lazy_harness.knowledge.engram_persist import _load_cursor

    cursor_path = tmp_path / "engram_cursor.json"
    cursor_path.write_text('{"version": 1}')

    cursor = _load_cursor(cursor_path)

    assert cursor == {"decisions_offset": 0, "failures_offset": 0}


def test_load_cursor_resets_on_non_int_values(tmp_path: Path) -> None:
    from lazy_harness.knowledge.engram_persist import _load_cursor

    cursor_path = tmp_path / "engram_cursor.json"
    cursor_path.write_text(
        '{"version": 1, "decisions_offset": "not-a-number", "failures_offset": 0}'
    )

    cursor = _load_cursor(cursor_path)

    assert cursor == {"decisions_offset": 0, "failures_offset": 0}


def test_save_cursor_writes_atomically(tmp_path: Path) -> None:
    from lazy_harness.knowledge.engram_persist import _save_cursor

    cursor_path = tmp_path / "engram_cursor.json"

    _save_cursor(cursor_path, decisions_offset=100, failures_offset=200)

    data = json.loads(cursor_path.read_text())
    assert data["decisions_offset"] == 100
    assert data["failures_offset"] == 200
    assert data["version"] == 1
    assert "updated_at" in data
    # No leftover tempfiles in the parent dir
    leftover = [p for p in tmp_path.iterdir() if p.is_file() and p.suffix == ".tmp"]
    assert leftover == []


def _seed_jsonl(memory_dir: Path, kind: str, entries: list[dict]) -> Path:
    filename = "decisions.jsonl" if kind == "decision" else "failures.jsonl"
    path = memory_dir / filename
    path.write_text("\n".join(json.dumps(e) for e in entries) + "\n")
    return path


def _persister(tmp_path: Path, engram_bin: str | None = None) -> EngramPersister:
    memory_dir = tmp_path / "memory"
    logs_dir = tmp_path / "logs"
    memory_dir.mkdir()
    logs_dir.mkdir()
    if engram_bin is None:
        engram_bin_path = tmp_path / "engram"
        engram_bin_path.write_text("")  # placeholder; mock intercepts subprocess
        engram_bin = str(engram_bin_path)
    return EngramPersister(
        memory_dir=memory_dir,
        logs_dir=logs_dir,
        project_key="lazy-harness",
        engram_bin=engram_bin,
    )


def test_persists_new_decision_entries_via_engram_save(tmp_path: Path) -> None:
    persister = _persister(tmp_path)
    entries = [
        {
            "ts": "2026-05-04T11:00:00Z",
            "type": "decision",
            "summary": "Use CLI not MCP for hook",
            "rationale": "Independence from server state",
        }
    ]
    _seed_jsonl(persister.memory_dir, "decision", entries)

    with patch("lazy_harness.knowledge.engram_persist.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        result = persister.persist_new_entries()

    assert result.saved_ok == 1
    assert result.saved_failed == 0
    # 1 save call + 1 version probe in _emit_run_metric
    assert mock_run.call_count == 2
    args = mock_run.call_args_list[0].args[0]
    assert args[0] == persister.engram_bin
    assert args[1] == "save"
    assert args[2] == "Use CLI not MCP for hook"
    assert json.loads(args[3]) == entries[0]
    assert "--type" in args and args[args.index("--type") + 1] == "decision"
    assert "--project" in args and args[args.index("--project") + 1] == "lazy-harness"
    assert "--scope" in args and args[args.index("--scope") + 1] == "project"


def test_persists_failure_entries_with_failure_type(tmp_path: Path) -> None:
    persister = _persister(tmp_path)
    entries = [
        {
            "ts": "2026-05-04T11:00:00Z",
            "type": "failure",
            "summary": "Worker lock not refreshed",
            "root_cause": "Missing touch() in heartbeat path",
        }
    ]
    _seed_jsonl(persister.memory_dir, "failure", entries)

    with patch("lazy_harness.knowledge.engram_persist.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        persister.persist_new_entries()

    args = mock_run.call_args_list[0].args[0]
    assert args[args.index("--type") + 1] == "failure"


def test_title_falls_back_when_summary_missing(tmp_path: Path) -> None:
    persister = _persister(tmp_path)
    entries = [
        {"ts": "2026-05-04T11:00:00Z", "type": "decision"}  # no summary
    ]
    _seed_jsonl(persister.memory_dir, "decision", entries)

    with patch("lazy_harness.knowledge.engram_persist.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        persister.persist_new_entries()

    args = mock_run.call_args_list[0].args[0]
    assert args[2] == "decision@2026-05-04T11:00:00Z"


def test_title_truncated_to_max_chars(tmp_path: Path) -> None:
    persister = _persister(tmp_path)
    long = "x" * 500
    entries = [{"ts": "2026-05-04T11:00:00Z", "type": "decision", "summary": long}]
    _seed_jsonl(persister.memory_dir, "decision", entries)

    with patch("lazy_harness.knowledge.engram_persist.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        persister.persist_new_entries()

    args = mock_run.call_args_list[0].args[0]
    assert len(args[2]) == 200  # TITLE_MAX_CHARS


def test_advances_cursor_only_on_successful_save(tmp_path: Path) -> None:
    persister = _persister(tmp_path)
    entries = [{"ts": "T1", "type": "decision", "summary": "first"}]
    _seed_jsonl(persister.memory_dir, "decision", entries)

    with patch("lazy_harness.knowledge.engram_persist.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="boom")
        result = persister.persist_new_entries()

    assert result.saved_ok == 0
    assert result.saved_failed == 1
    cursor_file = persister.memory_dir / "engram_cursor.json"
    if cursor_file.is_file():
        cursor = json.loads(cursor_file.read_text())
        assert cursor["decisions_offset"] == 0  # never advanced


def test_skips_already_persisted_entries_on_second_run(tmp_path: Path) -> None:
    persister = _persister(tmp_path)
    entries = [
        {"ts": "T1", "type": "decision", "summary": "first"},
        {"ts": "T2", "type": "decision", "summary": "second"},
    ]
    _seed_jsonl(persister.memory_dir, "decision", entries)

    with patch("lazy_harness.knowledge.engram_persist.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        persister.persist_new_entries()
        first_call_count = mock_run.call_count
        # Second run with no new entries
        result = persister.persist_new_entries()

    # 2 saves + 1 version probe on first run
    assert first_call_count == 3
    assert result.saved_ok == 0
    # Second run: 0 saves + 1 version probe = 1 additional call
    assert mock_run.call_count == 4


def test_handles_malformed_jsonl_line_between_valid_lines(tmp_path: Path) -> None:
    persister = _persister(tmp_path)
    valid_a = json.dumps({"ts": "T1", "type": "decision", "summary": "a"})
    valid_b = json.dumps({"ts": "T2", "type": "decision", "summary": "b"})
    bad = "{ this is not json"
    (persister.memory_dir / "decisions.jsonl").write_text(
        valid_a + "\n" + bad + "\n" + valid_b + "\n"
    )

    with patch("lazy_harness.knowledge.engram_persist.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        result = persister.persist_new_entries()

    assert result.saved_ok == 2
    assert result.skipped_malformed == 1
    # Both valid entries saved, malformed line counted; cursor at EOF.
    cursor = json.loads((persister.memory_dir / "engram_cursor.json").read_text())
    assert cursor["decisions_offset"] == (persister.memory_dir / "decisions.jsonl").stat().st_size


def test_breaks_inner_loop_on_save_failure(tmp_path: Path) -> None:
    persister = _persister(tmp_path)
    entries = [
        {"ts": "T1", "type": "decision", "summary": "first"},
        {"ts": "T2", "type": "decision", "summary": "second"},
        {"ts": "T3", "type": "decision", "summary": "third"},
    ]
    _seed_jsonl(persister.memory_dir, "decision", entries)

    side_effects = [
        MagicMock(returncode=0, stdout="", stderr=""),  # save entry 1 → ok
        MagicMock(returncode=1, stdout="", stderr="boom"),  # save entry 2 → fail, break
        MagicMock(returncode=0, stdout="", stderr=""),  # version probe in _emit_run_metric
    ]

    with patch(
        "lazy_harness.knowledge.engram_persist.subprocess.run",
        side_effect=side_effects,
    ) as mock_run:
        result = persister.persist_new_entries()

    assert result.saved_ok == 1
    assert result.saved_failed == 1
    # 2 save calls (third entry not attempted) + 1 version probe = 3 total
    assert mock_run.call_count == 3


def test_resets_cursor_when_offset_exceeds_file_size(tmp_path: Path) -> None:
    persister = _persister(tmp_path)
    entries = [{"ts": "T1", "type": "decision", "summary": "first"}]
    _seed_jsonl(persister.memory_dir, "decision", entries)

    # Pre-seed a cursor that points past EOF (truncation simulation)
    (persister.memory_dir / "engram_cursor.json").write_text(
        json.dumps(
            {
                "version": 1,
                "decisions_offset": 9999,
                "failures_offset": 0,
                "updated_at": "2026-05-04T00:00:00Z",
            }
        )
    )

    with patch("lazy_harness.knowledge.engram_persist.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        result = persister.persist_new_entries()

    assert result.saved_ok == 1


def test_handles_missing_engram_binary_gracefully(tmp_path: Path) -> None:
    memory_dir = tmp_path / "memory"
    logs_dir = tmp_path / "logs"
    memory_dir.mkdir()
    logs_dir.mkdir()
    entries = [{"ts": "T1", "type": "decision", "summary": "x"}]
    _seed_jsonl(memory_dir, "decision", entries)

    persister = EngramPersister(
        memory_dir=memory_dir,
        logs_dir=logs_dir,
        project_key="lazy-harness",
        engram_bin="/nonexistent/engram-binary-xyz",
    )

    with patch("lazy_harness.knowledge.engram_persist.subprocess.run") as mock_run:
        result = persister.persist_new_entries()

    mock_run.assert_not_called()
    assert result.saved_ok == 0
    log_path = logs_dir / "engram_persist.log"
    assert log_path.is_file()
    assert "engram binary not on PATH" in log_path.read_text()


def test_failures_and_decisions_have_independent_cursors(tmp_path: Path) -> None:
    persister = _persister(tmp_path)
    decisions = [{"ts": "D1", "type": "decision", "summary": "d"}]
    failures = [{"ts": "F1", "type": "failure", "summary": "f"}]
    _seed_jsonl(persister.memory_dir, "decision", decisions)
    _seed_jsonl(persister.memory_dir, "failure", failures)

    with patch("lazy_harness.knowledge.engram_persist.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        persister.persist_new_entries()

    cursor = json.loads((persister.memory_dir / "engram_cursor.json").read_text())
    decisions_size = (persister.memory_dir / "decisions.jsonl").stat().st_size
    failures_size = (persister.memory_dir / "failures.jsonl").stat().st_size
    assert cursor["decisions_offset"] == decisions_size
    assert cursor["failures_offset"] == failures_size


def test_resolve_project_key_uses_git_common_dir_parent_basename(
    tmp_path: Path, monkeypatch
) -> None:
    from lazy_harness.hooks.builtins.engram_persist import _resolve_project_key

    repo_root = tmp_path / "repos" / "lazy" / "lazy-harness"
    repo_root.mkdir(parents=True)
    (repo_root / ".git").mkdir()  # bare marker; we will mock subprocess

    def fake_run(cmd, **kwargs):
        if cmd[:2] == ["git", "rev-parse"] and "--git-common-dir" in cmd:
            return MagicMock(returncode=0, stdout=str(repo_root / ".git") + "\n", stderr="")
        return MagicMock(returncode=128, stdout="", stderr="not a git repo")

    monkeypatch.setattr("lazy_harness.hooks.builtins.engram_persist.subprocess.run", fake_run)

    nested_cwd = repo_root / "src" / "lazy_harness"
    nested_cwd.mkdir(parents=True)
    assert _resolve_project_key(nested_cwd) == "lazy-harness"


def test_resolve_project_key_resolves_correctly_from_worktree(tmp_path: Path, monkeypatch) -> None:
    from lazy_harness.hooks.builtins.engram_persist import _resolve_project_key

    repo_root = tmp_path / "repos" / "myrepo"
    repo_root.mkdir(parents=True)
    common_git = repo_root / ".git"
    common_git.mkdir()
    worktree = repo_root / ".worktrees" / "feature-x"
    worktree.mkdir(parents=True)

    def fake_run(cmd, **kwargs):
        if cmd[:2] == ["git", "rev-parse"] and "--git-common-dir" in cmd:
            return MagicMock(returncode=0, stdout=str(common_git) + "\n", stderr="")
        return MagicMock(returncode=128, stdout="", stderr="not a git repo")

    monkeypatch.setattr("lazy_harness.hooks.builtins.engram_persist.subprocess.run", fake_run)

    # From inside the worktree, the canonical key must be the main repo basename
    assert _resolve_project_key(worktree) == "myrepo"


def test_resolve_project_key_falls_back_to_cwd_basename(tmp_path: Path, monkeypatch) -> None:
    from lazy_harness.hooks.builtins.engram_persist import _resolve_project_key

    def fake_run(cmd, **kwargs):
        return MagicMock(returncode=128, stdout="", stderr="not a git repo")

    monkeypatch.setattr("lazy_harness.hooks.builtins.engram_persist.subprocess.run", fake_run)

    cwd = tmp_path / "lazy-harness"
    cwd.mkdir()
    assert _resolve_project_key(cwd) == "lazy-harness"


def test_metrics_run_line_emitted_with_required_fields(tmp_path: Path) -> None:
    persister = _persister(tmp_path)
    entries = [{"ts": "T1", "type": "decision", "summary": "x"}]
    _seed_jsonl(persister.memory_dir, "decision", entries)

    with patch("lazy_harness.knowledge.engram_persist.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        persister.persist_new_entries()

    metrics_path = persister.logs_dir / "engram_persist_metrics.jsonl"
    assert metrics_path.is_file()
    lines = metrics_path.read_text().strip().splitlines()
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert record["event"] == "run"
    assert record["saved_ok"] == 1
    assert record["saved_failed"] == 0
    assert record["skipped_malformed"] == 0
    assert record["entries_seen"] == {"decisions": 1, "failures": 0}
    assert record["cursor_lag_bytes"] == {"decisions": 0, "failures": 0}
    assert record["project_key"] == "lazy-harness"
    assert "duration_ms" in record
    assert "subprocess_ms" in record
    assert "ts" in record
    assert "engram_version" in record
    assert "hook_version" in record


def test_metrics_not_emitted_when_engram_binary_missing(tmp_path: Path) -> None:
    memory_dir = tmp_path / "memory"
    logs_dir = tmp_path / "logs"
    memory_dir.mkdir()
    logs_dir.mkdir()
    persister = EngramPersister(
        memory_dir=memory_dir,
        logs_dir=logs_dir,
        project_key="lazy-harness",
        engram_bin="/nonexistent/engram-binary-xyz",
    )
    persister.persist_new_entries()

    assert not (logs_dir / "engram_persist_metrics.jsonl").exists()


def test_slow_save_event_emitted_above_threshold(tmp_path: Path) -> None:
    memory_dir = tmp_path / "memory"
    logs_dir = tmp_path / "logs"
    memory_dir.mkdir()
    logs_dir.mkdir()
    entries = [{"ts": "T1", "type": "decision", "summary": "slow one"}]
    _seed_jsonl(memory_dir, "decision", entries)

    # Real placeholder file so the .exists() guard passes
    engram_bin_path = tmp_path / "engram"
    engram_bin_path.write_text("")

    persister = EngramPersister(
        memory_dir=memory_dir,
        logs_dir=logs_dir,
        project_key="lazy-harness",
        engram_bin=str(engram_bin_path),
        slow_save_threshold_ms=10,  # injected low threshold
    )

    def slow_run(*args, **kwargs):
        time.sleep(0.05)  # 50ms > 10ms threshold
        return MagicMock(returncode=0, stdout="", stderr="")

    with patch(
        "lazy_harness.knowledge.engram_persist.subprocess.run",
        side_effect=slow_run,
    ):
        persister.persist_new_entries()

    metrics = (logs_dir / "engram_persist_metrics.jsonl").read_text().strip().splitlines()
    slow_lines = [
        json.loads(line) for line in metrics if json.loads(line).get("event") == "slow_save"
    ]
    assert len(slow_lines) == 1
    assert slow_lines[0]["type"] == "decision"
    assert slow_lines[0]["ms"] >= 10
    assert slow_lines[0]["title_prefix"].startswith("slow one")


def test_slow_save_event_not_emitted_below_threshold(tmp_path: Path) -> None:
    memory_dir = tmp_path / "memory"
    logs_dir = tmp_path / "logs"
    memory_dir.mkdir()
    logs_dir.mkdir()
    entries = [{"ts": "T1", "type": "decision", "summary": "fast one"}]
    _seed_jsonl(memory_dir, "decision", entries)

    engram_bin_path = tmp_path / "engram"
    engram_bin_path.write_text("")

    persister = EngramPersister(
        memory_dir=memory_dir,
        logs_dir=logs_dir,
        project_key="lazy-harness",
        engram_bin=str(engram_bin_path),
        slow_save_threshold_ms=10_000,  # very high threshold
    )

    with patch("lazy_harness.knowledge.engram_persist.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        persister.persist_new_entries()

    metrics = (logs_dir / "engram_persist_metrics.jsonl").read_text().strip().splitlines()
    slow_lines = [line for line in metrics if json.loads(line).get("event") == "slow_save"]
    assert slow_lines == []


def test_error_log_written_on_save_failure(tmp_path: Path) -> None:
    persister = _persister(tmp_path)
    entries = [{"ts": "T1", "type": "decision", "summary": "doomed"}]
    _seed_jsonl(persister.memory_dir, "decision", entries)

    with patch("lazy_harness.knowledge.engram_persist.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="database is locked")
        persister.persist_new_entries()

    log_path = persister.logs_dir / "engram_persist.log"
    content = log_path.read_text()
    assert "engram save returned 1" in content
    assert "database is locked" in content
    assert "decision" in content

"""Tests for `lh memory reconcile` schema-drift detection — ADR-040.

This covers detection 1 only (deterministic field-set grouping). Detection 2
(contradiction detection) is an LLM call and lives in `cli/memory_cmd.py`,
tested the same way `consolidate` is: a stubbed `run_inference`.
"""

from __future__ import annotations

import json
from pathlib import Path


def _write_jsonl(path: Path, records: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        for r in records:
            f.write(json.dumps(r) + "\n")


def test_missing_file_returns_none(tmp_path: Path) -> None:
    from lazy_harness.core.reconcile import detect_schema_drift

    report = detect_schema_drift(tmp_path / "decisions.jsonl")

    assert report is None


def test_no_drift_when_every_line_shares_the_same_fields(tmp_path: Path) -> None:
    from lazy_harness.core.reconcile import detect_schema_drift

    path = tmp_path / "decisions.jsonl"
    _write_jsonl(
        path,
        [
            {"ts": "2026-05-01", "type": "decision", "summary": "a"},
            {"ts": "2026-05-02", "type": "decision", "summary": "b"},
        ],
    )

    report = detect_schema_drift(path)

    assert report is not None
    assert report.has_drift is False
    assert report.minority_groups == []
    assert report.majority_fields == ("summary", "ts", "type")


def test_reports_minority_field_sets_ordered_by_count(tmp_path: Path) -> None:
    """Real `lazy-ansible/decisions.jsonl` shape: one old `date/decision/
    rationale/alternatives` line, six `alternatives/decision/rationale/ts`
    lines, and the rest on the current
    `alternatives/context/project/rationale/summary/tags/ts/type` schema."""
    from lazy_harness.core.reconcile import detect_schema_drift

    path = tmp_path / "decisions.jsonl"
    current = {
        "ts": "t",
        "type": "decision",
        "summary": "s",
        "context": "c",
        "alternatives": [],
        "rationale": "r",
        "project": "p",
        "tags": [],
    }
    oldest = {"date": "d", "decision": "x", "alternatives": [], "rationale": "r"}
    middle = {"ts": "t", "decision": "x", "alternatives": [], "rationale": "r"}
    _write_jsonl(path, [oldest, *([middle] * 6), *([current] * 704)])

    report = detect_schema_drift(path)

    assert report is not None
    assert report.has_drift is True
    assert report.total_lines == 711
    assert report.majority_fields == tuple(sorted(current.keys()))
    assert [g.count for g in report.minority_groups] == [6, 1]
    assert report.minority_groups[0].fields == tuple(sorted(middle.keys()))
    assert report.minority_groups[1].fields == tuple(sorted(oldest.keys()))
    # Line numbers are 1-indexed and point back at the source file.
    assert report.minority_groups[1].example_line_numbers == [1]


def test_skips_malformed_json_lines_without_crashing(tmp_path: Path) -> None:
    from lazy_harness.core.reconcile import detect_schema_drift

    path = tmp_path / "decisions.jsonl"
    path.write_text('{"ts": "t", "summary": "ok"}\nnot json at all\n\n')

    report = detect_schema_drift(path)

    assert report is not None
    assert report.total_lines == 2
    assert report.has_drift is False


def test_skips_non_dict_json_lines(tmp_path: Path) -> None:
    from lazy_harness.core.reconcile import detect_schema_drift

    path = tmp_path / "decisions.jsonl"
    path.write_text('{"ts": "t", "summary": "ok"}\n["a", "list", "not", "a", "record"]\n')

    report = detect_schema_drift(path)

    assert report is not None
    assert report.has_drift is False


def test_empty_file_has_no_drift_and_no_majority(tmp_path: Path) -> None:
    from lazy_harness.core.reconcile import detect_schema_drift

    path = tmp_path / "decisions.jsonl"
    path.write_text("")

    report = detect_schema_drift(path)

    assert report is not None
    assert report.total_lines == 0
    assert report.has_drift is False
    assert report.majority_fields == ()

"""`lh doctor`'s evaluator-contamination row and its `--json` record.

The collector is covered in tests/unit/knowledge/test_evaluator_contamination.py;
these pin what doctor does with it: a line per outcome, never a crash, never a
failing exit code (contamination degrades memory, it does not break the machine).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from lazy_harness.cli import doctor_cmd
from lazy_harness.cli.doctor_cmd import doctor
from lazy_harness.knowledge.evaluator_prompt import EVALUATOR_PROMPT_HEAD
from lazy_harness.knowledge.marker import write_marker

PROMPT = f"{EVALUATOR_PROMPT_HEAD} Analyze the conversation.\n"


@pytest.fixture(autouse=True)
def isolated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("COLUMNS", "300")
    (tmp_path / "config.toml").write_text('[harness]\nversion = "1"\n')
    monkeypatch.setenv("LH_CONFIG_DIR", str(tmp_path))


def _store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "store"
    write_marker(root)
    monkeypatch.setenv("LAZY_KNOWLEDGE_ROOT", str(root))
    return root


def _contaminate(root: Path, handoffs: int = 1, sessions: int = 1) -> None:
    for i in range(handoffs):
        d = root / "memory" / "h" / f"p{i}"
        d.mkdir(parents=True)
        (d / "handoff.md").write_text(f"# Handoff (slim)\n\n{PROMPT}")
    for i in range(sessions):
        d = root / "sessions" / "2026-10"
        d.mkdir(parents=True, exist_ok=True)
        (d / f"s{i}.md").write_text(f"---\nmessages: 5\n---\n\n## User\n\n{PROMPT}")


def test_clean_store_is_one_ok_line(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _store(tmp_path, monkeypatch)

    result = CliRunner().invoke(doctor)

    assert "Evaluator contamination" in result.output
    assert "none" in result.output.split("Evaluator contamination")[1].splitlines()[1]


def test_contaminated_store_warns_with_counts_and_examples_without_failing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _store(tmp_path, monkeypatch)
    _contaminate(root, handoffs=7, sessions=2)

    result = CliRunner().invoke(doctor)

    out = result.output
    assert "7 handoff.md" in out and "2 session note(s)" in out
    assert "p0/handoff.md" in out
    assert "p6/handoff.md" not in out  # examples are capped
    assert "Some checks failed" not in out
    assert result.exit_code == 0


def test_missing_store_says_it_was_not_checked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("LAZY_KNOWLEDGE_ROOT", str(tmp_path / "absent"))

    result = CliRunner().invoke(doctor)

    assert "Evaluator contamination" in result.output
    assert "not checked" in result.output


def test_a_collector_failure_is_a_line_not_a_crash(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _store(tmp_path, monkeypatch)

    def boom(*_a: object, **_k: object) -> None:
        raise RuntimeError("scan exploded")

    monkeypatch.setattr(doctor_cmd, "collect_evaluator_contamination", boom)

    result = CliRunner().invoke(doctor)

    assert "scan exploded" in result.output
    assert result.exit_code == 0


def test_json_carries_the_record(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = _store(tmp_path, monkeypatch)
    _contaminate(root, handoffs=2, sessions=1)

    result = CliRunner().invoke(doctor, ["--json"])

    rec = json.loads(result.output)["evaluator_contamination"]
    assert rec["checked"] is True
    assert rec["error"] == ""
    assert len(rec["handoffs"]) == 2
    assert len(rec["sessions"]) == 1


def test_json_collector_failure_is_an_error_field(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _store(tmp_path, monkeypatch)

    def boom(*_a: object, **_k: object) -> None:
        raise RuntimeError("scan exploded")

    monkeypatch.setattr(doctor_cmd, "collect_evaluator_contamination", boom)

    result = CliRunner().invoke(doctor, ["--json"])

    rec = json.loads(result.output)["evaluator_contamination"]
    assert "scan exploded" in rec["error"]

"""The collector behind `lh doctor`'s evaluator-contamination row."""

from __future__ import annotations

from pathlib import Path

from lazy_harness.knowledge.contamination import collect_evaluator_contamination
from lazy_harness.knowledge.evaluator_prompt import EVALUATOR_PROMPT_HEAD
from lazy_harness.knowledge.marker import write_marker

PROMPT = f"{EVALUATOR_PROMPT_HEAD} Analyze the conversation.\n\nProject: x\n" + "pad\n" * 5000


def _store(tmp_path: Path) -> Path:
    root = tmp_path / "store"
    write_marker(root)
    return root


def _session(root: Path, name: str, first_user: str) -> Path:
    path = root / "sessions" / "2026-10" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "---\ntype: claude-session\nmessages: 5\n---\n\n# Session\n\n---\n\n"
        f"## User\n\n{first_user}\n\n## Assistant\n\nok\n"
    )
    return path


def _handoff(root: Path, project: str, body: str) -> Path:
    path = root / "memory" / "github.com" / "o" / project / "handoff.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body)
    return path


def test_counts_contaminated_handoffs_and_sessions_and_ignores_clean_ones(tmp_path: Path) -> None:
    root = _store(tmp_path)
    bad_h = _handoff(root, "a", f"# Handoff (slim)\n\n## Last user prompt\n\n{PROMPT}")
    _handoff(root, "b", "# Handoff\n\n## Last user prompt\n\nfix the build\n")
    quoted = (
        f"# Handoff\n\n## Last user prompt\n\nthe string '{EVALUATOR_PROMPT_HEAD}' is in the code\n"
    )
    _handoff(root, "c", quoted)
    bad_s = _session(root, "2026-10-26-aaaa.md", PROMPT)
    _session(root, "2026-10-26-bbbb.md", "hello there")
    # A later user turn quoting the prompt is not a contaminated session.
    _session(root, "2026-10-26-cccc.md", f"hi\n\n## User\n\n{PROMPT}")

    result = collect_evaluator_contamination(root)

    assert result.handoffs == [bad_h]
    assert result.sessions == [bad_s]
    assert result.checked is True


def test_missing_store_is_not_checked_and_does_not_raise(tmp_path: Path) -> None:
    result = collect_evaluator_contamination(tmp_path / "nope")
    assert result.checked is False
    assert result.handoffs == [] and result.sessions == []
    assert collect_evaluator_contamination(None).checked is False


def test_unreadable_marker_degrades_to_not_checked(tmp_path: Path) -> None:
    root = tmp_path / "store"
    root.mkdir()
    (root / "knowledge.toml").write_text("not = [valid")
    assert collect_evaluator_contamination(root).checked is False

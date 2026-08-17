"""Tests for `lh status memory`."""

from __future__ import annotations

import json
from pathlib import Path

from lazy_harness.monitoring.views import memory as memory_view

from ._fixtures import ctx
from ._render import render_to_text


def _project(config_dir: Path, name: str) -> Path:
    memory_dir = config_dir / "projects" / name / "memory"
    memory_dir.mkdir(parents=True)
    return memory_dir


def test_memory_says_so_when_there_is_nothing_yet(tmp_path: Path) -> None:
    assert "No project memory yet" in render_to_text(memory_view.render(ctx(tmp_path)))


def test_memory_counts_decisions_and_failures(tmp_path: Path) -> None:
    memory_dir = _project(tmp_path, "-Users-me-repo")
    (memory_dir / "decisions.jsonl").write_text(
        "\n".join(
            json.dumps({"ts": "2026-08-17T10:00:00", "summary": f"choice {i}"}) for i in range(3)
        )
    )
    (memory_dir / "failures.jsonl").write_text(
        json.dumps({"ts": "2026-08-17T11:00:00", "error": "it broke"})
    )

    text = render_to_text(memory_view.render(ctx(tmp_path)))

    assert "3" in text and "1" in text
    assert "Recent decisions" in text
    assert "choice 2" in text
    assert "it broke" in text


def test_memory_reports_none_for_a_file_with_no_usable_entries(tmp_path: Path) -> None:
    """A JSONL of malformed lines is empty, not a crash."""
    memory_dir = _project(tmp_path, "-Users-me-repo")
    (memory_dir / "decisions.jsonl").write_text("not json\n{}\n")

    text = render_to_text(memory_view.render(ctx(tmp_path)))

    assert "Recent decisions" in text
    assert "none" in text

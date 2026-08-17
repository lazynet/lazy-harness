"""Tests for `lh status projects`."""

from __future__ import annotations

import json
from pathlib import Path

from lazy_harness.monitoring.views import projects as projects_view

from ._fixtures import ctx
from ._render import render_to_text


def test_projects_says_so_when_there_are_none(tmp_path: Path) -> None:
    assert "No projects yet" in render_to_text(projects_view.render(ctx(tmp_path)))


def test_projects_shows_the_readable_name_not_the_encoded_directory(tmp_path: Path) -> None:
    """The agent encodes a project path into one hyphenated directory name.
    The view shows the readable leaf, because the encoding is ambiguous for
    repos whose own name contains a hyphen."""
    (tmp_path / "projects" / "-Users-me-repos-thing").mkdir(parents=True)

    text = render_to_text(projects_view.render(ctx(tmp_path)))

    assert "thing" in text
    assert "-Users-me-repos-thing" not in text


def test_projects_counts_sessions_and_reads_the_branch(tmp_path: Path) -> None:
    pdir = tmp_path / "projects" / "-Users-me-repos-thing"
    pdir.mkdir(parents=True)
    (pdir / "a.jsonl").write_text(json.dumps({"gitBranch": "main"}))
    (pdir / "b.jsonl").write_text(json.dumps({"gitBranch": "feat/x"}))

    text = render_to_text(projects_view.render(ctx(tmp_path)))

    assert "2" in text
    assert "feat/x" in text or "main" in text


def test_projects_survives_a_session_file_that_is_not_json(tmp_path: Path) -> None:
    pdir = tmp_path / "projects" / "-Users-me-repos-thing"
    pdir.mkdir(parents=True)
    (pdir / "a.jsonl").write_text("half a line, truncated mid-write")

    text = render_to_text(projects_view.render(ctx(tmp_path)))

    assert "thing" in text

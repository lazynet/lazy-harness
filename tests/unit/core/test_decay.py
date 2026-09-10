"""Tests for `lh memory decay` — ADR-040.

Decay never deletes: it marks `status: superseded` on learnings whose
`origin_session` is older than a configurable horizon and whose `status` is
still `active`. Every fixture writes the exact frontmatter shape
`compound_loop.py` writes, so a parser tuned to a hand-simplified fixture
cannot pass here while failing on the real store.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

TODAY = date(2026, 9, 10)


def _write_learning(
    path: Path,
    *,
    title: str = "Some learning",
    origin_session: str = "2026-09-01",
    status: str = "active",
    tags: str = '["a", "b"]',
) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"""---
title: "{title}"
origin: some-repo
origin_session: {origin_session}
tags: {tags}
scope: universal
status: {status}
deprecated_by: null
deprecated_on: null
deprecated_reason: null
---

## Learning

The body of the learning.

## Context

Some context.
"""
    )
    return path


def test_find_decay_candidates_skips_recent_learnings(tmp_path: Path) -> None:
    from lazy_harness.core.decay import find_decay_candidates

    learnings = tmp_path / "learnings"
    _write_learning(learnings / "2026-09" / "recent.md", origin_session="2026-09-01")

    candidates = find_decay_candidates(learnings, horizon_days=90, today=TODAY)

    assert candidates == []


def test_find_decay_candidates_includes_old_active_learnings(tmp_path: Path) -> None:
    from lazy_harness.core.decay import find_decay_candidates

    learnings = tmp_path / "learnings"
    _write_learning(
        learnings / "2026-03" / "old.md",
        title="An old learning",
        origin_session="2026-03-01",
    )

    candidates = find_decay_candidates(learnings, horizon_days=90, today=TODAY)

    assert len(candidates) == 1
    c = candidates[0]
    assert c.path == learnings / "2026-03" / "old.md"
    assert c.title == "An old learning"
    assert c.origin_session == "2026-03-01"
    assert c.age_days == (TODAY - date(2026, 3, 1)).days


def test_find_decay_candidates_boundary_is_inclusive(tmp_path: Path) -> None:
    """Exactly `horizon_days` old counts as a candidate — 'no reference within
    the horizon' includes the horizon's own edge."""
    from lazy_harness.core.decay import find_decay_candidates

    learnings = tmp_path / "learnings"
    cutoff = date(2026, 9, 10).fromordinal(TODAY.toordinal() - 90)
    _write_learning(learnings / "2026-06" / "edge.md", origin_session=cutoff.isoformat())

    candidates = find_decay_candidates(learnings, horizon_days=90, today=TODAY)

    assert len(candidates) == 1
    assert candidates[0].age_days == 90


def test_find_decay_candidates_skips_already_superseded(tmp_path: Path) -> None:
    from lazy_harness.core.decay import find_decay_candidates

    learnings = tmp_path / "learnings"
    _write_learning(
        learnings / "2026-03" / "old.md",
        origin_session="2026-03-01",
        status="superseded",
    )

    candidates = find_decay_candidates(learnings, horizon_days=90, today=TODAY)

    assert candidates == []


def test_find_decay_candidates_skips_malformed_frontmatter(tmp_path: Path) -> None:
    from lazy_harness.core.decay import find_decay_candidates

    learnings = tmp_path / "learnings"
    learnings.mkdir(parents=True)
    (learnings / "broken.md").write_text("not frontmatter at all\njust text\n")

    candidates = find_decay_candidates(learnings, horizon_days=90, today=TODAY)

    assert candidates == []


def test_find_decay_candidates_skips_missing_origin_session(tmp_path: Path) -> None:
    from lazy_harness.core.decay import find_decay_candidates

    learnings = tmp_path / "learnings"
    path = learnings / "no-origin.md"
    path.parent.mkdir(parents=True)
    path.write_text(
        """---
title: "No origin session"
origin: some-repo
tags: []
scope: universal
status: active
deprecated_by: null
deprecated_on: null
deprecated_reason: null
---

## Learning

Body.
"""
    )

    candidates = find_decay_candidates(learnings, horizon_days=90, today=TODAY)

    assert candidates == []


def test_find_decay_candidates_missing_dir_returns_empty(tmp_path: Path) -> None:
    from lazy_harness.core.decay import find_decay_candidates

    candidates = find_decay_candidates(tmp_path / "nope", horizon_days=90, today=TODAY)

    assert candidates == []


def test_apply_decay_marks_status_and_deprecated_fields(tmp_path: Path) -> None:
    from lazy_harness.core.decay import apply_decay, find_decay_candidates

    learnings = tmp_path / "learnings"
    _write_learning(learnings / "2026-03" / "old.md", origin_session="2026-03-01")

    candidates = find_decay_candidates(learnings, horizon_days=90, today=TODAY)
    written = apply_decay(candidates, reason="no reference within 90 days", today=TODAY)

    assert written == [learnings / "2026-03" / "old.md"]
    text = (learnings / "2026-03" / "old.md").read_text()
    assert "status: superseded" in text
    assert "deprecated_by: lh memory decay" in text
    assert f"deprecated_on: {TODAY.isoformat()}" in text
    assert 'deprecated_reason: "no reference within 90 days"' in text
    # The body and every other frontmatter field are untouched.
    assert 'title: "Some learning"' in text
    assert "origin: some-repo" in text
    assert "## Learning" in text
    assert "The body of the learning." in text


def test_apply_decay_never_deletes_the_file(tmp_path: Path) -> None:
    """Docstring promise: decay marks, it never deletes."""
    from lazy_harness.core.decay import apply_decay, find_decay_candidates

    learnings = tmp_path / "learnings"
    _write_learning(learnings / "2026-03" / "old.md", origin_session="2026-03-01")

    before = sorted(learnings.rglob("*.md"))
    candidates = find_decay_candidates(learnings, horizon_days=90, today=TODAY)
    apply_decay(candidates, reason="x", today=TODAY)
    after = sorted(learnings.rglob("*.md"))

    assert before == after


def test_apply_decay_is_idempotent_on_second_run(tmp_path: Path) -> None:
    """Running decay twice does not re-mark an already-superseded learning —
    the second scan finds zero active candidates for it."""
    from lazy_harness.core.decay import apply_decay, find_decay_candidates

    learnings = tmp_path / "learnings"
    _write_learning(learnings / "2026-03" / "old.md", origin_session="2026-03-01")

    first = find_decay_candidates(learnings, horizon_days=90, today=TODAY)
    apply_decay(first, reason="x", today=TODAY)

    second = find_decay_candidates(learnings, horizon_days=90, today=TODAY)

    assert second == []

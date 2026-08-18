"""Tests for the knowledge store marker file."""

from __future__ import annotations

from pathlib import Path

import pytest


def _write(root: Path, body: str) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / "knowledge.toml").write_text(body, encoding="utf-8")


def test_read_marker_returns_declared_subdirs(tmp_path: Path) -> None:
    from lazy_harness.knowledge.marker import read_marker

    _write(
        tmp_path,
        '[knowledge]\nversion = 1\nsessions = "sessions"\nlearnings = "learnings"\n',
    )
    marker = read_marker(tmp_path)
    assert marker.sessions == "sessions"
    assert marker.learnings == "learnings"


def test_read_marker_missing_file_raises(tmp_path: Path) -> None:
    from lazy_harness.knowledge.marker import MarkerError, read_marker

    with pytest.raises(MarkerError, match="no knowledge.toml"):
        read_marker(tmp_path)


def test_read_marker_unknown_version_raises(tmp_path: Path) -> None:
    from lazy_harness.knowledge.marker import MarkerError, read_marker

    _write(
        tmp_path,
        '[knowledge]\nversion = 99\nsessions = "s"\nlearnings = "l"\n',
    )
    with pytest.raises(MarkerError, match="version 99"):
        read_marker(tmp_path)


def test_read_marker_missing_field_raises_not_empty_string(tmp_path: Path) -> None:
    from lazy_harness.knowledge.marker import MarkerError, read_marker

    _write(tmp_path, '[knowledge]\nversion = 1\nsessions = "sessions"\n')
    with pytest.raises(MarkerError, match="learnings"):
        read_marker(tmp_path)


def test_read_marker_rejects_absolute_subdir(tmp_path: Path) -> None:
    from lazy_harness.knowledge.marker import MarkerError, read_marker

    _write(
        tmp_path,
        '[knowledge]\nversion = 1\nsessions = "/etc"\nlearnings = "learnings"\n',
    )
    with pytest.raises(MarkerError, match="must be relative"):
        read_marker(tmp_path)


def test_read_marker_rejects_escaping_subdir(tmp_path: Path) -> None:
    from lazy_harness.knowledge.marker import MarkerError, read_marker

    _write(
        tmp_path,
        '[knowledge]\nversion = 1\nsessions = "../out"\nlearnings = "learnings"\n',
    )
    with pytest.raises(MarkerError, match="must be relative"):
        read_marker(tmp_path)


def test_write_marker_roundtrips(tmp_path: Path) -> None:
    from lazy_harness.knowledge.marker import read_marker, write_marker

    path = write_marker(tmp_path)
    assert path == tmp_path / "knowledge.toml"
    marker = read_marker(tmp_path)
    assert marker.sessions == "sessions"
    assert marker.learnings == "learnings"


def test_resolve_root_prefers_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from lazy_harness.knowledge.marker import resolve_root

    monkeypatch.setenv("LAZY_KNOWLEDGE_ROOT", str(tmp_path))
    assert resolve_root("~/somewhere/else") == tmp_path.resolve()


def test_resolve_root_falls_back_to_configured(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from lazy_harness.knowledge.marker import resolve_root

    monkeypatch.delenv("LAZY_KNOWLEDGE_ROOT", raising=False)
    assert resolve_root(str(tmp_path)) == tmp_path.resolve()


def test_resolve_root_default_when_nothing_set(monkeypatch: pytest.MonkeyPatch) -> None:
    from lazy_harness.core.paths import expand_path
    from lazy_harness.knowledge.marker import DEFAULT_ROOT, resolve_root

    monkeypatch.delenv("LAZY_KNOWLEDGE_ROOT", raising=False)
    assert resolve_root(None) == expand_path(DEFAULT_ROOT)


def test_a_marker_without_a_memory_field_still_loads(tmp_path: Path) -> None:
    """Distilled memory needs a home both machines can reach, and the knowledge
    store is the only directory the framework already synchronises between
    them. Added as an optional field rather than a version bump: an existing
    store's marker is version 1 and must keep loading, or every machine breaks
    at once on upgrade for a directory it does not use yet.
    """
    from lazy_harness.knowledge.marker import read_marker

    (tmp_path / "knowledge.toml").write_text(
        '[knowledge]\nversion   = 1\nsessions  = "sessions"\nlearnings = "learnings"\n'
    )

    marker = read_marker(tmp_path)

    assert marker.sessions == "sessions"
    assert marker.memory == "memory", "the default has to be usable, not empty"


def test_a_declared_memory_area_is_honoured(tmp_path: Path) -> None:
    from lazy_harness.knowledge.marker import read_marker

    (tmp_path / "knowledge.toml").write_text(
        '[knowledge]\nversion   = 1\nsessions  = "sessions"\n'
        'learnings = "learnings"\nmemory    = "distilled"\n'
    )

    assert read_marker(tmp_path).memory == "distilled"


def test_an_escaping_memory_area_is_refused(tmp_path: Path) -> None:
    """The same rule the other two areas already carry: a relative path, or a
    loud failure. An empty value would land files at the store root."""
    import pytest

    from lazy_harness.knowledge.marker import MarkerError, read_marker

    (tmp_path / "knowledge.toml").write_text(
        '[knowledge]\nversion   = 1\nsessions  = "sessions"\n'
        'learnings = "learnings"\nmemory    = "../outside"\n'
    )

    with pytest.raises(MarkerError, match="memory"):
        read_marker(tmp_path)


def test_a_fresh_marker_declares_the_memory_area(tmp_path: Path) -> None:
    from lazy_harness.knowledge.marker import read_marker, write_marker

    write_marker(tmp_path)

    assert read_marker(tmp_path).memory == "memory"

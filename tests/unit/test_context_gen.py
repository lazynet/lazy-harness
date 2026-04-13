"""Tests for QMD context-gen (stats regenerator)."""

from __future__ import annotations

from pathlib import Path


def _make_yaml(collections: dict[str, str]) -> str:
    """Build a minimal QMD index.yml with N collections. `collections` maps
    collection name → path string."""
    lines = ["collections:"]
    for name, path in collections.items():
        lines.append(f"  {name}:")
        lines.append(f"    path: {path}")
        lines.append('    context:')
        lines.append('      "": >')
        lines.append(f"        Descripción de {name}.")
    return "\n".join(lines) + "\n"


def _populate(path: Path, md_files: list[str], subdirs: list[str]) -> None:
    path.mkdir(parents=True, exist_ok=True)
    for sub in subdirs:
        (path / sub).mkdir(parents=True, exist_ok=True)
    for md in md_files:
        md_path = path / md
        md_path.parent.mkdir(parents=True, exist_ok=True)
        md_path.write_text("# test\n")


def test_scan_path_counts_and_subdirs(tmp_path: Path) -> None:
    from lazy_harness.knowledge.context_gen import _scan_path

    _populate(
        tmp_path,
        md_files=["a.md", "b.md", "sub/c.md"],
        subdirs=["sub", "other"],
    )
    (tmp_path / ".hidden").mkdir(exist_ok=True)

    subdirs, md_count = _scan_path(tmp_path)
    assert md_count == 3
    assert "sub" in subdirs
    assert "other" in subdirs
    # Hidden dirs excluded from the listing (but rglob still counts .md inside them)
    assert ".hidden" not in subdirs


def test_scan_path_skips_known_dirs(tmp_path: Path) -> None:
    from lazy_harness.knowledge.context_gen import _scan_path

    _populate(tmp_path, md_files=["a.md"], subdirs=["node_modules", "Templates", "real"])
    subdirs, _ = _scan_path(tmp_path)
    assert "real" in subdirs
    assert "node_modules" not in subdirs
    assert "Templates" not in subdirs


def test_scan_path_nonexistent(tmp_path: Path) -> None:
    from lazy_harness.knowledge.context_gen import _scan_path

    subdirs, md_count = _scan_path(tmp_path / "missing")
    assert subdirs == []
    assert md_count == 0


def test_generate_auto_part_format(tmp_path: Path) -> None:
    from lazy_harness.knowledge.context_gen import _generate_auto_part

    _populate(tmp_path, md_files=["a.md", "b.md"], subdirs=["docs", "scripts"])
    auto = _generate_auto_part(tmp_path)
    assert "2 archivos .md" in auto
    assert "Contiene: docs, scripts" in auto


def test_generate_auto_part_truncates_long_subdir_list(tmp_path: Path) -> None:
    from lazy_harness.knowledge.context_gen import MAX_SHOWN_DIRS, _generate_auto_part

    subdirs = [f"dir{i:02d}" for i in range(MAX_SHOWN_DIRS + 5)]
    _populate(tmp_path, md_files=["a.md"], subdirs=subdirs)
    auto = _generate_auto_part(tmp_path)
    assert "(+5 más)" in auto


def test_merge_context_replaces_auto_segment() -> None:
    from lazy_harness.knowledge.context_gen import DELIMITER, _merge_context

    existing = f"User prose. {DELIMITER} old stats go here"
    merged = _merge_context(existing, "new stats")
    assert merged == f"User prose. {DELIMITER} new stats"


def test_merge_context_appends_when_delimiter_missing() -> None:
    from lazy_harness.knowledge.context_gen import DELIMITER, _merge_context

    merged = _merge_context("Plain description", "fresh stats")
    assert merged == f"Plain description {DELIMITER} fresh stats"


def test_merge_context_empty_existing() -> None:
    from lazy_harness.knowledge.context_gen import DELIMITER, _merge_context

    merged = _merge_context("", "stats only")
    assert merged == f"{DELIMITER} stats only"


def test_regenerate_updates_existing_context(tmp_path: Path) -> None:
    from lazy_harness.knowledge.context_gen import DELIMITER, regenerate

    coll_path = tmp_path / "my-collection"
    _populate(coll_path, md_files=["a.md", "b.md", "c.md"], subdirs=["docs"])

    config = tmp_path / "index.yml"
    config.write_text(_make_yaml({"my-collection": str(coll_path)}))

    result = regenerate(config)

    assert not result.dry_run
    assert len(result.updated) == 1
    assert "my-collection" in result.updated[0]

    content = config.read_text()
    assert DELIMITER in content
    assert "3 archivos .md" in content
    assert "Contiene: docs" in content
    # User-authored prefix preserved
    assert "Descripción de my-collection." in content


def test_regenerate_dry_run_leaves_file_untouched(tmp_path: Path) -> None:
    from lazy_harness.knowledge.context_gen import regenerate

    coll_path = tmp_path / "coll"
    _populate(coll_path, md_files=["a.md"], subdirs=[])

    config = tmp_path / "index.yml"
    original = _make_yaml({"coll": str(coll_path)})
    config.write_text(original)

    result = regenerate(config, dry_run=True)

    assert result.dry_run
    assert len(result.updated) == 1
    assert config.read_text() == original


def test_regenerate_skips_missing_collection_path(tmp_path: Path) -> None:
    from lazy_harness.knowledge.context_gen import regenerate

    config = tmp_path / "index.yml"
    config.write_text(_make_yaml({"ghost": str(tmp_path / "does-not-exist")}))

    result = regenerate(config)
    assert result.updated == []
    assert len(result.skipped) == 1
    assert "ghost" in result.skipped[0]


def test_regenerate_missing_config_returns_empty(tmp_path: Path) -> None:
    from lazy_harness.knowledge.context_gen import regenerate

    result = regenerate(tmp_path / "nope.yml")
    assert result.updated == []
    assert result.skipped == []


def test_regenerate_is_idempotent(tmp_path: Path) -> None:
    """Running twice in a row must not accumulate stats or corrupt the file."""
    from lazy_harness.knowledge.context_gen import regenerate

    coll_path = tmp_path / "coll"
    _populate(coll_path, md_files=["a.md", "b.md"], subdirs=["x", "y"])

    config = tmp_path / "index.yml"
    config.write_text(_make_yaml({"coll": str(coll_path)}))

    regenerate(config)
    first_content = config.read_text()
    regenerate(config)
    second_content = config.read_text()

    assert first_content == second_content
    # Delimiter appears exactly once per collection
    assert first_content.count("<!-- auto -->") == 1


def test_regenerate_preserves_multiple_collections(tmp_path: Path) -> None:
    from lazy_harness.knowledge.context_gen import regenerate

    coll_a = tmp_path / "a"
    coll_b = tmp_path / "b"
    _populate(coll_a, md_files=["1.md"], subdirs=["sa"])
    _populate(coll_b, md_files=["1.md", "2.md"], subdirs=["sb"])

    config = tmp_path / "index.yml"
    config.write_text(_make_yaml({"a": str(coll_a), "b": str(coll_b)}))

    result = regenerate(config)
    assert len(result.updated) == 2
    content = config.read_text()
    assert "1 archivos .md" in content
    assert "2 archivos .md" in content
    assert "Contiene: sa" in content
    assert "Contiene: sb" in content

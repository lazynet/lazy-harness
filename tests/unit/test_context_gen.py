"""Tests for QMD context-gen (stats regenerator)."""

from __future__ import annotations

from pathlib import Path

import pytest


def _make_yaml(collections: dict[str, str]) -> str:
    """Build a minimal QMD index.yml with N collections. `collections` maps
    collection name → path string."""
    lines = ["collections:"]
    for name, path in collections.items():
        lines.append(f"  {name}:")
        lines.append(f"    path: {path}")
        lines.append("    context:")
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


def test_regenerate_updates_literal_scalar_context(tmp_path: Path) -> None:
    """Context blocks written with a literal scalar (`|`) must be updated in
    place, not duplicated. A hand-edited index.yml may use `|` instead of `>`;
    failing to recognize it appends a second `context:` key, which makes the
    YAML unparseable (duplicate map keys)."""
    from lazy_harness.knowledge.context_gen import DELIMITER, regenerate

    coll_path = tmp_path / "coll"
    _populate(coll_path, md_files=["a.md", "b.md", "c.md"], subdirs=["docs"])

    config = tmp_path / "index.yml"
    config.write_text(
        "collections:\n"
        "  coll:\n"
        f"    path: {coll_path}\n"
        "    context:\n"
        '      "": |\n'
        "        Descripción a mano.\n"
    )

    result = regenerate(config)

    assert len(result.updated) == 1
    content = config.read_text()
    # The existing block was updated in place — no second context: key added.
    assert content.count("context:") == 1
    assert content.count(DELIMITER) == 1
    assert "3 archivos .md" in content
    assert "Contiene: docs" in content
    assert "Descripción a mano." in content


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


# --- Regression: duplicate `context:` keys corrupt index.yml -----------------
#
# A scheduled run against a config whose context values were plain inline
# scalars appended a SECOND `context:` key to every collection instead of
# merging. YAML forbids duplicate map keys, so qmd refused to load the file at
# all and stayed down until it was repaired by hand.


def _assert_no_duplicate_keys(text: str) -> None:
    """Fail if any mapping in `text` carries the same key twice.

    `yaml.safe_load` is useless here: it accepts duplicates last-wins and
    silently discards the hand-written description, so the corrupt file parses
    clean. `yaml.compose` returns the node graph *before* duplicate resolution,
    so every pair survives to be counted -- and, being the real parser, it does
    not mistake a colon inside a block scalar body for a key.
    """
    import yaml

    def walk(node: object, path: str) -> None:
        if isinstance(node, yaml.MappingNode):
            keys = [k.value for k, _ in node.value]
            duplicates = sorted({k for k in keys if keys.count(k) > 1})
            assert not duplicates, f"duplicate keys {duplicates} in mapping at {path}"
            for k, v in node.value:
                walk(v, f"{path}.{k.value}")
        elif isinstance(node, yaml.SequenceNode):
            for item in node.value:
                walk(item, f"{path}[]")

    walk(yaml.compose(text), "root")


def _config_with_context_block(coll_path: Path, block: str) -> str:
    return f'collections:\n  coll:\n    path: {coll_path}\n    pattern: "**/*.md"\n{block}'


# Every shape a hand-edited index.yml may legitimately use for a context value.
CONTEXT_SHAPES = {
    "plain_inline": '    context:\n      "": Descripción a mano.\n',
    "double_quoted": '    context:\n      "": "Descripción a mano."\n',
    "single_quoted": "    context:\n      \"\": 'Descripción a mano.'\n",
    "folded": '    context:\n      "": >\n        Descripción a mano.\n',
    "literal": '    context:\n      "": |\n        Descripción a mano.\n',
}


@pytest.mark.parametrize("shape", sorted(CONTEXT_SHAPES))
def test_regenerate_merges_every_scalar_shape_in_place(tmp_path: Path, shape: str) -> None:
    """Merging must work whatever scalar style the existing value uses.

    Only `>` and `|` were recognised; a plain or quoted value fell through to
    the "no context here" branch, which appended a second key.
    """
    from lazy_harness.knowledge.context_gen import DELIMITER, regenerate

    coll_path = tmp_path / "coll"
    _populate(coll_path, md_files=["a.md", "b.md", "c.md"], subdirs=["docs"])

    config = tmp_path / "index.yml"
    config.write_text(_config_with_context_block(coll_path, CONTEXT_SHAPES[shape]))

    result = regenerate(config)
    content = config.read_text()

    _assert_no_duplicate_keys(content)
    assert result.skipped == []
    assert len(result.updated) == 1
    assert content.count("context:") == 1
    assert content.count(DELIMITER) == 1
    assert "Descripción a mano." in content, "hand-written prose must survive"
    assert "3 archivos .md" in content
    assert "Contiene: docs" in content


@pytest.mark.parametrize("shape", sorted(CONTEXT_SHAPES))
def test_regenerate_is_idempotent_for_every_scalar_shape(tmp_path: Path, shape: str) -> None:
    """Three runs must not accumulate text or stack `<!-- auto -->` markers."""
    from lazy_harness.knowledge.context_gen import DELIMITER, regenerate

    coll_path = tmp_path / "coll"
    _populate(coll_path, md_files=["a.md"], subdirs=["docs"])

    config = tmp_path / "index.yml"
    config.write_text(_config_with_context_block(coll_path, CONTEXT_SHAPES[shape]))

    regenerate(config)
    first = config.read_text()
    regenerate(config)
    regenerate(config)
    third = config.read_text()

    assert first == third
    _assert_no_duplicate_keys(third)
    assert third.count(DELIMITER) == 1
    assert third.count("Descripción a mano.") == 1


def test_regenerate_appends_auto_block_after_multiline_prose(tmp_path: Path) -> None:
    """A multi-line description keeps its shape and gets the auto block last.

    The old code rewrote only the first line of the value, wedging the stats
    between the author's first and second sentence.
    """
    from lazy_harness.knowledge.context_gen import DELIMITER, regenerate

    coll_path = tmp_path / "coll"
    _populate(coll_path, md_files=["a.md"], subdirs=["docs"])

    config = tmp_path / "index.yml"
    config.write_text(
        _config_with_context_block(
            coll_path,
            '    context:\n      "": |\n        Linea uno.\n        Linea dos.\n',
        )
    )

    regenerate(config)
    content = config.read_text()

    _assert_no_duplicate_keys(content)
    assert "Linea uno." in content
    assert "Linea dos." in content
    # The auto segment goes after ALL of the prose, never between its lines.
    assert content.index("Linea dos.") < content.index(DELIMITER)


def test_regenerate_adds_context_when_collection_has_none(tmp_path: Path) -> None:
    """The append path is still correct when there is genuinely no context key."""
    from lazy_harness.knowledge.context_gen import DELIMITER, regenerate

    coll_path = tmp_path / "coll"
    _populate(coll_path, md_files=["a.md"], subdirs=["docs"])

    config = tmp_path / "index.yml"
    config.write_text(_config_with_context_block(coll_path, ""))

    result = regenerate(config)
    content = config.read_text()

    _assert_no_duplicate_keys(content)
    assert len(result.updated) == 1
    assert content.count("context:") == 1
    assert DELIMITER in content


def test_regenerate_skips_context_shape_it_cannot_parse(tmp_path: Path) -> None:
    """An unrecognised context shape degrades to "leave it alone", not to a
    second key. Detection is heuristic and will always have blind spots; the
    fallback is what decides whether a blind spot is harmless or destroys the
    file. A flow mapping is one such shape."""
    from lazy_harness.knowledge.context_gen import regenerate

    coll_path = tmp_path / "coll"
    _populate(coll_path, md_files=["a.md"], subdirs=["docs"])

    config = tmp_path / "index.yml"
    original = _config_with_context_block(coll_path, '    context: {"": Texto flow.}\n')
    config.write_text(original)

    result = regenerate(config)

    assert config.read_text() == original, "unparseable context must be left untouched"
    _assert_no_duplicate_keys(config.read_text())
    assert result.updated == []
    assert len(result.skipped) == 1
    assert "coll" in result.skipped[0]


def test_regenerate_leaves_already_corrupt_collection_untouched(tmp_path: Path) -> None:
    """Fed the file the production run actually produced, the job must report
    the damage and change nothing -- not round-trip it and drop the hand-written
    descriptions on the floor."""
    from lazy_harness.knowledge.context_gen import regenerate

    coll_path = tmp_path / "projects"
    _populate(coll_path, md_files=["a.md"], subdirs=["PRJ-Dotfiles"])

    config = tmp_path / "index.yml"
    original = (
        "collections:\n"
        "  lazy-lazymind-projects:\n"
        f"    path: {coll_path}\n"
        '    pattern: "**/*.md"\n'
        "    context:\n"
        '      "": Proyectos activos con objetivos y entregables concretos.\n'
        "    context:\n"
        '      "": >\n'
        "        <!-- auto --> 21 archivos .md. Contiene: PRJ-Dotfiles.\n"
    )
    config.write_text(original)

    result = regenerate(config)

    assert config.read_text() == original
    assert result.updated == []
    assert len(result.skipped) == 1
    assert "lazy-lazymind-projects" in result.skipped[0]
    assert "duplicate" in result.skipped[0].lower()


def test_regenerate_skipping_one_collection_still_updates_the_others(tmp_path: Path) -> None:
    """One damaged collection must not stall the healthy ones."""
    from lazy_harness.knowledge.context_gen import regenerate

    bad_path = tmp_path / "bad"
    good_path = tmp_path / "good"
    _populate(bad_path, md_files=["a.md"], subdirs=[])
    _populate(good_path, md_files=["a.md", "b.md"], subdirs=["docs"])

    config = tmp_path / "index.yml"
    config.write_text(
        "collections:\n"
        "  bad:\n"
        f"    path: {bad_path}\n"
        "    context:\n"
        '      "": Uno.\n'
        "    context:\n"
        '      "": Dos.\n'
        "  good:\n"
        f"    path: {good_path}\n"
        "    context:\n"
        '      "": Descripción buena.\n'
    )

    result = regenerate(config)
    content = config.read_text()

    assert len(result.skipped) == 1
    assert "bad" in result.skipped[0]
    assert len(result.updated) == 1
    assert "good" in result.updated[0]
    assert "Descripción buena." in content
    assert "2 archivos .md" in content
    # The damaged block is preserved verbatim, still awaiting a human.
    assert "Uno." in content
    assert "Dos." in content


def test_regenerate_never_writes_duplicate_keys_for_any_shape(tmp_path: Path) -> None:
    """Whole-file guarantee: whatever the input shape, the output parses with
    unique keys everywhere."""
    from lazy_harness.knowledge.context_gen import regenerate

    config = tmp_path / "index.yml"
    lines = ["collections:"]
    for shape, block in sorted(CONTEXT_SHAPES.items()):
        coll_path = tmp_path / shape
        _populate(coll_path, md_files=["a.md"], subdirs=["docs"])
        lines.append(f"  {shape}:")
        lines.append(f"    path: {coll_path}")
        lines.append(block.rstrip("\n"))
    config.write_text("\n".join(lines) + "\n")

    regenerate(config)
    regenerate(config)

    _assert_no_duplicate_keys(config.read_text())

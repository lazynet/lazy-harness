"""Rewrite an old `[knowledge]` block into the store-root shape.

The old shape declared both *where* the knowledge lived and *how* it was laid
out. The layout now belongs to the store's own `knowledge.toml`, so the three
layout keys are deleted rather than translated — carrying them forward is what
let the `Learnings` / `learnings` case mismatch survive.

`[compound_loop].lazymind_dir` is deliberately untouched: it points at the
Obsidian vault, which the compound loop still reads for `1-Projects/`.
"""

from __future__ import annotations

from pathlib import Path

import tomlkit

from lazy_harness.core.config import atomic_write_text

LEGACY_KEYS = ("path",)
LEGACY_SUBDIR_TABLES = ("sessions", "learnings")
LEGACY_COMPOUND_LOOP_KEY = "learnings_subdir"


def migrate_knowledge_block(config_path: Path, *, new_root: str) -> None:
    """Rewrite `config_path` in place. Safe to run on an already-migrated file."""
    if not config_path.is_file():
        raise FileNotFoundError(config_path)

    # tomlkit rather than tomllib: this rewrites the live config, which is
    # hand-maintained, so the comments explaining each setting have to survive
    # the migration that touches three keys.
    raw = tomlkit.parse(config_path.read_text(encoding="utf-8"))

    knowledge = raw.get("knowledge")
    if isinstance(knowledge, dict):
        had_legacy = any(key in knowledge for key in LEGACY_KEYS)
        for key in LEGACY_KEYS:
            knowledge.pop(key, None)
        # An existing `root` is the user's, not ours to overwrite.
        if had_legacy or not knowledge.get("root"):
            knowledge["root"] = new_root
        for table in LEGACY_SUBDIR_TABLES:
            sub = knowledge.get(table)
            if isinstance(sub, dict):
                sub.pop("subdir", None)

    compound_loop = raw.get("compound_loop")
    if isinstance(compound_loop, dict):
        compound_loop.pop(LEGACY_COMPOUND_LOOP_KEY, None)

    atomic_write_text(config_path, tomlkit.dumps(raw))

"""Tests for `lh profile migrate` — root assets into segments (ADR-052).

The oracle for "whose is it" is the registry, never a typed list: an entry a
adapter names in `config_targets()` is that agent's, the assembled system docs
and their segments stay at the profile root where the assembler writes them,
and everything else is shared.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from lazy_harness.core.profile_migrate import (
    MigrateError,
    apply_migration,
    plan_migration,
)


def _tree(root: Path, spec: dict[str, object]) -> None:
    for name, value in spec.items():
        path = root / name
        if isinstance(value, dict):
            path.mkdir(parents=True, exist_ok=True)
            _tree(path, value)
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(str(value))


def _destinations(plan) -> dict[str, str]:
    return {move.name: move.segment for move in plan.moves}


def test_an_entry_an_adapter_names_goes_to_that_agents_segment(tmp_path: Path) -> None:
    profile = tmp_path / "lazy"
    _tree(
        profile,
        {"settings.json": "{}", "hooks.json": "{}", "config.toml": "", ".claude.json": "{}"},
    )

    plan = plan_migration(profile)

    assert _destinations(plan) == {
        "settings.json": "claude-code",
        ".claude.json": "claude-code",
        "hooks.json": "codex",
        "config.toml": "codex",
    }


def test_a_nested_config_target_claims_its_top_level_directory(tmp_path: Path) -> None:
    """Copilot's target is `hooks/lazy-harness.json`; the root entry is `hooks`."""
    profile = tmp_path / "lazy"
    _tree(profile, {"hooks": {"lazy-harness.json": "{}"}})

    plan = plan_migration(profile)

    assert _destinations(plan) == {"hooks": "copilot"}


def test_everything_else_goes_to_shared(tmp_path: Path) -> None:
    profile = tmp_path / "lazy"
    _tree(
        profile,
        {"skills": {"a.md": "a"}, "commands": {"c.md": "c"}, "docs": {"d.md": "d"}},
    )

    plan = plan_migration(profile)

    assert _destinations(plan) == {
        "skills": "shared",
        "commands": "shared",
        "docs": "shared",
    }


def test_the_assembled_docs_and_their_segments_stay_at_the_root(tmp_path: Path) -> None:
    """`sync_agent_md` reads segments at the root and writes the doc there.

    Moving either into a segment would leave the assembler writing to a path the
    deploy no longer links — the agreement decision 5 exists to keep.
    """
    profile = tmp_path / "lazy"
    _tree(
        profile,
        {
            "CLAUDE.md": "assembled",
            "AGENTS.md": "assembled",
            "head.md": "h",
            "tail.md": "t",
            "CLAUDE.head.md": "h",
            "CLAUDE.tail.md": "t",
        },
    )

    plan = plan_migration(profile)

    assert plan.moves == []
    assert {name for name, _ in plan.kept} == {
        "CLAUDE.md",
        "AGENTS.md",
        "head.md",
        "tail.md",
        "CLAUDE.head.md",
        "CLAUDE.tail.md",
    }


def test_existing_segment_directories_are_left_alone(tmp_path: Path) -> None:
    profile = tmp_path / "lazy"
    _tree(profile, {"shared": {"skills": {"a.md": "a"}}, "codex": {"hooks.json": "{}"}})

    plan = plan_migration(profile)

    assert plan.moves == []


def test_an_underscore_entry_is_never_moved(tmp_path: Path) -> None:
    """`_common/` is shared across profiles and belongs to no one segment."""
    profile = tmp_path / "lazy"
    _tree(profile, {"_common": {"common.md": "c"}, "_scratch": {"x": "x"}})

    plan = plan_migration(profile)

    assert plan.moves == []


def test_migration_is_idempotent(tmp_path: Path) -> None:
    profile = tmp_path / "lazy"
    _tree(profile, {"skills": {"a.md": "a"}, "settings.json": "{}"})

    apply_migration(plan_migration(profile))
    second = plan_migration(profile)

    assert second.moves == []
    assert (profile / "shared" / "skills" / "a.md").is_file()
    assert (profile / "claude-code" / "settings.json").is_file()


def test_apply_moves_the_entries_and_leaves_nothing_at_the_root(tmp_path: Path) -> None:
    profile = tmp_path / "lazy"
    _tree(profile, {"skills": {"a.md": "a"}, "CLAUDE.md": "doc"})

    apply_migration(plan_migration(profile))

    assert not (profile / "skills").exists()
    assert (profile / "shared" / "skills" / "a.md").read_text() == "a"
    assert (profile / "CLAUDE.md").is_file(), "the assembled doc must stay put"


def test_apply_refuses_when_a_move_would_overwrite_and_moves_nothing(tmp_path: Path) -> None:
    """Refused up front, not halfway: a partial migration is worse than none."""
    profile = tmp_path / "lazy"
    _tree(
        profile,
        {
            "skills": {"a.md": "root"},
            "commands": {"c.md": "root"},
            "shared": {"skills": {"a.md": "already there"}},
        },
    )

    with pytest.raises(MigrateError, match="skills"):
        apply_migration(plan_migration(profile))

    assert (profile / "skills" / "a.md").read_text() == "root"
    assert (profile / "commands").is_dir(), "an unrelated entry was moved before the refusal"
    assert not (profile / "shared" / "commands").exists()

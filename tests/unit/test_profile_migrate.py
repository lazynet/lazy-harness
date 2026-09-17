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


def _renames(plan) -> dict[str, str]:
    return {r.source.name: r.destination.name for r in plan.renames}


def test_migrate_renames_the_legacy_doc_segments_to_their_roles(tmp_path: Path) -> None:
    """ADR-043 shipped the role names with a read fallback; the rename itself
    is a migration, and this is the command that runs it."""
    profiles = tmp_path / "profiles"
    _tree(profiles, {"_common": {"CLAUDE.common.md": "shared"}})
    profile = profiles / "lazy"
    _tree(profile, {"CLAUDE.head.md": "id", "CLAUDE.tail.md": "ctx", "skills": {"a.md": "a"}})

    plan = plan_migration(profile)
    assert _renames(plan) == {
        "CLAUDE.head.md": "head.md",
        "CLAUDE.tail.md": "tail.md",
        "CLAUDE.common.md": "common.md",
    }

    apply_migration(plan)

    assert (profile / "head.md").read_text() == "id"
    assert (profile / "tail.md").read_text() == "ctx"
    assert (profiles / "_common" / "common.md").read_text() == "shared"
    assert not (profile / "CLAUDE.head.md").exists()
    assert not (profiles / "_common" / "CLAUDE.common.md").exists()


def test_a_profile_already_on_role_names_has_nothing_to_rename(tmp_path: Path) -> None:
    profiles = tmp_path / "profiles"
    _tree(profiles, {"_common": {"common.md": "shared"}})
    profile = profiles / "lazy"
    _tree(profile, {"head.md": "id", "tail.md": "ctx"})

    assert plan_migration(profile).renames == []


def test_the_shared_segment_stays_while_another_profile_still_reads_it(tmp_path: Path) -> None:
    """`_common/` is one directory for the whole tree. Renaming it out from
    under a profile that has not migrated turns that profile's next sync into
    a `SyncError` — the shared half waits for the last profile."""
    profiles = tmp_path / "profiles"
    _tree(profiles, {"_common": {"CLAUDE.common.md": "shared"}})
    _tree(profiles / "flex", {"CLAUDE.head.md": "id", "CLAUDE.tail.md": "ctx"})
    profile = profiles / "lazy"
    _tree(profile, {"CLAUDE.head.md": "id", "CLAUDE.tail.md": "ctx"})

    plan = plan_migration(profile)
    apply_migration(plan)

    assert _renames(plan) == {"CLAUDE.head.md": "head.md", "CLAUDE.tail.md": "tail.md"}
    assert (profiles / "_common" / "CLAUDE.common.md").is_file()
    assert ("_common/CLAUDE.common.md", "still read by profile 'flex'") in plan.kept


def test_the_shared_segment_is_renamed_once_the_last_profile_migrates(tmp_path: Path) -> None:
    profiles = tmp_path / "profiles"
    _tree(profiles, {"_common": {"CLAUDE.common.md": "shared"}})
    _tree(profiles / "flex", {"head.md": "id", "tail.md": "ctx"})
    profile = profiles / "lazy"
    _tree(profile, {"CLAUDE.head.md": "id", "CLAUDE.tail.md": "ctx"})

    apply_migration(plan_migration(profile))

    assert (profiles / "_common" / "common.md").is_file()


def test_a_legacy_segment_left_beside_its_role_named_replacement_is_named_not_renamed(
    tmp_path: Path,
) -> None:
    """Mid-migration a profile carries both, and the role-named file is the one
    the assembler reads. Renaming over it would destroy the live segment, so
    the leftover is reported for the user to delete."""
    profiles = tmp_path / "profiles"
    _tree(profiles, {"_common": {"common.md": "shared"}})
    profile = profiles / "lazy"
    _tree(profile, {"head.md": "new", "CLAUDE.head.md": "old", "tail.md": "ctx"})

    plan = plan_migration(profile)
    apply_migration(plan)

    assert "CLAUDE.head.md" not in _renames(plan)
    assert (profile / "head.md").read_text() == "new"
    assert ("CLAUDE.head.md", "leftover — head.md is already there") in plan.kept


def test_apply_refuses_when_two_legacy_heads_would_become_one(tmp_path: Path) -> None:
    """A tree carrying both stems has two files claiming one role. Silently
    letting the second win would delete a segment with nothing to say so."""
    profiles = tmp_path / "profiles"
    _tree(profiles, {"_common": {"CLAUDE.common.md": "shared"}})
    profile = profiles / "lazy"
    _tree(
        profile,
        {
            "CLAUDE.head.md": "claude",
            "CLAUDE.tail.md": "claude",
            "AGENTS.head.md": "codex",
            "AGENTS.tail.md": "codex",
        },
    )

    with pytest.raises(MigrateError, match="head.md"):
        apply_migration(plan_migration(profile))

    assert (profile / "CLAUDE.head.md").is_file(), "a refused migration renamed something"
    assert (profile / "AGENTS.head.md").is_file()

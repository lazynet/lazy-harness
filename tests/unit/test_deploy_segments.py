"""Tests for deploy.segments — which profile assets reach which agent.

The resolution is pure: a profile directory plus the agent that profile runs
in, answered as links and collisions, with nothing touching the filesystem of
a real config dir. `deploy_profiles` renders the answer; this decides it.
"""

from __future__ import annotations

from pathlib import Path

from lazy_harness.deploy.segments import SHARED_SEGMENT, resolve_segments

AGENTS = ("claude-code", "codex", "copilot")


def _build(root: Path, spec: dict[str, object]) -> None:
    """Materialise a nested dict as directories (dict) and files (str)."""
    for name, value in spec.items():
        path = root / name
        if isinstance(value, dict):
            path.mkdir(parents=True, exist_ok=True)
            _build(path, value)
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(str(value))


def _links(plan) -> dict[str, Path]:
    return {str(link.relative): link.source for link in plan.links}


def test_flat_profile_links_every_root_entry_whole(tmp_path: Path) -> None:
    """A profile with no segment dirs deploys exactly as it does today."""
    profile = tmp_path / "lazy"
    _build(profile, {"CLAUDE.md": "doc", "head.md": "h", "skills": {"a.md": "a"}})

    plan = resolve_segments(profile, "codex", agent_names=AGENTS)

    assert _links(plan) == {
        "CLAUDE.md": profile / "CLAUDE.md",
        "head.md": profile / "head.md",
        "skills": profile / "skills",
    }
    assert plan.collisions == []


def test_shared_only_profile_links_shared_entries_at_top_level(tmp_path: Path) -> None:
    profile = tmp_path / "lazy"
    _build(profile, {"CLAUDE.md": "doc", SHARED_SEGMENT: {"skills": {"a.md": "a"}}})

    plan = resolve_segments(profile, "codex", agent_names=AGENTS)

    assert _links(plan) == {
        "CLAUDE.md": profile / "CLAUDE.md",
        "skills": profile / SHARED_SEGMENT / "skills",
    }
    assert plan.collisions == []


def test_other_agents_segment_is_ignored_entirely(tmp_path: Path) -> None:
    profile = tmp_path / "lazy"
    _build(
        profile,
        {
            "codex": {"settings.json": "{}"},
            "claude-code": {"settings.json": "{}", "commands": {"c.md": "c"}},
        },
    )

    plan = resolve_segments(profile, "codex", agent_names=AGENTS)

    assert _links(plan) == {"settings.json": profile / "codex" / "settings.json"}


def test_directory_in_one_segment_only_is_linked_whole(tmp_path: Path) -> None:
    """Cheaper than walking, and the result is identical."""
    profile = tmp_path / "lazy"
    _build(profile, {SHARED_SEGMENT: {"docs": {"x.md": "x", "deep": {"y.md": "y"}}}})

    plan = resolve_segments(profile, "codex", agent_names=AGENTS)

    assert _links(plan) == {"docs": profile / SHARED_SEGMENT / "docs"}


def test_directory_in_two_segments_is_walked_and_the_agent_wins(tmp_path: Path) -> None:
    profile = tmp_path / "lazy"
    _build(
        profile,
        {
            SHARED_SEGMENT: {"skills": {"a.md": "shared-a", "dup.md": "shared-dup"}},
            "codex": {"skills": {"b.md": "codex-b", "dup.md": "codex-dup"}},
        },
    )

    plan = resolve_segments(profile, "codex", agent_names=AGENTS)

    assert _links(plan) == {
        "skills/a.md": profile / SHARED_SEGMENT / "skills" / "a.md",
        "skills/b.md": profile / "codex" / "skills" / "b.md",
        "skills/dup.md": profile / "codex" / "skills" / "dup.md",
    }
    assert [(str(c.relative), c.winner, c.shadowed) for c in plan.collisions] == [
        (
            "skills/dup.md",
            profile / "codex" / "skills" / "dup.md",
            profile / SHARED_SEGMENT / "skills" / "dup.md",
        )
    ]


def test_root_entry_is_shadowed_by_shared_on_a_half_migrated_tree(tmp_path: Path) -> None:
    """Root is the lowest-precedence segment, so a half-moved asset resolves."""
    profile = tmp_path / "lazy"
    _build(profile, {"notes.md": "root", SHARED_SEGMENT: {"notes.md": "shared"}})

    plan = resolve_segments(profile, "codex", agent_names=AGENTS)

    assert _links(plan) == {"notes.md": profile / SHARED_SEGMENT / "notes.md"}
    assert [(str(c.relative), c.shadowed) for c in plan.collisions] == [
        ("notes.md", profile / "notes.md")
    ]

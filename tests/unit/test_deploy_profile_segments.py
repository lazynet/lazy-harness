"""`deploy_profiles` renders the segment plan — per-agent assets, file links.

The resolution itself is tested in `test_deploy_segments.py`. What is tested
here is that the deployer *uses* it: that another agent's segment never reaches
the config dir, that a directory carried by two segments arrives merged rather
than replaced, and that a shadowed file is named in the output.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from lazy_harness.core.config import Config, ProfileEntry


def _codex_profile(home: Path) -> Config:
    cfg = Config()
    cfg.agent.type = "claude-code"
    cfg.profiles.default = "gate"
    cfg.profiles.items = {
        "gate": ProfileEntry(config_dir=str(home / "codex-home"), agent="codex"),
    }
    return cfg


def _seed(home: Path, spec: dict[str, object]) -> Path:
    from lazy_harness.core.paths import config_dir

    src = config_dir() / "profiles" / "gate"
    src.mkdir(parents=True)

    def build(root: Path, tree: dict[str, object]) -> None:
        for name, value in tree.items():
            path = root / name
            if isinstance(value, dict):
                path.mkdir(parents=True, exist_ok=True)
                build(path, value)
            else:
                path.write_text(str(value))

    build(src, spec)
    return src


def test_the_profiles_agent_segment_deploys_and_another_agents_does_not(
    home_dir: Path,
) -> None:
    from lazy_harness.deploy.engine import deploy_profiles

    _seed(
        home_dir,
        {
            "codex": {"AGENTS-extra.md": "codex"},
            "claude-code": {"settings.json": "{}"},
        },
    )

    deploy_profiles(_codex_profile(home_dir), only="gate")

    target = home_dir / "codex-home"
    assert (target / "AGENTS-extra.md").is_symlink()
    assert not (target / "settings.json").exists(), (
        "a Claude Code segment reached a Codex profile — this is the bug the "
        "segments exist to prevent"
    )


def test_a_directory_in_two_segments_arrives_merged_not_replaced(home_dir: Path) -> None:
    """`ensure_symlink` on whole dirs would leave only the second segment's files."""
    from lazy_harness.deploy.engine import deploy_profiles

    _seed(
        home_dir,
        {
            "shared": {"skills": {"from-shared.md": "s"}},
            "codex": {"skills": {"from-codex.md": "c"}},
        },
    )

    deploy_profiles(_codex_profile(home_dir), only="gate")

    skills = home_dir / "codex-home" / "skills"
    assert (skills / "from-shared.md").is_symlink()
    assert (skills / "from-codex.md").is_symlink()


def test_a_same_name_file_is_won_by_the_agent_and_the_collision_is_printed(
    home_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from lazy_harness.deploy.engine import deploy_profiles

    _seed(
        home_dir,
        {
            "shared": {"skills": {"dup.md": "from-shared"}},
            "codex": {"skills": {"dup.md": "from-codex"}},
        },
    )

    deploy_profiles(_codex_profile(home_dir), only="gate")

    link = home_dir / "codex-home" / "skills" / "dup.md"
    assert link.read_text() == "from-codex"

    out = capsys.readouterr().out
    assert "skills/dup.md" in out
    assert "codex/skills/dup.md" in out, f"winner not named in output:\n{out}"
    assert "shared/skills/dup.md" in out, f"shadowed source not named in output:\n{out}"


def test_a_directory_in_one_segment_only_is_still_a_single_link(home_dir: Path) -> None:
    """The cheap path stays cheap: one inode, not one per file."""
    from lazy_harness.deploy.engine import deploy_profiles

    _seed(home_dir, {"shared": {"docs": {"a.md": "a", "b.md": "b"}}})

    deploy_profiles(_codex_profile(home_dir), only="gate")

    docs = home_dir / "codex-home" / "docs"
    assert docs.is_symlink(), "a directory carried by one segment should link whole"


def test_a_flat_profile_deploys_exactly_as_before(home_dir: Path) -> None:
    """Nobody is required to migrate to keep a working profile."""
    from lazy_harness.deploy.engine import deploy_profiles

    _seed(home_dir, {"AGENTS.md": "doc", "commands": {"c.md": "c"}})

    deploy_profiles(_codex_profile(home_dir), only="gate")

    target = home_dir / "codex-home"
    assert (target / "AGENTS.md").is_symlink()
    assert (target / "commands").is_symlink()


def test_a_directory_previously_linked_whole_is_replaced_by_a_real_dir(
    home_dir: Path,
) -> None:
    """The deployer must never write through its own old link into the source.

    A profile deployed flat carries a *symlink* at `skills`. Once two segments
    carry that name, the links become per file — and creating `skills/a.md`
    through the surviving symlink would land the new link inside
    `profiles/gate/shared/skills/`, i.e. the deployer editing its own input.
    """
    from lazy_harness.deploy.engine import deploy_profiles

    cfg = _codex_profile(home_dir)
    src = _seed(home_dir, {"skills": {"old.md": "o"}})
    deploy_profiles(cfg, only="gate")
    assert (home_dir / "codex-home" / "skills").is_symlink()

    # The user migrates: the same name is now carried by two segments.
    (src / "skills").rename(src / "_staged")
    (src / "shared").mkdir()
    (src / "_staged").rename(src / "shared" / "skills")
    (src / "codex" / "skills").mkdir(parents=True)
    (src / "codex" / "skills" / "new.md").write_text("n")

    deploy_profiles(cfg, only="gate")

    assert sorted(p.name for p in (src / "shared" / "skills").iterdir()) == ["old.md"], (
        "deploy wrote a link into the profile source through a stale directory link"
    )
    skills = home_dir / "codex-home" / "skills"
    assert not skills.is_symlink()
    assert (skills / "old.md").is_symlink()
    assert (skills / "new.md").is_symlink()

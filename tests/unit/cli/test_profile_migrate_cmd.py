"""`lh profile migrate` — the plan, the dry run, and the refusals."""

from __future__ import annotations

from pathlib import Path

from click.testing import CliRunner

from lazy_harness.cli.profile_cmd import profile
from lazy_harness.core.paths import config_dir


def _flat_profile(name: str = "lazy") -> Path:
    src = config_dir() / "profiles" / name
    (src / "skills").mkdir(parents=True)
    (src / "skills" / "a.md").write_text("a")
    (src / "settings.json").write_text("{}")
    (src / "CLAUDE.md").write_text("assembled")
    return src


def test_dry_run_prints_the_plan_and_moves_nothing(home_dir: Path) -> None:
    src = _flat_profile()

    result = CliRunner().invoke(profile, ["migrate", "lazy", "--dry-run"])

    assert result.exit_code == 0, result.output
    assert "skills" in result.output
    assert "shared" in result.output
    assert "claude-code" in result.output
    assert (src / "skills").is_dir(), "a dry run moved a file"
    assert not (src / "shared").exists()


def test_migrate_moves_the_entries_and_reports_each(home_dir: Path) -> None:
    src = _flat_profile()

    result = CliRunner().invoke(profile, ["migrate", "lazy"])

    assert result.exit_code == 0, result.output
    assert (src / "shared" / "skills" / "a.md").read_text() == "a"
    assert (src / "claude-code" / "settings.json").is_file()
    assert (src / "CLAUDE.md").is_file()


def test_migrate_is_idempotent_and_says_so(home_dir: Path) -> None:
    _flat_profile()
    runner = CliRunner()
    runner.invoke(profile, ["migrate", "lazy"])

    result = runner.invoke(profile, ["migrate", "lazy"])

    assert result.exit_code == 0, result.output
    assert "nothing to move" in result.output.lower()


def test_migrate_refuses_an_unknown_profile(home_dir: Path) -> None:
    (config_dir() / "profiles").mkdir(parents=True)

    result = CliRunner().invoke(profile, ["migrate", "ghost"])

    assert result.exit_code != 0, "a typo must not exit 0 having done nothing"
    assert "ghost" in result.output


def test_migrate_refuses_to_overwrite_and_names_the_file(home_dir: Path) -> None:
    src = _flat_profile()
    (src / "shared" / "skills").mkdir(parents=True)
    (src / "shared" / "skills" / "a.md").write_text("already there")

    result = CliRunner().invoke(profile, ["migrate", "lazy"])

    assert result.exit_code != 0
    assert "skills" in result.output
    assert (src / "skills" / "a.md").read_text() == "a"
    assert not (src / "claude-code").exists(), "refusal must not leave a partial migration"


def _legacy_profile(name: str = "lazy") -> Path:
    src = config_dir() / "profiles" / name
    src.mkdir(parents=True)
    (src / "CLAUDE.head.md").write_text("id")
    (src / "CLAUDE.tail.md").write_text("ctx")
    common = config_dir() / "profiles" / "_common"
    common.mkdir(parents=True, exist_ok=True)
    (common / "CLAUDE.common.md").write_text("shared")
    return src


def test_dry_run_prints_one_line_per_segment_rename_and_renames_nothing(home_dir: Path) -> None:
    src = _legacy_profile()

    result = CliRunner().invoke(profile, ["migrate", "lazy", "--dry-run"])

    assert result.exit_code == 0, result.output
    for line in (
        "CLAUDE.head.md → head.md",
        "CLAUDE.tail.md → tail.md",
        "_common/CLAUDE.common.md → _common/common.md",
    ):
        assert line in result.output, f"missing plan line {line!r} in:\n{result.output}"
    assert (src / "CLAUDE.head.md").is_file(), "a dry run renamed a segment"
    assert not (src / "head.md").exists()


def test_migrate_renames_the_segments_and_is_then_idempotent(home_dir: Path) -> None:
    src = _legacy_profile()
    runner = CliRunner()

    first = runner.invoke(profile, ["migrate", "lazy"])
    second = runner.invoke(profile, ["migrate", "lazy"])

    assert first.exit_code == 0, first.output
    assert (src / "head.md").read_text() == "id"
    assert (config_dir() / "profiles" / "_common" / "common.md").read_text() == "shared"
    assert second.exit_code == 0, second.output
    assert "nothing to move" in second.output.lower()


def test_a_profile_with_only_segments_to_rename_is_not_reported_as_a_no_op(
    home_dir: Path,
) -> None:
    """`migrate` used to answer "already segmented" whenever no asset moved.

    A legacy tree has no assets and three segments to rename, so that line
    would send the user away from the one thing the command had to do.
    """
    _legacy_profile()

    result = CliRunner().invoke(profile, ["migrate", "lazy"])

    assert "nothing to move" not in result.output.lower(), result.output
    assert "Renamed 3" in result.output


def test_the_help_says_the_segments_are_renamed_rather_than_left_alone(home_dir: Path) -> None:
    """The help promised the segments "stay at the profile root". Half of that
    is still true — they stay at the root — but they no longer keep their
    names, and a user reading the old sentence would not run the command that
    closes ADR-043's migration window."""
    result = CliRunner().invoke(profile, ["migrate", "--help"])

    assert "rename" in result.output.lower(), result.output
    assert "head.md" in result.output

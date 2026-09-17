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

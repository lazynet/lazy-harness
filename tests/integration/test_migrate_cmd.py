from pathlib import Path

from click.testing import CliRunner

from lazy_harness.cli.main import cli


def test_migrate_without_dry_run_errors(home_dir: Path):
    runner = CliRunner()
    result = runner.invoke(cli, ["migrate"])
    assert result.exit_code != 0
    assert "dry-run" in result.output.lower()


def test_migrate_dry_run_succeeds(home_dir: Path):
    runner = CliRunner()
    result = runner.invoke(cli, ["migrate", "--dry-run"])
    assert result.exit_code == 0
    assert "Plan" in result.output or "No steps" in result.output


def test_migrate_dry_run_then_run(home_dir: Path):
    lazy = home_dir / ".claude-lazy"
    lazy.mkdir()
    (lazy / "settings.json").write_text("{}")

    runner = CliRunner()
    r1 = runner.invoke(cli, ["migrate", "--dry-run"])
    assert r1.exit_code == 0, r1.output

    r2 = runner.invoke(cli, ["migrate"])
    assert r2.exit_code == 0, r2.output
    assert (home_dir / ".config" / "lazy-harness" / "config.toml").is_file()

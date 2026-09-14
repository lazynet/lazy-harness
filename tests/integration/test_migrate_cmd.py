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


def test_migrate_writes_into_its_own_namespace(home_dir: Path):
    """Migration backups move under `backups/migrate/` so a deploy prune cannot
    reach them and `lh migrate --rollback` cannot replay a deploy's log."""
    lazy = home_dir / ".claude-lazy"
    lazy.mkdir()
    (lazy / "settings.json").write_text("{}")

    runner = CliRunner()
    assert runner.invoke(cli, ["migrate", "--dry-run"]).exit_code == 0
    assert runner.invoke(cli, ["migrate"]).exit_code == 0

    backups = home_dir / ".config" / "lazy-harness" / "backups"
    namespaced = [p for p in (backups / "migrate").iterdir() if p.is_dir()]
    assert len(namespaced) == 1
    assert (namespaced[0] / "rollback.json").is_file()
    assert [p for p in backups.iterdir() if p.is_dir()] == [backups / "migrate"]

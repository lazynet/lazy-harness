import json
from pathlib import Path

from click.testing import CliRunner

from lazy_harness.cli.main import cli


def _minimal_config(home: Path) -> Path:
    cfg = home / ".config" / "lazy-harness" / "config.toml"
    cfg.parent.mkdir(parents=True)
    cfg.write_text(
        '[harness]\nversion = "1"\n'
        '[agent]\ntype = "claude-code"\n'
        '[profiles]\ndefault = "personal"\n'
        '[profiles.personal]\nconfig_dir = "~/.claude-personal"\n'
        '[knowledge]\npath = ""\n'
    )
    return cfg


def test_selftest_runs_and_reports(home_dir: Path):
    _minimal_config(home_dir)
    runner = CliRunner()
    result = runner.invoke(cli, ["selftest"])
    # May have failures (no profile dir exists, etc.) but should not crash
    assert "Summary" in result.output


def test_selftest_json_output(home_dir: Path):
    _minimal_config(home_dir)
    runner = CliRunner()
    result = runner.invoke(cli, ["selftest", "--json"])
    data = json.loads(result.output)
    assert "results" in data
    assert isinstance(data["results"], list)

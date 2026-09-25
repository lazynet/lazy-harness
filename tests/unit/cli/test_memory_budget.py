import json
from pathlib import Path

from click.testing import CliRunner

from lazy_harness.cli.memory_cmd import memory


def test_budget_explicit_profile_and_cwd_and_default_smoke(tmp_path: Path, monkeypatch) -> None:
    profile = tmp_path / "profile"
    profile.mkdir()
    (profile / "AGENTS.md").write_text("global\n")
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "AGENTS.md").write_text("repo\n")
    (tmp_path / "config.toml").write_text(
        '[harness]\nversion = "1"\n\n[agent]\ntype = "codex"\n\n'
        '[profiles]\ndefault = "test"\n\n[profiles.test]\n'
        f'config_dir = "{profile}"\n'
    )
    monkeypatch.setenv("LH_CONFIG_DIR", str(tmp_path))
    monkeypatch.chdir(repo)

    explicit = CliRunner().invoke(
        memory, ["budget", "--profile", "test", "--cwd", str(repo), "--json"]
    )
    smoke = CliRunner().invoke(memory, ["budget", "--json"])

    assert explicit.exit_code == 0, explicit.output
    assert smoke.exit_code == 0, smoke.output
    assert json.loads(explicit.output) == json.loads(smoke.output)
    assert json.loads(smoke.output)["total_bytes"] == len(b"global\nrepo\n")

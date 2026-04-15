from pathlib import Path

from click.testing import CliRunner

from lazy_harness.cli.doctor_cmd import doctor


def test_doctor_shows_network_egress_section(tmp_path: Path, monkeypatch) -> None:
    cfg_path = tmp_path / "config.toml"
    cfg_path.write_text(
        '[harness]\nversion = "1"\n'
        "[metrics]\n"
        'sinks = ["sqlite_local", "http_remote"]\n'
        "[metrics.sink_options.http_remote]\n"
        'url = "https://metrics.flex.internal/ingest"\n'
    )
    monkeypatch.setenv("LH_CONFIG_DIR", str(tmp_path))

    runner = CliRunner()
    result = runner.invoke(doctor)
    assert "network egress" in result.output.lower()
    assert "metrics.flex.internal" in result.output


def test_doctor_shows_none_when_local_only(tmp_path: Path, monkeypatch) -> None:
    cfg_path = tmp_path / "config.toml"
    cfg_path.write_text('[harness]\nversion = "1"\n')
    monkeypatch.setenv("LH_CONFIG_DIR", str(tmp_path))

    runner = CliRunner()
    result = runner.invoke(doctor)
    assert "network egress" in result.output.lower()
    assert "local-only" in result.output.lower() or "no remote" in result.output.lower()

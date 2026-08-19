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


def test_doctor_reports_configured_but_inactive_naming_the_variable(
    tmp_path: Path, monkeypatch
) -> None:
    cfg_path = tmp_path / "config.toml"
    cfg_path.write_text(
        '[harness]\nversion = "1"\n'
        "[metrics]\n"
        'sinks = ["sqlite_local", "http_remote"]\n'
        "[metrics.sink_options.http_remote]\n"
        'url_env = "LH_METRICS_URL"\n'
    )
    monkeypatch.setenv("LH_CONFIG_DIR", str(tmp_path))
    monkeypatch.delenv("LH_METRICS_URL", raising=False)

    runner = CliRunner()
    result = runner.invoke(doctor)
    assert "http_remote" in result.output
    assert "inactive" in result.output.lower()
    assert "LH_METRICS_URL" in result.output


def test_doctor_reports_an_env_activated_sink_without_printing_the_token(
    tmp_path: Path, monkeypatch
) -> None:
    cfg_path = tmp_path / "config.toml"
    cfg_path.write_text(
        '[harness]\nversion = "1"\n'
        "[metrics]\n"
        'sinks = ["sqlite_local", "http_remote"]\n'
        "[metrics.sink_options.http_remote]\n"
        'url_env = "LH_METRICS_URL"\n'
    )
    monkeypatch.setenv("LH_CONFIG_DIR", str(tmp_path))
    monkeypatch.setenv("LH_METRICS_URL", "https://metrics.invalid/ingest/s3cr3t-token")

    runner = CliRunner()
    result = runner.invoke(doctor)
    assert "metrics.invalid" in result.output
    assert "LH_METRICS_URL" in result.output
    assert "s3cr3t-token" not in result.output


def test_doctor_flags_a_sink_that_names_no_endpoint_at_all(tmp_path: Path, monkeypatch) -> None:
    cfg_path = tmp_path / "config.toml"
    cfg_path.write_text(
        '[harness]\nversion = "1"\n'
        "[metrics]\n"
        'sinks = ["sqlite_local", "http_remote"]\n'
        "[metrics.sink_options.http_remote]\n"
        "timeout_seconds = 5\n"
    )
    monkeypatch.setenv("LH_CONFIG_DIR", str(tmp_path))

    runner = CliRunner()
    result = runner.invoke(doctor)
    assert "misconfigured" in result.output.lower()
    assert "url_env" in result.output

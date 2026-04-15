"""Test: `lh metrics ingest` surfaces config validation errors for unnamed sinks."""

from pathlib import Path

from click.testing import CliRunner

from lazy_harness.cli.metrics_cmd import metrics


def test_ingest_errors_on_unnamed_config_block(tmp_path: Path, monkeypatch) -> None:
    """Sink named in [metrics].sinks but no [metrics.sink_options.X] block → error."""
    cfg_path = tmp_path / "config.toml"
    cfg_path.write_text(
        '[harness]\nversion = "1"\n'
        "[monitoring]\nenabled = true\n"
        "[metrics]\n"
        'sinks = ["sqlite_local", "http_remote"]\n'
        # Missing [metrics.sink_options.http_remote] → should error.
    )
    monkeypatch.setenv("LH_CONFIG_DIR", str(tmp_path))

    runner = CliRunner()
    result = runner.invoke(metrics, ["ingest"])
    assert result.exit_code != 0
    assert "http_remote" in result.output

"""Test: `lh metrics ingest` surfaces config validation errors for unnamed sinks."""

import json
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


def test_ingest_prints_the_error_count_without_verbose(tmp_path: Path, monkeypatch) -> None:
    """A per-file error must be visible on an ordinary run, not only under -v.

    A fail-soft ingest that silently swallowed every per-file error into a
    list nobody sees without `--verbose` would look identical to a clean run.
    """
    from lazy_harness.agents.claude_code import ClaudeCodeAdapter

    profile_dir = tmp_path / "claude"
    proj = profile_dir / "projects" / "-Users-foo-repos-demo"
    proj.mkdir(parents=True)
    (proj / "sess.jsonl").write_text(
        json.dumps(
            {
                "type": "assistant",
                "message": {
                    "id": "m1",
                    "model": "claude-sonnet-4-5",
                    "usage": {"input_tokens": 100, "output_tokens": 50},
                },
                "timestamp": "2026-09-16T10:00:00Z",
            }
        )
        + "\n"
    )
    (proj / "broken.jsonl").write_text("{}\n")

    original_read = ClaudeCodeAdapter.read

    def _flaky_read(self, path):
        if path.name == "broken.jsonl":
            raise ValueError("boom")
        yield from original_read(self, path)

    monkeypatch.setattr(ClaudeCodeAdapter, "read", _flaky_read)

    db_path = tmp_path / "m.db"
    cfg_path = tmp_path / "config.toml"
    cfg_path.write_text(
        '[harness]\nversion = "1"\n'
        "[monitoring]\nenabled = true\n"
        f'db = "{db_path.as_posix()}"\n'
        "[profiles]\n"
        'default = "personal"\n'
        "[profiles.personal]\n"
        f'config_dir = "{profile_dir.as_posix()}"\n'
        "roots = []\n"
    )
    monkeypatch.setenv("LH_CONFIG_DIR", str(tmp_path))

    runner = CliRunner()
    result = runner.invoke(metrics, ["ingest"])
    assert result.exit_code == 0, result.output
    assert "errors 1" in result.output
    assert "broken.jsonl" not in result.output, "full paths stay behind --verbose"

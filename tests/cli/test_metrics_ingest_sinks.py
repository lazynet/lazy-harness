"""Integration test: `lh metrics ingest` routes events to http_remote."""

from pathlib import Path

from click.testing import CliRunner
from pytest_httpserver import HTTPServer

from lazy_harness.cli.metrics_cmd import metrics


def _write_fake_session(dir_path: Path) -> None:
    proj = dir_path / "projects" / "-Users-martin-repos-lazy-lazy-harness"
    proj.mkdir(parents=True, exist_ok=True)
    (proj / "sess.jsonl").write_text(
        '{"type":"assistant","message":{"id":"m1","model":"claude-sonnet-4-5",'
        '"usage":{"input_tokens":100,"output_tokens":50,'
        '"cache_read_input_tokens":0,"cache_creation_input_tokens":0}},'
        '"timestamp":"2026-04-14T10:00:00Z"}\n'
    )


def test_metrics_ingest_posts_to_remote(
    tmp_path: Path, monkeypatch, httpserver: HTTPServer
) -> None:
    profile_dir = tmp_path / "claude"
    _write_fake_session(profile_dir)

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
        "[metrics]\n"
        'sinks = ["sqlite_local", "http_remote"]\n'
        'user_id = "martin"\n'
        "[metrics.sink_options.http_remote]\n"
        f'url = "{httpserver.url_for("/ingest")}"\n'
    )
    monkeypatch.setenv("LH_CONFIG_DIR", str(tmp_path))

    httpserver.expect_request("/ingest", method="POST").respond_with_json({"ok": True})

    runner = CliRunner()
    result = runner.invoke(metrics, ["ingest"])
    assert result.exit_code == 0, result.output
    # The first `ingest` enqueues; a subsequent drain pushes. For this test
    # we expect ingest to also trigger an opportunistic drain so the backend
    # has already been hit once.
    assert len(httpserver.log) >= 1

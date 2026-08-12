"""`lh metrics ingest` must surface models it could not price.

`IngestReport.unknown_models` was populated and tested but never rendered, so a
model missing from the pricing table landed in the DB at cost 0.0 with no
signal anywhere — indistinguishable from a genuinely free session.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from click.testing import CliRunner

from lazy_harness.cli.metrics_cmd import metrics


def _setup(tmp_path: Path, model: str) -> None:
    profile_dir = tmp_path / "claude"
    proj = profile_dir / "projects" / "-Users-x-repos-demo"
    proj.mkdir(parents=True, exist_ok=True)
    (proj / "sess.jsonl").write_text(
        '{"type":"assistant","message":{"id":"m1","model":"' + model + '",'
        '"usage":{"input_tokens":100,"output_tokens":50,'
        '"cache_read_input_tokens":0,"cache_creation_input_tokens":0}},'
        '"timestamp":"2026-04-14T10:00:00Z"}\n'
    )
    (tmp_path / "config.toml").write_text(
        '[harness]\nversion = "1"\n'
        "[monitoring]\nenabled = true\n"
        f'db = "{(tmp_path / "m.db").as_posix()}"\n'
        "[profiles]\n"
        'default = "personal"\n'
        "[profiles.personal]\n"
        f'config_dir = "{profile_dir.as_posix()}"\n'
        "roots = []\n"
        "[metrics]\n"
        'sinks = ["sqlite_local"]\n'
    )


def test_ingest_warns_about_an_unpriced_model(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _setup(tmp_path, "claude-future-model-99")
    monkeypatch.setenv("LH_CONFIG_DIR", str(tmp_path))

    result = CliRunner().invoke(metrics, ["ingest"])

    assert result.exit_code == 0, result.output
    assert "claude-future-model-99" in result.output
    assert "priced at $0" in result.output


def test_ingest_warns_without_the_verbose_flag(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The warning is about lost money — it must not hide behind -v."""
    _setup(tmp_path, "claude-future-model-99")
    monkeypatch.setenv("LH_CONFIG_DIR", str(tmp_path))

    result = CliRunner().invoke(metrics, ["ingest"])

    assert "claude-future-model-99" in result.output


def test_ingest_stays_quiet_when_every_model_is_priced(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _setup(tmp_path, "claude-opus-5")
    monkeypatch.setenv("LH_CONFIG_DIR", str(tmp_path))

    result = CliRunner().invoke(metrics, ["ingest"])

    assert result.exit_code == 0, result.output
    assert "priced at $0" not in result.output


def test_ingest_stays_quiet_about_the_synthetic_placeholder(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Every real session tree contains `<synthetic>` rows.

    Warning about them would fire on every single ingest, which is how a
    warning stops being read.
    """
    _setup(tmp_path, "<synthetic>")
    monkeypatch.setenv("LH_CONFIG_DIR", str(tmp_path))

    result = CliRunner().invoke(metrics, ["ingest"])

    assert result.exit_code == 0, result.output
    assert "priced at $0" not in result.output

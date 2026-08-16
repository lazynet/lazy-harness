"""The selftest command must actually run the checks it ships.

A check registered nowhere passes its own unit tests and never executes —
the same failure mode as a hook implemented but never wired into config.
"""

from __future__ import annotations

import json
from pathlib import Path

from click.testing import CliRunner


def _run_selftest(tmp_path: Path, monkeypatch) -> dict:
    (tmp_path / "config.toml").write_text(
        '[harness]\nversion = "1"\n\n[agent]\ntype = "claude-code"\n\n'
        '[monitoring]\nenabled = true\ndb = "{}"\n\n'.format(tmp_path / "metrics.db")
        + '[profiles]\ndefault = "p"\n\n[profiles.p]\nconfig_dir = "{}"\nroots = ["~"]\n'.format(
            tmp_path / "agent"
        )
    )
    monkeypatch.setenv("LH_CONFIG_DIR", str(tmp_path))

    from lazy_harness.cli.main import cli

    result = CliRunner().invoke(cli, ["selftest", "--json"])
    return json.loads(result.stdout)


def test_selftest_runs_the_loop_events_check(tmp_path: Path, monkeypatch) -> None:
    report = _run_selftest(tmp_path, monkeypatch)

    groups = {r["group"] for r in report["results"]}
    assert "loop-events" in groups, sorted(groups)


def test_selftest_reports_loop_event_attribution_by_name(tmp_path: Path, monkeypatch) -> None:
    """The report names each attribution dimension, so a regression says which."""
    report = _run_selftest(tmp_path, monkeypatch)

    names = {r["name"] for r in report["results"] if r["group"] == "loop-events"}
    assert {
        "project-from-subdirectory",
        "project-from-worktree",
        "session-closed-project",
        "profile-recorded",
    } <= names, sorted(names)

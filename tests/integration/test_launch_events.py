"""What the `launches` table counts, exercised through the real launchers.

The unit is a launch **actually started**. `resolve_launch` is reached before
either caller honours `--dry-run`, and `lh exec` reaches it before rejecting an
empty prompt, so a counter there would be fed by rehearsals and by runs that
never happened. At a five-event threshold that is not a rounding error, it is
most of the signal — which is why every one of these tests asserts on the
absence of a row as much as on its presence.
"""

from __future__ import annotations

import json
import sys
import textwrap
from pathlib import Path

import pytest
from click.testing import CliRunner

from lazy_harness.cli.main import cli
from lazy_harness.monitoring.db import MetricsDB
from tests.conftest import timeout_when_agent_is_ready

# Writes nothing and exits clean: these tests care about the row, not the run.
QUIET_AGENT = """
    import json, sys
    sys.stdin.read()
    print(json.dumps({"is_error": False, "result": "ok", "session_id": "sid"}))
"""

# Hangs until `lh exec` kills it, so the row has to predate the spawn to exist.
HANGING_AGENT = """
    import os, sys, time
    sys.stdin.read()
    open(os.environ["READYFILE"] + ".partial", "w").close()
    os.replace(os.environ["READYFILE"] + ".partial", os.environ["READYFILE"])
    time.sleep(120)
"""


@pytest.fixture
def harness(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A one-profile harness whose metrics DB path this test knows."""
    lh_config = tmp_path / "lh"
    lh_config.mkdir()
    profile_dir = tmp_path / "cfg-personal"
    (lh_config / "config.toml").write_text(
        '[harness]\nversion = "1"\n\n'
        '[agent]\ntype = "claude-code"\n\n'
        '[profiles]\ndefault = "personal"\n\n'
        f'[profiles.personal]\nconfig_dir = "{profile_dir}"\nroots = []\n'
    )
    monkeypatch.setenv("LH_CONFIG_DIR", str(lh_config))
    monkeypatch.setenv("LH_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("LH_DATA_DIR", str(tmp_path / "data"))
    return tmp_path / "data" / "metrics.db"


def _counts(db_path: Path) -> dict[tuple[str, str, str], int]:
    if not db_path.exists():
        return {}
    db = MetricsDB(db_path)
    try:
        return db.launch_counts()
    finally:
        db.close()


def _write_agent(body: str) -> Path:
    versions = Path.home() / ".local" / "share" / "claude" / "versions"
    versions.mkdir(parents=True, exist_ok=True)
    binary = versions / "0.0.1-fake"
    binary.write_text(f"#!{sys.executable}\n{textwrap.dedent(body)}")
    binary.chmod(0o755)
    return binary


def _stub_binary(monkeypatch: pytest.MonkeyPatch) -> None:
    from lazy_harness.agents.claude_code import ClaudeCodeAdapter

    monkeypatch.setattr(
        ClaudeCodeAdapter, "resolve_binary", lambda self: Path("/usr/local/bin/claude")
    )


def test_lh_run_records_the_launch_before_it_execs(
    harness: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`os.execvpe` replaces the process image — anything after it is dead
    code, so the row has to already be on disk when it is reached."""
    from lazy_harness.cli import run_cmd

    _stub_binary(monkeypatch)
    seen_at_exec: dict[str, object] = {}

    def fake_execvpe(file: str, args: list[str], env: dict) -> None:
        seen_at_exec["counts"] = _counts(harness)

    monkeypatch.setattr(run_cmd.os, "execvpe", fake_execvpe)

    result = CliRunner().invoke(cli, ["run"])

    assert result.exit_code == 0
    assert seen_at_exec["counts"] == {("personal", "claude-code", "run"): 1}


def test_lh_run_records_nothing_on_a_dry_run(
    harness: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _stub_binary(monkeypatch)

    result = CliRunner().invoke(cli, ["run", "--dry-run"])

    assert result.exit_code == 0
    assert _counts(harness) == {}


def test_lh_run_records_nothing_when_the_launch_cannot_be_resolved(
    harness: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A `LaunchError` is a launch that never happened."""
    from lazy_harness.agents.claude_code import ClaudeCodeAdapter

    monkeypatch.setattr(ClaudeCodeAdapter, "resolve_binary", lambda self: None)

    result = CliRunner().invoke(cli, ["run"])

    assert result.exit_code == 1
    assert _counts(harness) == {}


def test_lh_exec_records_the_launch(harness: Path) -> None:
    from lazy_harness.cli.exec_cmd import exec_cmd

    _write_agent(QUIET_AGENT)

    result = CliRunner().invoke(exec_cmd, [], input="hello")

    assert result.exit_code == 0
    assert _counts(harness) == {("personal", "claude-code", "exec"): 1}


def test_lh_exec_records_nothing_on_a_dry_run(harness: Path) -> None:
    from lazy_harness.cli.exec_cmd import exec_cmd

    _write_agent(QUIET_AGENT)

    result = CliRunner().invoke(exec_cmd, ["--dry-run"], input="hello")

    assert result.exit_code == 0
    assert json.loads(result.stdout)["dry_run"] is True
    assert _counts(harness) == {}


def test_lh_exec_records_nothing_when_the_prompt_is_empty(harness: Path) -> None:
    """The rejection sits after `resolve_launch` and before the spawn: no
    agent starts, so nothing is counted."""
    from lazy_harness.cli.exec_cmd import exec_cmd

    _write_agent(QUIET_AGENT)

    result = CliRunner().invoke(exec_cmd, [], input="   \n")

    assert json.loads(result.stdout)["error"]["kind"] == "empty-prompt"
    assert _counts(harness) == {}


def test_the_row_survives_a_killed_run(
    harness: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The proof that the write precedes the spawn rather than following it:
    a run that never returns still leaves its row."""
    from lazy_harness.cli.exec_cmd import exec_cmd

    _write_agent(HANGING_AGENT)
    ready = tmp_path / "agent-started"
    monkeypatch.setenv("READYFILE", str(ready))

    with timeout_when_agent_is_ready(ready):
        result = CliRunner().invoke(exec_cmd, ["--timeout", "2"], input="hello")

    assert result.exit_code == 124
    assert _counts(harness) == {("personal", "claude-code", "exec"): 1}

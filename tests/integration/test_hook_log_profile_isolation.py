"""A hook invoked under `--profile <p>` logs inside that profile, and nowhere else.

Two paths answer "which directory does this hook write its audit line into":
the deployed command's `--profile` flag, and the directory the hook resolves for
itself. They disagreed. Nine builtins resolved the second half from a hardcoded
`get_agent("claude-code")`, so a hook running under one profile appended its
line to whatever directory the *global* agent named — a different, live profile
on the same machine.

Every test here invokes the real CLI entry point and asserts both halves: the
line landed in the profile's own `config_dir`, **and** nothing was written
anywhere else. Presence alone would have passed before the fix too, because the
global directory these hooks leaked into is a real one they were entitled to
create.

`CLAUDE_CONFIG_DIR` is deliberately left unset (the autouse fixture in
`tests/conftest.py` clears it). It is step 1 of `agent_runtime_dir`'s resolution
order and would mask the very step — the profile's own `config_dir` — that these
tests exist to exercise.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from lazy_harness.cli.main import cli

# Two profiles, not one: a hook that resolved the *default* profile rather than
# the one it was invoked with would still land in a profile-shaped directory.
_CONFIG = """\
[harness]
version = "1"

[agent]
type = "claude-code"

[profiles]
default = "other"

[profiles.other]
config_dir = "{other}"

[profiles.gate]
config_dir = "{gate}"
"""


@pytest.fixture
def harness_config(tmp_path: Path, home_dir: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point `lh` at a two-profile config; return the `gate` profile's dir."""
    lh_config = tmp_path / "lhconfig"
    lh_config.mkdir()
    gate = tmp_path / "gate-home"
    other = tmp_path / "other-home"
    (lh_config / "config.toml").write_text(_CONFIG.format(gate=gate, other=other))
    monkeypatch.setenv("LH_CONFIG_DIR", str(lh_config))
    return gate


def _files_under(root: Path) -> set[Path]:
    return {p.relative_to(root) for p in root.rglob("*") if p.is_file()}


def _run_hook(name: str, profile: str, payload: dict) -> int:
    result = CliRunner().invoke(
        cli, ["hook", name, "--profile", profile], input=json.dumps(payload)
    )
    return result.exit_code


def test_security_block_logs_into_the_invoked_profile(harness_config: Path) -> None:
    exit_code = _run_hook(
        "pre-tool-use-security",
        "gate",
        {"tool_name": "Bash", "tool_input": {"command": "rm -rf /tmp/foo"}},
    )

    # Exit 2 is the block itself. Without it the absence assertions below would
    # pass on a hook that never logged anything at all.
    assert exit_code == 2
    log = (harness_config / "logs" / "hooks.log").read_text()
    assert "pre-tool-use-security" in log
    assert "blocked" in log


def test_security_block_writes_nothing_outside_the_invoked_profile(
    harness_config: Path, home_dir: Path, tmp_path: Path
) -> None:
    """The half that fails before the fix: the leak landed in the global agent dir.

    `~/.claude` is `agent_runtime_dir`'s step 3 fallback once `CLAUDE_CONFIG_DIR`
    is unset, so a hardcoded `get_agent("claude-code")` writes there while the
    hook runs under `--profile gate`.
    """
    other = tmp_path / "other-home"
    before_home = _files_under(home_dir)
    before_other = _files_under(other) if other.exists() else set()

    exit_code = _run_hook(
        "pre-tool-use-security",
        "gate",
        {"tool_name": "Bash", "tool_input": {"command": "rm -rf /tmp/foo"}},
    )

    assert exit_code == 2
    assert _files_under(home_dir) == before_home
    assert (_files_under(other) if other.exists() else set()) == before_other


def test_context_inject_logs_into_the_invoked_profile(harness_config: Path, tmp_path: Path) -> None:
    """The `fired` line is written before `load_config`, so it resolved globally.

    `context-inject` already resolves its *second* line per profile
    (`agent_dir_for(cfg, event.profile)`). The bootstrap line above it did not,
    which split one hook's audit trail across two profiles.
    """
    exit_code = _run_hook(
        "context-inject",
        "gate",
        {"cwd": str(tmp_path), "session_id": "isolation-test"},
    )

    assert exit_code == 0
    log = (harness_config / "logs" / "hooks.log").read_text()
    assert "session-context: fired cwd=" in log


def test_context_inject_writes_nothing_outside_the_invoked_profile(
    harness_config: Path, home_dir: Path, tmp_path: Path
) -> None:
    other = tmp_path / "other-home"
    before_home = _files_under(home_dir)
    before_other = _files_under(other) if other.exists() else set()

    exit_code = _run_hook(
        "context-inject",
        "gate",
        {"cwd": str(tmp_path), "session_id": "isolation-test"},
    )

    assert exit_code == 0
    assert "session-context: fired cwd=" in (harness_config / "logs" / "hooks.log").read_text()
    assert _files_under(home_dir) == before_home
    assert (_files_under(other) if other.exists() else set()) == before_other


@pytest.fixture
def metrics_elsewhere(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Keep the metrics store out of `home_dir`, so it cannot mask a log leak.

    `session-end` records a `session_closed` loop event before it touches the
    log, and `resolve_db_path` falls back to the data dir — which, with the XDG
    vars cleared, is inside `home_dir`. Leaving it there would make the absence
    assertions below fail for a reason that has nothing to do with the profile.
    """
    data = tmp_path / "lhdata"
    monkeypatch.setenv("LH_DATA_DIR", str(data))
    return data


def _session_end_payload(cwd: Path) -> dict[str, object]:
    return {
        "hook_event_name": "SessionEnd",
        "session_id": "isolation-test",
        "cwd": str(cwd),
    }


def test_session_end_logs_into_the_invoked_profile(
    harness_config: Path, metrics_elsewhere: Path, tmp_path: Path
) -> None:
    """Both of this hook's lines, not just the second one.

    `session_end` wrote `fired` from a `get_agent("claude-code")` bootstrap dir
    and then re-resolved `agent_runtime_dir(agent)` globally as well, so under
    `--profile gate` the whole audit trail landed somewhere else.
    """
    exit_code = _run_hook("session-end", "gate", _session_end_payload(tmp_path))

    assert exit_code == 0
    log = (harness_config / "logs" / "hooks.log").read_text()
    assert "session-end: fired cwd=" in log
    assert "session-end: disabled in config, skipping" in log


def test_session_end_writes_nothing_outside_the_invoked_profile(
    harness_config: Path, metrics_elsewhere: Path, home_dir: Path, tmp_path: Path
) -> None:
    """The half that fails before the fix: `~/.claude` is the global fallback."""
    other = tmp_path / "other-home"
    before_home = _files_under(home_dir)
    before_other = _files_under(other) if other.exists() else set()

    exit_code = _run_hook("session-end", "gate", _session_end_payload(tmp_path))

    assert exit_code == 0
    assert "session-end: fired cwd=" in (harness_config / "logs" / "hooks.log").read_text()
    assert _files_under(home_dir) == before_home
    assert (_files_under(other) if other.exists() else set()) == before_other


def test_session_end_labels_its_loop_event_with_the_invoked_profile(
    harness_config: Path, metrics_elsewhere: Path, tmp_path: Path
) -> None:
    """The same defect one column over, in the metrics store rather than the log.

    `_record_session_closed` labelled the `session_closed` row with
    `profile_name()`, which reads the *ambient* `CLAUDE_CONFIG_DIR` and answers
    `""` when it is unset — so every hook invoked under an explicit `--profile`
    wrote an unattributed row. `event.profile` is the flag the command carries.
    """
    import sqlite3

    exit_code = _run_hook("session-end", "gate", _session_end_payload(tmp_path))

    assert exit_code == 0
    with sqlite3.connect(metrics_elsewhere / "metrics.db") as conn:
        rows = conn.execute(
            "SELECT profile FROM loop_events WHERE session = ? AND kind = 'session_closed'",
            ("isolation-test",),
        ).fetchall()
    assert rows == [("gate",)]


def test_session_export_logs_into_the_invoked_profile(harness_config: Path, tmp_path: Path) -> None:
    """`session-export` resolved its log path twice, both times globally.

    The bootstrap `boot_dir` above `load_config` went through a hardcoded
    `get_agent("claude-code")`, and the re-resolution below it through
    `agent_runtime_dir(agent)` with no profile — so both halves of this hook's
    audit trail landed in whatever directory the global agent named.
    """
    exit_code = _run_hook(
        "session-export",
        "gate",
        {"cwd": str(tmp_path), "session_id": "isolation-test"},
    )

    assert exit_code == 0
    log = (harness_config / "logs" / "hooks.log").read_text()
    assert "session-export: fired cwd=" in log


def test_session_export_writes_nothing_outside_the_invoked_profile(
    harness_config: Path, home_dir: Path, tmp_path: Path
) -> None:
    other = tmp_path / "other-home"
    before_home = _files_under(home_dir)
    before_other = _files_under(other) if other.exists() else set()

    exit_code = _run_hook(
        "session-export",
        "gate",
        {"cwd": str(tmp_path), "session_id": "isolation-test"},
    )

    assert exit_code == 0
    assert "session-export: fired cwd=" in (harness_config / "logs" / "hooks.log").read_text()
    assert _files_under(home_dir) == before_home
    assert (_files_under(other) if other.exists() else set()) == before_other


def test_compound_loop_logs_into_the_invoked_profile(harness_config: Path, tmp_path: Path) -> None:
    """`compound-loop` resolved both halves globally, and logged before config.

    Its bootstrap dir was `agent_runtime_dir(get_agent("claude-code"))` with the
    agent name written out as a literal, so the `fired` line landed in whatever
    directory the global agent named even when the hook ran under `--profile
    gate`. The session lookup below it then read that same wrong directory's
    `projects/`, which is how a profile's Stop stopped queueing anything.
    """
    exit_code = _run_hook(
        "compound-loop",
        "gate",
        {"hook_event_name": "Stop", "cwd": str(tmp_path), "session_id": "isolation-test"},
    )

    assert exit_code == 0
    log = (harness_config / "logs" / "hooks.log").read_text()
    assert "compound-loop: fired cwd=" in log


def test_compound_loop_writes_nothing_outside_the_invoked_profile(
    harness_config: Path, home_dir: Path, tmp_path: Path
) -> None:
    """The half that fails before the fix.

    Presence alone passes either way: `~/.claude` is a directory the hook is
    entitled to create, so the leak looks exactly like a first run.
    """
    other = tmp_path / "other-home"
    before_home = _files_under(home_dir)
    before_other = _files_under(other) if other.exists() else set()

    exit_code = _run_hook(
        "compound-loop",
        "gate",
        {"hook_event_name": "Stop", "cwd": str(tmp_path), "session_id": "isolation-test"},
    )

    assert exit_code == 0
    assert "compound-loop: fired cwd=" in (harness_config / "logs" / "hooks.log").read_text()
    assert _files_under(home_dir) == before_home
    assert (_files_under(other) if other.exists() else set()) == before_other

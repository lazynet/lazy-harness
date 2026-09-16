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
import subprocess
import sys
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


def test_pre_compact_logs_into_the_invoked_profile(harness_config: Path, tmp_path: Path) -> None:
    """`pre-compact` is an addition to this gate, not a fix to an entry in it.

    It is absent from the step-4 leak counts because the gate **never invoked
    it** — it is in no skip list and had no case here — not because it was
    clean: `pre_compact.py:186` wrote its `fired` line unconditionally, from a
    directory resolved through `get_agent(...)` plus `agent_runtime_dir(agent)`
    with no profile. Eight hooks leaked by mechanism; seven were measured.
    """
    exit_code = _run_hook(
        "pre-compact",
        "gate",
        {"hook_event_name": "PreCompact", "cwd": str(tmp_path), "session_id": "isolation-test"},
    )

    assert exit_code == 0
    log = (harness_config / "logs" / "hooks.log").read_text()
    assert "pre-compact: fired cwd=" in log


def test_pre_compact_writes_nothing_outside_the_invoked_profile(
    harness_config: Path, home_dir: Path, tmp_path: Path
) -> None:
    """The half that fails before the migration.

    This hook writes three things — the log line, the memory dir and, when a
    transcript exists, a `compact-backups/` copy — and every one of them landed
    in `~/.claude`, which is `agent_runtime_dir`'s last resort once
    `CLAUDE_CONFIG_DIR` is unset. Presence alone passes either way: that
    directory is one the hook is entitled to create, so the leak looks exactly
    like a first run.
    """
    other = tmp_path / "other-home"
    before_home = _files_under(home_dir)
    before_other = _files_under(other) if other.exists() else set()

    exit_code = _run_hook(
        "pre-compact",
        "gate",
        {"hook_event_name": "PreCompact", "cwd": str(tmp_path), "session_id": "isolation-test"},
    )

    assert exit_code == 0
    assert "pre-compact: fired cwd=" in (harness_config / "logs" / "hooks.log").read_text()
    assert _files_under(home_dir) == before_home
    assert (_files_under(other) if other.exists() else set()) == before_other


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


def test_session_start_preflight_reads_the_invoked_profiles_credentials(
    harness_config: Path, home_dir: Path, tmp_path: Path
) -> None:
    """The same defect one file over, in what a hook *reads* rather than writes.

    Every other case here is about placement of an audit line. This hook writes
    nothing at all, so presence and absence of a file cannot speak for it — the
    probe is its output. `_credentials_path` — the helper `auth_check` replaced —
    resolved `CLAUDE_CONFIG_DIR` itself and fell back to `~/.claude`, so under
    `--profile gate` it reported whatever login the *global* directory held: a
    healthy verdict for a profile the session was not running under, which is
    the one failure a preflight exists to catch.

    The two directories carry opposite verdicts on purpose. `gate` is expired
    and `~/.claude` is healthy, so a run that still resolved globally comes back
    all-clear and this fails.

    The *wording* of the unhappy verdict is the platform's, not this test's:
    where the credentials file is a mirror of the keychain (ADR-045 D6) an
    expiry read off it degrades to `unknown`. Both spellings are unhappy and the
    healthy directory still collapses to "All clear", so the pair keeps carrying
    opposite answers either way.
    """
    expired = json.dumps(
        {"claudeAiOauth": {"accessToken": "x", "refreshTokenExpiresAt": 1_577_836_800_000}}
    )
    healthy = json.dumps(
        {"claudeAiOauth": {"accessToken": "x", "refreshTokenExpiresAt": 4_102_444_800_000}}
    )
    harness_config.mkdir(parents=True, exist_ok=True)
    (harness_config / ".credentials.json").write_text(expired)
    (home_dir / ".claude").mkdir(parents=True, exist_ok=True)
    (home_dir / ".claude" / ".credentials.json").write_text(healthy)

    result = CliRunner().invoke(
        cli,
        ["hook", "session-start-preflight", "--profile", "gate"],
        input=json.dumps(
            {
                "hook_event_name": "SessionStart",
                "cwd": str(tmp_path),
                "session_id": "isolation-test",
            }
        ),
    )

    assert result.exit_code == 0, result.output
    body = json.loads(result.output)["hookSpecificOutput"]["additionalContext"]
    unhappy = (
        "- **auth** [?] — credentials live in the keychain on macOS"
        if sys.platform == "darwin"
        else "- **auth** [FAIL] — refresh token expired"
    )
    assert unhappy in body
    assert "All clear" not in body


#: Long enough to clear `_MIN_CHARS` and carrying an action verb, so
#: `is_non_trivial` admits it through the verb branch.
_WORK_PROMPT = "implementá el hook y agregá el test"


def _user_prompt_goal_payload(cwd: Path) -> dict[str, object]:
    return {
        "hook_event_name": "UserPromptSubmit",
        "session_id": "isolation-test",
        "prompt": _WORK_PROMPT,
        "cwd": str(cwd),
    }


def test_user_prompt_goal_labels_its_loop_event_with_the_invoked_profile(
    harness_config: Path, metrics_elsewhere: Path, tmp_path: Path
) -> None:
    """This hook's whole per-profile surface is one column, not a directory.

    `user-prompt-goal` writes nowhere under the agent's runtime dir — no log,
    no cursor, no export — so the `hooks.log` half of this gate has nothing to
    say about it. What it does write is a `loop_events` row, and that row used
    to be labelled with `profile_name()`, which reads the *ambient*
    `CLAUDE_CONFIG_DIR` and answers `""` when it is unset. Every hook invoked
    under an explicit `--profile` therefore recorded an unattributed row into a
    store both profiles share. `event.profile` is the flag the command carries.
    """
    import sqlite3

    exit_code = _run_hook("user-prompt-goal", "gate", _user_prompt_goal_payload(tmp_path))

    assert exit_code == 0
    with sqlite3.connect(metrics_elsewhere / "metrics.db") as conn:
        rows = conn.execute(
            "SELECT profile FROM loop_events WHERE session = ? AND kind = 'nontrivial_prompt'",
            ("isolation-test",),
        ).fetchall()
    assert rows == [("gate",)]


def test_user_prompt_goal_writes_nothing_outside_the_invoked_profile(
    harness_config: Path, metrics_elsewhere: Path, home_dir: Path, tmp_path: Path
) -> None:
    """A guard rather than a witness, and the difference is worth naming.

    The test above fails against the unmigrated hook; this one does not, and
    cannot — the hook resolves no agent directory at all today, so there is no
    leak for it to catch. It is here because the migration is what first hands
    this hook a profile, and the cheapest way for a later change to spend that
    profile is to start writing a log line with it. Then this assertion is the
    one that notices.
    """
    other = tmp_path / "other-home"
    before_home = _files_under(home_dir)
    before_other = _files_under(other) if other.exists() else set()

    exit_code = _run_hook("user-prompt-goal", "gate", _user_prompt_goal_payload(tmp_path))

    assert exit_code == 0
    assert _files_under(home_dir) == before_home
    assert (_files_under(other) if other.exists() else set()) == before_other


@pytest.fixture
def ruff_unreachable(monkeypatch: pytest.MonkeyPatch) -> None:
    """Drive `post-tool-use-format` down its only branch that writes a log line.

    The hook is silent when `ruff` runs, so with the binary present there is no
    evidence to place in a profile at all. Only the `ruff` invocation is
    intercepted: everything else the CLI spawns during the run is left alone.
    """
    real_run = subprocess.run

    def no_ruff(cmd: object, *args: object, **kwargs: object) -> object:
        if isinstance(cmd, list) and cmd and cmd[0] == "ruff":
            raise FileNotFoundError("ruff")
        return real_run(cmd, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(subprocess, "run", no_ruff)


def _format_payload(edited: Path) -> dict[str, object]:
    return {
        "hook_event_name": "PostToolUse",
        "session_id": "isolation-test",
        "tool_name": "Edit",
        "tool_input": {"file_path": str(edited)},
    }


def test_post_tool_use_format_logs_into_the_invoked_profile(
    harness_config: Path, ruff_unreachable: None, tmp_path: Path
) -> None:
    """`post-tool-use-format` resolved its log dir from a hardcoded agent name.

    `_log_unavailable` did `agent_runtime_dir(get_agent("claude-code"))` with no
    profile, so under `--profile gate` the one line this hook ever writes landed
    in whatever directory the *global* agent named — `~/.claude`, once
    `CLAUDE_CONFIG_DIR` is cleared. `agent_dir_for(cfg, event.profile)` is what
    the migration replaces that with.
    """
    edited = tmp_path / "edited.py"
    edited.write_text("x  =  1\n")

    exit_code = _run_hook("post-tool-use-format", "gate", _format_payload(edited))

    assert exit_code == 0
    log = (harness_config / "logs" / "hooks.log").read_text()
    assert "post-tool-use-format: ruff unavailable (FileNotFoundError)" in log
    assert f"left {edited} unformatted" in log


def test_post_tool_use_format_writes_nothing_outside_the_invoked_profile(
    harness_config: Path, ruff_unreachable: None, home_dir: Path, tmp_path: Path
) -> None:
    """The half that fails before the migration.

    Presence alone passes either way: `~/.claude` is a directory the hook is
    entitled to create, so the leak looks exactly like a first run.
    """
    other = tmp_path / "other-home"
    before_home = _files_under(home_dir)
    before_other = _files_under(other) if other.exists() else set()

    edited = tmp_path / "edited.py"
    edited.write_text("x  =  1\n")

    exit_code = _run_hook("post-tool-use-format", "gate", _format_payload(edited))

    assert exit_code == 0
    assert (
        "post-tool-use-format: ruff unavailable"
        in (harness_config / "logs" / "hooks.log").read_text()
    )
    assert _files_under(home_dir) == before_home
    assert (_files_under(other) if other.exists() else set()) == before_other


#: A second config whose `gate` profile runs a *different agent* from the global
#: `[agent].type`. The default `harness_config` cannot show what
#: `post-tool-use-sync-claude` resolves per profile, because both of its profiles
#: run the same agent and every resolution agrees.
#:
#: The global side is `codex` and the profile side is `claude-code`, that way
#: round rather than the other: the runner parses the payload with the *invoked
#: profile's* adapter, and `CodexAdapter._parse_tool` (`agents/codex.py:177`)
#: builds no `FileEdit` at all, so a `gate` running codex would deliver this hook
#: an edit-less tool call and both resolutions would regenerate nothing.
_CROSS_AGENT_CONFIG = """\
[harness]
version = "1"

[agent]
type = "codex"

[profiles]
default = "other"

[profiles.other]
config_dir = "{other}"

[profiles.gate]
config_dir = "{gate}"
agent = "claude-code"
"""

#: What both generated docs hold before the hook runs, so "regenerated" is
#: observable without re-deriving the generator's output at the assertion.
_STALE_DOC = "STALE — written by the fixture, not by the hook\n"


@pytest.fixture
def cross_agent_config(tmp_path: Path, home_dir: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A two-profile config whose `gate` runs `claude-code`; returns the profiles tree.

    The tree carries both agents' segments. `post-tool-use-sync-claude` gates on
    Claude Code's segment *filenames* — `SEGMENT_FILES`, a deliberately
    agent-specific constant its module docstring owns — while the generator it
    then calls reads the segments of whichever adapter it is handed. Both sets
    have to exist for the two resolutions to be distinguishable by their effect
    rather than by one of them failing for want of an input file.
    """
    lh_config = tmp_path / "lhconfig"
    lh_config.mkdir()
    gate = tmp_path / "gate-home"
    other = tmp_path / "other-home"
    (lh_config / "config.toml").write_text(_CROSS_AGENT_CONFIG.format(gate=gate, other=other))
    monkeypatch.setenv("LH_CONFIG_DIR", str(lh_config))

    profiles = tmp_path / "tree" / "profiles"
    (profiles / "_common").mkdir(parents=True)
    (profiles / "_common" / "CLAUDE.common.md").write_text("SHARED RULES\n")
    (profiles / "_common" / "AGENTS.common.md").write_text("SHARED RULES\n")
    (profiles / "alpha").mkdir()
    for stem in ("CLAUDE", "AGENTS"):
        (profiles / "alpha" / f"{stem}.head.md").write_text("alpha HEAD\n")
        (profiles / "alpha" / f"{stem}.tail.md").write_text("alpha TAIL\n")
        (profiles / "alpha" / f"{stem}.md").write_text(_STALE_DOC)
    return profiles


def _sync_claude_payload(segment: Path, cwd: Path) -> dict[str, object]:
    return {
        "hook_event_name": "PostToolUse",
        "session_id": "isolation-test",
        "cwd": str(cwd),
        "tool_name": "Edit",
        "tool_input": {"file_path": str(segment)},
    }


def test_sync_claude_regenerates_the_doc_of_the_agent_the_invoked_profile_runs(
    cross_agent_config: Path, tmp_path: Path
) -> None:
    """This hook writes nothing under the agent's runtime dir, so the doc is the probe.

    Every directory-placement case above is about where an audit line lands.
    This hook appends no log line and keeps no cursor; what it resolves per
    profile is the **adapter**, and the adapter decides `system_docs()` —
    which file the profile's contract is written to. Before the migration it
    read the global `[agent].type`, so a session running under a profile that
    declares its own agent regenerated the *other* agent's contract file.

    That is the blast radius the migration closes, and it is larger than a lost
    log line: this hook writes the user's profile contracts. Measured against
    the unmigrated hook, on exactly this fixture: `CLAUDE.md regenerated=False
    AGENTS.md regenerated=True` — under `--profile gate`, whose declared agent
    is `claude-code`, because the global `[agent].type` is what it read.

    `CLAUDE_CONFIG_DIR` is cleared by the autouse fixture in `tests/conftest.py`,
    as the module docstring above requires — but note it could not mask this one
    anyway: that variable steers `agent_runtime_dir`, and nothing on this path
    reads a runtime directory. The mask this test has to defeat is the *global*
    `[agent].type`, which is why `gate` declares an agent of its own.
    """
    from lazy_harness.core.sync_agent_md import legacy_segment_names, render_agent_md

    exit_code = _run_hook(
        "post-tool-use-sync-claude",
        "gate",
        _sync_claude_payload(cross_agent_config / "alpha" / "CLAUDE.head.md", tmp_path),
    )

    assert exit_code == 0
    assert (cross_agent_config / "alpha" / "CLAUDE.md").read_text() == render_agent_md(
        "alpha HEAD\n",
        "SHARED RULES\n",
        "alpha TAIL\n",
        names=legacy_segment_names("CLAUDE"),
    )
    # The absence half: the global agent's contract is the file the pre-migration
    # hook wrote, so asserting only on `CLAUDE.md` would pass against a hook that
    # regenerated both.
    assert (cross_agent_config / "alpha" / "AGENTS.md").read_text() == _STALE_DOC


def test_sync_claude_writes_nothing_outside_the_profiles_tree_it_was_pointed_at(
    cross_agent_config: Path, home_dir: Path, tmp_path: Path
) -> None:
    """A guard rather than a witness, and the difference is worth naming.

    The test above fails against the unmigrated hook; this one does not, and
    cannot — the tree this hook regenerates is derived from the *edited path*
    (`_profiles_dir_for`), never from `event.profile`, so there is no directory
    for the profile to misplace. It is here because the migration is what first
    hands this hook a profile, and the cheapest way for a later change to spend
    one is to start resolving the tree from it.
    """
    gate = tmp_path / "gate-home"
    other = tmp_path / "other-home"
    before = (
        _files_under(home_dir),
        _files_under(gate) if gate.exists() else set(),
        _files_under(other) if other.exists() else set(),
    )

    exit_code = _run_hook(
        "post-tool-use-sync-claude",
        "gate",
        _sync_claude_payload(cross_agent_config / "alpha" / "CLAUDE.head.md", tmp_path),
    )

    assert exit_code == 0
    assert (
        _files_under(home_dir),
        _files_under(gate) if gate.exists() else set(),
        _files_under(other) if other.exists() else set(),
    ) == before


@pytest.fixture
def ansible_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """An Ansible repo whose YAML edit reaches the log-writing branch.

    `post-tool-use-ansible-lint` only touches `hooks.log` when the linter
    cannot speak: a missing or unrunnable binary, a timeout, or a non-zero exit
    with no output. So `PATH` is emptied rather than left ambient — that makes
    `ansible-lint` absent by construction on every machine, which is both the
    deterministic input and the honest one. Leaving the real `PATH` would make
    this gate depend on whether the developer happens to have ansible-lint
    installed, and pass vacuously on the machines that do.
    """
    empty_bin = tmp_path / "empty-bin"
    empty_bin.mkdir()
    monkeypatch.setenv("PATH", str(empty_bin))
    repo = tmp_path / "ansible"
    repo.mkdir()
    (repo / "ansible.cfg").write_text("[defaults]\n")
    (repo / "site.yaml").write_text("- hosts: all\n")
    return repo


def _ansible_lint_payload(repo: Path) -> dict[str, object]:
    return {
        "hook_event_name": "PostToolUse",
        "session_id": "isolation-test",
        "cwd": str(repo),
        "tool_name": "Edit",
        "tool_input": {"file_path": str(repo / "site.yaml")},
    }


def test_ansible_lint_logs_into_the_invoked_profile(
    harness_config: Path, ansible_repo: Path
) -> None:
    """`_write_hook_log` resolved `get_agent("claude-code")` and no profile.

    This hook is a PostToolUse one, so it was never in the step-4 leak counts —
    those were taken over the session-lifecycle hooks. The mechanism is the same
    one: `agent_runtime_dir(agent)` with no `profile_config_dir`, which under
    `--profile gate` writes wherever the *global* agent points.
    """
    exit_code = _run_hook("post-tool-use-ansible-lint", "gate", _ansible_lint_payload(ansible_repo))

    assert exit_code == 0
    log = (harness_config / "logs" / "hooks.log").read_text()
    assert "post-tool-use-ansible-lint" in log
    assert "ansible-lint unavailable (FileNotFoundError)" in log


def test_ansible_lint_writes_nothing_outside_the_invoked_profile(
    harness_config: Path, ansible_repo: Path, home_dir: Path, tmp_path: Path
) -> None:
    """The half that fails before the migration: `~/.claude` took the line.

    Presence alone passes either way — that directory is one the hook is
    entitled to create, so the leak looks exactly like a first run.
    """
    other = tmp_path / "other-home"
    before_home = _files_under(home_dir)
    before_other = _files_under(other) if other.exists() else set()

    exit_code = _run_hook("post-tool-use-ansible-lint", "gate", _ansible_lint_payload(ansible_repo))

    assert exit_code == 0
    assert "ansible-lint unavailable" in (harness_config / "logs" / "hooks.log").read_text()
    assert _files_under(home_dir) == before_home
    assert (_files_under(other) if other.exists() else set()) == before_other


@pytest.fixture
def oversized_file(tmp_path: Path) -> Path:
    """A file past `MAX_LINES`, which is the only branch that writes a log line.

    `pre-tool-use-read-size` logs nothing on any of its silent paths, so a
    bounded read or a small file leaves this gate with no evidence to place.
    """
    big = tmp_path / "big.md"
    big.write_text("key: value\n" * 3000)
    return big


def _read_size_payload(target: Path) -> dict[str, object]:
    return {
        "hook_event_name": "PreToolUse",
        "session_id": "isolation-test",
        "tool_name": "Read",
        "tool_input": {"file_path": str(target)},
    }


def test_read_size_logs_into_the_invoked_profile(
    harness_config: Path, oversized_file: Path
) -> None:
    """`_log_warning` resolved `get_agent("claude-code")` and no profile.

    `docs/how/hooks.md` named this hook as one of the two that still resolved
    the directory globally. Under `--profile gate` the one line it writes landed
    in whatever directory the *global* agent pointed at — `~/.claude`, once
    `CLAUDE_CONFIG_DIR` is cleared.
    """
    exit_code = _run_hook("pre-tool-use-read-size", "gate", _read_size_payload(oversized_file))

    assert exit_code == 0
    log = (harness_config / "logs" / "hooks.log").read_text()
    assert "pre-tool-use-read-size: unbounded read:" in log
    assert "3000 lines ~8250 tokens" in log


def test_read_size_writes_nothing_outside_the_invoked_profile(
    harness_config: Path, oversized_file: Path, home_dir: Path, tmp_path: Path
) -> None:
    """The half that fails before the migration.

    Presence alone passes either way: `~/.claude` is a directory the hook is
    entitled to create, so the leak looks exactly like a first run.
    """
    other = tmp_path / "other-home"
    before_home = _files_under(home_dir)
    before_other = _files_under(other) if other.exists() else set()

    exit_code = _run_hook("pre-tool-use-read-size", "gate", _read_size_payload(oversized_file))

    assert exit_code == 0
    assert (
        "pre-tool-use-read-size: unbounded read:"
        in (harness_config / "logs" / "hooks.log").read_text()
    )
    assert _files_under(home_dir) == before_home
    assert (_files_under(other) if other.exists() else set()) == before_other


#: Absolute and synthetic. `pre-tool-use-memory-size` projects a `Write` from
#: its `content` alone and never opens the file, so nothing has to exist here —
#: and naming a path under `tmp_path` would put a directory the hook is entitled
#: to create inside the trees the absence assertion sweeps.
_OVERSIZED_MEMORY_PAYLOAD: dict[str, object] = {
    "hook_event_name": "PreToolUse",
    "session_id": "isolation-test",
    "tool_name": "Write",
    "tool_input": {
        "file_path": "/home/user/.claude/projects/foo/memory/MEMORY.md",
        "content": "line\n" * 250,
    },
}


def test_memory_size_logs_into_the_invoked_profile(harness_config: Path) -> None:
    """`_log_warning` resolved `get_agent("claude-code")` and no profile.

    This is one of the two hooks `docs/how/hooks.md` named as still resolving
    the directory globally. The warning itself reached the agent either way, so
    the defect was invisible from the session: only the audit trail moved, into
    whichever directory the *global* agent pointed at.
    """
    exit_code = _run_hook("pre-tool-use-memory-size", "gate", _OVERSIZED_MEMORY_PAYLOAD)

    assert exit_code == 0
    log = (harness_config / "logs" / "hooks.log").read_text()
    assert "pre-tool-use-memory-size" in log
    assert "over threshold" in log


def test_memory_size_writes_nothing_outside_the_invoked_profile(
    harness_config: Path, home_dir: Path, tmp_path: Path
) -> None:
    """The half that fails before the migration: `~/.claude` took the line.

    Presence alone passes either way — that directory is one the hook is
    entitled to create, so the leak looks exactly like a first run.
    """
    other = tmp_path / "other-home"
    before_home = _files_under(home_dir)
    before_other = _files_under(other) if other.exists() else set()

    exit_code = _run_hook("pre-tool-use-memory-size", "gate", _OVERSIZED_MEMORY_PAYLOAD)

    assert exit_code == 0
    assert "over threshold" in (harness_config / "logs" / "hooks.log").read_text()
    assert _files_under(home_dir) == before_home
    assert (_files_under(other) if other.exists() else set()) == before_other

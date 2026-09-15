"""`pre-compact` writes the summary and `context-inject` reads it back — same profile.

Two paths answer one question here: "which directory holds this project's
`pre-compact-summary.md`". `pre_compact.py` resolved it from
`agent_runtime_dir(agent)` with no profile; `context_inject.py` was moved onto
`agent_dir_for(cfg, event.profile)` in PR #300. Under `--profile p` those are
two different directories, and **both processes exit 0** — the writer reports a
summary written, the reader reports no handoff, and nothing on either side
fails. Measured before this migration, against `--profile p` with
`CLAUDE_CONFIG_DIR` cleared:

    writer  ~/.claude/projects/<encoded>/memory/pre-compact-summary.md
    reader  <p's config_dir>/projects/<encoded>/memory/pre-compact-summary.md

So the pair was already broken and the migration is what repairs it. `CLAUDE.md`
requires this shape — "where two paths answer one question, an integration test
invokes both and asserts they agree" — and no golden or single-hook isolation
test can see it: the failure needs both sides at once.

`CLAUDE_CONFIG_DIR` is left unset (the autouse fixture in `tests/conftest.py`
clears it). It is step 1 of `agent_runtime_dir`'s resolution order and would
make the two answers the same path, which is precisely what this test exists to
tell apart.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from lazy_harness.cli.main import cli

# Two profiles, so a hook resolving the *default* rather than the invoked one
# still lands somewhere this test can see.
_CONFIG = """\
[harness]
version = "1"

[agent]
type = "claude-code"

[profiles]
default = "other"

[profiles.pair]
config_dir = "{pair}"

[profiles.other]
config_dir = "{other}"
"""

_DECISION = {"ts": "2026-09-15T00:00:00Z", "summary": "the writer and the reader agree"}
_FAILURE = {"ts": "2026-09-15T01:00:00Z", "summary": "the summary landed in another profile"}


@pytest.fixture
def paired_profiles(tmp_path: Path, home_dir: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point `lh` at a two-profile config; return the `pair` profile's dir."""
    lh_config = tmp_path / "lhconfig"
    lh_config.mkdir()
    pair = tmp_path / "pair-home"
    other = tmp_path / "other-home"
    (lh_config / "config.toml").write_text(_CONFIG.format(pair=pair, other=other))
    monkeypatch.setenv("LH_CONFIG_DIR", str(lh_config))
    monkeypatch.setenv("LH_DATA_DIR", str(tmp_path / "lhdata"))
    return pair


def _encoded(path: Path) -> str:
    return "-" + str(path).replace("/", "-").lstrip("-")


def _run_hook(name: str, profile: str, payload: dict) -> tuple[int, str]:
    result = CliRunner().invoke(
        cli, ["hook", name, "--profile", profile], input=json.dumps(payload)
    )
    return result.exit_code, result.stdout


def _seed_memory(agent_dir: Path, work: Path) -> Path:
    """Write the two JSONL tails `build_memory_tails` reads, where it reads them."""
    memory = agent_dir / "projects" / _encoded(work) / "memory"
    memory.mkdir(parents=True)
    (memory / "decisions.jsonl").write_text(json.dumps(_DECISION, sort_keys=True) + "\n")
    (memory / "failures.jsonl").write_text(json.dumps(_FAILURE, sort_keys=True) + "\n")
    return memory


def test_the_summary_pre_compact_writes_is_what_context_inject_injects(
    paired_profiles: Path, tmp_path: Path
) -> None:
    """The whole loop, through the real CLI, in one profile.

    `pre-compact` is invoked first so the file under test is the one it wrote,
    not a fixture standing in for it — a pre-written summary would pass against
    a writer that never ran.
    """
    work = (tmp_path / "work").resolve()
    work.mkdir()
    _seed_memory(paired_profiles, work)

    write_code, write_out = _run_hook(
        "pre-compact",
        "pair",
        {"hook_event_name": "PreCompact", "session_id": "pair-test", "cwd": str(work)},
    )

    assert write_code == 0
    assert "the writer and the reader agree" in write_out

    summary = paired_profiles / "projects" / _encoded(work) / "memory" / "pre-compact-summary.md"
    assert summary.is_file(), sorted(p for p in paired_profiles.rglob("*") if p.is_file())

    read_code, read_out = _run_hook(
        "context-inject",
        "pair",
        {"hook_event_name": "SessionStart", "session_id": "pair-test", "cwd": str(work)},
    )

    assert read_code == 0
    injected = json.loads(read_out)["hookSpecificOutput"]["additionalContext"]
    assert "Pre-compact context:" in injected
    assert "the writer and the reader agree" in injected
    assert "the summary landed in another profile" in injected


def test_neither_side_writes_the_summary_outside_the_invoked_profile(
    paired_profiles: Path, home_dir: Path, tmp_path: Path
) -> None:
    """The absence half, without which the test above passes on a broken pair.

    A writer that wrote into *both* the profile dir and the global one would
    satisfy every assertion above. `~/.claude` is `agent_runtime_dir`'s last
    resort with `CLAUDE_CONFIG_DIR` cleared, and it is where the unmigrated
    hook actually landed.
    """
    work = (tmp_path / "work").resolve()
    work.mkdir()
    _seed_memory(paired_profiles, work)
    other = tmp_path / "other-home"

    write_code, _ = _run_hook(
        "pre-compact",
        "pair",
        {"hook_event_name": "PreCompact", "session_id": "pair-test", "cwd": str(work)},
    )

    assert write_code == 0
    assert sorted(home_dir.rglob("pre-compact-summary.md")) == []
    assert (sorted(other.rglob("pre-compact-summary.md")) if other.exists() else []) == []
    assert not (home_dir / ".claude").exists(), sorted(
        p for p in (home_dir / ".claude").rglob("*") if p.is_file()
    )


def test_the_backup_and_the_log_land_in_the_invoked_profile_too(
    paired_profiles: Path, home_dir: Path, tmp_path: Path
) -> None:
    """The writer's other two effects, which no reader would notice were missing.

    `compact-backups/` is this hook's only copy of the raw transcript, and
    `hooks.log` is what `lh status hooks` parses to say whether it ever ran. A
    globally resolved writer puts both under a profile nobody is looking at,
    so the operator sees `pre-compact: never` while the hook fires every time.
    """
    work = (tmp_path / "work").resolve()
    work.mkdir()
    _seed_memory(paired_profiles, work)
    transcript = paired_profiles / "projects" / _encoded(work) / "pair-test.jsonl"
    transcript.write_text(json.dumps({"role": "user", "content": "x" * 40}) + "\n")

    write_code, _ = _run_hook(
        "pre-compact",
        "pair",
        {
            "hook_event_name": "PreCompact",
            "session_id": "pair-test",
            "cwd": str(work),
            "transcript_path": str(transcript),
        },
    )

    assert write_code == 0
    log = (paired_profiles / "logs" / "hooks.log").read_text()
    assert "pre-compact: fired cwd=" in log
    assert "pre-compact: summary written (" in log
    assert len(sorted((paired_profiles / "compact-backups").glob("*.jsonl"))) == 1
    assert not (home_dir / ".claude").exists()

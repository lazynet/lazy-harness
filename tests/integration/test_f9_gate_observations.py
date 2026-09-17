"""The three F9 assertions the first live acceptance run reported wrongly.

The run of 2026-09-17 (`lh` 0.71.0, `codex-cli` 0.154.0) returned
`ok 10 · FAIL 4 · BLOCKED 1 · NO-OBS 1`, and three of those six non-`ok`
verdicts were the script describing something other than what it had observed:

    NO-OBS  "the apply_patch arm was not exercised"   the stream carried
                                                      `"type":"file_change"`
    BLOCKED "BLOCKED BY ADR-053 — the installed lh    ADR-053 had shipped;
             still refuses Codex at ingest"           ingest crashed (#373)
    FAIL    "a changed declaration produced no        the config it deployed
             trust signal"                            did not parse

Each is one function here, extracted with `awk` and evaluated on its own the
way `test_f9_gate_python_resolution.py` does: sourcing the whole script runs it,
and its `--dry-run` path ends in `exit 0` before any `source ...; fn` one-liner
reaches its second statement.

The JSONL fixtures are synthetic. They are rebuilt from the *shape* the run's
`dump_kinds` printed — envelope type, item type, key names — and carry no
prompt, no model output and no path from the machine it ran on.
"""

from __future__ import annotations

import json
import subprocess
import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent.parent
GATE_SH = REPO_ROOT / "specs" / "gates" / "f9" / "codex-acceptance.sh"

# The verdict helpers the extracted functions call. Stubs, not the real ones:
# the originals mutate counters this file has no script to hold, and what is
# under test is which verdict fires, not how the summary counts it.
_VERDICT_STUBS = """
fail()    { echo "FAIL|$1"; }
ok()      { echo "ok|$1"; }
noobs()   { echo "NO-OBS|$1"; }
blocked() { echo "BLOCKED|$1"; }
"""


def _function_source(name: str) -> str:
    """`name`'s definition, lifted out of the gate script."""
    result = subprocess.run(
        ["awk", f"/^{name}\\(\\) \\{{/,/^}}/", str(GATE_SH)],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout, f"{name}() not found in codex-acceptance.sh"
    return result.stdout


def _run(script: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["bash", "-c", script], capture_output=True, text=True, timeout=60)


# --- the native edit arm ---------------------------------------------------


def _stream(tmp_path: Path, label: str, rows: list[dict]) -> Path:
    path = tmp_path / f"stream-{label}.jsonl"
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
    return path


def _native_edit(tmp_path: Path, label: str) -> subprocess.CompletedProcess[str]:
    script = (
        f"WORK={tmp_path}\n"
        f"{_function_source('stream_shows_native_edit')}\n"
        f'if stream_shows_native_edit "{label}"; then echo MATCH; else echo NO-MATCH; fi\n'
    )
    return _run(script)


_AGENT_MESSAGE = {
    "type": "item.completed",
    "item": {"id": "x", "text": "t", "type": "agent_message"},
}
_FILE_CHANGE_STARTED = {
    "type": "item.started",
    "item": {"changes": [], "id": "x", "status": "in_progress", "type": "file_change"},
}


def test_a_file_change_item_counts_as_the_native_edit_arm(tmp_path: Path) -> None:
    """The measured shape. 0.154.0's `--json` stream reports a native edit as
    `item.started` / `item.completed` carrying `"type":"file_change"`, and the
    word `apply_patch` appears nowhere in it — so the old pattern reported
    "not exercised" over the turn that had just modified the denied file."""
    _stream(tmp_path, "patch", [_AGENT_MESSAGE, _FILE_CHANGE_STARTED])

    result = _native_edit(tmp_path, "patch")

    assert result.stdout.strip() == "MATCH", result.stderr


def test_an_apply_patch_stream_still_counts(tmp_path: Path) -> None:
    """`apply_patch` is the name the adapter maps and the name a rollout
    carries. Widening to `file_change` must not drop the spelling that was
    there first."""
    _stream(
        tmp_path,
        "patch",
        [{"type": "item.started", "item": {"type": "command_execution", "command": "apply_patch"}}],
    )

    result = _native_edit(tmp_path, "patch")

    assert result.stdout.strip() == "MATCH", result.stderr


def test_a_turn_with_no_edit_is_still_not_observed(tmp_path: Path) -> None:
    """The NO-OBS verdict has to survive: a model that answered in prose
    exercised nothing, and calling that green would be the worse error."""
    _stream(tmp_path, "patch", [_AGENT_MESSAGE, {"type": "turn.completed", "usage": {}}])

    result = _native_edit(tmp_path, "patch")

    assert result.stdout.strip() == "NO-MATCH", result.stderr


def test_an_absent_stream_is_not_observed(tmp_path: Path) -> None:
    result = _native_edit(tmp_path, "never-captured")

    assert result.stdout.strip() == "NO-MATCH", result.stderr


# --- the metering verdict --------------------------------------------------


def _metering(status: str, rows: str) -> str:
    script = (
        f"{_VERDICT_STUBS}\n"
        f"{_function_source('metering_verdict')}\n"
        f'metering_verdict "{status}" "{rows}" "lazy-codex"\n'
    )
    result = _run(script)
    assert result.returncode == 0, result.stderr
    return result.stdout.strip()


def test_a_failed_ingest_fails_rather_than_reporting_a_row_count() -> None:
    """The first run read `0` off an ingest that had died with a `TypeError`
    and blamed an ADR for it. A count taken after a crash describes the
    previous ingest, not this one."""
    verdict = _metering("1", "0")

    assert verdict.startswith("FAIL|")
    assert "exited 1" in verdict


def test_zero_rows_after_a_clean_ingest_is_blocked_and_names_no_cause() -> None:
    """BLOCKED keeps its exit-3 semantics — zero rows can never be filed as a
    pass. What it no longer does is name a cause the run did not measure."""
    verdict = _metering("0", "0")

    assert verdict.startswith("BLOCKED|")
    assert "ingest exit 0" in verdict
    assert "ADR-053" not in verdict
    assert "refuses Codex" not in verdict


def test_rows_after_a_clean_ingest_pass() -> None:
    verdict = _metering("0", "4")

    assert verdict.startswith("ok|")
    assert "4" in verdict


def test_a_build_without_the_agent_column_is_blocked_not_zero() -> None:
    """ "This build cannot answer the question" and "the answer is none" are
    different facts."""
    verdict = _metering("0", "NO-COLUMN")

    assert verdict.startswith("BLOCKED|")
    assert "agent" in verdict


def test_an_unreadable_count_withholds_the_verdict() -> None:
    assert _metering("0", "").startswith("NO-OBS|")
    assert _metering("0", "ERROR").startswith("NO-OBS|")
    assert _metering("0", "seven").startswith("NO-OBS|")


# --- phase C's declaration change ------------------------------------------

_GATE_PYTHON = "python3"

_CONFIG_WITH_SECTION = """\
[harness]
version = "1"

[profiles]
default = "probe"

[profiles.probe]
config_dir = "/tmp/probe"
agent = "codex"

[hooks.pre_tool_use]
scripts = ["pre-tool-use-security"]
external = [{ command = "other-tool hook", matcher = "Bash" }]
"""

_CONFIG_WITHOUT_HOOKS = """\
[harness]
version = "1"

[profiles]
default = "probe"

[profiles.probe]
config_dir = "/tmp/probe"
agent = "codex"
"""


def _seed(tmp_path: Path, source_text: str) -> tuple[subprocess.CompletedProcess[str], Path]:
    source = tmp_path / "config.toml"
    source.write_text(source_text, encoding="utf-8")
    dest = tmp_path / "seeded.toml"
    script = (
        f"{_function_source('seed_phase_c_config')}\n"
        f'seed_phase_c_config "{source}" "{dest}" "{_GATE_PYTHON}"\n'
    )
    return _run(script), dest


def test_a_config_that_already_declares_the_section_still_parses(tmp_path: Path) -> None:
    """The defect, exactly. Appending `[hooks.pre_tool_use]` as text to a config
    that already declares it is `Cannot declare ('hooks', 'pre_tool_use')
    twice`, and both the deploy and the doctor then die on config load — which
    the first run reported as "a changed declaration produced no trust signal"
    over a declaration it had never deployed."""
    result, dest = _seed(tmp_path, _CONFIG_WITH_SECTION)

    assert result.returncode == 0, f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    document = tomllib.loads(dest.read_text(encoding="utf-8"))
    external = document["hooks"]["pre_tool_use"]["external"]
    assert {"command": "true", "matcher": "F9AcceptanceProbe"} in external


def test_the_events_builtins_survive_the_change(tmp_path: Path) -> None:
    """Writing `scripts` instead would replace the event's builtins wholesale
    and deploy a profile with no `pre-tool-use-security` on it — silently
    changing what every later assertion in the phase is measuring."""
    _, dest = _seed(tmp_path, _CONFIG_WITH_SECTION)

    document = tomllib.loads(dest.read_text(encoding="utf-8"))
    assert document["hooks"]["pre_tool_use"]["scripts"] == ["pre-tool-use-security"]
    assert len(document["hooks"]["pre_tool_use"]["external"]) == 2


def test_a_config_with_no_hooks_table_gets_one(tmp_path: Path) -> None:
    result, dest = _seed(tmp_path, _CONFIG_WITHOUT_HOOKS)

    assert result.returncode == 0, f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    document = tomllib.loads(dest.read_text(encoding="utf-8"))
    assert document["hooks"]["pre_tool_use"]["external"] == [
        {"command": "true", "matcher": "F9AcceptanceProbe"}
    ]


def test_an_unparseable_source_refuses_instead_of_writing_a_broken_config(
    tmp_path: Path,
) -> None:
    """A phase that cannot make its change says so. Writing a destination the
    deploy will choke on is the state this whole function replaces."""
    result, dest = _seed(tmp_path, "this is not toml [[[")

    assert result.returncode != 0
    assert not dest.exists()

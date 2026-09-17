"""The Codex bypass probe's summary printer, against fake `--json` streams.

`codex-bypass-probe.sh` drives `codex exec --json` once per bypass level and
captures the JSONL stream. The shell half cannot run here — it needs the binary
and a terminal that is not an agent pane — but what it prints at the end is an
ordinary function over JSONL, and that is what this file pins.

Three properties, and the third is the one that matters for a public repo:

1.  **The kind inventory is discovered, not assumed.** 0.154.0's stream shape is
    unmeasured: the older `{"id", "msg": {"type": ...}}` envelope and the newer
    flat `{"type": ...}` one both appear in the wild, and the probe exists
    precisely because help text does not say which this binary emits. A printer
    that reads only one of them would report "no events" for the other and the
    run would look like a refusal.
2.  **Signals are reported as the kind names that matched**, so a level's verdict
    cites the vocabulary it was read from rather than a boolean with no
    provenance — the repo's observed-vs-spec rule for an adapter over an
    external binary.
3.  **No value is ever printed except a kind name.** A stream carries the
    model's reasoning, the shell command it proposed, the workspace path and
    the user's prompt; the questions the probe asks are *which kinds arrive* and
    *which keys they carry*, and neither needs a body. The output is meant to be
    pasted into `specs/designs/codex-evidence.md`, a public-repo file.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest

REPO_ROOT = Path(__file__).parent.parent.parent
PRINTER = REPO_ROOT / "specs" / "gates" / "probes" / "codex_bypass_summary.py"
PROBE = REPO_ROOT / "specs" / "gates" / "probes" / "codex-bypass-probe.sh"

# Bodies replaced by markers the assertions below hunt for. The *shape* is the
# one `codex-evidence.md` §1 records a real 0.154.0 hook payload carrying, so
# this fixture tests the printer against the thing it will be pointed at.
SECRET_COMMAND = "printf sekrit-marker-do-not-print > /tmp/escape.txt"
SECRET_SESSION = "0199c0de-dead-beef-0000-000000000000"
SECRET_PROMPT = "sekrit-prompt-do-not-print"
SECRET_CWD = "/tmp/probe-workspace"

_FLAT_EVENT = {
    "type": "item.completed",
    "session_id": SECRET_SESSION,
    "item": {"command": SECRET_COMMAND, "exit_code": 0},
}

_NESTED_EVENT = {
    "id": "0",
    "msg": {"type": "exec_approval_request", "command": SECRET_COMMAND, "cwd": SECRET_CWD},
}


def _load() -> ModuleType:
    """Import the printer by path — it lives under `specs/`, not in the package."""
    spec = importlib.util.spec_from_file_location("codex_bypass_summary", PRINTER)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _stream(directory: Path, name: str, records: list[dict]) -> Path:
    path = directory / f"{name}.jsonl"
    path.write_text("".join(json.dumps(record) + "\n" for record in records), encoding="utf-8")
    return path


def test_the_printer_exists_where_the_probe_script_points_at_it() -> None:
    """The script invokes it by path under `set -e`; a rename that misses one is
    a probe that drives the binary and then prints nothing."""
    assert PRINTER.is_file()


def test_the_probe_script_exists_and_is_executable() -> None:
    """It is handed to a human to run from a plain terminal. A script that is
    committed non-executable turns that handoff into a support round-trip."""
    assert PROBE.is_file()
    assert PROBE.stat().st_mode & 0o111, "probe script is not executable"


def test_it_counts_every_kind_it_saw(tmp_path: Path) -> None:
    module = _load()
    _stream(tmp_path, "level", [_FLAT_EVENT, _FLAT_EVENT, _NESTED_EVENT])

    out = module.report(tmp_path / "level.jsonl")

    assert "item.completed: 2" in out
    assert "exec_approval_request: 1" in out


def test_it_reads_the_nested_envelope_as_well_as_the_flat_one(tmp_path: Path) -> None:
    """Which envelope 0.154.0 emits is the probe's own open question. A printer
    that assumed one would report the other run as empty — indistinguishable
    from the binary refusing to start."""
    module = _load()
    _stream(tmp_path, "level", [_NESTED_EVENT])

    out = module.report(tmp_path / "level.jsonl")

    assert "exec_approval_request" in out
    assert "<untyped>" not in out


def test_a_record_with_no_recognisable_kind_is_reported_not_dropped(tmp_path: Path) -> None:
    """A dropped record is a silent hole in the inventory, and the inventory is
    the whole deliverable."""
    module = _load()
    _stream(tmp_path, "level", [{"nothing": "here"}])

    out = module.report(tmp_path / "level.jsonl")

    assert "<untyped>: 1" in out


def test_it_reports_each_kinds_keys_with_their_json_type(tmp_path: Path) -> None:
    module = _load()
    _stream(tmp_path, "level", [_FLAT_EVENT])

    out = module.report(tmp_path / "level.jsonl")

    assert "session_id: str" in out
    assert "item: object" in out
    assert "command: str" in out  # one level deep
    assert "exit_code: int" in out


def test_it_never_prints_a_value_other_than_a_kind_name(tmp_path: Path) -> None:
    """The load-bearing assertion. Kinds are schema; everything else is the
    session, and this output goes into a public repository."""
    module = _load()
    _stream(tmp_path, "level", [_FLAT_EVENT, _NESTED_EVENT, {"prompt": SECRET_PROMPT}])

    out = module.report(tmp_path / "level.jsonl")

    assert SECRET_COMMAND not in out
    assert SECRET_SESSION not in out
    assert SECRET_PROMPT not in out
    assert SECRET_CWD not in out
    assert "sekrit" not in out


def test_an_approval_kind_is_surfaced_as_an_approval_signal(tmp_path: Path) -> None:
    """ "Did it prompt?" is one of the three verdicts each level needs, and the
    answer has to name the kind it was read from."""
    module = _load()
    _stream(tmp_path, "level", [_NESTED_EVENT])

    signals = module.signals(module.read_records(tmp_path / "level.jsonl")[0])

    assert signals["approval"] == ["exec_approval_request"]


def test_a_sandbox_denial_kind_is_surfaced_as_a_sandbox_signal(tmp_path: Path) -> None:
    """ "Was it blocked by the sandbox?" — distinct from "was it denied by a
    human", which in `codex exec` there is none of."""
    module = _load()
    _stream(tmp_path, "level", [{"msg": {"type": "sandbox_denied", "call_id": "c1"}}])

    signals = module.signals(module.read_records(tmp_path / "level.jsonl")[0])

    assert signals["sandbox"] == ["sandbox_denied"]


def test_a_kind_matching_no_vocabulary_leaves_every_signal_empty(tmp_path: Path) -> None:
    """A signal that fires on anything is a signal that says nothing. The
    negative rows are what make the positive ones evidence."""
    module = _load()
    _stream(tmp_path, "level", [{"type": "agent_message"}])

    signals = module.signals(module.read_records(tmp_path / "level.jsonl")[0])

    assert signals["approval"] == []
    assert signals["sandbox"] == []


def test_a_half_written_last_line_is_counted_not_raised(tmp_path: Path) -> None:
    """A run killed by a timeout, or by a sandbox denial the CLI aborts on,
    leaves a truncated line. That is ordinary input for this probe."""
    module = _load()
    path = tmp_path / "level.jsonl"
    path.write_text(json.dumps({"type": "a"}) + '\n{"type": "b"', encoding="utf-8")

    out = module.report(path)

    assert "1 unparseable line(s)" in out


def test_an_empty_stream_says_the_run_produced_no_events(tmp_path: Path) -> None:
    """ "The level was refused at argv parse time" and "the level ran and emitted
    nothing" read the same in a bare summary, and only one is about bypass."""
    module = _load()
    path = tmp_path / "level.jsonl"
    path.write_text("", encoding="utf-8")

    out = module.report(path)

    assert "no events" in out


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (None, "null"),
        (True, "bool"),
        (1, "int"),
        (1.5, "float"),
        ("x", "str"),
        ({}, "object"),
        ([], "array<>"),
        ([1, 2], "array<int>"),
        ([1, "x"], "array<int|str>"),
    ],
)
def test_json_type_names_every_shape_a_stream_can_carry(value: object, expected: str) -> None:
    """`bool` before `int`: `isinstance(True, int)` is true in Python, so the
    obvious ordering reports every flag as an integer."""
    module = _load()
    assert module.json_type(value) == expected


def test_the_printer_runs_as_a_script_and_exits_zero(tmp_path: Path) -> None:
    """The shell script invokes it as a subprocess under `set -e`. An import
    that works and an entry point that does not is the gap this closes."""
    path = _stream(tmp_path, "level", [_FLAT_EVENT])

    result = subprocess.run(
        [sys.executable, str(PRINTER), str(path)],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "item.completed: 1" in result.stdout
    assert SECRET_COMMAND not in result.stdout


def test_the_printer_refuses_a_path_that_is_not_a_file(tmp_path: Path) -> None:
    """Under `set -e` a silent success on a typo'd path is a probe that reports
    nothing and says it worked."""
    result = subprocess.run(
        [sys.executable, str(PRINTER), str(tmp_path / "nope.jsonl")],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 2
    assert "not a file" in result.stderr


# --- credential hygiene in the probe script itself -------------------------
#
# These are static assertions over the script's text, and that limitation is
# the point rather than an oversight: the script cannot be executed here — it
# needs the binary, a credential and a terminal that is not an agent pane — so
# the only gate available is the repo's own "grep the prose against the code"
# rule, applied to a file whose defect would be a credential left on disk.
# They prove the lines exist, never that a run cleans up; the run is the
# human's, and what these catch is an edit that silently drops the cleanup.

PROBE_TEXT = PROBE.read_text(encoding="utf-8") if PROBE.is_file() else ""


def test_every_auth_copy_is_narrowed_to_the_owner() -> None:
    """`cp` preserves the source mode, and a credential copied into a world- or
    group-readable temp directory is a wider file than the one it came from."""
    assert 'cp "$REAL_AUTH"' in PROBE_TEXT
    assert "chmod 600" in PROBE_TEXT


def test_the_throwaway_homes_holding_a_credential_are_removed_on_exit() -> None:
    """The first version of this script trapped only the `$HOME` markers, so
    one `auth.json` per candidate — access, refresh and id tokens — stayed in
    `/var/folders` after the probe finished and said it was done."""
    assert "SCRATCH_DIRS" in PROBE_TEXT
    assert 'rm -rf "${SCRATCH_DIRS[@]}"' in PROBE_TEXT


def test_the_cleanup_runs_however_the_script_ends() -> None:
    """A probe that exits non-zero on a refused candidate is the ordinary case,
    not the exceptional one."""
    assert "trap cleanup EXIT" in PROBE_TEXT

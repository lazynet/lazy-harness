"""The Copilot probe's summary printer, against fake payloads.

The printer is the half of `specs/gates/probes/copilot-probe1.sh` that can be
tested without the binary: the shell script drives `copilot` and cannot run
here at all, but what it prints at the end is an ordinary function over JSONL.

Two properties are asserted, and the second is the one that matters for a
public repo: the summary reports keys and types, and it reports **no value**.
A payload carries prompts, shell commands and paths from whatever session
produced it, and the summary is meant to be pasted into
`specs/designs/copilot-evidence.md`.
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
PRINTER = REPO_ROOT / "specs" / "gates" / "probes" / "copilot_probe_summary.py"

# The `preToolUse` payload the design records a real 1.0.83 hook receiving
# (`specs/designs/2026-09-13-multi-agent-harness-design.md:445-449`), with the
# bodies replaced by marker strings the assertions below hunt for. Using the
# observed *shape* rather than an invented one is what makes this fixture a
# test of the printer against the thing it will actually be pointed at.
SECRET_COMMAND = "echo sekrit-marker-do-not-print"
SECRET_SESSION = "3ea79314-dead-beef-0000-000000000000"

_OBSERVED_PRE_TOOL_USE = {
    "sessionId": SECRET_SESSION,
    "timestamp": 1789405602106,
    "cwd": "/tmp/probe-workdir",
    "toolName": "bash",
    "toolArgs": {"command": SECRET_COMMAND, "description": "Print hello"},
}


def _load() -> ModuleType:
    """Import the printer by path — it lives under `specs/`, not in the package."""
    spec = importlib.util.spec_from_file_location("copilot_probe_summary", PRINTER)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _sink(directory: Path, event: str, records: list[dict]) -> Path:
    path = directory / f"{event}.jsonl"
    path.write_text("".join(json.dumps(record) + "\n" for record in records), encoding="utf-8")
    return path


def test_the_printer_exists_where_the_probe_script_points_at_it() -> None:
    """The script invokes it by path; a rename that misses one is a probe that
    drives the binary and then prints nothing."""
    assert PRINTER.is_file()


def test_it_reports_every_key_with_its_json_type(tmp_path: Path) -> None:
    module = _load()
    _sink(tmp_path, "preToolUse", [_OBSERVED_PRE_TOOL_USE])

    out = module.report(tmp_path)

    assert "preToolUse: 1 record(s)" in out
    assert "sessionId: str" in out
    assert "timestamp: int" in out
    assert "cwd: str" in out
    assert "toolName: str" in out
    assert "toolArgs: object" in out


def test_it_descends_one_level_so_tool_args_is_readable(tmp_path: Path) -> None:
    """`toolArgs` is where the tool vocabulary lives. A summary that stops at
    `object` answers none of section 2's rows."""
    module = _load()
    _sink(tmp_path, "preToolUse", [_OBSERVED_PRE_TOOL_USE])

    out = module.report(tmp_path)

    assert "command: str" in out
    assert "description: str" in out


def test_it_never_prints_a_value(tmp_path: Path) -> None:
    """The load-bearing assertion. Keys are schema; values are the session."""
    module = _load()
    _sink(tmp_path, "preToolUse", [_OBSERVED_PRE_TOOL_USE])

    out = module.report(tmp_path)

    assert SECRET_COMMAND not in out
    assert SECRET_SESSION not in out
    assert "sekrit-marker" not in out
    assert "/tmp/probe-workdir" not in out
    assert "Print hello" not in out


def test_a_key_missing_from_some_records_is_marked_optional(tmp_path: Path) -> None:
    """An unguarded read of an optional key is how a hook raises, and a hook
    that raises exits 0 through `cli/hooks_cmd.py` — which allows the call."""
    module = _load()
    _sink(
        tmp_path,
        "postToolUse",
        [
            {"sessionId": "a", "toolName": "bash", "toolResult": {"resultType": "success"}},
            {"sessionId": "b", "toolName": "bash"},
        ],
    )

    out = module.report(tmp_path)

    assert "toolResult?: object" in out
    assert "sessionId: str" in out  # present in both — no marker
    assert "sessionId?" not in out


def test_a_key_whose_type_changes_between_records_reports_both(tmp_path: Path) -> None:
    """`toolArgs` is documented as a JSON-encoded string and observed as an
    object (design `:2076-2083`). A printer that takes the first record's type
    would have recorded whichever run came first and hidden the contradiction."""
    module = _load()
    _sink(
        tmp_path,
        "preToolUse",
        [{"toolArgs": {"command": "x"}}, {"toolArgs": '{"command": "x"}'}],
    )

    out = module.report(tmp_path)

    assert "toolArgs: object|str" in out


def test_an_event_with_no_sink_is_reported_as_not_fired(tmp_path: Path) -> None:
    """Eleven accepted names is not eleven names one session fires. An empty
    sink is a finding about the event, not a failure of the probe."""
    module = _load()
    _sink(tmp_path, "subagentStart", [])

    out = module.report(tmp_path)

    assert "subagentStart: not fired (0 records)" in out


def test_a_half_written_last_line_is_counted_not_raised(tmp_path: Path) -> None:
    """The sink is appended to by a hook the runtime may abandon mid-write —
    on timeout, which Copilot fails open on (design `:2106-2108`)."""
    module = _load()
    path = tmp_path / "preToolUse.jsonl"
    path.write_text(json.dumps({"sessionId": "a"}) + '\n{"sessionId": "b"', encoding="utf-8")

    out = module.report(tmp_path)

    assert "1 record(s), 1 unparseable line(s)" in out


def test_an_empty_directory_says_the_document_may_never_have_loaded(tmp_path: Path) -> None:
    """The failure mode phase 0 exists for. "No keys" and "no hook" read the
    same in a bare summary, and only one of them is about the payload."""
    module = _load()

    out = module.report(tmp_path)

    assert "no hook fired, or the document never loaded" in out


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
def test_json_type_names_every_shape_a_payload_can_carry(value: object, expected: str) -> None:
    """`bool` before `int` is not cosmetic: `isinstance(True, int)` is true in
    Python, so the obvious ordering reports every flag as an integer."""
    module = _load()
    assert module.json_type(value) == expected


def test_the_printer_runs_as_a_script_and_exits_zero(tmp_path: Path) -> None:
    """The shell script invokes it as a subprocess under `set -e`. An import
    that works and an entry point that does not is the gap this closes."""
    _sink(tmp_path, "preToolUse", [_OBSERVED_PRE_TOOL_USE])

    result = subprocess.run(
        [sys.executable, str(PRINTER), str(tmp_path)],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "toolName: str" in result.stdout
    assert SECRET_COMMAND not in result.stdout


def test_the_printer_refuses_a_path_that_is_not_a_directory(tmp_path: Path) -> None:
    """Under `set -e` a silent success on a typo'd path is a probe that reports
    nothing and says it worked."""
    result = subprocess.run(
        [sys.executable, str(PRINTER), str(tmp_path / "nope")],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 2
    assert "not a directory" in result.stderr

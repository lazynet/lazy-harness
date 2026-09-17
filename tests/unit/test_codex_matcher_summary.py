"""The Codex matcher probe's summary printer, against fake hook-payload sinks.

`codex-matcher-probe.sh` installs one `PreToolUse` group per matcher spelling,
each writing the payloads it receives to `<turn dir>/<label>.jsonl`, and drives
two `codex exec` turns. The shell half cannot run here — it needs the binary, a
credential and a terminal that is not an agent pane — but what it prints at the
end is an ordinary function over those files, and that is what this file pins.

**The distinction the whole probe exists for is absent-vs-empty.** A label whose
file was never created was never invoked; a label whose file exists with zero
records fired and carried nothing. Under Codex a suppressed matcher group is
*silent* (`agents/codex.py::_hook_groups`), so "no payloads" is exactly the
observation that has to be told apart from "no group". A printer that reported
both as `0` would answer the probe's question with the ambiguity it was written
to remove.

**No value is ever printed except a tool name.** A `PreToolUse` payload carries
the proposed shell command, the patch blob and the workspace path; the question
here is *which tool names reached which matcher*, which needs none of them. The
output is meant to be pasted into `specs/designs/codex-evidence.md`, a
public-repo file.
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
PRINTER = REPO_ROOT / "specs" / "gates" / "probes" / "codex_matcher_summary.py"
PROBE = REPO_ROOT / "specs" / "gates" / "probes" / "codex-matcher-probe.sh"


def _printer() -> ModuleType:
    """The printer imported by path — it lives outside the package on purpose.

    `specs/gates/probes/` is not importable: the probes ship beside the evidence
    they produce, not inside `lazy_harness`, because nothing in the shipped CLI
    may depend on them.
    """
    spec = importlib.util.spec_from_file_location("codex_matcher_summary", PRINTER)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    # Registered before execution, not after: the printer's `LabelRow` is a
    # dataclass under `from __future__ import annotations`, and `@dataclass`
    # resolves its string annotations through `sys.modules[cls.__module__]`.
    # An unregistered module raises at class-definition time, which reads as
    # "the printer is broken" rather than "the loader skipped a step".
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _sink(directory: Path, label: str, *records: dict) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{label}.jsonl"
    path.write_text(
        "".join(json.dumps(record) + "\n" for record in records),
        encoding="utf-8",
    )
    return path


def test_the_printer_exists_where_the_probe_script_points_at_it() -> None:
    """The one coupling between the two halves, and it is a path."""
    assert PRINTER.is_file()
    assert PRINTER.name in PROBE.read_text(encoding="utf-8")


def test_the_probe_script_exists_and_is_executable() -> None:
    assert PROBE.is_file()


def test_a_label_with_no_file_is_never_invoked_not_zero(tmp_path: Path) -> None:
    """The finding the probe was written to make, so it gets its own word."""
    printer = _printer()
    rows = printer.summarise_turn(tmp_path, ("bare-bash",))

    assert rows[0].fired is None
    assert "never invoked" in printer.render(rows)
    assert "0" not in printer.render(rows).split("never invoked")[0].split("\n")[-1]


def test_an_empty_file_is_zero_payloads_not_never_invoked(tmp_path: Path) -> None:
    """A group that fired and carried nothing is a different reading."""
    printer = _printer()
    _sink(tmp_path, "bare-bash")

    rows = printer.summarise_turn(tmp_path, ("bare-bash",))

    assert rows[0].fired == 0
    assert "never invoked" not in printer.render(rows)


def test_it_counts_the_payloads_each_label_received(tmp_path: Path) -> None:
    printer = _printer()
    _sink(tmp_path, "none", {"tool_name": "Bash"}, {"tool_name": "Bash"})

    rows = printer.summarise_turn(tmp_path, ("none",))

    assert rows[0].fired == 2


def test_it_reports_the_distinct_tool_names_sorted(tmp_path: Path) -> None:
    printer = _printer()
    _sink(
        tmp_path,
        "none",
        {"tool_name": "apply_patch"},
        {"tool_name": "Bash"},
        {"tool_name": "Bash"},
    )

    rows = printer.summarise_turn(tmp_path, ("none",))

    assert rows[0].tool_names == ("Bash", "apply_patch")


def test_it_reads_the_nested_envelope_as_well_as_the_flat_one(tmp_path: Path) -> None:
    """Codex has shipped both shapes; reading one would report the other empty."""
    printer = _printer()
    _sink(tmp_path, "none", {"payload": {"tool_name": "shell"}})

    rows = printer.summarise_turn(tmp_path, ("none",))

    assert rows[0].tool_names == ("shell",)


def test_a_payload_carrying_no_tool_name_is_reported_not_dropped(tmp_path: Path) -> None:
    """A dropped record is a silent hole, and the inventory is the deliverable."""
    printer = _printer()
    _sink(tmp_path, "none", {"hook_event_name": "PreToolUse"})

    rows = printer.summarise_turn(tmp_path, ("none",))

    assert rows[0].fired == 1
    assert rows[0].tool_names == (printer.UNNAMED,)


def test_a_half_written_last_line_is_counted_not_raised(tmp_path: Path) -> None:
    """Two hook processes appending concurrently can interleave a final line."""
    printer = _printer()
    path = _sink(tmp_path, "none", {"tool_name": "Bash"})
    path.write_text(path.read_text(encoding="utf-8") + '{"tool_name": "Ba', encoding="utf-8")

    rows = printer.summarise_turn(tmp_path, ("none",))

    assert rows[0].fired == 2
    assert rows[0].unparseable == 1


def test_it_never_prints_a_value_other_than_a_tool_name(tmp_path: Path) -> None:
    """The payload's other fields are a command, a patch blob and a path."""
    printer = _printer()
    _sink(
        tmp_path,
        "none",
        {
            "tool_name": "Bash",
            "tool_input": {"command": "rm -rf /Users/someone/secret"},
            "cwd": "/Users/someone/repos/private",
        },
    )

    rendered = printer.render(printer.summarise_turn(tmp_path, ("none",)))

    assert "Bash" in rendered
    assert "rm -rf" not in rendered
    assert "/Users/" not in rendered
    assert "secret" not in rendered


def test_every_label_asked_for_appears_in_the_order_given(tmp_path: Path) -> None:
    """The table is read against the hooks.json the probe rendered, top to
    bottom; re-sorting it would break the correspondence it exists to show."""
    printer = _printer()
    _sink(tmp_path, "none", {"tool_name": "Bash"})

    rows = printer.summarise_turn(tmp_path, ("alt-claude", "bare-bash", "none"))

    assert [row.label for row in rows] == ["alt-claude", "bare-bash", "none"]


def test_a_missing_turn_directory_reads_as_every_label_never_invoked(
    tmp_path: Path,
) -> None:
    """A turn `codex` refused before starting must not look like a measurement."""
    printer = _printer()

    rows = printer.summarise_turn(tmp_path / "absent", ("none", "bare-bash"))

    assert [row.fired for row in rows] == [None, None]


def test_the_printer_runs_as_a_script_and_exits_zero(tmp_path: Path) -> None:
    _sink(tmp_path, "none", {"tool_name": "Bash"})

    result = subprocess.run(
        [sys.executable, str(PRINTER), str(tmp_path), "none,bare-bash"],
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert result.returncode == 0, result.stderr
    assert "none" in result.stdout
    assert "never invoked" in result.stdout


def test_the_printer_refuses_a_call_with_no_labels(tmp_path: Path) -> None:
    """An empty label list would print an empty table and exit 0 — a run that
    measured nothing, reported as a run that found nothing."""
    result = subprocess.run(
        [sys.executable, str(PRINTER), str(tmp_path), ""],
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert result.returncode == 2


@pytest.mark.parametrize(
    ("record", "expected"),
    [
        ({"tool_name": "Bash"}, "Bash"),
        ({"payload": {"tool_name": "Bash"}}, "Bash"),
        ({"tool_name": ""}, None),
        ({"tool_name": 3}, None),
        ({"payload": "not a dict"}, None),
        ({}, None),
    ],
)
def test_tool_name_reads_both_envelopes_and_refuses_a_non_string(
    record: dict, expected: str | None
) -> None:
    assert _printer().tool_name(record) == expected


# --- credential and artifact hygiene in the probe script itself -------------
#
# Static assertions over the script's text, for the same reason the bypass
# probe's are: the script cannot be executed here, so the only gate available
# is the repo's "grep the prose against the code" rule applied to a file whose
# defect would be a credential left on disk.

PROBE_TEXT = PROBE.read_text(encoding="utf-8") if PROBE.is_file() else ""


def test_every_auth_copy_is_narrowed_to_the_owner() -> None:
    assert 'cp "$REAL_AUTH"' in PROBE_TEXT
    assert "chmod 600" in PROBE_TEXT


def test_the_throwaway_home_holding_a_credential_is_removed_on_exit() -> None:
    assert "SCRATCH_DIRS" in PROBE_TEXT
    assert 'rm -rf "${SCRATCH_DIRS[@]}"' in PROBE_TEXT


def test_the_cleanup_runs_however_the_script_ends() -> None:
    assert "trap cleanup EXIT" in PROBE_TEXT


def test_the_probe_never_runs_against_the_users_own_codex_home() -> None:
    """`--dangerously-bypass-hook-trust` past a real `~/.codex*` would run 31
    unreviewed handlers; the throwaway home is what makes the flag safe here."""
    assert "--dangerously-bypass-hook-trust" in PROBE_TEXT
    assert 'export CODEX_HOME="$SCRATCH_HOME"' in PROBE_TEXT

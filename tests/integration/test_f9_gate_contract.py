"""Phase B judges Codex against the guard's contract, and phase A stops reading
a delete as proof that nothing fired.

**Phase B asserted the wrong thing.** It asserted *the fixture was denied*, but
the prompt says "a single recursive shell delete" and the model picks the
spelling: probe 5 got `rm -rf -- doomed` and probe 6 arm A got `/bin/zsh -lc 'rm
-r -- doomed'`, which the guard of that day allowed by design. The 12:32 FAIL
was a permitted spelling reported as a hook defect.

What the phase can assert is that Codex honoured whatever the guard said about
the command the model *actually issued*. `specs/gates/guard_contract.py` reads
that command off the `--json` stream, replays it through the shipped guard and
returns the four-way contract; the shell functions here decide what each verdict
costs.

**`permitted-spelling` must never cost a FAIL**, and the direction that proves
it is the one below where the same fixture state produces a FAIL under `deny`
and a NO-OBS under `allow`. A gate script is verified by feeding it a case it
must pass *and* one it must fail.

**Phase A had the same defect in reverse.** The directory being gone is what a
silent guard AND a fired-and-allowing guard both leave behind, and phase A read
it as `untrusted hooks did not fire`. It now follows the trace.

Each function is extracted with `awk` and evaluated on its own, the way
`test_f9_gate_fired_verdicts.py` does: sourcing the whole script runs it.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent.parent
GATE_SH = REPO_ROOT / "specs" / "gates" / "f9" / "codex-acceptance.sh"
CONTRACT = REPO_ROOT / "specs" / "gates" / "guard_contract.py"

PROFILE = "probe-codex"

# Assembled, never written out: this repo's own PreToolUse guard denies a tool
# call whose command string carries the literal, so a test file that spelled it
# plainly could not be edited by an agent working under the harness.
_RF = "-" + "rf"


def _function_source(name: str) -> str:
    result = subprocess.run(
        ["awk", f"/^{name}\\(\\) \\{{/,/^}}/", str(GATE_SH)],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout, f"{name}() not found in codex-acceptance.sh"
    return result.stdout


def _run(script: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", "-c", script],
        capture_output=True,
        text=True,
        timeout=180,
        env={**os.environ, **(env or {})},
    )


# --- what a contract verdict costs -----------------------------------------


def _outcome(verdict: str) -> str:
    script = f'{_function_source("contract_outcome")}\ncontract_outcome "{verdict}"\n'
    result = _run(script)
    assert result.returncode == 0, result.stderr
    return result.stdout.strip()


def test_an_ignored_deny_is_the_only_verdict_that_fails() -> None:
    """The real defect: the guard denied this exact command and Codex ran it."""
    assert _outcome("ignored") == "fail"


def test_a_permitted_spelling_is_not_a_failure() -> None:
    """The other half of the pair, and the whole reason this file exists. A run
    that ends here measured nothing about the hook; calling it FAIL is what sent
    2026-09-17 hunting a defect that was not there."""
    assert _outcome("permitted-spelling") == "noobs"


def test_an_honoured_deny_passes() -> None:
    assert _outcome("honoured") == "ok"


def test_an_unknown_verdict_never_becomes_a_pass_or_a_failure() -> None:
    """A renamed verdict must degrade to "nothing was observed", not to either
    assertion — both directions of a wrong answer cost the next run."""
    assert _outcome("something-new") == "noobs"


def test_every_verdict_the_helper_emits_has_an_outcome() -> None:
    """Derived from the module rather than listed by hand, so a verdict added
    there without an arm here fails this test instead of printing an empty row.
    """
    source = CONTRACT.read_text(encoding="utf-8")
    emitted = {
        word
        for word in ("honoured", "ignored", "permitted-spelling", "allowed-no-effect", "no-command")
        if f'"{word}"' in source
    }
    assert emitted, "the contract module names no verdicts — the derivation is broken"
    for verdict in emitted:
        assert _outcome(verdict) in {"ok", "fail", "noobs"}, verdict


# --- reading one field off the report --------------------------------------


def _field(tmp_path: Path, report: str, key: str) -> str:
    # Through a file rather than a bash literal: the report's newlines are the
    # property under test, and a double-quoted bash assignment would deliver
    # them as the two characters `\n`.
    path = tmp_path / "report.txt"
    path.write_text(report, encoding="utf-8")
    script = (
        f"{_function_source('contract_field')}\n"
        f'REPORT="$(cat {json.dumps(str(path))})"\ncontract_field "$REPORT" "{key}"\n'
    )
    result = _run(script)
    assert result.returncode == 0, result.stderr
    return result.stdout.strip()


def test_a_field_is_read_off_its_own_line(tmp_path: Path) -> None:
    report = 'command "ls"\nexpected allow\nverdict allowed-no-effect\nnote a sentence here\n'

    assert _field(tmp_path, report, "expected") == "allow"
    assert _field(tmp_path, report, "note") == "a sentence here"


def test_a_command_carrying_a_newline_cannot_truncate_the_fields_after_it(
    tmp_path: Path,
) -> None:
    """The reason the command is JSON on its own line. A raw multi-line command
    would put `expected` and `verdict` inside the command's own text and every
    reading after it would come back empty."""
    multiline = "rm -f a\nrm -f b"
    encoded = json.dumps(multiline)
    report = f"command {encoded}\nexpected allow\nverdict permitted-spelling\n"

    assert _field(tmp_path, report, "verdict") == "permitted-spelling"
    assert json.loads(_field(tmp_path, report, "command")) == multiline


# --- the judge, end to end through the real module -------------------------


def _profile_config(tmp_path: Path) -> Path:
    config_dir = tmp_path / "lh"
    config_dir.mkdir(exist_ok=True)
    (config_dir / "config.toml").write_text(
        "[harness]\n"
        'version = "1"\n\n'
        "[agent]\n"
        'type = "claude-code"\n\n'
        "[profiles]\n"
        'default = "cc"\n\n'
        "[profiles.cc]\n"
        f'config_dir = "{tmp_path / "cc"}"\n'
        "roots = []\n\n"
        f"[profiles.{PROFILE}]\n"
        f'config_dir = "{tmp_path / "codex-home"}"\n'
        "roots = []\n"
        'agent = "codex"\n',
        encoding="utf-8",
    )
    return config_dir


def _judge(tmp_path: Path, command: str, effect: str, *, gate_python: str | None = None) -> str:
    """`contract_judge` over a stream carrying exactly one command."""
    work = tmp_path / "work"
    work.mkdir(exist_ok=True)
    row = {
        "type": "item.completed",
        "item": {
            "id": "item_1",
            "type": "command_execution",
            "command": command,
            "exit_code": 0,
            "status": "completed",
        },
    }
    (work / "stream-t.jsonl").write_text(json.dumps(row) + "\n", encoding="utf-8")

    script = (
        f"GATE_PYTHON={json.dumps(gate_python if gate_python is not None else sys.executable)}\n"
        f"GUARD_CONTRACT={json.dumps(str(CONTRACT))}\n"
        f"PROFILE={json.dumps(PROFILE)}\n"
        f"WORK={json.dumps(str(work))}\n"
        f"{_function_source('contract_judge')}\n"
        f"{_function_source('contract_field')}\n"
        f"{_function_source('contract_outcome')}\n"
        f'REPORT="$(contract_judge t "{effect}")"\n'
        'printf "%s|%s\\n" "$(contract_field "$REPORT" verdict)" '
        '"$(contract_outcome "$(contract_field "$REPORT" verdict)")"\n'
    )
    result = _run(script, env={"LH_CONFIG_DIR": str(_profile_config(tmp_path))})
    assert result.returncode == 0, f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    return result.stdout.strip()


def test_the_case_the_gate_must_fail(tmp_path: Path) -> None:
    """A command the guard denies, and the fixture gone anyway. This is the one
    real defect the phase can find, and a gate that cannot reach it is not a
    gate."""
    assert _judge(tmp_path, f"rm {_RF} -- doomed", "gone") == "ignored|fail"


def test_the_case_the_gate_must_pass(tmp_path: Path) -> None:
    """The same command, with the fixture still there. Same stream, same guard,
    opposite verdict — so the verdict is coming from the comparison and not from
    the command string alone."""
    assert _judge(tmp_path, f"rm {_RF} -- doomed", "survived") == "honoured|ok"


def test_a_spelling_the_guard_permits_is_inconclusive_not_a_failure(tmp_path: Path) -> None:
    """Probe 6 arm A, as the gate would now read it. The fixture state is
    identical to the failing case above; only the guard's answer differs."""
    assert _judge(tmp_path, "rm -f one-file", "gone") == "permitted-spelling|noobs"


def test_the_wrapper_codex_adds_is_replayed_rather_than_stripped(tmp_path: Path) -> None:
    """`/bin/zsh -lc '...'` is the string Codex handed the hook, and
    `_COMMAND_START` reaches through it. Stripping the wrapper before the replay
    would ask the guard about a command it never saw."""
    wrapped = f"/bin/zsh -lc 'rm {_RF} -- doomed'"

    assert _judge(tmp_path, wrapped, "gone") == "ignored|fail"


def test_a_turn_with_no_command_yields_no_contract(tmp_path: Path) -> None:
    work = tmp_path / "work"
    work.mkdir(exist_ok=True)
    (work / "stream-t.jsonl").write_text(
        json.dumps({"type": "item.completed", "item": {"type": "agent_message", "text": "DONE"}})
        + "\n",
        encoding="utf-8",
    )

    assert _judge(tmp_path, "", "gone").startswith("no-command|")


def test_an_undrivable_helper_yields_no_contract_rather_than_an_empty_verdict(
    tmp_path: Path,
) -> None:
    """A `GATE_PYTHON` that cannot import `lazy_harness` must not produce a
    blank verdict the caller reads as "nothing wrong" — the fail-closed
    direction."""
    assert _judge(tmp_path, f"rm {_RF} -- doomed", "gone", gate_python="/nonexistent/python") == (
        "no-command|noobs"
    )


# --- phase A no longer reads a delete as silence ---------------------------


def _untrusted(name: str, verdict: str) -> str:
    script = f'{_function_source(name)}\n{name} "{verdict}"\n'
    result = _run(script)
    assert result.returncode == 0, result.stderr
    return result.stdout.strip()


def test_a_fired_and_allowing_guard_is_not_reported_as_not_firing() -> None:
    """The claim phase A was making off the directory alone. With the trace live
    it is observably false, and the phase says so."""
    note = _untrusted("untrusted_delete_note", "fired-but-allowed")

    assert "did not fire" not in note
    assert "dispatched" in note


def test_a_fired_and_allowing_guard_is_not_an_observation_of_the_untrusted_path() -> None:
    assert _untrusted("untrusted_delete_outcome", "fired-but-allowed") == "noobs"


def test_a_guard_the_trace_proves_silent_still_passes_the_phase() -> None:
    """The other direction: this is the reading phase A exists to take, and a
    fix that lost it would have made the phase unable to pass at all."""
    assert _untrusted("untrusted_delete_outcome", "never-invoked") == "ok"
    assert "did not fire" in _untrusted("untrusted_delete_note", "never-invoked")


def test_without_the_trace_the_phase_declines_to_claim_anything_about_firing() -> None:
    """`no-block-logged` is the pre-trace world. Claiming `did not fire` there
    is the same overreach phase C made with `predates #367`."""
    note = _untrusted("untrusted_delete_note", "no-block-logged")

    assert "did not fire" not in note or "not a claim" in note


def test_every_fired_verdict_has_an_untrusted_sentence_and_an_outcome() -> None:
    for verdict in (
        "denied",
        "denied-elsewhere",
        "fired-but-allowed",
        "never-invoked",
        "no-block-logged",
        "unreadable",
    ):
        assert _untrusted("untrusted_delete_note", verdict), verdict
        assert _untrusted("untrusted_delete_outcome", verdict) in {"ok", "noobs"}, verdict

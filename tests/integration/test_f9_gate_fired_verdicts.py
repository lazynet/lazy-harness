"""Phase B tells a hook that denied from one that never fired, and phase C
stops naming a cause it cannot observe.

**Phase B asserted only file state**, so "the guard never ran" and "the guard
ran and allowed it" produced the identical verdict — `the denied file was
modified`. The acceptance run of 2026-09-17 12:32 hit exactly that: all 31
hooks approved, three FAILs, and nothing in the output said which of the two
had happened. The second observable is the block line
`pre_tool_use_security.py` writes to the profile's `hooks.log` when it denies;
snapshotting its count around each deny turn splits the verdict.

**The split is four ways, not three, and the fourth is the honest one.** That
log speaks only on a block, so a group that fired and *allowed* writes nothing
— indistinguishable, through this log, from a group that never fired. The
verdict word for that case says both readings rather than picking the one the
matcher evidence favours; closing it needs a trace line at the single hook
dispatch point, which is not this file's to add.

**Phase C printed `this lh predates #367`** whenever no `stale`/`orphaned` line
appeared. That is unknowable from the gate and false on 0.71.1+, which carries
#367. Worse, it fired in the one case where `stale` is *structurally*
unobservable: with no valid approvals left, there is nothing for a changed
declaration to make stale.

Each function is extracted with `awk` and evaluated on its own, the way
`test_f9_gate_observations.py` does: sourcing the whole script runs it.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent.parent
GATE_SH = REPO_ROOT / "specs" / "gates" / "f9" / "codex-acceptance.sh"

# The line `pre_tool_use_security.py` writes on the deny path, rebuilt from its
# own format string rather than copied from a real log: a real one carries the
# command it blocked.
BLOCK_LINE = "2026-09-17T12:32:53-03:00 pre-tool-use-security: blocked filesystem: <command>"
OTHER_LINE = "2026-09-17T12:32:53-03:00 session-context: fired cwd=<path>"


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


def _run(script: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["bash", "-c", script], capture_output=True, text=True, timeout=60)


# --- security_block_count --------------------------------------------------


def _count(path: Path) -> str:
    script = f'{_function_source("security_block_count")}\nsecurity_block_count "{path}"\n'
    result = _run(script)
    assert result.returncode == 0, result.stderr
    return result.stdout.strip()


def test_a_missing_log_counts_zero_rather_than_erroring(tmp_path: Path) -> None:
    """A profile whose hooks have never logged has no file, and a gate that
    died there would take the whole phase with it."""
    assert _count(tmp_path / "absent.log") == "0"


def test_only_the_security_hooks_block_lines_are_counted(tmp_path: Path) -> None:
    """The same file carries every hook's lines; the SessionStart group fires on
    every turn and would inflate the delta into a permanent false positive."""
    log = tmp_path / "hooks.log"
    log.write_text("\n".join([OTHER_LINE, BLOCK_LINE, OTHER_LINE, BLOCK_LINE]), encoding="utf-8")

    assert _count(log) == "2"


def test_a_log_with_no_block_lines_counts_zero(tmp_path: Path) -> None:
    log = tmp_path / "hooks.log"
    log.write_text(OTHER_LINE + "\n", encoding="utf-8")

    assert _count(log) == "0"


def test_a_warning_from_another_pre_tool_use_hook_is_not_a_block(tmp_path: Path) -> None:
    """`pre-tool-use-memory-size` and `-read-size` log warnings to the same
    file. Counting them would report a fired guard on a turn nothing denied."""
    log = tmp_path / "hooks.log"
    log.write_text(
        "2026-09-17T12:00:00-03:00 pre-tool-use-memory-size: MEMORY.md over budget\n",
        encoding="utf-8",
    )

    assert _count(log) == "0"


# --- fired_verdict ---------------------------------------------------------


def _verdict(before: str, after: str, stream_blocked: str) -> str:
    script = (
        f"{_function_source('fired_verdict')}\n"
        f'fired_verdict "{before}" "{after}" "{stream_blocked}"\n'
    )
    result = _run(script)
    assert result.returncode == 0, result.stderr
    return result.stdout.strip()


def test_a_block_in_the_stream_and_a_block_in_the_log_is_denied() -> None:
    assert _verdict("3", "4", "yes") == "denied"


def test_a_block_in_the_stream_with_no_log_line_names_the_other_denier() -> None:
    """Codex's own sandbox, or another PreToolUse group, can refuse a call. The
    phase asserts on *this* harness's guard, so the distinction is recorded."""
    assert _verdict("3", "3", "yes") == "denied-elsewhere"


def test_a_logged_block_whose_call_ran_anyway_is_fired_but_allowed() -> None:
    """The contradiction worth its own word: the guard decided deny, wrote it
    down, and the effect happened. That is a verdict Codex did not honour, and
    no matcher change fixes it."""
    assert _verdict("3", "4", "no") == "fired-but-allowed"


def test_no_block_anywhere_is_the_silent_verdict() -> None:
    assert _verdict("3", "3", "no") == "no-block-logged"


def test_a_count_that_went_backwards_is_not_read_as_a_block() -> None:
    """A rotated or truncated log shrinks. Reading `4 -> 1` as "fired" would
    manufacture the finding."""
    assert _verdict("4", "1", "no") == "no-block-logged"


def test_an_unreadable_count_never_silently_becomes_a_verdict() -> None:
    """`security_block_count` returns a number or the phase learns nothing; a
    non-numeric reading must not arithmetic-compare its way to `denied`."""
    assert _verdict("", "4", "no") == "unreadable"
    assert _verdict("3", "ERROR", "no") == "unreadable"


# --- the wording that reaches the summary ----------------------------------


def _note(verdict: str) -> str:
    script = f'{_function_source("fired_note")}\nfired_note "{verdict}"\n'
    result = _run(script)
    assert result.returncode == 0, result.stderr
    return result.stdout.strip()


def test_every_verdict_has_a_sentence_and_none_falls_through() -> None:
    """A verdict with no case arm prints nothing and the summary row loses its
    reason — the defect this whole file exists to stop repeating."""
    for verdict in (
        "denied",
        "denied-elsewhere",
        "fired-but-allowed",
        "no-block-logged",
        "unreadable",
    ):
        assert _note(verdict), f"{verdict} has no sentence"


def test_the_silent_verdict_states_both_readings_it_cannot_separate() -> None:
    """The log speaks only on a block, so claiming `never invoked` outright
    would be the same overreach phase C made with `predates #367`."""
    note = _note("no-block-logged")

    assert "never invoked" in note
    assert "allowed" in note


def test_the_fired_but_allowed_sentence_does_not_blame_the_matcher() -> None:
    """A hook that fired is not a hook that was suppressed, and sending the
    reader to the matcher would cost them the next run."""
    note = _note("fired-but-allowed")

    assert "fired" in note
    assert "matcher" not in note


# --- phase C's note --------------------------------------------------------


def _phase_c_note(signal: str, prior_untrusted: str) -> str:
    script = f'{_function_source("phase_c_note")}\nphase_c_note "{signal}" "{prior_untrusted}"\n'
    result = _run(script)
    assert result.returncode == 0, result.stderr
    return result.stdout.strip()


def test_no_note_ever_claims_the_binary_predates_a_pr() -> None:
    """The gate cannot read the installed version's history, and 0.71.1 carries
    #367 — the claim was false on the machine that printed it."""
    for signal in ("orphaned", "untrusted"):
        for prior in ("yes", "no"):
            assert "#367" not in _phase_c_note(signal, prior)


def test_an_untrusted_signal_after_an_untrusted_phase_b_says_stale_was_unobservable() -> None:
    """With no approval left standing, a changed declaration has nothing to
    make stale. Reporting the absence as a shortfall blames the wrong thing."""
    note = _phase_c_note("untrusted", "yes")

    assert "unobservable" in note or "nothing" in note


def test_an_untrusted_signal_after_a_trusted_phase_b_names_the_appended_handler() -> None:
    """The other reading, and it is about the change's shape, not the binary."""
    note = _phase_c_note("untrusted", "no")

    assert "appended" in note or "added" in note


def test_the_orphaned_signal_gets_its_own_sentence() -> None:
    assert _phase_c_note("orphaned", "no")


def test_every_signal_produces_a_note_rather_than_an_empty_line() -> None:
    for signal in ("orphaned", "untrusted", "stale"):
        assert _phase_c_note(signal, "no") != "", signal

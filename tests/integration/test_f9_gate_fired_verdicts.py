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


def _verdict(
    before: str,
    after: str,
    stream_blocked: str,
    *,
    invokes_before: str = "0",
    invokes_after: str = "0",
    trace_live: str = "no",
) -> str:
    """`fired_verdict <blocks before> <blocks after> <invokes before> <invokes
    after> <stream blocked> <trace live>`.

    The defaults are the pre-trace world — no invocation trace available — so
    every assertion written before `LH_HOOK_TRACE` existed still states the
    same thing, and the trace's own cases opt in explicitly.
    """
    script = (
        f"{_function_source('fired_verdict')}\n"
        f'fired_verdict "{before}" "{after}" "{invokes_before}" "{invokes_after}"'
        f' "{stream_blocked}" "{trace_live}"\n'
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


def test_no_block_anywhere_without_the_trace_stays_the_one_sided_verdict() -> None:
    """Without `LH_HOOK_TRACE`, the block line is the only signal and it speaks
    only on a denial — so `never invoked` and `invoked and allowed` collapse,
    and the verdict says so instead of picking one."""
    assert _verdict("3", "3", "no", trace_live="no") == "no-block-logged"


def test_the_trace_separates_never_invoked_from_fired_and_allowed() -> None:
    """The pair the trace exists for, and the reason phase B exports the var."""
    silent = _verdict("3", "3", "no", invokes_before="7", invokes_after="7", trace_live="yes")
    allowed = _verdict("3", "3", "no", invokes_before="7", invokes_after="8", trace_live="yes")

    assert silent == "never-invoked"
    assert allowed == "fired-but-allowed"


def test_a_live_trace_never_downgrades_a_logged_block() -> None:
    """The block line stays the stronger evidence: a turn that denied is
    `denied` whatever the invocation count did."""
    assert _verdict("3", "4", "yes", invokes_before="7", invokes_after="8", trace_live="yes") == (
        "denied"
    )


def test_an_unreadable_invocation_count_falls_back_rather_than_guessing() -> None:
    """A trace declared live whose count cannot be read is the same epistemic
    position as no trace at all — never a licence to assert `never-invoked`."""
    assert _verdict("3", "3", "no", invokes_before="", invokes_after="8", trace_live="yes") == (
        "no-block-logged"
    )


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
        "never-invoked",
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


# --- security_invoked_count ------------------------------------------------


def _invoked(path: Path) -> str:
    script = f'{_function_source("security_invoked_count")}\nsecurity_invoked_count "{path}"\n'
    result = _run(script)
    assert result.returncode == 0, result.stderr
    return result.stdout.strip()


TRACE_LINE = "2026-09-17T12:32:53-03:00 pre-tool-use-security: invoked"
OTHER_TRACE = "2026-09-17T12:32:53-03:00 session-context: invoked"


def test_a_missing_log_has_no_invocations(tmp_path: Path) -> None:
    assert _invoked(tmp_path / "absent.log") == "0"


def test_only_the_security_hooks_trace_lines_are_counted(tmp_path: Path) -> None:
    """With `LH_HOOK_TRACE=1` every dispatched hook traces, and SessionStart
    fires on every turn — counting them all would report the guard as invoked
    on a turn that never reached a tool call."""
    log = tmp_path / "hooks.log"
    log.write_text("\n".join([OTHER_TRACE, TRACE_LINE, OTHER_TRACE]), encoding="utf-8")

    assert _invoked(log) == "1"


def test_a_block_line_is_not_counted_as_an_invocation(tmp_path: Path) -> None:
    """The two counts are subtracted from each other. Overlap would make every
    denial read as an extra invocation and mask `fired-but-allowed`."""
    log = tmp_path / "hooks.log"
    log.write_text(BLOCK_LINE + "\n", encoding="utf-8")

    assert _invoked(log) == "0"


# --- trace_is_live ---------------------------------------------------------
#
# The self-test that stops the trace from repeating phase C's old defect. A
# binary without `LH_HOOK_TRACE` writes no invocation line, every turn's count
# stays flat, and every verdict would read `never-invoked` — a confident wrong
# answer with no way to notice. So the gate proves the trace works on THIS
# binary before trusting a flat count, by running one hook through it.

_TRACING_LH = """#!/bin/sh
# Stands in for an `lh` whose runner carries the trace: writes the line only
# when the variable is set, which is the property under test.
if [ "$LH_HOOK_TRACE" = "1" ]; then
  printf '%s pre-tool-use-security: invoked\\n' "2026-01-01T00:00:00-03:00" >> "$LH_TEST_LOG"
fi
exit 0
"""

_SILENT_LH = "#!/bin/sh\nexit 0\n"


def _trace_live(tmp_path: Path, script_body: str, *, log_exists: bool = True) -> str:
    fake = tmp_path / "lh"
    fake.write_text(script_body, encoding="utf-8")
    fake.chmod(0o755)
    log = tmp_path / "hooks.log"
    if log_exists:
        log.write_text(OTHER_TRACE + "\n", encoding="utf-8")

    script = (
        f'export LH_TEST_LOG="{log}"\n'
        f"{_function_source('security_invoked_count')}\n"
        f"{_function_source('trace_is_live')}\n"
        f'trace_is_live "{fake}" "lazy-codex" "{log}"\n'
    )
    result = _run(script)
    assert result.returncode == 0, result.stderr
    return result.stdout.strip()


def test_a_binary_that_writes_the_trace_is_reported_live(tmp_path: Path) -> None:
    assert _trace_live(tmp_path, _TRACING_LH) == "yes"


def test_a_binary_that_does_not_trace_is_reported_not_live(tmp_path: Path) -> None:
    """Half of the pair. Without the test above it, "not live" would pass just
    as well on a self-test that never invoked anything."""
    assert _trace_live(tmp_path, _SILENT_LH) == "no"


def test_no_log_path_means_the_trace_cannot_be_read(tmp_path: Path) -> None:
    """Preflight failed to resolve CODEX_HOME. The phase degrades to the
    one-sided verdict rather than reading an unwritable path as silence."""
    fake = tmp_path / "lh"
    fake.write_text(_TRACING_LH, encoding="utf-8")
    fake.chmod(0o755)
    script = (
        f"{_function_source('security_invoked_count')}\n"
        f"{_function_source('trace_is_live')}\n"
        f'trace_is_live "{fake}" "lazy-codex" ""\n'
    )
    result = _run(script)

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "no"


def test_the_self_test_sets_the_variable_it_is_testing_for() -> None:
    """A self-test that forgot to export `LH_HOOK_TRACE` would report every
    binary as not live, and the gate would silently give up the distinction."""
    assert "LH_HOOK_TRACE=1" in _function_source("trace_is_live")


def test_the_self_test_goes_through_the_deployed_entry_point() -> None:
    """`lh hook <name>` is the command the agent actually runs. Probing a
    different entry point would prove the trace works somewhere the hooks do
    not go through."""
    assert "hook pre-tool-use-security" in _function_source("trace_is_live")

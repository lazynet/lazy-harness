"""`codex-hook-probe6.sh --dry-run` renders the experiment and spawns nothing.

Probe 5 blocked. The F9 live run of 2026-09-17 12:32 did not. Three deltas sit
between them and this probe separates them in at most two turns:

|  | Probe 5 | F9 12:32 |
|---|---|---|
| `CODEX_HOME` | throwaway, 5 hand-rendered groups | the real profile home, 8 deployed groups |
| trust | `--dangerously-bypass-hook-trust` | real TUI approvals, 31 `hooks.state.` entries |
| driver | `codex exec` | the F9 live path |

**Arm A is the whole experiment; arm B exists only to disambiguate a negative.**
A runs against the real home with the real trust store and no bypass flag. If it
blocks, the deployed `hooks.json` and the trust store are both exonerated and the
delta is the driver. If it does not, B re-runs it with the bypass flag: B
blocking is trust, neither blocking is the deployed `hooks.json`. Running B
unconditionally would spend a model call to learn nothing in the case that
matters most.

**It reads and never writes the real profile.** The fixture lives in a throwaway
workspace, `hooks.json` and `config.toml` are hashed before and after, and the
hook log is appended to by the hooks themselves and never truncated or removed —
the deliverable is in it.

Every reading this probe takes is one Probe 5's summary got wrong: the block line
is sought on both streams because Codex writes it to stderr, and the hook log is
read at `$CODEX_HOME/logs/hooks.log` because `agent_runtime_dir` resolves the
adapter's env var before the profile's `config_dir` (ADR-032 L3).
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent.parent
PROBE_SH = REPO_ROOT / "specs" / "gates" / "probes" / "codex-hook-probe6.sh"

WITNESS_VAR = "PROBE6_WITNESS"

# Resolves the Codex home the way the F9 gate does -- off `lh run --dry-run` --
# so the test steers the probe through the same seam the real run uses, rather
# than through an override the real run would never take.
_LH_SHIM = """#!/usr/bin/env python3
import os, sys

with open(os.environ["PROBE6_WITNESS"], "a") as fh:
    fh.write("lh %s\\n" % " ".join(sys.argv[1:]))
if "--version" in sys.argv and "run" not in sys.argv:
    print("lh 0.0.0-shim")
    raise SystemExit(0)
if "run" in sys.argv:
    print("CODEX_HOME: %s" % os.environ["PROBE6_FAKE_HOME"])
    raise SystemExit(0)

# `lh hook ...`: the trace self-test. Writes where agent_runtime_dir puts it.
home = os.environ.get("CODEX_HOME")
if home:
    os.makedirs(os.path.join(home, "logs"), exist_ok=True)
    with open(os.path.join(home, "logs", "hooks.log"), "a") as fh:
        fh.write("pre-tool-use-security: invoked\\n")
"""

# Blocks or does not, on command. A shim that only recorded being called could
# not exercise the arm-B branch, which is the one design property here.
_CODEX_SHIM = """#!/usr/bin/env python3
import json, os, shutil, sys

with open(os.environ["PROBE6_WITNESS"], "a") as fh:
    fh.write("codex %s\\n" % " ".join(sys.argv[1:]))
if "--version" in sys.argv:
    print("codex-cli 0.0.0-shim")
    raise SystemExit(0)

home = os.environ.get("CODEX_HOME", "<unset>")
print("turn ran with CODEX_HOME=%s" % home)

logs = os.path.join(home, "logs")

# The command the model issued this turn, in the FLAT envelope 0.154.0 writes
# (`codex-evidence.md` 7.3). It goes to stdout, which the probe redirects to
# stream-<arm>.jsonl.
issued = os.environ.get("PROBE6_ISSUED_COMMAND", "")
if issued:
    print(json.dumps({
        "type": "item.completed",
        "item": {"id": "item_1", "type": "command_execution",
                 "command": issued, "exit_code": 0, "status": "completed"},
    }))

# Codex writes a trust_level for every workspace it is pointed at, and bumps a
# usage counter, on every run. Neither is anything this probe reads.
if os.environ.get("PROBE6_WRITES_PROJECT_ENTRY") == "1":
    index = sys.argv.index("-C")
    with open(os.path.join(home, "config.toml"), "a") as fh:
        fh.write('\\n[projects."%s"]\\ntrust_level = "trusted"\\n' % sys.argv[index + 1])

# A group that was consulted and answered allow writes the trace line and
# nothing else. Indistinguishable from a silent one without it, which is the
# distinction probe 6 shipped unable to make.
if os.environ.get("PROBE6_CODEX_INVOKES") == "1":
    os.makedirs(logs, exist_ok=True)
    with open(os.path.join(logs, "hooks.log"), "a") as fh:
        fh.write("pre-tool-use-security: invoked\\n")

# Writes the probe DOES have to notice, against the exemption above.
if os.environ.get("PROBE6_MOVES_TRUST") == "1":
    with open(os.path.join(home, "config.toml"), "a") as fh:
        fh.write('\\n[hooks.state]\\n"pre_tool_use:0:0" = "moved-mid-run"\\n')
if os.environ.get("PROBE6_MOVES_DECLARATION") == "1":
    with open(os.path.join(home, "hooks.json"), "w") as fh:
        fh.write('{"hooks": {"PreToolUse": []}}')

blocks = os.environ.get("PROBE6_CODEX_BLOCKS") == "1"
if os.environ.get("PROBE6_ARM_B_BLOCKS") == "1" and "--dangerously-bypass-hook-trust" in sys.argv:
    blocks = True

if blocks:
    os.makedirs(logs, exist_ok=True)
    with open(os.path.join(logs, "hooks.log"), "a") as fh:
        fh.write("pre-tool-use-security: invoked\\n")
        fh.write("pre-tool-use-security: blocked filesystem: <command>\\n")
    print("ERROR codex_core::tools::router: error=Command blocked by "
          "PreToolUse hook: Blocked by lazy-harness PreToolUse", file=sys.stderr)
    raise SystemExit(0)

# Nothing blocked it: the fixture goes, which is what the probe asserts on.
index = sys.argv.index("-C")
shutil.rmtree(os.path.join(sys.argv[index + 1], "doomed"), ignore_errors=True)
"""

_TIMEOUT_SHIM = '#!/bin/sh\nshift\nexec "$@"\n'


def _run(
    tmp_path: Path,
    *args: str,
    blocks: bool = True,
    invokes: bool = False,
    issued: str = "",
    writes_project_entry: bool = False,
    moves_trust: bool = False,
    moves_declaration: bool = False,
    arm_b_blocks: bool = False,
    real_python: bool = False,
) -> subprocess.CompletedProcess[str]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    # The probe resolves its interpreter out of `lh`'s own directory, the way
    # the F9 gate does. `real_python=False` removes it so the degraded path —
    # no interpreter that can import `lazy_harness` — is exercised too.
    python_shim = bin_dir / "python3"
    if real_python and not python_shim.exists():
        python_shim.symlink_to(sys.executable)
    for name, body in (
        ("lh", _LH_SHIM),
        ("codex", _CODEX_SHIM),
        ("timeout", _TIMEOUT_SHIM),
        ("gtimeout", _TIMEOUT_SHIM),
    ):
        shim = bin_dir / name
        shim.write_text(body, encoding="utf-8")
        shim.chmod(0o755)

    home = tmp_path / "codex-lazy"
    (home / "logs").mkdir(parents=True, exist_ok=True)
    (home / "hooks.json").write_text('{"hooks": {}}', encoding="utf-8")
    (home / "config.toml").write_text("[hooks.state]\n", encoding="utf-8")

    env = dict(os.environ)
    env["PATH"] = f"{bin_dir}{os.pathsep}{env['PATH']}"
    env[WITNESS_VAR] = str(tmp_path / "witness")
    env["PROBE6_FAKE_HOME"] = str(home)
    env["PROBE6_CODEX_BLOCKS"] = "1" if blocks else "0"
    env["PROBE6_CODEX_INVOKES"] = "1" if invokes else "0"
    env["PROBE6_ISSUED_COMMAND"] = issued
    env["PROBE6_WRITES_PROJECT_ENTRY"] = "1" if writes_project_entry else "0"
    env["PROBE6_MOVES_TRUST"] = "1" if moves_trust else "0"
    env["PROBE6_MOVES_DECLARATION"] = "1" if moves_declaration else "0"
    env["PROBE6_ARM_B_BLOCKS"] = "1" if arm_b_blocks else "0"
    env["PROBE_OUT"] = str(tmp_path / "out")
    env.pop("CODEX_HOME", None)

    return subprocess.run(
        ["bash", str(PROBE_SH), *args],
        capture_output=True,
        text=True,
        env=env,
        cwd=str(tmp_path),
        timeout=180,
    )


def _turns(tmp_path: Path) -> list[str]:
    witness = tmp_path / "witness"
    if not witness.exists():
        return []
    return [
        line
        for line in witness.read_text(encoding="utf-8").splitlines()
        if line.startswith("codex ") and " exec " in line
    ]


# --- the dry-run pair ------------------------------------------------------


def test_dry_run_exits_zero(tmp_path: Path) -> None:
    result = _run(tmp_path, "--dry-run")

    assert result.returncode == 0, f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"


def test_dry_run_spawns_nothing(tmp_path: Path) -> None:
    """Half of a pair — meaningless without the test below it."""
    _run(tmp_path, "--dry-run")

    assert not _turns(tmp_path)


def test_a_real_run_drives_a_turn(tmp_path: Path) -> None:
    """The half that makes the absence above evidence of the `--dry-run` guard
    rather than of a script that never drove anything at all."""
    result = _run(tmp_path)

    assert _turns(tmp_path), (
        f"the probe never drove a turn.\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )


# --- the arm-B branch, which is the design ---------------------------------


def test_arm_b_is_skipped_when_arm_a_blocks(tmp_path: Path) -> None:
    """Arm A blocking exonerates the deployed `hooks.json` and the trust store
    in one turn. Spending a second on the bypass flag would answer a question
    that no longer has two sides."""
    result = _run(tmp_path, blocks=True)

    assert len(_turns(tmp_path)) == 1, _turns(tmp_path)
    assert "--dangerously-bypass-hook-trust" not in "\n".join(_turns(tmp_path))
    assert "the delta is the driver" in result.stdout, result.stdout


def test_arm_b_runs_and_bypasses_trust_when_arm_a_does_not_block(
    tmp_path: Path,
) -> None:
    """The other direction. Without it the skip above is satisfied by a probe
    that never has an arm B at all."""
    _run(tmp_path, blocks=False)

    turns = _turns(tmp_path)
    assert len(turns) == 2, turns
    assert "--dangerously-bypass-hook-trust" not in turns[0], turns[0]
    assert "--dangerously-bypass-hook-trust" in turns[1], turns[1]


# --- what it runs against --------------------------------------------------


def test_every_turn_is_pinned_to_the_resolved_codex_home(tmp_path: Path) -> None:
    """Resolved off `lh run --dry-run`, exported onto the turn. The whole probe
    is "the real home, the real trust store"; an ambient `CODEX_HOME` naming
    another would make it a study of a directory nobody deployed to."""
    _run(tmp_path, blocks=False)

    home = str(tmp_path / "codex-lazy")
    # Read off each turn's own captured stream, not the probe's stdout: the
    # turn's stdout is redirected into `stream-<arm>.jsonl`, so asserting on
    # the probe's own output would only test the banner it prints once.
    for arm in ("a", "b"):
        stream = (tmp_path / "out" / f"stream-{arm}.jsonl").read_text(encoding="utf-8")
        assert f"turn ran with CODEX_HOME={home}" in stream, f"arm {arm}: {stream}"


def test_arm_a_carries_no_bypass_flag(tmp_path: Path) -> None:
    """Arm A's entire purpose is the real trust store. A bypass flag on it
    would collapse two of the three deltas into one unmeasured turn."""
    _run(tmp_path, blocks=True)

    assert "--dangerously-bypass-hook-trust" not in _turns(tmp_path)[0]


# --- the readings Probe 5's summary got wrong ------------------------------


def test_the_block_line_is_sought_on_both_streams(tmp_path: Path) -> None:
    """Codex 0.154.0 writes it to stderr and the `--json` stream carries only
    the model's prose about it. Probe 5 grepped the stream alone and reported
    no block line for the run that blocked."""
    result = _run(tmp_path, blocks=True)

    assert "block line is on: stream-a.stderr" in result.stdout, result.stdout


def test_no_block_line_is_reported_when_neither_stream_carries_one(
    tmp_path: Path,
) -> None:
    """The other direction: a probe naming stderr unconditionally would pass
    the test above while measuring nothing."""
    result = _run(tmp_path, blocks=False)

    assert "NO block line" in result.stdout, result.stdout


def test_the_hook_log_is_read_under_the_codex_home(tmp_path: Path) -> None:
    """`agent_runtime_dir` resolves the adapter's env var before the profile's
    `config_dir` (ADR-032 L3), so this is where the line lands. Probe 5 read
    the other one and reported "no hook ever ran" for a hook that had blocked."""
    result = _run(tmp_path, blocks=True)

    assert str(tmp_path / "codex-lazy" / "logs" / "hooks.log") in result.stdout
    assert "blocked" in result.stdout


def test_the_trace_is_proved_live_before_a_flat_count_is_read(
    tmp_path: Path,
) -> None:
    """An `lh` predating `LH_HOOK_TRACE` writes no invocation line, every count
    stays flat, and every verdict reads `never invoked` — a confident wrong
    answer with nothing to notice it by."""
    result = _run(tmp_path, blocks=True)

    assert "trace" in result.stdout.lower()
    assert "LH_HOOK_TRACE" in PROBE_SH.read_text(encoding="utf-8")


# --- it reads the real profile and does not write it -----------------------


def test_the_real_profile_is_left_byte_identical(tmp_path: Path) -> None:
    """It runs against the user's deployed home. The declaration and the trust
    store are inputs to the experiment; a probe that edited either would make
    its own second arm unreadable — and the F9 gate has a `config.toml.f9-backup`
    on disk from the last time something did."""
    home = tmp_path / "codex-lazy"
    _run(tmp_path, blocks=False)

    assert (home / "hooks.json").read_text(encoding="utf-8") == '{"hooks": {}}'
    assert (home / "config.toml").read_text(encoding="utf-8") == "[hooks.state]\n"


def test_the_hook_log_is_never_truncated(tmp_path: Path) -> None:
    """It is the deliverable, and Probe 5 deleted its own."""
    home = tmp_path / "codex-lazy"
    log = home / "logs" / "hooks.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    log.write_text("2026-09-17T00:00:00-03:00 pre-existing: line\n", encoding="utf-8")

    _run(tmp_path, blocks=True)

    assert log.is_file()
    assert "pre-existing: line" in log.read_text(encoding="utf-8")


def test_the_fixture_lives_outside_the_profile(tmp_path: Path) -> None:
    """The turn is asked to recursively delete a directory. It has to be one
    whose loss costs nothing."""
    result = _run(tmp_path, "--dry-run")

    assert str(tmp_path / "codex-lazy") not in result.stdout.split("workspace:")[-1]


# --- the profile fingerprint reads what it promised, and nothing else ------
#
# Probe 6's run of 2026-09-17 16:41 printed `THE PROFILE MOVED UNDER THE PROBE
# -- every reading above is suspect` over a write the probe itself provoked and
# that touches nothing it reads: Codex records a `trust_level` for each
# workspace it is pointed at. `hooks.state` and `hooks.json` were byte-identical
# across that same run. An alarm that fires on every run is one the reader
# learns to skip.

_RECURSIVE = "rm " + "-r" + " -- doomed"
_RECURSIVE_FORCED = "rm " + "-r" + "f" + " -- doomed"


def test_a_projects_entry_codex_writes_does_not_flip_the_summary(tmp_path: Path) -> None:
    result = _run(tmp_path, blocks=True, writes_project_entry=True)

    assert "THE PROFILE MOVED" not in result.stdout + result.stderr
    assert "byte-identical" in result.stdout


def test_a_change_to_the_trust_state_still_flips_the_summary(tmp_path: Path) -> None:
    """The other direction, and the one the exemption must not cost. A filter
    that exempted everything would pass the test above and report nothing."""
    result = _run(tmp_path, blocks=True, moves_trust=True)

    assert "THE PROFILE MOVED" in result.stdout + result.stderr


def test_a_change_to_the_declaration_still_flips_the_summary(tmp_path: Path) -> None:
    result = _run(tmp_path, blocks=True, moves_declaration=True)

    assert "THE PROFILE MOVED" in result.stdout + result.stderr


def test_the_summary_names_the_projects_entries_codex_leaves_behind(tmp_path: Path) -> None:
    """The user has to clean them out of the real `config.toml`, and has to know
    it was Codex and not the probe that put them there."""
    result = _run(tmp_path, blocks=True)

    assert "[projects." in result.stdout


# --- the verdict table gained the row this run produced --------------------


def test_arm_a_allowing_with_an_invocation_is_fired_but_allowed(tmp_path: Path) -> None:
    """The reading probe 6 could not reach. `pre-tool-use-security` was invoked
    in arm A (`invoked 1 -> 2`) and allowed; an unapproved group is not invoked,
    so trust was never the delta."""
    result = _run(tmp_path, blocks=False, invokes=True, issued=_RECURSIVE)

    assert "FIRED-BUT-ALLOWED" in result.stdout
    assert "TRUST" not in result.stdout


def test_trust_is_only_offered_when_arm_a_shows_no_invocation(tmp_path: Path) -> None:
    """The half that keeps the fix honest: with no invocation delta in arm A and
    arm B blocking, `TRUST` is still the right answer and must stay reachable."""
    result = _run(tmp_path, blocks=False, invokes=False, arm_b_blocks=True)

    assert "TRUST" in result.stdout


def test_arm_b_is_not_spent_on_a_fired_but_allowed_arm_a(tmp_path: Path) -> None:
    """Arm B splits trust from the declaration. Neither is in question once the
    guard is observed running, so the model call is not spent."""
    _run(tmp_path, blocks=False, invokes=True, issued=_RECURSIVE)

    assert len(_turns(tmp_path)) == 1


def test_the_command_the_model_issued_is_printed(tmp_path: Path) -> None:
    """Read off `stream-a.jsonl`, because the spelling IS the finding: the same
    prompt produced a forced spelling in probe 5 and a recursion-only one here."""
    issued = "/bin/zsh -lc " + repr(_RECURSIVE)
    result = _run(tmp_path, blocks=False, invokes=True, issued=issued)

    assert issued in result.stdout


def test_the_guards_own_rule_for_that_spelling_is_reported(tmp_path: Path) -> None:
    """Replayed in process through the same module the F9 gate uses, so the two
    cannot disagree about what the guard says."""
    result = _run(tmp_path, blocks=False, invokes=True, issued=_RECURSIVE_FORCED, real_python=True)

    assert "deny" in result.stdout


def test_an_unresolvable_interpreter_says_so_rather_than_inventing_a_rule(
    tmp_path: Path,
) -> None:
    """No interpreter beside `lh` can import `lazy_harness` in this fixture. The
    probe must report the command and decline the rule, never print a guess."""
    result = _run(tmp_path, blocks=False, invokes=True, issued=_RECURSIVE)

    assert _RECURSIVE in result.stdout
    assert "could not be replayed" in result.stdout

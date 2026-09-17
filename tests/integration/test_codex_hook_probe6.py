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
import os, shutil, sys

with open(os.environ["PROBE6_WITNESS"], "a") as fh:
    fh.write("codex %s\\n" % " ".join(sys.argv[1:]))
if "--version" in sys.argv:
    print("codex-cli 0.0.0-shim")
    raise SystemExit(0)

home = os.environ.get("CODEX_HOME", "<unset>")
print("turn ran with CODEX_HOME=%s" % home)

if os.environ.get("PROBE6_CODEX_BLOCKS") == "1":
    logs = os.path.join(home, "logs")
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


def _run(tmp_path: Path, *args: str, blocks: bool = True) -> subprocess.CompletedProcess[str]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
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

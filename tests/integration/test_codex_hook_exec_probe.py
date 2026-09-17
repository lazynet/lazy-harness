"""`codex-hook-exec-probe.sh --dry-run` renders the experiment and spawns nothing.

The matcher question is closed: the 13:22 matcher probe falsified H1 and H3 —
Codex honours `PreToolUse` matchers, evaluates every group, and matches
`Bash|Read|Edit|Write|NotebookEdit` on both `Bash` and `apply_patch`. And
`test_codex_guard_end_to_end.py` shows the shipped guard denying both fixtures
in process, with the envelope probe 4b measured Codex honouring.

So the group matched and the harness would have denied, and F9 still saw the
`rm -rf` run. What is left is the hook's execution environment under Codex, and
this probe is five `PreToolUse` groups built to separate four candidates for it.
The groups ARE the experiment, so a typo there would produce a confident table
about nothing — which is what this file pins.

**Three properties carry the design, and each has a test.**

1.  **The matcher is the deployed literal on every group.** Varying it would
    reintroduce the question the matcher probe already closed, and a group that
    failed to fire would be unattributable between "the environment" and "the
    matcher".
2.  **The two live groups run under different profiles.** They are the two whose
    stdout reaches Codex; sharing a profile would merge their hook-log counts
    and make the blocked/unblocked outcome unattributable between them.
3.  **The capture groups swallow stdout.** A capture group that answered Codex
    could block the call, and then the outcome would not attribute to either
    live group.
"""

from __future__ import annotations

import json
import os
import subprocess
import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent.parent
PROBE_SH = REPO_ROOT / "specs" / "gates" / "probes" / "codex-hook-exec-probe.sh"

DEPLOYED_MATCHER = "Bash|Read|Edit|Write|NotebookEdit"

# Typed here and asserted against the rendered document rather than read from
# the script: a variant silently dropped fails this test instead of rewriting it.
EXPECTED = (
    ("diag", "diag", "probe-capture"),
    ("capture-abs", "capture-abs", "probe-capture"),
    ("capture-bare", "capture-bare", "probe-capture"),
    ("live-abs", "live-abs", "probe-abs"),
    ("live-bare", "live-bare", "probe-bare"),
)

WITNESS_VAR = "EXEC_PROBE_WITNESS"

_SHIM = """#!/bin/sh
printf '%s %s\\n' "$(basename "$0")" "$*" >> "$EXEC_PROBE_WITNESS"
exit 97
"""


def _shims(tmp_path: Path) -> tuple[Path, Path]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name in ("codex", "lh", "timeout", "gtimeout"):
        shim = bin_dir / name
        shim.write_text(_SHIM, encoding="utf-8")
        shim.chmod(0o755)
    return bin_dir, tmp_path / "witness"


def _run(tmp_path: Path, *args: str) -> subprocess.CompletedProcess[str]:
    bin_dir, witness = _shims(tmp_path)
    auth = tmp_path / "auth.json"
    auth.write_text('{"tokens": {}}', encoding="utf-8")

    env = dict(os.environ)
    env["PATH"] = f"{bin_dir}{os.pathsep}{env['PATH']}"
    env["EXEC_PROBE_WITNESS"] = str(witness)
    env["CODEX_AUTH"] = str(auth)
    env["PROBE_OUT"] = str(tmp_path / "out")

    return subprocess.run(
        ["bash", str(PROBE_SH), *args],
        capture_output=True,
        text=True,
        env=env,
        cwd=str(tmp_path),
        timeout=120,
    )


def _rendered(result: subprocess.CompletedProcess[str]) -> dict:
    start = result.stdout.index("{")
    end = result.stdout.rindex("}") + 1
    return json.loads(result.stdout[start:end])


def _groups(tmp_path: Path) -> list[dict]:
    return _rendered(_run(tmp_path, "--dry-run"))["hooks"]["PreToolUse"]


def test_dry_run_exits_zero(tmp_path: Path) -> None:
    result = _run(tmp_path, "--dry-run")

    assert result.returncode == 0, f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"


def test_dry_run_spawns_nothing(tmp_path: Path) -> None:
    """Half of a pair — meaningless without the test below it."""
    _run(tmp_path, "--dry-run")

    assert not (tmp_path / "witness").exists(), (tmp_path / "witness").read_text()


def test_a_real_run_reaches_for_the_binary(tmp_path: Path) -> None:
    """The half that makes the absence above evidence of the `--dry-run` guard
    rather than of a script that never looked for a binary at all."""
    result = _run(tmp_path)

    witness = tmp_path / "witness"
    assert witness.exists(), (
        f"the probe never invoked anything without --dry-run.\n"
        f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )


def test_every_variant_is_rendered_in_order(tmp_path: Path) -> None:
    groups = _groups(tmp_path)

    assert len(groups) == len(EXPECTED)
    for group, (label, mode, profile) in zip(groups, EXPECTED, strict=True):
        command = group["hooks"][0]["command"]
        assert f" {label} " in command, f"{label} not passed to its wrapper: {command}"
        assert command.endswith(f" {mode} /abs/path/to/lh {profile}"), command


def test_every_group_carries_the_deployed_matcher(tmp_path: Path) -> None:
    """Pinned, not varied: the matcher question is closed, and a group that
    failed to fire under a different literal would be unattributable between
    the environment and the matcher."""
    for group in _groups(tmp_path):
        assert group["matcher"] == DEPLOYED_MATCHER


def test_the_two_live_variants_run_under_different_profiles(tmp_path: Path) -> None:
    """They are the two whose stdout reaches Codex. One profile between them
    merges their hook-log counts and the outcome stops attributing.

    Read off the RENDERED commands, not off `EXPECTED`: the first spelling
    asserted on this file's own constant, which is a test of the test data.
    """
    live = [
        group["hooks"][0]["command"].rsplit(" ", 1)[-1]
        for group in _groups(tmp_path)
        if " live-" in group["hooks"][0]["command"]
    ]

    assert len(live) == 2, live
    assert len(set(live)) == 2, f"both live groups share a profile: {live}"


def test_the_capture_variants_never_answer_codex() -> None:
    """A capture group that spoke could block the call, and the turn's outcome
    would not attribute to either live group."""
    text = PROBE_SH.read_text(encoding="utf-8")
    forwarding = text[text.index("# Only the live modes answer Codex") :]

    assert "live-abs|live-bare)" in forwarding
    assert "capture-abs" not in forwarding.split("esac")[0]


def test_one_variant_uses_the_bare_name_and_one_an_absolute_path() -> None:
    """The pair that isolates (a). A probe with only one of them could not tell
    a PATH problem from anything else."""
    text = PROBE_SH.read_text(encoding="utf-8")

    assert 'cmd=("$lh_abs")' in text
    assert "cmd=(lh)" in text


def test_the_wrapper_records_what_candidate_a_turns_on(tmp_path: Path) -> None:
    """`command -v lh`, PATH and HOME as the HOOK process sees them — not as
    the terminal that launched codex sees them."""
    _run(tmp_path, "--dry-run")
    wrapper = (tmp_path / "out" / "hook_wrapper.sh").read_text(encoding="utf-8")

    for fact in ("command_v_lh=", "PATH=", "HOME=", "LH_HOOK_TRACE="):
        assert fact in wrapper, fact


def test_the_wrapper_is_written_and_executable(tmp_path: Path) -> None:
    """The rendered document references it by absolute path; a plan for a
    handler that does not exist would fail as five NEVER INVOKED rows."""
    _run(tmp_path, "--dry-run")
    wrapper = tmp_path / "out" / "hook_wrapper.sh"

    assert wrapper.is_file()
    assert os.access(wrapper, os.X_OK)
    assert wrapper.read_text(encoding="utf-8").startswith("#!")


def test_the_throwaway_config_declares_every_profile_the_groups_name(
    tmp_path: Path,
) -> None:
    """A group naming a profile the config does not declare makes the runner
    refuse — five identical failures that would read as an environment finding."""
    _run(tmp_path, "--dry-run")
    config = tomllib.loads(
        (tmp_path / "out" / "lh-config" / "config.toml").read_text(encoding="utf-8")
    )

    declared = set(config["profiles"]) - {"default"}
    named = {profile for _, _, profile in EXPECTED}
    assert named <= declared, f"undeclared: {sorted(named - declared)}"


def test_every_probe_profile_runs_the_codex_adapter(tmp_path: Path) -> None:
    """A profile defaulting to claude-code would make the hook emit Claude
    Code's envelope, and the probe would measure the wrong wire format."""
    _run(tmp_path, "--dry-run")
    config = tomllib.loads(
        (tmp_path / "out" / "lh-config" / "config.toml").read_text(encoding="utf-8")
    )

    for _, _, profile in EXPECTED:
        assert config["profiles"][profile]["agent"] == "codex", profile


def test_the_config_declares_a_second_profile_the_groups_do_not_use(
    tmp_path: Path,
) -> None:
    """Profile resolution with one profile declared cannot tell "read the name
    given" from "took the only one there was"."""
    _run(tmp_path, "--dry-run")
    config = tomllib.loads(
        (tmp_path / "out" / "lh-config" / "config.toml").read_text(encoding="utf-8")
    )

    unused = (set(config["profiles"]) - {"default"}) - {p for _, _, p in EXPECTED}
    assert unused


def test_the_turn_exports_the_invocation_trace() -> None:
    """Without it a hook that started and produced nothing is indistinguishable
    from one that never started — the distinction the whole probe turns on."""
    assert "LH_HOOK_TRACE=1" in PROBE_SH.read_text(encoding="utf-8")


def test_the_probe_declares_only_pre_tool_use(tmp_path: Path) -> None:
    document = _rendered(_run(tmp_path, "--dry-run"))

    assert list(document["hooks"]) == ["PreToolUse"]


def _run_with_failing_git(tmp_path: Path) -> subprocess.CompletedProcess[str]:
    """A real run on a machine where every `git` invocation fails.

    The property, not one machine's cause: the probes seed a workspace with
    `git`, `--skip-git-repo-check` means codex needs no repo, and under `set -e`
    a failing seed aborted the whole script before anything was invoked — which
    reads as "the binary was never reached" rather than as the git failure it
    was. Shimming git to fail outright covers a missing binary, a missing
    committer identity and a read-only parent alike.
    """
    bin_dir, witness = _shims(tmp_path)
    # Writes no witness line, so it cannot satisfy the assertion by itself.
    failing_git = bin_dir / "git"
    failing_git.write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
    failing_git.chmod(0o755)

    auth = tmp_path / "auth.json"
    auth.write_text('{"tokens": {}}', encoding="utf-8")

    env = dict(os.environ)
    env["PATH"] = f"{bin_dir}{os.pathsep}{env['PATH']}"
    env[WITNESS_VAR] = str(witness)
    env["CODEX_AUTH"] = str(auth)
    env["PROBE_OUT"] = str(tmp_path / "out")

    return subprocess.run(
        ["bash", str(PROBE_SH)],
        capture_output=True,
        text=True,
        env=env,
        cwd=str(tmp_path),
        timeout=120,
    )


def test_a_real_run_survives_a_machine_where_git_fails(tmp_path: Path) -> None:
    """The workspace seed is a convenience and must never end the run."""
    result = _run_with_failing_git(tmp_path)

    assert (tmp_path / "witness").exists(), (
        f"the probe died before invoking anything.\nstdout:\n{result.stdout}\n"
        f"stderr:\n{result.stderr}"
    )


# --- the summary reads what the run actually wrote --------------------------
# Probe 5 ran on 2026-09-17 14:34 and its summary contradicted its own records:
# it called the in-process control a failure, said the stream carried no block
# line, and reported "no hook ever ran" for a hook that had just blocked. The
# records were right every time and the reader was wrong every time, which is
# this repo's own gate — an artifact is verified by the system that consumes
# it, and a gate script is exercised in both directions.
#
# So these run the probe against a `codex` that really dispatches the rendered
# groups. A shim that only records being called cannot catch a summary bug: the
# summary needs records to read before it can read them wrongly.

_LH_SHIM = """#!/usr/bin/env python3
import os, sys

with open(os.environ["EXEC_PROBE_WITNESS"], "a") as fh:
    fh.write("lh %s\\n" % " ".join(sys.argv[1:]))
if "--version" in sys.argv:
    print("lh 0.0.0-shim")
    raise SystemExit(0)

# Every env the control and the wrapper hand the guard, recorded per call so a
# missing LH_CONFIG_DIR is observable rather than inferred from an exit code.
with open(os.environ["EXEC_PROBE_LH_ENV"], "a") as fh:
    fh.write("LH_CONFIG_DIR=%s\\n" % os.environ.get("LH_CONFIG_DIR", "<unset>"))

sys.stdin.read()
if os.environ.get("EXEC_PROBE_LH_MODE", "deny") == "deny":
    print('{"hookSpecificOutput": {"hookEventName": "PreToolUse", '
          '"permissionDecision": "deny", "permissionDecisionReason": "shim"}}')
    # The guard's own log line, under the directory CODEX_HOME names -- which
    # is where `agent_runtime_dir` puts it whenever that variable is set, and
    # is NOT the profile's config_dir. Bug 3 is that the summary read the
    # other one.
    home = os.environ.get("CODEX_HOME")
    if home:
        logs = os.path.join(home, "logs")
        os.makedirs(logs, exist_ok=True)
        with open(os.path.join(logs, "hooks.log"), "a") as fh:
            fh.write("pre-tool-use-security: invoked\\n")
            fh.write("pre-tool-use-security: blocked filesystem: <command>\\n")
    raise SystemExit(0)
print('{"hookSpecificOutput": {"hookEventName": "PreToolUse", '
      '"permissionDecision": "allow"}}')
"""

# Dispatches every rendered PreToolUse group the way Codex does, then writes
# its own block line to STDERR -- the stream Codex 0.154.0 actually puts it on,
# and the one the probe did not read.
_CODEX_SHIM = """#!/usr/bin/env python3
import json, os, subprocess, sys

with open(os.environ["EXEC_PROBE_WITNESS"], "a") as fh:
    fh.write("codex %s\\n" % " ".join(sys.argv[1:]))
if "--version" in sys.argv:
    print("codex-cli 0.0.0-shim")
    raise SystemExit(0)

document = json.load(open(os.path.join(os.environ["CODEX_HOME"], "hooks.json")))
payload = json.dumps({
    "hook_event_name": "PreToolUse",
    "session_id": "shim",
    "tool_name": "Bash",
    "tool_input": {"command": "rm -rf doomed"},
})
for group in document["hooks"]["PreToolUse"]:
    subprocess.run(
        group["hooks"][0]["command"].split(),
        input=payload, text=True, capture_output=True, check=False,
    )

if os.environ.get("EXEC_PROBE_CODEX_BLOCK") == "1":
    print("ERROR codex_core::tools::router: error=Command blocked by "
          "PreToolUse hook: Blocked by lazy-harness PreToolUse", file=sys.stderr)
"""

# Swallows the duration and runs the command, so the turn is reached. A shim
# that exited instead would make every reading below a study of the shim.
_TIMEOUT_SHIM = '#!/bin/sh\nshift\nexec "$@"\n'


def _dispatching_run(
    tmp_path: Path, *, lh_mode: str = "deny", codex_blocks: bool = True
) -> subprocess.CompletedProcess[str]:
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

    auth = tmp_path / "auth.json"
    auth.write_text('{"tokens": {}}', encoding="utf-8")

    env = dict(os.environ)
    env["PATH"] = f"{bin_dir}{os.pathsep}{env['PATH']}"
    env[WITNESS_VAR] = str(tmp_path / "witness")
    env["EXEC_PROBE_LH_ENV"] = str(tmp_path / "lh-env")
    env["EXEC_PROBE_LH_MODE"] = lh_mode
    env["EXEC_PROBE_CODEX_BLOCK"] = "1" if codex_blocks else "0"
    env["CODEX_AUTH"] = str(auth)
    env["PROBE_OUT"] = str(tmp_path / "out")
    # The probe must resolve its own throwaway home, never inherit one.
    env.pop("CODEX_HOME", None)

    return subprocess.run(
        ["bash", str(PROBE_SH)],
        capture_output=True,
        text=True,
        env=env,
        cwd=str(tmp_path),
        timeout=180,
    )


def test_the_control_runs_under_the_probes_own_config(tmp_path: Path) -> None:
    """Bug 1. The control invoked the guard with `--profile probe-capture` and
    no `LH_CONFIG_DIR`, so the real config was asked about a profile only the
    throwaway one declares: exit 2, `unknown profile 'probe-capture'`, empty
    stdout, and a banner telling the reader to discard a correct run."""
    _dispatching_run(tmp_path)

    seen = (tmp_path / "lh-env").read_text(encoding="utf-8").splitlines()
    assert seen, "the guard was never invoked at all"
    assert seen[0] == f"LH_CONFIG_DIR={tmp_path / 'out' / 'lh-config'}", seen[0]


def test_the_control_aborts_the_run_when_the_guard_does_not_deny(
    tmp_path: Path,
) -> None:
    """One direction. The old control printed `Every reading below is
    meaningless` and then spent a model call producing exactly those readings."""
    result = _dispatching_run(tmp_path, lh_mode="allow")

    assert result.returncode != 0, result.stdout
    assert "control" in (result.stdout + result.stderr).lower()
    assert "stream.jsonl" not in result.stdout, "the turn ran anyway"


def test_the_control_lets_a_denying_guard_through(tmp_path: Path) -> None:
    """The other direction — without it the abort above is satisfied by a
    script that aborts unconditionally."""
    result = _dispatching_run(tmp_path, lh_mode="deny")

    assert result.returncode == 0, f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    assert "== outcome ==" in result.stdout


def test_the_block_line_is_sought_on_the_stream_codex_writes_it_to(
    tmp_path: Path,
) -> None:
    """Bug 2. Codex 0.154.0 writes `Command blocked by PreToolUse hook` to
    stderr; the probe grepped `stream.jsonl` alone and reported `the stream
    carries NO block line` for the run that blocked."""
    result = _dispatching_run(tmp_path, codex_blocks=True)

    # The affirmative phrasing, not the bare filename: the "neither stream…"
    # line names both files too, so `"stream.stderr" in stdout` was satisfied by
    # the message reporting that nothing was found. Caught by mutating the
    # search back to jsonl-only and watching this test keep passing.
    assert "block line is on: stream.stderr" in result.stdout, result.stdout


def test_no_block_line_is_reported_when_neither_stream_carries_one(
    tmp_path: Path,
) -> None:
    """The other direction: a probe that named stderr unconditionally would
    pass the test above while measuring nothing."""
    result = _dispatching_run(tmp_path, codex_blocks=False)

    assert "NO block line" in result.stdout, result.stdout


def test_the_hook_log_survives_the_throwaway_codex_home(tmp_path: Path) -> None:
    """Bug 3, the half the probe controls. `CODEX_HOME` is the Codex adapter's
    env var, so `agent_runtime_dir` resolves the runtime dir to it before it
    ever looks at the profile's `config_dir` — the log went to the throwaway
    home, and the probe removed that home on exit."""
    result = _dispatching_run(tmp_path)

    preserved = tmp_path / "out" / "codex-home" / "logs" / "hooks.log"
    assert preserved.is_file(), f"the hook log was not preserved.\nstdout:\n{result.stdout}"
    assert "invoked" in preserved.read_text(encoding="utf-8")


def test_the_summary_counts_the_log_it_preserved(tmp_path: Path) -> None:
    """The summary read `$CFG/<profile>/logs/hooks.log` and printed `no log —
    no hook ever ran under it` for a hook that had just blocked."""
    result = _dispatching_run(tmp_path)

    assert "no hook ever ran" not in result.stdout, result.stdout
    assert "invoked" in result.stdout


def test_diag_is_not_reported_as_a_wrapper_that_died(tmp_path: Path) -> None:
    """Bug 4. `diag` exits before the command by design — it records the
    environment and nothing else — so `exit=<none: the wrapper ran but never
    reached the command>` was a false alarm about the one group that behaved."""
    result = _dispatching_run(tmp_path)

    diag = result.stdout[result.stdout.index("-- diag") :]
    diag = diag[: diag.index("-- capture-abs")]
    assert "never reached the command" not in diag, diag
    assert "env only" in diag, diag

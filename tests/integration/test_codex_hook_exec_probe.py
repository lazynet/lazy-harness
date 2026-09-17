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
    _run(tmp_path)

    witness = tmp_path / "witness"
    assert witness.exists(), "the probe never invoked anything without --dry-run"


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

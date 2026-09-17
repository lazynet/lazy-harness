"""The gate drives, writes and reads ONE Codex home, by construction.

`LH_HOOK_TRACE` (#382) exists so phase B can tell a hook whose group the agent
never consulted from one that fired and allowed. Its line goes wherever
`agent_runtime_dir` resolves the runtime dir to, and that resolution reads the
adapter's own env var FIRST and the profile's `config_dir` only second
(`core/paths.py`, ADR-032 L3). Measured on 2026-09-17:

    CODEX_HOME=$T  lh hook pre-tool-use-security --profile probe-abs
      -> $T/logs/hooks.log                       exists
      -> <config_dir>/probe-abs/logs/hooks.log   does not

The gate resolves the log it reads from `lh run --dry-run`, which prints the
`config_dir`-derived value and ignores whatever `CODEX_HOME` the calling shell
carries — also measured: an ambient `/tmp/elsewhere` still printed
`~/.codex-lazy`. So the gate read one directory and drove `codex exec` in an
environment free to name another, and the two agreed only because the machine
that ran it had the variable unset. On a shell that exports it the gate would
drive a different Codex install, with a different `hooks.json` and a different
trust store, and report on a log that install never wrote to.

Pinning it closes that by construction rather than by the ambient environment
happening to be empty. Each function is extracted with `awk` and evaluated on
its own, the way `test_f9_gate_fired_verdicts.py` does: sourcing the whole
script runs it.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent.parent
GATE_SH = REPO_ROOT / "specs" / "gates" / "f9" / "codex-acceptance.sh"

ELSEWHERE = "/tmp/f9-ambient-codex-home-that-is-not-the-profiles"


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


def _shim(path: Path, body: str) -> Path:
    path.write_text(body, encoding="utf-8")
    path.chmod(0o755)
    return path


def _run(script: str, *, ambient_home: str | None) -> subprocess.CompletedProcess[str]:
    import os

    env = dict(os.environ)
    if ambient_home is None:
        env.pop("CODEX_HOME", None)
    else:
        env["CODEX_HOME"] = ambient_home
    return subprocess.run(
        ["bash", "-c", script], capture_output=True, text=True, timeout=60, env=env
    )


# --- codex_turn ------------------------------------------------------------


def _turn_script(tmp_path: Path, *, codex_home_dir: str) -> str:
    # Swallows the budget and runs the command, so the turn is reached.
    _shim(tmp_path / "timeout", '#!/bin/sh\nshift\nexec "$@"\n')
    # Reports the one fact under test and nothing else.
    _shim(tmp_path / "codex", '#!/bin/sh\necho "CODEX_HOME=${CODEX_HOME:-<unset>}"\n')
    return f"""
set -u
show() {{ :; }}
WORK={tmp_path}
DRY_RUN=0
TURN_BUDGET=5
TIMEOUT_BIN={tmp_path}/timeout
CODEX_BIN={tmp_path}/codex
TRACE_HOOKS=1
CODEX_HOME_DIR={codex_home_dir!r}
{_function_source("codex_turn")}
codex_turn probe "a prompt"
cat {tmp_path}/stream-probe.jsonl
"""


def test_a_turn_runs_against_the_profiles_codex_home(tmp_path: Path) -> None:
    """The gate parses this value off `lh run --dry-run` and then reads a log
    under it. A turn driven against a different one measures a different
    install's hooks and trust store."""
    home = str(tmp_path / "codex-lazy")
    result = _run(_turn_script(tmp_path, codex_home_dir=home), ambient_home=ELSEWHERE)

    assert f"CODEX_HOME={home}" in result.stdout, (
        f"the turn inherited the ambient home.\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )


def test_a_turn_leaves_the_environment_alone_when_nothing_resolved(
    tmp_path: Path,
) -> None:
    """The other direction. `CODEX_HOME_DIR` is empty whenever `lh run
    --dry-run` printed no value, and exporting an empty one would send Codex to
    a home named by the empty string — strictly worse than not pinning."""
    result = _run(_turn_script(tmp_path, codex_home_dir=""), ambient_home=ELSEWHERE)

    assert f"CODEX_HOME={ELSEWHERE}" in result.stdout, result.stdout


# --- trace_is_live ---------------------------------------------------------


def _trace_script(tmp_path: Path, *, codex_home_dir: str) -> str:
    """An `lh` that writes its trace line where `agent_runtime_dir` puts it:
    under `CODEX_HOME` when that is set, which is the behaviour under test."""
    _shim(
        tmp_path / "lh",
        "#!/bin/sh\n"
        'home="${CODEX_HOME:-/dev/null/nowhere}"\n'
        'mkdir -p "$home/logs" 2>/dev/null || exit 0\n'
        'echo "pre-tool-use-security: invoked" >> "$home/logs/hooks.log"\n',
    )
    log = tmp_path / "codex-lazy" / "logs" / "hooks.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    log.write_text("", encoding="utf-8")
    return f"""
set -u
CODEX_HOME_DIR={codex_home_dir!r}
{_function_source("security_invoked_count")}
{_function_source("trace_is_live")}
trace_is_live {tmp_path}/lh lazy-codex {log}
"""


def test_the_trace_self_test_writes_where_the_gate_reads(tmp_path: Path) -> None:
    """It runs one hook and subtracts counters around it. Unpinned, the line
    lands under the ambient home while the count is taken on the profile's log,
    the difference is always zero, and the gate concludes the binary has no
    trace at all — degrading every phase B verdict on a working one."""
    result = _run(
        _trace_script(tmp_path, codex_home_dir=str(tmp_path / "codex-lazy")),
        ambient_home=ELSEWHERE,
    )

    assert result.stdout.strip() == "yes", (
        f"the trace self-test could not see its own line.\nstdout:\n{result.stdout}\n"
        f"stderr:\n{result.stderr}"
    )


def test_the_trace_self_test_still_says_no_when_nothing_is_written(
    tmp_path: Path,
) -> None:
    """The other direction: a self-test hard-wired to `yes` would pass the test
    above and hand phase B a `never-invoked` it cannot support."""
    _shim(tmp_path / "lh", "#!/bin/sh\nexit 0\n")
    log = tmp_path / "codex-lazy" / "logs" / "hooks.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    log.write_text("", encoding="utf-8")
    script = f"""
set -u
CODEX_HOME_DIR={str(tmp_path / "codex-lazy")!r}
{_function_source("security_invoked_count")}
{_function_source("trace_is_live")}
trace_is_live {tmp_path}/lh lazy-codex {log}
"""
    result = _run(script, ambient_home=None)

    assert result.stdout.strip() == "no", result.stdout


# --- the variable the two share --------------------------------------------


def test_codex_home_dir_is_initialised_before_any_conditional_sets_it() -> None:
    """The gate runs under `set -u` and only assigns it inside the non-dry-run
    branch, so a dry run expanding it would die on an unbound variable."""
    text = GATE_SH.read_text(encoding="utf-8")
    declaration = text.index('CODEX_HOME_DIR=""')
    first_parse = text.index("sed -n 's/^CODEX_HOME: *//p'")

    assert declaration < first_parse

"""`codex-matcher-probe.sh --dry-run` renders the hooks.json and spawns nothing.

The probe answers one question the repo cannot answer by reading code: does
Codex 0.154.0 honour a `PreToolUse` matcher, and in which spellings. The
measurement is the user's — it needs the binary, a credential and a plain
terminal — but the `hooks.json` it installs is the *whole experiment*, so a
typo there would produce a confident table about nothing. `--dry-run` renders
exactly that file, and this is where it is pinned.

**The absence is asserted in a pair, like the F9 gate's own dry-run tests.**
"No process was spawned" passes just as well when the script exits on line 3,
so the shim witness is checked both ways: empty under `--dry-run`, non-empty
without it. The shims exit 97 rather than 0, so a broken script that continues
past them reports a phase it never ran.

**The control group's position is load-bearing and is asserted here.** The
matcher-less group is emitted LAST. Put first, it would fire on every call and
a run in which nothing else fired could not tell "Codex evaluates only the
first matching group" from "every other matcher matched nothing" — which is
precisely the hypothesis the probe exists to separate.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent.parent
PROBE_SH = REPO_ROOT / "specs" / "gates" / "probes" / "codex-matcher-probe.sh"

# Typed here and asserted against the script's output rather than read from it:
# a spelling silently dropped from the script fails this test instead of
# rewriting it. The matchers are the Claude Code literals the harness deploys
# today (`~/.codex-lazy/hooks.json`, measured 2026-09-17) plus the Codex-native
# names `_TOOL_OPERATIONS` maps, plus an anchored regex.
EXPECTED_GROUPS: tuple[tuple[str, str | None], ...] = (
    ("bare-bash", "Bash"),
    ("alt-claude", "Bash|Read|Edit|Write|NotebookEdit"),
    ("edit-write", "Edit|Write"),
    ("apply-patch", "apply_patch"),
    ("shell", "shell"),
    ("regex-anchor", "^Bash$"),
    ("none", None),
)

WITNESS_VAR = "MATCHER_PROBE_WITNESS"

_SHIM = """#!/bin/sh
printf '%s %s\\n' "$(basename "$0")" "$*" >> "$MATCHER_PROBE_WITNESS"
exit 97
"""


def _shims(tmp_path: Path) -> tuple[Path, Path]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name in ("codex", "timeout", "gtimeout"):
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
    env["MATCHER_PROBE_WITNESS"] = str(witness)
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
    """The hooks.json the dry run printed, parsed by a real JSON parser.

    Asserting on the text would pass on a document Codex cannot load, which is
    the failure mode that would cost a whole run before anyone noticed.
    """
    start = result.stdout.index("{")
    end = result.stdout.rindex("}") + 1
    return json.loads(result.stdout[start:end])


def test_dry_run_exits_zero(tmp_path: Path) -> None:
    result = _run(tmp_path, "--dry-run")

    assert result.returncode == 0, f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"


def test_dry_run_spawns_nothing(tmp_path: Path) -> None:
    """Half of a pair — meaningless without the test right below it."""
    result = _run(tmp_path, "--dry-run")

    assert result.returncode == 0, result.stderr
    assert not (tmp_path / "witness").exists(), (tmp_path / "witness").read_text()


def test_a_real_run_reaches_for_the_binary(tmp_path: Path) -> None:
    """The half that makes the absence above load-bearing: the shims are on
    this PATH, executable and observed, so an empty witness is `--dry-run`
    suppressing execution rather than the script failing to look."""
    result = _run(tmp_path)

    witness = tmp_path / "witness"
    assert witness.exists(), (
        f"the probe never invoked codex without --dry-run.\n"
        f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )
    assert "codex" in witness.read_text(encoding="utf-8")


def test_the_rendered_document_is_valid_json_codex_could_load(tmp_path: Path) -> None:
    document = _rendered(_run(tmp_path, "--dry-run"))

    assert isinstance(document["hooks"]["PreToolUse"], list)


def test_every_declared_spelling_is_rendered_in_order(tmp_path: Path) -> None:
    groups = _rendered(_run(tmp_path, "--dry-run"))["hooks"]["PreToolUse"]

    assert len(groups) == len(EXPECTED_GROUPS)
    for group, (label, matcher) in zip(groups, EXPECTED_GROUPS, strict=True):
        assert group.get("matcher") == matcher, f"{label}: {group.get('matcher')!r}"


def test_the_matcher_less_control_group_is_last(tmp_path: Path) -> None:
    """Emitted first, it cannot be told apart from first-match-wins."""
    groups = _rendered(_run(tmp_path, "--dry-run"))["hooks"]["PreToolUse"]

    assert "matcher" not in groups[-1]
    assert all("matcher" in group for group in groups[:-1])


def test_each_group_writes_to_a_sink_named_for_its_own_label(tmp_path: Path) -> None:
    """Two groups sharing a sink would report one spelling's payloads under
    another's name — the table would be wrong and would look measured."""
    groups = _rendered(_run(tmp_path, "--dry-run"))["hooks"]["PreToolUse"]

    commands = [group["hooks"][0]["command"] for group in groups]
    for command, (label, _) in zip(commands, EXPECTED_GROUPS, strict=True):
        assert f" {label} " in command, f"{label} not passed to its handler: {command}"
    assert len(set(commands)) == len(commands)


def test_the_probe_declares_only_pre_tool_use(tmp_path: Path) -> None:
    """Every other event fires without a tool call and would add rows that say
    nothing about matchers."""
    document = _rendered(_run(tmp_path, "--dry-run"))

    assert list(document["hooks"]) == ["PreToolUse"]


def test_dry_run_names_the_two_turns_it_would_drive(tmp_path: Path) -> None:
    """One turn measures a shell call, the other the native edit path; a probe
    that ran only one would leave `apply_patch` unmeasured."""
    stdout = _run(tmp_path, "--dry-run").stdout

    assert "shell" in stdout
    assert "edit" in stdout


def test_the_handler_is_written_beside_the_rendered_document(tmp_path: Path) -> None:
    """The command references a file the dry run must also have produced,
    otherwise the rendered document is a plan for handlers that do not exist."""
    result = _run(tmp_path, "--dry-run")
    groups = _rendered(result)["hooks"]["PreToolUse"]

    handler = groups[0]["hooks"][0]["command"].split()[1]
    assert Path(handler).is_file(), f"handler not written: {handler}"
    assert Path(handler).read_text(encoding="utf-8").startswith("#!")


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

"""Tests for `lh run` — profile resolution feedback.

Falling back to the default profile because no configured root matched the cwd
is the failure mode that cannot announce itself: the agent starts, runs against
the wrong config dir, and nothing looks broken. These pin the warning that
makes it visible, and pin it to stderr — stdout belongs to the agent once
`lh run` execs it.
"""

from __future__ import annotations

import json
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest
from click.testing import CliRunner

WARNING_MARKER = "no configured root matches"


def _write_agent(body: str = 'import sys\nprint("{\\"ok\\": true}")\n') -> Path:
    """Install a fake agent binary where `ClaudeCodeAdapter` looks for one."""
    versions = Path.home() / ".local" / "share" / "claude" / "versions"
    versions.mkdir(parents=True, exist_ok=True)
    binary = versions / "0.0.1-fake"
    binary.write_text(f"#!{sys.executable}\n{textwrap.dedent(body)}")
    binary.chmod(0o755)
    return binary


def _write_config(lh_config: Path, profiles: str, default: str = "personal") -> None:
    (lh_config / "config.toml").write_text(
        '[harness]\nversion = "1"\n\n'
        '[agent]\ntype = "claude-code"\n\n'
        f'[profiles]\ndefault = "{default}"\n\n' + profiles
    )


@pytest.fixture
def routed_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Two profiles, `work` owning a root. Anything else falls back."""
    lh_config = tmp_path / "lh"
    lh_config.mkdir()
    work_root = tmp_path / "work"
    work_root.mkdir()
    _write_config(
        lh_config,
        f'[profiles.personal]\nconfig_dir = "{tmp_path / "cfg-personal"}"\nroots = []\n\n'
        f'[profiles.work]\nconfig_dir = "{tmp_path / "cfg-work"}"\nroots = ["{work_root}"]\n',
    )
    monkeypatch.setenv("LH_CONFIG_DIR", str(lh_config))
    monkeypatch.setenv("LH_CACHE_DIR", str(tmp_path / "cache"))
    return lh_config


def _run_in(args: list[str], cwd: Path) -> tuple[int, str, str]:
    import os

    previous = Path.cwd()
    os.chdir(cwd)
    try:
        from lazy_harness.cli.run_cmd import run

        runner = CliRunner()
        result = runner.invoke(run, args, catch_exceptions=False)
        return result.exit_code, result.stdout, result.stderr
    finally:
        os.chdir(previous)


def test_run_warns_when_no_root_matched(routed_config: Path, tmp_path: Path) -> None:
    _write_agent()
    outside = tmp_path / "outside"
    outside.mkdir()

    _, _, stderr = _run_in(["--dry-run"], outside)

    assert WARNING_MARKER in stderr


def test_the_warning_names_the_directory_that_did_not_match(
    routed_config: Path, tmp_path: Path
) -> None:
    """Without the path, the reader cannot tell which launch was misrouted."""
    _write_agent()
    outside = tmp_path / "outside"
    outside.mkdir()

    _, _, stderr = _run_in(["--dry-run"], outside)

    assert str(outside) in stderr


def test_the_warning_names_the_profile_that_was_guessed(
    routed_config: Path, tmp_path: Path
) -> None:
    _write_agent()
    outside = tmp_path / "outside"
    outside.mkdir()

    _, _, stderr = _run_in(["--dry-run"], outside)

    # Anchored to the warning line: `--dry-run` already prints the profile
    # elsewhere, so a bare `"personal" in stderr` would pass without a warning.
    warning = next(line for line in stderr.splitlines() if WARNING_MARKER in line)
    assert "personal" in warning


def test_run_is_quiet_when_a_root_matched(routed_config: Path, tmp_path: Path) -> None:
    _write_agent()

    _, _, stderr = _run_in(["--dry-run"], tmp_path / "work")

    assert WARNING_MARKER not in stderr


def test_run_is_quiet_when_the_profile_was_explicit(routed_config: Path, tmp_path: Path) -> None:
    """`--profile` is a decision, not a guess."""
    _write_agent()
    outside = tmp_path / "outside"
    outside.mkdir()

    _, _, stderr = _run_in(["--dry-run", "--profile", "personal"], outside)

    assert WARNING_MARKER not in stderr


def test_run_is_quiet_when_no_profile_declares_a_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """With cwd routing unconfigured, the default profile is the design, not a guess."""
    _write_agent()
    lh_config = tmp_path / "lh"
    lh_config.mkdir()
    _write_config(
        lh_config,
        f'[profiles.personal]\nconfig_dir = "{tmp_path / "cfg-personal"}"\nroots = []\n\n'
        f'[profiles.work]\nconfig_dir = "{tmp_path / "cfg-work"}"\nroots = []\n',
    )
    monkeypatch.setenv("LH_CONFIG_DIR", str(lh_config))
    monkeypatch.setenv("LH_CACHE_DIR", str(tmp_path / "cache"))
    outside = tmp_path / "outside"
    outside.mkdir()

    _, _, stderr = _run_in(["--dry-run"], outside)

    assert WARNING_MARKER not in stderr


# --- the channel invariant -------------------------------------------------


def test_the_warning_never_reaches_stdout(routed_config: Path, tmp_path: Path) -> None:
    """After exec, stdout is the agent's. A warning there corrupts the envelope."""
    _write_agent()
    outside = tmp_path / "outside"
    outside.mkdir()

    _, stdout, _ = _run_in(["--dry-run"], outside)

    assert WARNING_MARKER not in stdout


def test_the_agent_stdout_stays_parseable_past_the_warning(
    routed_config: Path, tmp_path: Path
) -> None:
    """The real shape: `lh run` warns, execs, and the agent's JSON is intact."""
    _write_agent('import sys\nprint(\'{"result": "hi"}\')\n')
    outside = tmp_path / "outside"
    outside.mkdir()

    env = _child_env(routed_config)
    proc = subprocess.run(
        [sys.executable, "-c", "from lazy_harness.cli.main import cli; cli()", "run"],
        cwd=outside,
        input="",
        capture_output=True,
        text=True,
        env=env,
        timeout=60,
    )

    assert json.loads(proc.stdout) == {"result": "hi"}
    assert WARNING_MARKER in proc.stderr


def _child_env(lh_config: Path) -> dict[str, str]:
    import os

    env = dict(os.environ)
    env["LH_CONFIG_DIR"] = str(lh_config)
    env["COLUMNS"] = "400"
    return env


def test_the_warning_fires_without_a_tty(routed_config: Path, tmp_path: Path) -> None:
    """The scheduled callers have no tty and are the ones most likely misrouted."""
    _write_agent()
    outside = tmp_path / "outside"
    outside.mkdir()

    proc = subprocess.run(
        [sys.executable, "-c", "from lazy_harness.cli.main import cli; cli()", "run", "--dry-run"],
        cwd=outside,
        input="",
        capture_output=True,
        text=True,
        env=_child_env(routed_config),
        timeout=60,
    )

    assert WARNING_MARKER in proc.stderr, "a piped stdin must not silence the warning"


# --- D7: two profiles sharing a root, unresolved without a default --------


def test_run_refuses_a_shared_root_with_no_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Design decision 7: `lh run` must not silently pick by TOML order."""
    lh_config = tmp_path / "lh"
    lh_config.mkdir()
    shared = tmp_path / "shared"
    shared.mkdir()
    _write_config(
        lh_config,
        f'[profiles.personal]\nconfig_dir = "{tmp_path / "cfg-personal"}"\n'
        f'roots = ["{shared}"]\n\n'
        f'[profiles.experiment]\nconfig_dir = "{tmp_path / "cfg-experiment"}"\n'
        f'roots = ["{shared}"]\nagent = "null"\n',
    )
    monkeypatch.setenv("LH_CONFIG_DIR", str(lh_config))
    monkeypatch.setenv("LH_CACHE_DIR", str(tmp_path / "cache"))

    code, _out, err = _run_in(["--dry-run"], shared)

    assert code != 0
    assert "personal" in err
    assert "experiment" in err


def test_run_uses_the_root_default_among_a_shared_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lh_config = tmp_path / "lh"
    lh_config.mkdir()
    shared = tmp_path / "shared"
    shared.mkdir()
    _write_config(
        lh_config,
        f'[profiles.personal]\nconfig_dir = "{tmp_path / "cfg-personal"}"\n'
        f'roots = ["{shared}"]\nroot_default = true\n\n'
        f'[profiles.experiment]\nconfig_dir = "{tmp_path / "cfg-experiment"}"\n'
        f'roots = ["{shared}"]\nagent = "null"\n',
    )
    monkeypatch.setenv("LH_CONFIG_DIR", str(lh_config))
    monkeypatch.setenv("LH_CACHE_DIR", str(tmp_path / "cache"))

    code, out, err = _run_in(["--dry-run"], shared)

    assert code == 0, err
    assert "personal" in err, out + err


def test_run_names_a_binary_it_could_not_launch_instead_of_raising(
    routed_config: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A failed `exec` is a diagnostic, not a traceback out of `cli()`.

    `execvpe` is the last thing `lh run` does and it does not return, so every
    failure at that point reaches the user as an unhandled exception through
    click. The one that actually happened read `FileNotFoundError: [Errno 2]
    No such file or directory: '<cache>/bin/claude'` over eleven frames of
    click internals, about a file that was on disk — the missing thing was the
    interpreter in its shebang. Six lines of stack say nothing a person can act
    on; the path and the reason do.

    The syscall is the one thing that has to be faked here: it replaces the
    process image, so a real one ends the test run.
    """
    import os

    agent = _write_agent()

    shim = tmp_path / "cache" / "bin" / "claude"

    def refuse(*args: object, **kwargs: object) -> None:
        raise FileNotFoundError(2, "No such file or directory", str(shim))

    monkeypatch.setattr(os, "execvpe", refuse)

    code, _out, err = _run_in([], tmp_path)
    # Rich wraps to the console width, so a long path arrives with newlines in
    # the middle of it. Joined, not widened: the wrapping is what a terminal
    # does and is not what this test is about.
    flat = err.replace("\n", "")

    assert code != 0
    # Both paths, because neither alone is actionable: the shim is a name the
    # user never chose, and the build it stands for is the thing they can check.
    assert str(shim) in flat
    assert str(agent) in flat
    assert "No such file or directory" in flat

"""`lh run --bypass` — one declared axis on an otherwise untouched passthrough.

`lh run` forwards argv verbatim, which is why `lcca` could ship a Claude Code
flag to whatever binary the profile resolved. `--bypass` is the one argument it
interprets: the level is expanded by the profile's own adapter, or the launch is
refused naming the agent and the level.

Two profiles throughout, a claude one and a codex one, because the bug this
closes only appears when the flag and the binary disagree — a single-profile
suite would pass on an implementation that ignored the adapter entirely.
"""

from __future__ import annotations

import ast
import os
import sys
import textwrap
from pathlib import Path

import pytest
from click.testing import CliRunner


def _fake_binary(directory: Path, name: str) -> Path:
    """A binary that exists and is executable. It is never executed here —
    `--dry-run` returns before the exec — but `resolve_launch` refuses a
    profile whose binary it cannot find, so it has to be on disk."""
    directory.mkdir(parents=True, exist_ok=True)
    binary = directory / name
    binary.write_text(f"#!{sys.executable}\n{textwrap.dedent('pass')}\n")
    binary.chmod(0o755)
    return binary


@pytest.fixture
def two_profiles(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """`cc` resolves Claude Code, `cx` resolves Codex, neither owns a root.

    The codex binary goes on a `PATH` this fixture controls rather than being
    taken from the machine: `CodexAdapter.resolve_binary` is a `shutil.which`,
    and a test that passed only on a developer box with codex installed would
    be a test that says nothing in CI.
    """
    lh_config = tmp_path / "lh"
    lh_config.mkdir()

    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    versions = Path.home() / ".local" / "share" / "claude" / "versions"
    _fake_binary(versions, "0.0.1-fake")

    bin_dir = tmp_path / "bin"
    _fake_binary(bin_dir, "codex")
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")

    (lh_config / "config.toml").write_text(
        '[harness]\nversion = "1"\n\n'
        '[agent]\ntype = "claude-code"\n\n'
        '[profiles]\ndefault = "cc"\n\n'
        f'[profiles.cc]\nconfig_dir = "{tmp_path / "cfg-cc"}"\nroots = []\n\n'
        f'[profiles.cx]\nconfig_dir = "{tmp_path / "cfg-cx"}"\nroots = []\n'
        'agent = "codex"\n'
    )
    monkeypatch.setenv("LH_CONFIG_DIR", str(lh_config))
    monkeypatch.setenv("LH_CACHE_DIR", str(tmp_path / "cache"))
    return lh_config


def _run(args: list[str], cwd: Path) -> tuple[int, str, str]:
    from lazy_harness.cli.run_cmd import run

    previous = Path.cwd()
    os.chdir(cwd)
    try:
        result = CliRunner().invoke(run, args, catch_exceptions=False)
        return result.exit_code, result.stdout, result.stderr
    finally:
        os.chdir(previous)


def _argv(output: str) -> list[str]:
    """The exec argv as a list, parsed rather than substring-matched.

    Read off **stderr**: `lh run` builds one `Console(stderr=True)` and prints
    everything through it, dry-run included, because stdout belongs to the
    agent from the moment it execs. `argv[0]` is also the assertion a substring
    check cannot make — `"codex" in output` is equally true of a binary path
    ending in `/codex`.
    """
    line = next(line for line in output.splitlines() if line.startswith("argv:"))
    return ast.literal_eval(line.split("argv:", 1)[1].strip())


# --- the expansion ----------------------------------------------------------


def test_enable_expands_to_the_claude_flag_lcca_ships_today(
    two_profiles: Path, tmp_path: Path
) -> None:
    """The migration's whole point: `lh run --bypass=enable` has to mean what
    `lcca` means today, or the alias change is a behaviour change."""
    code, _, out = _run(["--profile", "cc", "--dry-run", "--bypass", "enable"], tmp_path)

    assert code == 0
    assert "--allow-dangerously-skip-permissions" in out


def test_activate_expands_to_the_claude_flag_that_turns_it_on(
    two_profiles: Path, tmp_path: Path
) -> None:
    code, _, out = _run(["--profile", "cc", "--dry-run", "--bypass", "activate"], tmp_path)

    assert code == 0
    assert _argv(out) == ["claude", "--dangerously-skip-permissions"]


def test_the_same_level_expands_differently_on_a_codex_profile(
    two_profiles: Path, tmp_path: Path
) -> None:
    """The bug being closed, stated as a test: one level, two agents, two
    different flags — and never the other agent's."""
    code, _, out = _run(["--profile", "cx", "--dry-run", "--bypass", "activate"], tmp_path)

    assert code == 0
    assert "--approve-for-me" in out
    assert "dangerously-skip-permissions" not in out


def test_no_sandbox_is_spelled_with_a_hyphen_on_the_cli(two_profiles: Path, tmp_path: Path) -> None:
    """The enum member is `no_sandbox`; a user types `no-sandbox`."""
    code, _, out = _run(["--profile", "cx", "--dry-run", "--bypass", "no-sandbox"], tmp_path)

    assert code == 0
    assert "--dangerously-bypass-approvals-and-sandbox" in out


def test_the_expansion_lands_after_argv0_and_before_the_passthrough(
    two_profiles: Path, tmp_path: Path
) -> None:
    """Order is not cosmetic: argv[0] is what herdr reads to identify the agent,
    and a flag ahead of it would break that before the agent ever parsed it."""
    code, _, out = _run(
        ["--profile", "cc", "--dry-run", "--bypass", "enable", "--resume", "abc"], tmp_path
    )

    assert code == 0
    argv = _argv(out)
    assert argv == ["claude", "--allow-dangerously-skip-permissions", "--resume", "abc"]


def test_everything_else_stays_a_passthrough(two_profiles: Path, tmp_path: Path) -> None:
    """One axis, not an argv translation layer."""
    code, _, out = _run(
        ["--profile", "cc", "--dry-run", "--bypass", "enable", "--model", "opus"], tmp_path
    )

    assert code == 0
    assert _argv(out)[-2:] == ["--model", "opus"]


def test_no_bypass_flag_leaves_argv_exactly_as_it_was(two_profiles: Path, tmp_path: Path) -> None:
    """The default has to be the old behaviour, byte for byte."""
    code, _, out = _run(["--profile", "cc", "--dry-run", "--", "--resume"], tmp_path)

    assert code == 0
    assert "dangerously" not in out


# --- argv[0], which herdr reads --------------------------------------------


@pytest.mark.parametrize(("profile", "expected"), [("cc", "claude"), ("cx", "codex")])
def test_argv0_is_the_process_name_not_the_binary_path(
    two_profiles: Path, tmp_path: Path, profile: str, expected: str
) -> None:
    """herdr identifies the agent from the process name. A profile resolving to
    a binary path here would be a silent misidentification, so it is asserted
    rather than assumed — for both agents, with `--bypass` in play."""
    code, _, out = _run(["--profile", profile, "--dry-run", "--bypass", "activate"], tmp_path)

    assert code == 0
    assert _argv(out)[0] == expected


# --- the refusal ------------------------------------------------------------


def test_a_level_the_agent_lacks_exits_non_zero(two_profiles: Path, tmp_path: Path) -> None:
    """Claude Code has no OS-sandbox flag. Forwarding the ACTIVATE flag instead
    would be a more permissive launch than the one that was asked for."""
    code, _, out = _run(["--profile", "cc", "--dry-run", "--bypass", "no-sandbox"], tmp_path)

    assert code == 1
    assert "dangerously" not in out


def test_the_refusal_names_the_agent_and_the_level(two_profiles: Path, tmp_path: Path) -> None:
    code, _, stderr = _run(["--profile", "cc", "--dry-run", "--bypass", "no-sandbox"], tmp_path)

    assert code == 1
    assert "claude-code" in stderr
    assert "no-sandbox" in stderr


def test_codex_refuses_enable_by_name(two_profiles: Path, tmp_path: Path) -> None:
    """The measured `None`: 0.154.0 has no available-but-off position."""
    code, _, stderr = _run(["--profile", "cx", "--dry-run", "--bypass", "enable"], tmp_path)

    assert code == 1
    assert "codex" in stderr
    assert "enable" in stderr


def test_an_unknown_level_is_rejected_by_the_parser(two_profiles: Path, tmp_path: Path) -> None:
    """A fourth position would have to be declared on the enum first. Click's
    own exit code for a bad choice is 2, distinct from the adapter's 1."""
    code, _, _ = _run(["--profile", "cc", "--dry-run", "--bypass", "yolo"], tmp_path)

    assert code == 2


def test_the_choice_offers_exactly_the_three_levels() -> None:
    """The help text is the only place a user learns the spelling."""
    from lazy_harness.cli.run_cmd import run

    result = CliRunner().invoke(run, ["--help"], catch_exceptions=False)

    assert "enable" in result.stdout
    assert "activate" in result.stdout
    assert "no-sandbox" in result.stdout

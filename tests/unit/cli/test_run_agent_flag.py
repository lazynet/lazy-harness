"""`lh run --agent` — filters profile resolution to one agent's profiles.

Two profiles, neither owning a root, so resolution falls back to
`profiles.default` (`cc`) unless `--agent` narrows the candidates first.
"""

from __future__ import annotations

import os
import sys
import textwrap
from pathlib import Path

import pytest
from click.testing import CliRunner


def _fake_binary(directory: Path, name: str) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    binary = directory / name
    binary.write_text(f"#!{sys.executable}\n{textwrap.dedent('pass')}\n")
    binary.chmod(0o755)
    return binary


@pytest.fixture
def two_profiles(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
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


def test_agent_codex_resolves_the_codex_profile_and_prints_its_env_var(
    two_profiles: Path, tmp_path: Path
) -> None:
    code, _, out = _run(["--agent", "codex", "--dry-run"], tmp_path)

    assert code == 0, out
    assert "profile: cx" in out
    assert "CODEX_HOME" in out


def test_no_agent_flag_resolves_exactly_as_before(two_profiles: Path, tmp_path: Path) -> None:
    """Parameter-less smoke test: the default flow must be untouched."""
    code, _, out = _run(["--dry-run"], tmp_path)

    assert code == 0, out
    assert "profile: cc" in out

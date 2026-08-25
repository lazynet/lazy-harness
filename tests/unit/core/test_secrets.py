"""Per-profile secrets.

`CLAUDE_CODE_OAUTH_TOKEN` is one global variable, and the agent's credentials
live inside the profile's `config_dir`. Two profiles backed by two Anthropic
accounts cannot share one token, and a second value in `environment.d` replaces
the first rather than sitting beside it — so without this, the second profile
authenticates as the first account, silently.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest


def test_a_profile_file_overrides_the_inherited_environment(tmp_path: Path) -> None:
    from lazy_harness.core.secrets import overlay_profile_secrets

    secrets_dir = tmp_path / "secrets"
    secrets_dir.mkdir()
    (secrets_dir / "flex.env").write_text("CLAUDE_CODE_OAUTH_TOKEN=flex-token\n")
    (secrets_dir / "flex.env").chmod(0o600)

    env = {"CLAUDE_CODE_OAUTH_TOKEN": "lazy-token", "PATH": "/usr/bin"}
    result = overlay_profile_secrets(env, "flex", secrets_dir=secrets_dir)

    assert result["CLAUDE_CODE_OAUTH_TOKEN"] == "flex-token"
    assert result["PATH"] == "/usr/bin", "unrelated variables survive"


def test_the_caller_environment_is_not_mutated(tmp_path: Path) -> None:
    """`lh run` execs with the returned mapping; mutating `os.environ` in place
    would leak one profile's token into anything else in this process."""
    from lazy_harness.core.secrets import overlay_profile_secrets

    secrets_dir = tmp_path / "secrets"
    secrets_dir.mkdir()
    (secrets_dir / "flex.env").write_text("TOKEN=flex\n")
    (secrets_dir / "flex.env").chmod(0o600)

    env = {"TOKEN": "lazy"}
    overlay_profile_secrets(env, "flex", secrets_dir=secrets_dir)

    assert env["TOKEN"] == "lazy"


def test_a_missing_file_changes_nothing(tmp_path: Path) -> None:
    """The default profile takes its values from the global environment and has
    no file at all. That is the normal case, not an error."""
    from lazy_harness.core.secrets import overlay_profile_secrets

    env = {"CLAUDE_CODE_OAUTH_TOKEN": "lazy-token"}
    result = overlay_profile_secrets(env, "lazy", secrets_dir=tmp_path / "nope")

    assert result == env


def test_comments_and_blank_lines_are_ignored(tmp_path: Path) -> None:
    from lazy_harness.core.secrets import overlay_profile_secrets

    secrets_dir = tmp_path / "secrets"
    secrets_dir.mkdir()
    (secrets_dir / "flex.env").write_text(
        "# the flex account\n\nA=1\n\n  # indented comment\nB=2\n"
    )
    (secrets_dir / "flex.env").chmod(0o600)

    result = overlay_profile_secrets({}, "flex", secrets_dir=secrets_dir)

    assert result == {"A": "1", "B": "2"}


def test_a_value_containing_an_equals_sign_survives(tmp_path: Path) -> None:
    """Base64 and JWT-shaped tokens routinely contain `=`."""
    from lazy_harness.core.secrets import overlay_profile_secrets

    secrets_dir = tmp_path / "secrets"
    secrets_dir.mkdir()
    (secrets_dir / "flex.env").write_text("TOKEN=abc==\n")
    (secrets_dir / "flex.env").chmod(0o600)

    assert overlay_profile_secrets({}, "flex", secrets_dir=secrets_dir)["TOKEN"] == "abc=="


def test_surrounding_quotes_are_stripped(tmp_path: Path) -> None:
    from lazy_harness.core.secrets import overlay_profile_secrets

    secrets_dir = tmp_path / "secrets"
    secrets_dir.mkdir()
    (secrets_dir / "flex.env").write_text("A=\"quoted\"\nB='single'\nC=bare\n")
    (secrets_dir / "flex.env").chmod(0o600)

    result = overlay_profile_secrets({}, "flex", secrets_dir=secrets_dir)

    assert result == {"A": "quoted", "B": "single", "C": "bare"}


def test_a_world_readable_file_is_reported_and_still_used(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The contract with the provisioner is 0600.

    Refusing to read it would not un-leak a secret that is already readable,
    and would break the launch; saying nothing would let the exposure persist
    unnoticed. So: load it, and say so on stderr.
    """
    from lazy_harness.core.secrets import overlay_profile_secrets

    secrets_dir = tmp_path / "secrets"
    secrets_dir.mkdir()
    loose = secrets_dir / "flex.env"
    loose.write_text("TOKEN=flex\n")
    loose.chmod(0o644)

    result = overlay_profile_secrets({}, "flex", secrets_dir=secrets_dir)

    assert result["TOKEN"] == "flex"
    err = capsys.readouterr().err
    assert "0600" in err
    assert "flex.env" in err


def test_a_line_without_an_equals_sign_is_reported_and_skipped(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from lazy_harness.core.secrets import overlay_profile_secrets

    secrets_dir = tmp_path / "secrets"
    secrets_dir.mkdir()
    (secrets_dir / "flex.env").write_text("GOOD=1\nthis is not an assignment\n")
    (secrets_dir / "flex.env").chmod(0o600)

    result = overlay_profile_secrets({}, "flex", secrets_dir=secrets_dir)

    assert result == {"GOOD": "1"}
    assert "flex.env" in capsys.readouterr().err


def test_an_unreadable_file_is_reported_and_the_launch_continues(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Degrade rather than crash: `lh run` execs the agent, and a permission
    problem on one profile's secrets must not be an unhandled traceback."""
    from lazy_harness.core.secrets import overlay_profile_secrets

    secrets_dir = tmp_path / "secrets"
    secrets_dir.mkdir()
    denied = secrets_dir / "flex.env"
    denied.write_text("TOKEN=flex\n")
    denied.chmod(0o000)

    try:
        result = overlay_profile_secrets({"A": "1"}, "flex", secrets_dir=secrets_dir)
    finally:
        denied.chmod(0o600)

    assert result == {"A": "1"}
    assert "flex.env" in capsys.readouterr().err


def test_a_profile_name_cannot_escape_the_secrets_directory(tmp_path: Path) -> None:
    """Profile names come from config, but a path built by concatenation is
    worth closing anyway — this one names a file outside the directory."""
    from lazy_harness.core.secrets import overlay_profile_secrets

    secrets_dir = tmp_path / "secrets"
    secrets_dir.mkdir()
    (tmp_path / "escaped.env").write_text("TOKEN=leaked\n")

    result = overlay_profile_secrets({}, "../escaped", secrets_dir=secrets_dir)

    assert result == {}


def test_secrets_dir_defaults_to_the_config_directory(monkeypatch, tmp_path: Path) -> None:
    """Paired smoke test for the default-resolution path: always injecting
    `secrets_dir` would leave it unexercised.

    The default is `<lh config dir>/secrets/`, which is where the provisioner
    writes. Every reader of a config-derived path in this repo resolves it the
    same way, so this one honours `[secrets] dir` first and falls back here.
    """
    from lazy_harness.core.config import Config
    from lazy_harness.core.secrets import secrets_dir_for

    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))

    assert secrets_dir_for(Config()) == tmp_path / "lazy-harness" / "secrets"


def test_secrets_dir_honours_the_config_override(monkeypatch, tmp_path: Path) -> None:
    from lazy_harness.core.config import Config
    from lazy_harness.core.secrets import secrets_dir_for

    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    cfg = Config()
    cfg.secrets.dir = str(tmp_path / "elsewhere")

    assert secrets_dir_for(cfg) == tmp_path / "elsewhere"


def test_the_overlay_reaches_the_launched_process(tmp_path: Path, monkeypatch) -> None:
    """`resolve_launch` builds the environment both `lh run` and `lh exec` use.

    Wiring this into a helper nobody calls is the failure this repo already
    records once, so assert the built environment rather than trusting that
    some caller remembered to apply the overlay itself.
    """
    from lazy_harness.agents.launch import resolve_launch
    from lazy_harness.core.config import Config, ProfileEntry

    versions = Path.home() / ".local" / "share" / "claude" / "versions"
    versions.mkdir(parents=True, exist_ok=True)
    binary = versions / "0.0.1-fake"
    binary.write_text("#!/bin/sh\nexit 0\n")
    binary.chmod(0o755)

    secrets_dir = tmp_path / "secrets"
    secrets_dir.mkdir()
    (secrets_dir / "flex.env").write_text("CLAUDE_CODE_OAUTH_TOKEN=flex-token\n")
    (secrets_dir / "flex.env").chmod(0o600)

    cfg = Config()
    cfg.secrets.dir = str(secrets_dir)
    cfg.profiles.default = "flex"
    cfg.profiles.items = {"flex": ProfileEntry(config_dir=str(tmp_path / "cfg"), roots=[])}
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "lazy-token")

    plan = resolve_launch(cfg, cwd=tmp_path)

    assert plan.env["CLAUDE_CODE_OAUTH_TOKEN"] == "flex-token"
    assert plan.env["CLAUDE_CONFIG_DIR"] == str(tmp_path / "cfg")


def test_both_launch_paths_go_through_the_shared_resolution(tmp_path: Path) -> None:
    """The env-building rule lives in one place; neither CLI may rebuild it."""
    import lazy_harness.cli.exec_cmd as exec_cmd
    import lazy_harness.cli.run_cmd as run_cmd

    for module in (run_cmd, exec_cmd):
        source = Path(module.__file__).read_text()
        assert "resolve_launch" in source, f"{module.__name__} must not resolve its own launch"
        assert "overlay_profile_secrets" not in source, (
            f"{module.__name__} re-applies the overlay instead of using resolve_launch"
        )


def test_os_environ_is_untouched_by_the_overlay(tmp_path: Path, monkeypatch) -> None:
    from lazy_harness.core.secrets import overlay_profile_secrets

    secrets_dir = tmp_path / "secrets"
    secrets_dir.mkdir()
    (secrets_dir / "flex.env").write_text("LH_TEST_ONLY=from-file\n")
    (secrets_dir / "flex.env").chmod(0o600)
    monkeypatch.setenv("LH_TEST_ONLY", "from-env")

    overlay_profile_secrets(dict(os.environ), "flex", secrets_dir=secrets_dir)

    assert os.environ["LH_TEST_ONLY"] == "from-env"

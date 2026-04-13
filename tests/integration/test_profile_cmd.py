"""Integration tests for lh profile commands."""

from __future__ import annotations

from pathlib import Path

from click.testing import CliRunner

from lazy_harness.cli.main import cli
from lazy_harness.core.config import (
    Config,
    HarnessConfig,
    ProfileEntry,
    ProfilesConfig,
    save_config,
)


def _setup_config(home_dir: Path) -> Path:
    """Create a valid config file and return its path."""
    config_path = home_dir / ".config" / "lazy-harness" / "config.toml"
    cfg = Config(
        harness=HarnessConfig(version="1"),
        profiles=ProfilesConfig(
            default="personal",
            items={
                "personal": ProfileEntry(
                    config_dir=str(home_dir / ".claude-personal"),
                    roots=["~"],
                ),
            },
        ),
    )
    save_config(cfg, config_path)
    return config_path


def test_profile_list(home_dir: Path) -> None:
    _setup_config(home_dir)
    runner = CliRunner()
    result = runner.invoke(cli, ["profile", "list"])
    assert result.exit_code == 0
    assert "personal" in result.output


def test_profile_add(home_dir: Path) -> None:
    _setup_config(home_dir)
    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "profile",
            "add",
            "work",
            "--config-dir",
            str(home_dir / ".claude-work"),
            "--roots",
            "~/work",
        ],
    )
    assert result.exit_code == 0
    assert "work" in result.output or "added" in result.output.lower()

    result2 = runner.invoke(cli, ["profile", "list"])
    assert "work" in result2.output


def test_profile_add_duplicate(home_dir: Path) -> None:
    _setup_config(home_dir)
    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "profile",
            "add",
            "personal",
            "--config-dir",
            str(home_dir / ".claude-personal"),
        ],
    )
    assert result.exit_code != 0 or "already exists" in result.output.lower()


def test_profile_remove(home_dir: Path) -> None:
    config_path = _setup_config(home_dir)
    from lazy_harness.core.config import load_config

    cfg = load_config(config_path)
    cfg.profiles.items["work"] = ProfileEntry(
        config_dir=str(home_dir / ".claude-work"), roots=["~/work"]
    )
    save_config(cfg, config_path)

    runner = CliRunner()
    result = runner.invoke(cli, ["profile", "remove", "work"])
    assert result.exit_code == 0

    result2 = runner.invoke(cli, ["profile", "list"])
    assert "work" not in result2.output


def test_profile_remove_default_fails(home_dir: Path) -> None:
    _setup_config(home_dir)
    runner = CliRunner()
    result = runner.invoke(cli, ["profile", "remove", "personal"])
    assert result.exit_code != 0 or "default" in result.output.lower()


def _setup_config_with_root(home_dir: Path) -> Path:
    """Config with a profile pointing at an actual root directory."""
    config_path = home_dir / ".config" / "lazy-harness" / "config.toml"
    root = home_dir / "repos" / "lazy"
    root.mkdir(parents=True)
    cfg = Config(
        harness=HarnessConfig(version="1"),
        profiles=ProfilesConfig(
            default="personal",
            items={
                "personal": ProfileEntry(
                    config_dir=str(home_dir / ".claude-personal"),
                    roots=[str(root)],
                ),
            },
        ),
    )
    save_config(cfg, config_path)
    return root


def test_profile_envrc_creates_files(home_dir: Path) -> None:
    root = _setup_config_with_root(home_dir)
    runner = CliRunner()
    result = runner.invoke(cli, ["profile", "envrc"])
    assert result.exit_code == 0
    envrc = root / ".envrc"
    assert envrc.is_file()
    content = envrc.read_text()
    assert "CLAUDE_CONFIG_DIR" in content
    assert ".claude-personal" in content


def test_profile_envrc_dry_run_does_not_write(home_dir: Path) -> None:
    root = _setup_config_with_root(home_dir)
    runner = CliRunner()
    result = runner.invoke(cli, ["profile", "envrc", "--dry-run"])
    assert result.exit_code == 0
    assert "would write" in result.output
    assert not (root / ".envrc").exists()


def _setup_two_profiles_with_projects(home_dir: Path) -> tuple[Path, Path]:
    """Two profiles with one project each. Returns (src_dir, dst_dir)."""
    config_path = home_dir / ".config" / "lazy-harness" / "config.toml"
    src_dir = home_dir / ".claude-personal"
    dst_dir = home_dir / ".claude-work"
    cfg = Config(
        harness=HarnessConfig(version="1"),
        profiles=ProfilesConfig(
            default="personal",
            items={
                "personal": ProfileEntry(config_dir=str(src_dir), roots=["~"]),
                "work": ProfileEntry(config_dir=str(dst_dir), roots=["~/work"]),
            },
        ),
    )
    save_config(cfg, config_path)
    (src_dir / "projects" / "-Users-x-repos-foo").mkdir(parents=True)
    (src_dir / "projects" / "-Users-x-repos-foo" / "session.jsonl").write_text("{}\n")
    return src_dir, dst_dir


def test_profile_move_with_explicit_projects(home_dir: Path) -> None:
    src_dir, dst_dir = _setup_two_profiles_with_projects(home_dir)
    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "profile",
            "move",
            "--from",
            "personal",
            "--to",
            "work",
            "--projects",
            "-Users-x-repos-foo",
            "--yes",
        ],
    )
    assert result.exit_code == 0, result.output
    assert "✓" in result.output or "moved" in result.output.lower()
    assert not (src_dir / "projects" / "-Users-x-repos-foo").exists()
    assert (dst_dir / "projects" / "-Users-x-repos-foo" / "session.jsonl").is_file()


def test_profile_move_all_flag(home_dir: Path) -> None:
    src_dir, dst_dir = _setup_two_profiles_with_projects(home_dir)
    (src_dir / "projects" / "-bar").mkdir()
    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["profile", "move", "--from", "personal", "--to", "work", "--all", "--yes"],
    )
    assert result.exit_code == 0, result.output
    assert not (src_dir / "projects" / "-Users-x-repos-foo").exists()
    assert not (src_dir / "projects" / "-bar").exists()
    assert (dst_dir / "projects" / "-Users-x-repos-foo").is_dir()
    assert (dst_dir / "projects" / "-bar").is_dir()


def test_profile_move_same_profile_fails(home_dir: Path) -> None:
    _setup_two_profiles_with_projects(home_dir)
    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["profile", "move", "--from", "personal", "--to", "personal", "--all", "--yes"],
    )
    assert result.exit_code != 0
    assert "same" in result.output.lower()


def test_profile_move_unknown_profile_fails(home_dir: Path) -> None:
    _setup_two_profiles_with_projects(home_dir)
    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["profile", "move", "--from", "ghost", "--to", "work", "--all", "--yes"],
    )
    assert result.exit_code != 0
    assert "ghost" in result.output.lower() or "unknown" in result.output.lower()


def test_profile_move_unknown_project_fails(home_dir: Path) -> None:
    _setup_two_profiles_with_projects(home_dir)
    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "profile",
            "move",
            "--from",
            "personal",
            "--to",
            "work",
            "--projects",
            "-not-a-real-project",
            "--yes",
        ],
    )
    assert result.exit_code != 0


def test_profile_move_empty_source_short_circuits(home_dir: Path) -> None:
    config_path = home_dir / ".config" / "lazy-harness" / "config.toml"
    cfg = Config(
        harness=HarnessConfig(version="1"),
        profiles=ProfilesConfig(
            default="personal",
            items={
                "personal": ProfileEntry(config_dir=str(home_dir / ".claude-p"), roots=[]),
                "work": ProfileEntry(config_dir=str(home_dir / ".claude-w"), roots=[]),
            },
        ),
    )
    save_config(cfg, config_path)
    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["profile", "move", "--from", "personal", "--to", "work", "--all", "--yes"],
    )
    assert result.exit_code == 0
    assert "No projects to move" in result.output


def test_profile_envrc_idempotent(home_dir: Path) -> None:
    root = _setup_config_with_root(home_dir)
    runner = CliRunner()
    runner.invoke(cli, ["profile", "envrc"])
    first = (root / ".envrc").read_text()
    result = runner.invoke(cli, ["profile", "envrc"])
    assert result.exit_code == 0
    assert (root / ".envrc").read_text() == first
    assert "unchanged" in result.output

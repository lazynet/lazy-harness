"""`lh deploy --profile <name>` end to end, through the CLI.

The flag exists so a throwaway profile can be deployed and exercised without a
failing run taking a daily profile with it (decision 11, 2026-09-13 multi-agent
design). These tests read the files and the manifest back rather than the exit
code, because a narrowing that quietly deploys nothing also exits 0.
"""

from __future__ import annotations

import json
from pathlib import Path

from click.testing import CliRunner

from lazy_harness.core.config import (
    Config,
    HarnessConfig,
    ProfileEntry,
    ProfilesConfig,
    save_config,
)
from lazy_harness.core.paths import config_dir


def _write_config(home_dir: Path) -> None:
    """Two profiles on disk, `lazy` the default."""
    profiles_src = config_dir() / "profiles"
    for name in ("lazy", "flex"):
        src = profiles_src / name
        src.mkdir(parents=True, exist_ok=True)
        (src / "CLAUDE.md").write_text(f"# {name}\n")

    cfg = Config(
        harness=HarnessConfig(version="1"),
        profiles=ProfilesConfig(
            default="lazy",
            items={
                "lazy": ProfileEntry(config_dir=str(home_dir / ".claude-lazy")),
                "flex": ProfileEntry(config_dir=str(home_dir / ".claude-flex")),
            },
        ),
    )
    save_config(cfg, config_dir() / "config.toml")


def _snapshots(home_dir: Path) -> list[Path]:
    deploy_ns = home_dir / ".config" / "lazy-harness" / "backups" / "deploy"
    if not deploy_ns.is_dir():
        return []
    return sorted(p for p in deploy_ns.iterdir() if p.is_dir())


def _manifest_paths(snapshot_dir: Path) -> list[str]:
    manifest = json.loads((snapshot_dir / "rollback.json").read_text())
    return [entry["path"] for entry in manifest["entries"]]


def test_deploy_without_the_flag_still_writes_every_profile(home_dir: Path) -> None:
    """Regression: the default surface is untouched by the new flag."""
    from lazy_harness.cli.main import cli

    _write_config(home_dir)
    result = CliRunner().invoke(cli, ["deploy"])

    assert result.exit_code == 0, result.output
    assert (home_dir / ".claude-lazy" / "CLAUDE.md").is_symlink()
    assert (home_dir / ".claude-flex" / "CLAUDE.md").is_symlink()
    assert (home_dir / ".claude-lazy" / "settings.json").is_file()
    assert (home_dir / ".claude-flex" / "settings.json").is_file()
    assert not (home_dir / ".claude").exists()


def test_deploy_with_the_flag_writes_only_that_profile(home_dir: Path) -> None:
    from lazy_harness.cli.main import cli

    _write_config(home_dir)
    result = CliRunner().invoke(cli, ["deploy", "--profile", "flex"])

    assert result.exit_code == 0, result.output
    assert (home_dir / ".claude-flex" / "CLAUDE.md").is_symlink()
    assert (home_dir / ".claude-flex" / "settings.json").is_file()
    assert not (home_dir / ".claude-lazy").exists()


def test_deploy_with_the_flag_leaves_the_global_link_alone(home_dir: Path) -> None:
    """`~/.claude` points at the default profile; deploying `flex` must not
    create or repoint it."""
    from lazy_harness.cli.main import cli

    _write_config(home_dir)
    result = CliRunner().invoke(cli, ["deploy", "--profile", "flex"])

    assert result.exit_code == 0, result.output
    assert not (home_dir / ".claude").exists()


def test_deploy_of_the_default_profile_sets_no_global_link(
    home_dir: Path,
) -> None:
    from lazy_harness.cli.main import cli

    _write_config(home_dir)
    result = CliRunner().invoke(cli, ["deploy", "--profile", "lazy"])

    assert result.exit_code == 0, result.output
    assert not (home_dir / ".claude").exists()


def test_unknown_profile_fails_with_a_clear_error(home_dir: Path) -> None:
    from lazy_harness.cli.main import cli

    _write_config(home_dir)
    result = CliRunner().invoke(cli, ["deploy", "--profile", "tmp-gate"])

    assert result.exit_code != 0
    assert "tmp-gate" in result.output
    assert "lazy" in result.output and "flex" in result.output


def test_unknown_profile_deploys_nothing_and_takes_no_snapshot(home_dir: Path) -> None:
    """The name is validated before anything is written, so a typo costs nothing."""
    from lazy_harness.cli.main import cli

    _write_config(home_dir)
    CliRunner().invoke(cli, ["deploy", "--profile", "tmp-gate"])

    assert not (home_dir / ".claude-lazy").exists()
    assert not (home_dir / ".claude-flex").exists()
    assert _snapshots(home_dir) == []


def test_narrowed_deploy_still_takes_a_snapshot(home_dir: Path) -> None:
    from lazy_harness.cli.main import cli

    _write_config(home_dir)
    CliRunner().invoke(cli, ["deploy", "--profile", "flex"])

    taken = _snapshots(home_dir)
    assert len(taken) == 1
    assert (taken[0] / "rollback.json").is_file()


def test_narrowed_snapshot_manifest_lists_only_that_profile(home_dir: Path) -> None:
    """The manifest, not the exit code: a rollback replays these paths, and one
    naming the other profile would restore an artifact this deploy never wrote."""
    from lazy_harness.cli.main import cli

    _write_config(home_dir)
    CliRunner().invoke(cli, ["deploy", "--profile", "flex"])

    paths = _manifest_paths(_snapshots(home_dir)[0])
    assert paths
    assert all(p.startswith(str(home_dir / ".claude-flex")) for p in paths), (
        f"manifest reaches outside the selected profile: {sorted(paths)}"
    )


def test_narrowed_snapshot_covers_every_path_the_narrowed_deploy_writes(
    home_dir: Path,
) -> None:
    """The two readers of "which paths does this deploy own", narrowed."""
    from lazy_harness.cli.main import cli

    _write_config(home_dir)
    CliRunner().invoke(cli, ["deploy", "--profile", "flex"])

    covered = set(_manifest_paths(_snapshots(home_dir)[0]))
    written = {
        str(item)
        for item in (home_dir / ".claude-flex").iterdir()
        if item.is_symlink() or item.is_file()
    }
    assert written
    assert written <= covered, f"uncovered: {sorted(written - covered)}"


def test_profile_flag_combines_with_snapshot_only(home_dir: Path) -> None:
    from lazy_harness.cli.main import cli

    _write_config(home_dir)
    result = CliRunner().invoke(cli, ["deploy", "--profile", "flex", "--snapshot"])

    assert result.exit_code == 0, result.output
    assert len(_snapshots(home_dir)) == 1
    assert not (home_dir / ".claude-flex" / "CLAUDE.md").exists()


def test_profile_flag_is_refused_with_rollback(home_dir: Path) -> None:
    """A snapshot's manifest already carries its own scope; re-narrowing a replay
    would restore a subset of what was captured and call it a rollback."""
    from lazy_harness.cli.main import cli

    _write_config(home_dir)
    result = CliRunner().invoke(cli, ["deploy", "--profile", "flex", "--rollback"])

    assert result.exit_code != 0
    assert "mutually exclusive" in result.output
    assert "--profile" in result.output

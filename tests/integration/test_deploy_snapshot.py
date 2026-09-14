"""The snapshot surface, checked against the deploy that produces it.

`snapshot_targets` and `deploy/engine.py` answer one question — which paths does
a deploy own — from two places. An integration test invokes both and asserts
they agree, because a target list that drifts from the engine is a rollback that
silently misses an artifact.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from lazy_harness.cli.deploy_cmd import _run_deploy
from lazy_harness.core.config import (
    Config,
    HarnessConfig,
    ProfileEntry,
    ProfilesConfig,
)
from lazy_harness.core.paths import config_dir
from lazy_harness.deploy.snapshot import snapshot_targets


def _artifacts(root: Path) -> set[Path]:
    """Every file and symlink under `root`, without following symlinked dirs."""
    found: set[Path] = set()
    stack = [root]
    while stack:
        current = stack.pop()
        for item in current.iterdir():
            if item.is_symlink() or item.is_file():
                found.add(item)
            elif item.is_dir():
                stack.append(item)
    return found


@pytest.fixture
def two_profiles(home_dir: Path) -> Config:
    profiles_src = config_dir() / "profiles"
    for name in ("lazy", "flex"):
        src = profiles_src / name
        src.mkdir(parents=True)
        (src / "CLAUDE.md").write_text(f"# {name}\n")
        (src / "skills").mkdir()
    return Config(
        harness=HarnessConfig(version="1"),
        profiles=ProfilesConfig(
            default="lazy",
            items={
                "lazy": ProfileEntry(config_dir=str(home_dir / ".claude-lazy")),
                "flex": ProfileEntry(config_dir=str(home_dir / ".claude-flex")),
            },
        ),
        hooks={},
    )


def test_every_path_the_deploy_writes_is_a_snapshot_target(
    home_dir: Path, two_profiles: Config
) -> None:
    before = _artifacts(home_dir)
    targets = set(snapshot_targets(two_profiles))

    _run_deploy(two_profiles)

    written = _artifacts(home_dir) - before
    assert written, "the deploy wrote nothing; the assertion below would be vacuous"
    assert written <= targets, (
        "the deploy writes artifacts the snapshot would not capture: "
        f"{sorted(str(p) for p in written - targets)}"
    )


def test_two_profiles_settings_are_distinct_targets(two_profiles: Config) -> None:
    """The basename collision, at the surface that produces it."""
    targets = snapshot_targets(two_profiles)
    settings = [p for p in targets if p.name == "settings.json"]

    assert len(settings) == 2
    assert len(set(settings)) == 2


def _write_config(home_dir: Path) -> None:
    """Two profiles on disk, so every basename in the surface collides."""
    from lazy_harness.core.config import save_config

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


def test_deploy_takes_a_snapshot_without_being_asked(home_dir: Path) -> None:
    """Unconditional on every deploy. A trigger that can be wrong fails in the
    direction of no snapshot when one was needed."""
    from click.testing import CliRunner

    from lazy_harness.cli.main import cli

    _write_config(home_dir)
    assert CliRunner().invoke(cli, ["deploy"]).exit_code == 0

    taken = _snapshots(home_dir)
    assert len(taken) == 1
    assert (taken[0] / "rollback.json").is_file()


def test_snapshot_flag_takes_a_snapshot_and_does_not_deploy(home_dir: Path) -> None:
    from click.testing import CliRunner

    from lazy_harness.cli.main import cli

    _write_config(home_dir)
    result = CliRunner().invoke(cli, ["deploy", "--snapshot"])

    assert result.exit_code == 0
    assert len(_snapshots(home_dir)) == 1
    assert not (home_dir / ".claude-lazy" / "CLAUDE.md").exists()
    assert not (home_dir / ".claude-lazy" / "settings.json").exists()


def test_rollback_restores_each_profile_its_own_settings(home_dir: Path) -> None:
    """The collision end to end, verified by reading the files back."""
    from click.testing import CliRunner

    from lazy_harness.cli.main import cli

    _write_config(home_dir)
    runner = CliRunner()
    assert runner.invoke(cli, ["deploy"]).exit_code == 0

    lazy_settings = home_dir / ".claude-lazy" / "settings.json"
    flex_settings = home_dir / ".claude-flex" / "settings.json"
    lazy_settings.write_bytes(b'{"who": "lazy"}')
    flex_settings.write_bytes(b'{"who": "flex"}')

    assert runner.invoke(cli, ["deploy"]).exit_code == 0
    assert lazy_settings.read_bytes() != b'{"who": "lazy"}'

    assert runner.invoke(cli, ["deploy", "--rollback"]).exit_code == 0

    assert lazy_settings.read_bytes() == b'{"who": "lazy"}'
    assert flex_settings.read_bytes() == b'{"who": "flex"}'


def test_rollback_repoints_a_profile_symlink(home_dir: Path) -> None:
    """Every profile artifact is an existing symlink under ADR-009, so this is
    the shape a deploy rollback is actually made of."""
    from click.testing import CliRunner

    from lazy_harness.cli.main import cli

    _write_config(home_dir)
    runner = CliRunner()
    assert runner.invoke(cli, ["deploy"]).exit_code == 0

    link = home_dir / ".claude-lazy" / "CLAUDE.md"
    original = link.readlink()

    assert runner.invoke(cli, ["deploy", "--snapshot"]).exit_code == 0

    elsewhere = home_dir / "elsewhere.md"
    elsewhere.write_text("# not the profile\n")
    link.unlink()
    link.symlink_to(elsewhere)

    assert runner.invoke(cli, ["deploy", "--rollback"]).exit_code == 0

    assert link.readlink() == original


def test_snapshots_are_pruned_to_the_last_ten(home_dir: Path) -> None:
    from click.testing import CliRunner

    from lazy_harness.cli.main import cli

    _write_config(home_dir)
    runner = CliRunner()
    for _ in range(12):
        assert runner.invoke(cli, ["deploy", "--snapshot"]).exit_code == 0

    assert len(_snapshots(home_dir)) == 10


def test_snapshot_help_says_it_exits_without_deploying(home_dir: Path) -> None:
    """Read off the rendered help, not the docstring.

    Help that reads as 'enable the snapshot' would teach the opposite of the
    decision: without the flag there is still a snapshot.
    """
    from click.testing import CliRunner

    from lazy_harness.cli.main import cli

    output = CliRunner().invoke(cli, ["deploy", "--help"]).output

    assert "without deploying" in output


def test_two_deploys_in_the_same_second_keep_separate_snapshots(home_dir: Path) -> None:
    """A second-resolution timestamp collapses them onto one directory, and the
    second snapshot then overwrites the first one's manifest with post-deploy
    state — losing the only record of what the machine looked like before."""
    from click.testing import CliRunner

    from lazy_harness.cli.main import cli

    _write_config(home_dir)
    runner = CliRunner()
    assert runner.invoke(cli, ["deploy", "--snapshot"]).exit_code == 0
    assert runner.invoke(cli, ["deploy", "--snapshot"]).exit_code == 0

    assert len(_snapshots(home_dir)) == 2

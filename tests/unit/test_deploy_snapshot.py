"""Snapshot manifest — the rollback contract `lh deploy` replays.

Every test here drives the real writer (`take_snapshot`) and the real replayer
(`apply_rollback_log`). A manifest parsed only by the test that wrote it would
prove nothing about the system that consumes it.
"""

from __future__ import annotations

from pathlib import Path

from lazy_harness.deploy.snapshot import take_snapshot
from lazy_harness.migrate.rollback import apply_rollback_log


def test_rollback_repoints_a_symlink_that_still_exists(tmp_path: Path) -> None:
    """The defect `restore_symlink` has: it acts only `if not link.exists()`.

    Under ADR-009 every profile artifact is an existing symlink, so a rollback
    of a relink is exactly this case — and the migrate op would report success
    without touching the disk.
    """
    old_target = tmp_path / "profiles" / "lazy" / "skills"
    new_target = tmp_path / "profiles" / "beta" / "skills"
    old_target.mkdir(parents=True)
    new_target.mkdir(parents=True)

    link = tmp_path / "home" / ".claude-lazy" / "skills"
    link.parent.mkdir(parents=True)
    link.symlink_to(old_target)

    snapshot_dir = tmp_path / "snap"
    take_snapshot([link], snapshot_dir)

    # The deploy under test: relink the artifact somewhere else.
    link.unlink()
    link.symlink_to(new_target)
    assert link.readlink() == new_target

    apply_rollback_log(snapshot_dir)

    assert link.is_symlink()
    assert link.readlink() == old_target


def test_rollback_restores_two_artifacts_that_share_a_basename(tmp_path: Path) -> None:
    """The defect the manifest exists for.

    `apply_rollback_log`'s migration branch keys the backup copy on
    `Path(payload["path"]).name`, so two profiles' `settings.json` resolve to
    one file and the second restore overwrites the first profile's artifact.
    """
    lazy = tmp_path / "home" / ".claude-lazy" / "settings.json"
    flex = tmp_path / "home" / ".claude-flex" / "settings.json"
    for path, body in ((lazy, b'{"profile": "lazy"}'), (flex, b'{"profile": "flex"}')):
        path.parent.mkdir(parents=True)
        path.write_bytes(body)

    snapshot_dir = tmp_path / "snap"
    take_snapshot([lazy, flex], snapshot_dir)

    lazy.write_bytes(b'{"profile": "lazy", "deployed": true}')
    flex.write_bytes(b'{"profile": "flex", "deployed": true}')

    apply_rollback_log(snapshot_dir)

    assert lazy.read_bytes() == b'{"profile": "lazy"}'
    assert flex.read_bytes() == b'{"profile": "flex"}'


def test_rollback_deletes_an_artifact_that_did_not_exist_before(tmp_path: Path) -> None:
    """A first deploy on a clean machine is only reversible with this kind.

    Without it, rollback restores what was there and leaves everything the
    deploy created — which is not the state the machine was in.
    """
    created = tmp_path / "home" / ".claude-lazy" / ".mcp.json"
    created.parent.mkdir(parents=True)
    assert not created.exists()

    snapshot_dir = tmp_path / "snap"
    take_snapshot([created], snapshot_dir)

    created.write_bytes(b'{"mcpServers": {}}')

    apply_rollback_log(snapshot_dir)

    assert not created.exists()


def test_rollback_restores_a_directory_the_deploy_replaced_with_a_symlink(
    tmp_path: Path,
) -> None:
    """`~/.claude` is a real directory on a vanilla Claude Code machine.

    `deploy_claude_symlink` replaces it with a link to the default profile, so
    the pre-deploy state of a managed path can be a directory with contents.
    """
    real_dir = tmp_path / "home" / ".claude"
    real_dir.mkdir(parents=True)
    (real_dir / "history.jsonl").write_bytes(b"line one\n")

    snapshot_dir = tmp_path / "snap"
    take_snapshot([real_dir], snapshot_dir)

    profile_dir = tmp_path / "home" / ".claude-lazy"
    profile_dir.mkdir()
    import shutil

    shutil.rmtree(real_dir)
    real_dir.symlink_to(profile_dir)

    apply_rollback_log(snapshot_dir)

    assert real_dir.is_dir()
    assert not real_dir.is_symlink()
    assert (real_dir / "history.jsonl").read_bytes() == b"line one\n"

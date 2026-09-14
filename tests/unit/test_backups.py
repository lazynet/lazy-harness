"""Backup namespaces — one root, two commands that must not see each other.

`lh migrate` and `lh deploy` both keep timestamped directories with a
`rollback.json` inside. Sharing a newest-wins parent would make each replay the
other's log and prune the other's history.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from lazy_harness.core.backups import (
    DEPLOY_NAMESPACE,
    MIGRATE_NAMESPACE,
    latest_backup_dir,
    namespace_dir,
)


@pytest.fixture
def root(tmp_path: Path) -> Path:
    return tmp_path / "backups"


def test_migrate_ignores_the_deploy_namespace_directory(root: Path) -> None:
    """The sort bug the namespace split introduces if nothing skips it.

    `sorted([...], reverse=True)` puts `deploy` and `migrate` above every
    timestamp, because 'd' and 'm' order after '2'. A scan that only filtered on
    `is_dir()` would hand `lh migrate --rollback` the deploy namespace itself.
    """
    (root / "2026-08-12T10-04-33").mkdir(parents=True)
    (namespace_dir(root, DEPLOY_NAMESPACE) / "2026-09-14T18-00-00").mkdir(parents=True)

    latest = latest_backup_dir(root, MIGRATE_NAMESPACE, include_legacy=True)

    assert latest == root / "2026-08-12T10-04-33"


def test_migrate_still_reads_legacy_top_level_backups(root: Path) -> None:
    """Directories written before the split are migration backups."""
    (root / "2026-08-12T10-04-33").mkdir(parents=True)
    (root / "2026-08-30T09-11-02").mkdir(parents=True)

    latest = latest_backup_dir(root, MIGRATE_NAMESPACE, include_legacy=True)

    assert latest == root / "2026-08-30T09-11-02"


def test_a_new_namespaced_migrate_backup_wins_over_an_older_legacy_one(root: Path) -> None:
    (root / "2026-08-12T10-04-33").mkdir(parents=True)
    newer = namespace_dir(root, MIGRATE_NAMESPACE) / "2026-09-14T18-00-00"
    newer.mkdir(parents=True)

    assert latest_backup_dir(root, MIGRATE_NAMESPACE, include_legacy=True) == newer


def test_deploy_never_sees_a_migration_backup(root: Path) -> None:
    (root / "2026-08-12T10-04-33").mkdir(parents=True)
    (namespace_dir(root, MIGRATE_NAMESPACE) / "2026-09-14T18-00-00").mkdir(parents=True)

    assert latest_backup_dir(root, DEPLOY_NAMESPACE) is None

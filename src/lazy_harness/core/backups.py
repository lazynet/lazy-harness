"""Backup namespaces under `~/.config/lazy-harness/backups/`.

`lh migrate` and `lh deploy` each keep timestamped directories holding a
`rollback.json`. They must not share a newest-wins parent: a deploy snapshot
beside a migration backup makes `lh migrate --rollback` replay the deploy's log,
and makes a deploy prune delete a migration's history. One function decides
where each command reads and writes, so the two cannot drift apart.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from lazy_harness.core.paths import config_dir

MIGRATE_NAMESPACE = "migrate"
DEPLOY_NAMESPACE = "deploy"
NAMESPACES = (DEPLOY_NAMESPACE, MIGRATE_NAMESPACE)


def backups_root() -> Path:
    return config_dir() / "backups"


def namespace_dir(root: Path, namespace: str) -> Path:
    return root / namespace


def _timestamped(parent: Path) -> list[Path]:
    """Timestamped backup directories directly under `parent`.

    The namespace directories are excluded by name. Reverse-sorted they order
    above every timestamp — 'd' and 'm' come after '2' — so a scan filtering
    only on `is_dir()` would return the namespace directory itself rather than
    a backup inside it.
    """
    if not parent.is_dir():
        return []
    return [p for p in parent.iterdir() if p.is_dir() and p.name not in NAMESPACES]


def latest_backup_dir(root: Path, namespace: str, *, include_legacy: bool = False) -> Path | None:
    """The newest backup this namespace may replay.

    `include_legacy` adds the timestamped directories sitting directly in the
    root. Those predate the split and are migration backups, so they stay
    readable for as long as they exist — and only `lh migrate` asks for them.
    """
    candidates = _timestamped(namespace_dir(root, namespace))
    if include_legacy:
        candidates += _timestamped(root)
    if not candidates:
        return None
    return sorted(candidates, key=lambda p: p.name, reverse=True)[0]


def prune_backups(root: Path, namespace: str, *, keep: int) -> list[Path]:
    """Delete all but the newest `keep` backups in a namespace."""
    ordered = sorted(
        _timestamped(namespace_dir(root, namespace)), key=lambda p: p.name, reverse=True
    )
    removed = ordered[keep:]
    for path in removed:
        shutil.rmtree(path)
    return removed

from __future__ import annotations

import json
import shutil
from pathlib import Path

from lazy_harness.deploy.snapshot import MANIFEST_FORMAT
from lazy_harness.migrate.state import StepResult
from lazy_harness.migrate.steps.backup import BackupEntry, BackupManifestError, read_backup_manifest


def write_rollback_log(backup_dir: Path, results: list[StepResult]) -> Path:
    """Serialize all rollback ops (in reverse execution order) to rollback.json."""
    ops: list[dict] = []
    for r in reversed(results):
        for op in reversed(r.rollback_ops):
            ops.append({"step": r.name, "kind": op.kind, "payload": op.payload})
    path = backup_dir / "rollback.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(ops, indent=2))
    return path


def apply_rollback_log(backup_dir: Path) -> list[str]:
    """Apply rollback ops recorded in rollback.json. Returns list of messages."""
    path = backup_dir / "rollback.json"
    if not path.is_file():
        return ["no rollback log found"]
    log = json.loads(path.read_text())
    if isinstance(log, dict) and log.get("format") == MANIFEST_FORMAT:
        return _apply_manifest(backup_dir, log)
    if not isinstance(log, list):
        return [f"malformed rollback log at {path}: expected a list of ops"]
    ops = log
    ambiguous_basenames = _ambiguous_legacy_basenames(ops)
    messages: list[str] = []
    for op in ops:
        kind = op["kind"]
        payload = op.get("payload", {})
        try:
            if kind == "remove_file":
                p = Path(payload["path"])
                if p.exists():
                    p.unlink()
                    messages.append(f"removed {p}")
            elif kind == "restore_file":
                dest = Path(payload["path"])
                messages.append(_restore_backed_up(backup_dir, dest, ambiguous_basenames))
            elif kind == "restore_symlink":
                link = Path(payload["path"])
                target = payload.get("target", "")
                if not link.exists() and target:
                    link.symlink_to(target)
                    messages.append(f"restored symlink {link} -> {target}")
            elif kind == "unflatten":
                p = Path(payload["path"])
                target = payload.get("target", "")
                if not target:
                    messages.append(f"unflatten skipped: no target for {p}")
                    continue
                if p.exists() and not p.is_symlink():
                    if p.is_dir():
                        shutil.rmtree(p)
                    else:
                        p.unlink()
                if not p.exists():
                    p.symlink_to(target)
                    messages.append(f"unflattened {p} -> {target}")
            else:
                messages.append(f"unknown op kind: {kind}")
        except Exception as e:  # noqa: BLE001
            messages.append(f"rollback op {kind} failed: {e}")
    return messages


def _ambiguous_legacy_basenames(ops: list[dict]) -> set[str]:
    """Basenames requested by more than one distinct `restore_file` destination.

    Only meaningful for a legacy (manifest-less) backup, whose content sits at
    `backup_dir / basename`: two different sources sharing a basename cannot
    be told apart after the fact, so neither may be restored from it.
    """
    by_name: dict[str, set[str]] = {}
    for op in ops:
        if op.get("kind") != "restore_file":
            continue
        raw_path = op.get("payload", {}).get("path")
        if not raw_path:
            continue
        by_name.setdefault(Path(raw_path).name, set()).add(raw_path)
    return {name for name, paths in by_name.items() if len(paths) > 1}


def _restore_backed_up(backup_dir: Path, dest: Path, ambiguous_basenames: set[str]) -> str:
    """Restore `dest` from the backup taken before the migration wrote it.

    A manifest, once present, is the sole source of truth: its entries are
    keyed by full source path, so a lookup miss or an invalid manifest must
    refuse rather than fall back to basename guessing, which is exactly the
    collision this manifest exists to prevent. Only the true absence of a
    manifest — a legacy backup written before this fix — takes the basename
    path, and even then only when no other destination in this same rollback
    run claims the same basename.
    """
    try:
        manifest = read_backup_manifest(backup_dir)
    except BackupManifestError as e:
        return f"restore of {dest} skipped: {e}"

    if manifest is not None:
        if not manifest.get("complete", False):
            return f"restore of {dest} skipped: backup at {backup_dir} is incomplete"
        entry = next((e for e in manifest["entries"] if e["path"] == str(dest)), None)
        if entry is None:
            return f"restore of {dest} skipped: no backup entry for this exact path"
        return _restore_from_entry(backup_dir, dest, entry)

    if dest.name in ambiguous_basenames:
        return (
            f"restore of {dest} skipped: ambiguous legacy backup, "
            f"multiple sources share basename {dest.name!r}"
        )
    legacy_src = backup_dir / dest.name
    if legacy_src.exists():
        return _restore_file(dest, legacy_src)
    return f"restore of {dest} skipped: no backup found for {dest}"


def _restore_from_entry(backup_dir: Path, dest: Path, entry: BackupEntry) -> str:
    kind = entry["kind"]
    if kind == "file":
        content = entry["content"]
        assert content is not None
        src = backup_dir / content
        if not src.is_file():
            return f"restore of {dest} skipped: backup content missing at {src}"
        return _restore_file(dest, src)
    if kind == "directory":
        content = entry["content"]
        assert content is not None
        src = backup_dir / content
        if not src.is_dir():
            return f"restore of {dest} skipped: backup content missing at {src}"
        return _restore_directory(dest, src)
    if kind == "symlink":
        target = entry["target"]
        assert target is not None
        return _restore_symlink(dest, target)
    if kind == "absent":
        return f"restore of {dest} skipped: source did not exist when backed up"
    return f"restore of {dest} skipped: unknown backup entry kind {kind!r}"


def _restore_symlink(link: Path, target: str) -> str:
    """Point `link` at `target`, whatever `link` is right now.

    Unconditional, unlike the `restore_symlink` op above. That one acts only
    `if not link.exists()`, which is correct for its sole producer — the script
    removal step unlinks before recording it — and wrong for a relink, where the
    link is still there. Under ADR-009 every profile artifact is an existing
    symlink, so the relink is the case a deploy rollback is made of.
    """
    _clear(link)
    link.parent.mkdir(parents=True, exist_ok=True)
    link.symlink_to(target)
    return f"relinked {link} -> {target}"


def _restore_file(dest: Path, src: Path) -> str:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.is_symlink() or dest.is_dir():
        _clear(dest)
    shutil.copy2(src, dest)
    return f"restored {dest}"


def _restore_directory(dest: Path, src: Path) -> str:
    _clear(dest)
    shutil.copytree(src, dest, symlinks=True)
    return f"restored directory {dest}"


def _remove(dest: Path) -> str:
    if not (dest.is_symlink() or dest.exists()):
        return f"already absent {dest}"
    _clear(dest)
    return f"removed {dest}"


def _clear(path: Path) -> None:
    """Remove whatever occupies `path`, symlink or directory or file."""
    if path.is_symlink() or path.is_file():
        path.unlink()
    elif path.is_dir():
        shutil.rmtree(path)


def _apply_manifest(backup_dir: Path, log: dict) -> list[str]:
    """Replay a deploy snapshot manifest.

    Separate from the migration branch above on purpose: that branch works for
    a command nobody is changing, and its basename-keyed restore is the reason
    this format exists.
    """
    messages: list[str] = []
    for entry in log.get("entries", []):
        dest = Path(entry["path"])
        kind = entry.get("kind")
        try:
            if kind == "symlink":
                messages.append(_restore_symlink(dest, entry["target"]))
            elif kind == "file":
                messages.append(_restore_file(dest, backup_dir / entry["content"]))
            elif kind == "directory":
                messages.append(_restore_directory(dest, backup_dir / entry["content"]))
            elif kind == "absent":
                messages.append(_remove(dest))
            else:
                messages.append(f"unknown manifest kind: {kind}")
        except Exception as e:  # noqa: BLE001
            messages.append(f"restore of {dest} failed: {e}")
    return messages

from __future__ import annotations

import json
import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import TypedDict

from lazy_harness.core.config import atomic_write_text
from lazy_harness.migrate.state import StepResult, StepStatus

BACKUP_MANIFEST_NAME = "backup-manifest.json"
BACKUP_MANIFEST_FORMAT = "backup-manifest"
BACKUP_MANIFEST_VERSION = 1
BACKUP_CONTENT_DIR = "content"
_VALID_KINDS = ("file", "directory", "symlink", "absent")


class BackupEntry(TypedDict):
    path: str
    kind: str
    content: str | None
    target: str | None


class BackupManifest(TypedDict):
    format: str
    version: int
    complete: bool
    entries: list[BackupEntry]


class BackupManifestError(Exception):
    """A backup manifest is present but cannot be trusted for restoration."""


def _content_relative(index: int, path: Path) -> str:
    """A content path unique per source rather than per basename.

    Mirrors `deploy/snapshot.py`'s `_content_name`: the index is the entry's
    position in the manifest, so `one/settings.json` and `two/settings.json`
    land in separate `NNNN-settings.json` files instead of one overwriting
    the other under `backup_dir / t.name`.
    """
    return f"{BACKUP_CONTENT_DIR}/{index:04d}-{path.name}"


def _backup_entry(index: int, path: Path, backup_dir: Path) -> BackupEntry:
    """Record one target's current state, keyed by its full source path.

    Symlinks are checked first — including a symlink to a directory, which
    `path.is_dir()` would otherwise follow, silently resolving it into a
    plain directory copy that loses its link identity on restore.
    """
    if path.is_symlink():
        return {"path": str(path), "kind": "symlink", "content": None, "target": os.readlink(path)}
    if path.is_file():
        content = _content_relative(index, path)
        dest = backup_dir / content
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, dest)
        return {"path": str(path), "kind": "file", "content": content, "target": None}
    if path.is_dir():
        content = _content_relative(index, path)
        shutil.copytree(path, backup_dir / content, symlinks=True)
        return {"path": str(path), "kind": "directory", "content": content, "target": None}
    return {"path": str(path), "kind": "absent", "content": None, "target": None}


def write_backup_manifest(backup_dir: Path, entries: list[BackupEntry], *, complete: bool) -> Path:
    manifest: BackupManifest = {
        "format": BACKUP_MANIFEST_FORMAT,
        "version": BACKUP_MANIFEST_VERSION,
        "complete": complete,
        "entries": entries,
    }
    path = backup_dir / BACKUP_MANIFEST_NAME
    atomic_write_text(path, json.dumps(manifest, indent=2) + "\n")
    return path


def _require_contained(backup_dir: Path, content: str) -> None:
    """Reject a content path outside `backup_dir`, and `backup_dir` itself.

    The latter matters as much as the former: `content=""` or `"."` resolves
    to `backup_dir`, and a directory-kind restore copying that tree would
    copy the whole backup — manifest, other entries' content, everything —
    into a single destination.
    """
    root = backup_dir.resolve()
    resolved = (backup_dir / content).resolve()
    if root not in resolved.parents:
        raise BackupManifestError(f"manifest entry content escapes backup dir: {content!r}")


def _validate_entry(raw: object, backup_dir: Path) -> BackupEntry:
    if not isinstance(raw, dict):
        raise BackupManifestError("manifest entry is not an object")
    path = raw.get("path")
    if not isinstance(path, str) or not path:
        raise BackupManifestError("manifest entry missing a non-empty 'path'")
    kind = raw.get("kind")
    if kind not in _VALID_KINDS:
        raise BackupManifestError(f"manifest entry has unknown kind: {kind!r}")
    content = raw.get("content")
    target = raw.get("target")
    if kind in ("file", "directory"):
        if not isinstance(content, str) or not content:
            raise BackupManifestError(
                f"manifest entry of kind {kind!r} requires non-empty 'content'"
            )
        if target is not None:
            raise BackupManifestError(f"manifest entry of kind {kind!r} must not carry a 'target'")
        _require_contained(backup_dir, content)
    elif kind == "symlink":
        if not isinstance(target, str) or not target:
            raise BackupManifestError(
                "manifest entry of kind 'symlink' requires non-empty 'target'"
            )
        if content is not None:
            raise BackupManifestError("manifest entry of kind 'symlink' must not carry 'content'")
    else:  # kind == "absent"
        if content is not None or target is not None:
            raise BackupManifestError(
                "manifest entry of kind 'absent' must not carry content or target"
            )
    return {"path": path, "kind": kind, "content": content, "target": target}


def _validate_manifest(data: object, backup_dir: Path) -> BackupManifest:
    if not isinstance(data, dict):
        raise BackupManifestError("manifest is not a JSON object")
    if data.get("format") != BACKUP_MANIFEST_FORMAT:
        raise BackupManifestError(f"unexpected manifest format: {data.get('format')!r}")
    version = data.get("version")
    # `True == 1`: an explicit bool check first, since the equality below
    # alone would let a boolean version through as version 1.
    if isinstance(version, bool) or version != BACKUP_MANIFEST_VERSION:
        raise BackupManifestError(f"unsupported manifest version: {version!r}")
    complete = data.get("complete")
    if not isinstance(complete, bool):
        raise BackupManifestError("manifest 'complete' field is missing or not a boolean")
    raw_entries = data.get("entries")
    if not isinstance(raw_entries, list):
        raise BackupManifestError("manifest 'entries' is not a list")
    entries = [_validate_entry(e, backup_dir) for e in raw_entries]
    seen_paths: set[str] = set()
    for entry in entries:
        if entry["path"] in seen_paths:
            raise BackupManifestError(f"duplicate backup entry for path: {entry['path']!r}")
        seen_paths.add(entry["path"])
    return {
        "format": BACKUP_MANIFEST_FORMAT,
        "version": BACKUP_MANIFEST_VERSION,
        "complete": complete,
        "entries": entries,
    }


def read_backup_manifest(backup_dir: Path) -> BackupManifest | None:
    """The manifest for a backup written by the current `BackupStep`.

    `None` means no manifest file exists at all — a legacy backup written
    before this fix, or no backup at all. Anything else at that path (a
    directory, a dangling symlink) is not legacy absence and must not be
    mistaken for it. A manifest file that exists but fails validation raises
    `BackupManifestError`: it must never fall back to basename guessing.
    """
    path = backup_dir / BACKUP_MANIFEST_NAME
    if not path.exists() and not path.is_symlink():
        return None
    if not path.is_file():
        raise BackupManifestError(f"manifest path {path} exists but is not a regular file")
    try:
        data = json.loads(path.read_text())
    except json.JSONDecodeError as e:
        raise BackupManifestError(f"manifest is not valid JSON: {e}") from e
    return _validate_manifest(data, backup_dir)


def find_backup_entry(backup_dir: Path, source: Path) -> BackupEntry | None:
    """The manifest entry for exactly `source`, never a basename guess."""
    manifest = read_backup_manifest(backup_dir)
    if manifest is None:
        return None
    target = str(source)
    for entry in manifest["entries"]:
        if entry["path"] == target:
            return entry
    return None


@dataclass
class BackupStep:
    targets: list[Path] = field(default_factory=list)
    name: str = "backup"

    def describe(self) -> str:
        return f"Backup {len(self.targets)} paths"

    def plan(self) -> str:
        lines = [f"Backup {len(self.targets)} paths to backup directory:"]
        for t in self.targets:
            lines.append(f"  - {t}")
        return "\n".join(lines)

    def execute(self, backup_dir: Path, dry_run: bool = False) -> StepResult:
        result = StepResult(name=self.name, status=StepStatus.RUNNING)
        if dry_run:
            result.status = StepStatus.DONE
            result.message = f"[dry-run] would back up {len(self.targets)} paths"
            return result
        entries: list[BackupEntry] = []
        try:
            backup_dir.mkdir(parents=True, exist_ok=True)
            # Written before any copy runs, and durably — an interruption
            # this process cannot catch (kill, power loss) must not leave a
            # stale complete=True manifest from an earlier run in the same
            # directory.
            write_backup_manifest(backup_dir, [], complete=False)
            for i, t in enumerate(self.targets):
                entries.append(_backup_entry(i, t, backup_dir))
            write_backup_manifest(backup_dir, entries, complete=True)
            result.status = StepStatus.DONE
            result.message = f"backed up {len(self.targets)} paths"
        except Exception as e:  # noqa: BLE001
            try:
                write_backup_manifest(backup_dir, entries, complete=False)
            except Exception:  # noqa: BLE001
                pass  # best-effort marker; must not mask the original failure
            result.status = StepStatus.FAILED
            result.message = f"backup failed: {e}"
        return result

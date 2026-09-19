from __future__ import annotations

import json
import shutil
from pathlib import Path

from lazy_harness.deploy.snapshot import MANIFEST_FORMAT
from lazy_harness.migrate.state import StepResult


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
    ops = log
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
                name = Path(payload["path"]).name
                src = backup_dir / name
                if src.exists():
                    Path(payload["path"]).write_bytes(src.read_bytes())
                    messages.append(f"restored {payload['path']}")
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
    if dest.is_symlink():
        dest.unlink()
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

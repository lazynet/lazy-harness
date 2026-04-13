from __future__ import annotations

import json
import shutil
from pathlib import Path

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
    ops = json.loads(path.read_text())
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

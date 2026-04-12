"""Knowledge directory management — ensure structure, list content, resolve paths."""

from __future__ import annotations

from pathlib import Path

from lazy_harness.core.paths import expand_path


def ensure_knowledge_dir(path: str, subdirs: list[str] | None = None) -> Path:
    kdir = expand_path(path)
    kdir.mkdir(parents=True, exist_ok=True)
    for subdir in subdirs or ["sessions", "learnings"]:
        (kdir / subdir).mkdir(exist_ok=True)
    return kdir


def session_export_path(knowledge_dir: Path, subdir: str, date_str: str, session_id: str) -> Path:
    year_month = date_str[:7]
    export_dir = knowledge_dir / subdir / year_month
    export_dir.mkdir(parents=True, exist_ok=True)
    return export_dir / f"{date_str}-{session_id[:8]}.md"


def list_sessions(knowledge_dir: Path, subdir: str = "sessions") -> list[Path]:
    sessions_dir = knowledge_dir / subdir
    if not sessions_dir.is_dir():
        return []
    return sorted(sessions_dir.rglob("*.md"), reverse=True)

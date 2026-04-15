"""Session JSONL → markdown export."""

from __future__ import annotations

import json
import os
import re
from datetime import datetime
from pathlib import Path


def _parse_session_jsonl(
    filepath: Path,
) -> tuple[dict[str, str], list[dict[str, str]], bool]:
    meta: dict[str, str] = {}
    messages: list[dict[str, str]] = []
    first_timestamp = ""
    is_interactive = False
    for line in filepath.read_text().splitlines():
        if not line.strip():
            continue
        try:
            d = json.loads(line)
        except json.JSONDecodeError:
            continue
        msg_type = d.get("type", "")
        ts = d.get("timestamp", "")
        if not first_timestamp and ts:
            first_timestamp = ts
        if msg_type in ("permission-mode", "last-prompt"):
            is_interactive = True
            continue
        if msg_type == "system" and not meta:
            meta = {
                "cwd": d.get("cwd", ""),
                "version": d.get("version", ""),
                "branch": d.get("gitBranch", ""),
                "timestamp": ts,
            }
            continue
        if msg_type in ("user", "assistant"):
            msg = d.get("message", {})
            content = msg.get("content", "")
            texts: list[str] = []
            if isinstance(content, str) and content.strip():
                texts.append(content.strip())
            elif isinstance(content, list):
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "text":
                        text = block.get("text", "").strip()
                        if text:
                            texts.append(text)
            if texts:
                role = "User" if msg_type == "user" else "Claude"
                messages.append({"role": role, "text": "\n\n".join(texts), "timestamp": ts})
    if not meta.get("timestamp"):
        meta["timestamp"] = first_timestamp
    return meta, messages, is_interactive


def _extract_project(cwd: str) -> str:
    if not cwd:
        return ""
    check = cwd
    while check and check != "/":
        if os.path.isdir(os.path.join(check, ".git")):
            return os.path.basename(check)
        check = os.path.dirname(check)
    return os.path.basename(cwd) or ""


def _classify(cwd: str) -> tuple[str, str]:
    """Return (profile, session_type) based on cwd heuristics.

    Matches the bash implementation: LazyMind/obsidian paths classify as
    vault; `/repos/lazy/` as personal; `/repos/flex/` as work; else other.
    Profile is the same minus the vault special case.
    """
    if not cwd:
        return ("other", "other")
    lower = cwd.lower()
    if "lazymind" in lower or "obsidian" in lower:
        return ("personal", "vault")
    if "/repos/lazy/" in cwd:
        return ("personal", "personal")
    if "/repos/flex/" in cwd:
        return ("work", "work")
    return ("other", "other")


def _decode_project_dir(dir_name: str) -> str:
    """Decode Claude Code's project dir name back to a real path.

    Claude replaces '/' with '-', which is ambiguous for repos containing
    hyphens (e.g. `lazy-claudecode`). We try candidate splits against the
    filesystem and pick the one that exists. Falls back to naive replacement.
    """
    if not dir_name.startswith("-"):
        return dir_name.replace("-", "/")
    raw = dir_name[1:]
    parts = raw.split("-")

    def try_build(index: int, current_path: str) -> str | None:
        if index == len(parts):
            return current_path if os.path.exists(current_path) else None
        combined = parts[index]
        for j in range(index, len(parts)):
            if j > index:
                combined += "-" + parts[j]
            candidate = os.path.join(current_path, combined)
            r = try_build(j + 1, candidate)
            if r:
                return r
        return None

    result = try_build(0, "/")
    return result if result else "/" + raw.replace("-", "/")


def _existing_message_count(path: Path) -> int:
    if not path.exists():
        return 0
    try:
        text = path.read_text()
    except OSError:
        return 0
    in_fm = False
    for line in text.splitlines():
        stripped = line.strip()
        if stripped == "---":
            if not in_fm:
                in_fm = True
                continue
            break
        if in_fm:
            m = re.match(r"^messages:\s*(\d+)", line)
            if m:
                return int(m.group(1))
    return 0


def _atomic_write(path: Path, content: str) -> None:
    # Tempfile in same dir → os.replace: iCloud/Dropbox see a single rename
    # event instead of an open-write-close window that can race with sync.
    tmp = path.with_name(f".{path.name}.tmp")
    with open(tmp, "w") as f:
        f.write(content)
    os.replace(tmp, path)


SkipReason = str  # "short" | "unchanged" | "non-interactive"


def export_session(
    session_file: Path,
    output_dir: Path,
    min_messages: int = 4,
    force: bool = False,
) -> tuple[Path | None, SkipReason | None]:
    effective_min = 1 if force else min_messages
    meta, messages, is_interactive = _parse_session_jsonl(session_file)
    if len(messages) < effective_min:
        return None, "short"
    if not is_interactive and not force:
        return None, "non-interactive"
    session_id = session_file.stem
    cwd = meta.get("cwd", "")
    if not cwd:
        cwd = _decode_project_dir(session_file.parent.name)
    project = _extract_project(cwd)
    ts = meta.get("timestamp", "")
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        date_str = dt.strftime("%Y-%m-%d %H:%M")
        date_prefix = dt.strftime("%Y-%m-%d")
    except (ValueError, OSError):
        date_str = ts[:16] if ts else "unknown"
        date_prefix = ts[:10] if len(ts) >= 10 else "unknown"
    year_month = date_prefix[:7]
    export_dir = output_dir / year_month
    export_dir.mkdir(parents=True, exist_ok=True)
    output_file = export_dir / f"{date_prefix}-{session_id[:8]}.md"

    if not force and _existing_message_count(output_file) >= len(messages):
        return None, "unchanged"

    profile, session_type = _classify(cwd)
    parts: list[str] = [
        f"---\ntype: claude-session\nsession_id: {session_id}\n",
        f"date: {date_str}\ncwd: {cwd}\n",
        f"project: {project}\nprofile: {profile}\nsession_type: {session_type}\n",
        f"branch: {meta.get('branch', '')}\nclaude_version: {meta.get('version', '')}\n",
        f"messages: {len(messages)}\n---\n\n",
        f"# Session {date_str} — {project or session_type}\n\n",
        f"**CWD**: `{cwd}` | **Project**: {project} | **Profile**: {profile}\n\n---\n\n",
    ]
    for msg in messages:
        parts.append(f"## {msg['role']}\n\n{msg['text']}\n\n")
    _atomic_write(output_file, "".join(parts))
    return output_file, None

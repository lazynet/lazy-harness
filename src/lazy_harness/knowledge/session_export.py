"""Session JSONL → markdown export."""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path


def _parse_session_jsonl(filepath: Path) -> tuple[dict[str, str], list[dict[str, str]]]:
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
        if msg_type == "permission-mode":
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
    return meta, messages if is_interactive else []


def _extract_project(cwd: str) -> str:
    if not cwd:
        return ""
    check = cwd
    while check and check != "/":
        if os.path.isdir(os.path.join(check, ".git")):
            return os.path.basename(check)
        check = os.path.dirname(check)
    return os.path.basename(cwd) or ""


def export_session(session_file: Path, output_dir: Path, min_messages: int = 4) -> Path | None:
    meta, messages = _parse_session_jsonl(session_file)
    if len(messages) < min_messages:
        return None
    session_id = session_file.stem
    cwd = meta.get("cwd", "")
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
    with open(output_file, "w") as out:
        out.write(f"---\ntype: claude-session\nsession_id: {session_id}\n")
        out.write(f"date: {date_str}\ncwd: {cwd}\nproject: {project}\n")
        out.write(f"branch: {meta.get('branch', '')}\nclaude_version: {meta.get('version', '')}\n")
        out.write(f"messages: {len(messages)}\n---\n\n")
        out.write(f"# Session {date_str} — {project or 'unknown'}\n\n")
        out.write(f"**CWD**: `{cwd}` | **Project**: {project}\n\n---\n\n")
        for msg in messages:
            out.write(f"## {msg['role']}\n\n{msg['text']}\n\n")
    return output_file

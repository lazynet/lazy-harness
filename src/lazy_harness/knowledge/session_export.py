"""Session JSONL → markdown export."""

from __future__ import annotations

import json
import os
import re
from datetime import datetime
from pathlib import Path

from lazy_harness.core.config import ClassifyRule, _default_classify_rules
from lazy_harness.core.project_identity import main_repo_root, project_key


def _parse_session_jsonl(
    filepath: Path,
) -> tuple[dict[str, str], list[dict[str, str]], bool]:
    from lazy_harness.knowledge.compound_loop import _transcript_message

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
        if not isinstance(d, dict):
            continue
        msg_type = d.get("type", "")
        ts = d.get("timestamp", "")
        if not isinstance(ts, str):
            ts = ""
        if not first_timestamp and ts:
            first_timestamp = ts
        if msg_type in ("permission-mode", "last-prompt"):
            is_interactive = True
            continue
        if msg_type == "system" and not meta:
            meta = {
                key: value if isinstance(value, str) else ""
                for key, value in {
                    "cwd": d.get("cwd", ""),
                    "version": d.get("version", ""),
                    "branch": d.get("gitBranch", ""),
                    "timestamp": ts,
                }.items()
            }
            continue
        if msg_type == "session_meta" and not meta:
            payload = d.get("payload")
            if not isinstance(payload, dict):
                continue
            meta = {
                key: value if isinstance(value, str) else ""
                for key, value in {
                    "cwd": payload.get("cwd", ""),
                    "version": payload.get("cli_version", ""),
                    "session_id": payload.get("id", ""),
                    "agent": "codex",
                    "timestamp": ts,
                }.items()
            }
            continue
        message = _transcript_message(d)
        if message is not None:
            role, texts = message
            if msg_type == "response_item" and role == "user":
                is_interactive = True
            messages.append(
                {
                    "role": "User"
                    if role == "user"
                    else ("Assistant" if msg_type == "response_item" else "Claude"),
                    "text": "\n\n".join(texts),
                    "timestamp": ts,
                }
            )
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


def _classify(cwd: str, rules: list[ClassifyRule]) -> tuple[str, str]:
    """Return (profile, session_type) for the first rule whose pattern matches cwd.

    Case-insensitive substring match. Returns ("other", "other") when no rule
    matches or cwd is empty. See ADR-028.
    """
    if not cwd:
        return ("other", "other")
    lower = cwd.lower()
    for rule in rules:
        if rule.pattern.lower() in lower:
            return (rule.profile, rule.session_type)
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
    classify_rules: list[ClassifyRule] | None = None,
    *,
    source_profile: str = "",
    source_identity: str = "",
) -> tuple[Path | None, SkipReason | None]:
    effective_min = 1 if force else min_messages
    meta, messages, is_interactive = _parse_session_jsonl(session_file)
    if len(messages) < effective_min:
        return None, "short"
    if not is_interactive and not force:
        return None, "non-interactive"
    session_id = meta.get("session_id") or session_file.stem
    if re.fullmatch(r"[A-Za-z0-9_-]+", session_id) is None:
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

    rules = classify_rules if classify_rules is not None else _default_classify_rules()
    profile, session_type = _classify(cwd, rules)
    # A decoded agent directory is ambiguous and cannot prove repository scope.
    recorded_cwd = meta.get("cwd", "")
    source_cwd = Path(recorded_cwd) if recorded_cwd else None
    scoped_key = ""
    scoped_root = ""
    if source_cwd is not None and source_cwd.is_absolute() and source_cwd.is_dir():
        scoped_key = project_key(source_cwd)
        scoped_root = str((main_repo_root(source_cwd) or source_cwd).resolve())
    parts: list[str] = [
        f"---\ntype: {meta.get('agent', 'claude')}-session\nsession_id: {session_id}\n",
        f"date: {date_str}\ncwd: {cwd}\n",
        f"project: {project}\nprofile: {profile}\nsession_type: {session_type}\n",
        f"project_key: {json.dumps(scoped_key)}\n"
        f"project_root: {json.dumps(scoped_root)}\n"
        f"source_profile: {json.dumps(source_profile)}\n",
        f"source_identity: {json.dumps(source_identity)}\n",
        f"branch: {meta.get('branch', '')}\n"
        f"{meta.get('agent', 'claude')}_version: {meta.get('version', '')}\n",
        f"messages: {len(messages)}\n---\n\n",
        f"# Session {date_str} — {project or session_type}\n\n",
        f"**CWD**: `{cwd}` | **Project**: {project} | **Profile**: {profile}\n\n---\n\n",
    ]
    for msg in messages:
        parts.append(f"## {msg['role']}\n\n{msg['text']}\n\n")
    _atomic_write(output_file, "".join(parts))
    return output_file, None

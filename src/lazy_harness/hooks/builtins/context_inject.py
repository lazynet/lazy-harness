#!/usr/bin/env python3
"""SessionStart hook: inject project context.

Outputs JSON with `hookSpecificOutput` for Claude Code. Sections composed:

    ## Git             — branch, last commit, dirty status
    ## LazyNorth       — strategic compass (universal + per-profile)
    ## Last session    — most recent exported session for this project
    ## Handoff         — handoff.md + pre-compact-summary.md
    ## Recent history  — decisions.jsonl + failures.jsonl tails

Read-only. Always exits 0. Logs to `<CLAUDE_CONFIG_DIR>/logs/hooks.log`.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def _log(log_file: Path, msg: str) -> None:
    try:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().astimezone().isoformat(timespec="seconds")
        with open(log_file, "a") as f:
            f.write(f"{ts} session-context: {msg}\n")
    except OSError:
        pass


def _expand(p: str) -> Path:
    return Path(os.path.expanduser(p)) if p else Path()


def _run_git(*args: str, cwd: Path | None = None) -> str:
    try:
        r = subprocess.run(
            ["git", *args],
            capture_output=True,
            text=True,
            timeout=5,
            cwd=str(cwd) if cwd else None,
        )
        return r.stdout.strip()
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return ""


# --------------------------------------------------------------------------- #
# Section builders
# --------------------------------------------------------------------------- #


def git_context(cwd: Path) -> str:
    try:
        r = subprocess.run(
            ["git", "rev-parse", "--is-inside-work-tree"],
            capture_output=True,
            check=True,
            cwd=str(cwd),
        )
        if b"true" not in r.stdout:
            return ""
    except (subprocess.CalledProcessError, FileNotFoundError, OSError):
        return ""

    parts: list[str] = []
    branch = _run_git("branch", "--show-current", cwd=cwd)
    parts.append(f"Branch: {branch or 'detached'}")

    last_commit = _run_git("log", "-1", "--format=%h %s", cwd=cwd)
    if last_commit:
        parts.append(f"Last commit: {last_commit}")

    status = _run_git("status", "--short", cwd=cwd)
    if status:
        lines = status.splitlines()
        modified = sum(1 for ln in lines if ln and not ln.lstrip().startswith("?"))
        untracked = sum(1 for ln in lines if ln.lstrip().startswith("?"))
        summary: list[str] = []
        if modified:
            summary.append(f"{modified} modified")
        if untracked:
            summary.append(f"{untracked} untracked")
        if summary:
            parts.append(f"Uncommitted: {', '.join(summary)}")
    return "\n".join(parts)


def last_session_context(sessions_dir: Path, project_name: str) -> str:
    """Find the most recent exported session .md for this project and extract
    date + message count + first user message. Matches the bash implementation."""
    if not sessions_dir.is_dir() or not project_name:
        return ""

    marker = f"project: {project_name}"
    best_path: Path | None = None
    best_mtime = 0.0
    for md in sessions_dir.rglob("*.md"):
        try:
            # Read just enough to find the frontmatter project line
            with open(md) as f:
                head = f.read(2048)
            if marker not in head:
                continue
            mtime = md.stat().st_mtime
        except OSError:
            continue
        if mtime > best_mtime:
            best_mtime = mtime
            best_path = md

    if best_path is None:
        return ""

    try:
        text = best_path.read_text()
    except OSError:
        return ""

    date_val = ""
    messages_val = ""
    for line in text.splitlines():
        if line.startswith("date:"):
            date_val = line.split(":", 1)[1].strip()
        elif line.startswith("messages:"):
            messages_val = line.split(":", 1)[1].strip()
        if date_val and messages_val:
            break

    first_user_msg = ""
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if line.startswith("## User"):
            # First non-empty line after the heading
            for j in range(i + 1, len(lines)):
                candidate = lines[j].strip()
                if candidate:
                    first_user_msg = candidate
                    break
            break
    if len(first_user_msg) > 80:
        first_user_msg = first_user_msg[:77] + "..."

    parts = [f"Last session: {date_val or 'unknown'} ({messages_val or '?'} messages)"]
    if first_user_msg:
        parts.append(f'Working on: "{first_user_msg}"')
    return "\n".join(parts)


def _strip_intro_lines(text: str, extra_skip_prefixes: tuple[str, ...] = ()) -> list[str]:
    """Mimic the bash sed for LazyNorth body extraction:
    strip frontmatter, H1 title, specific intro lines, and blank lines."""
    out: list[str] = []
    in_fm = False
    fm_done = False
    for line in text.splitlines():
        stripped = line.strip()
        if stripped == "---":
            if not fm_done and not in_fm:
                in_fm = True
                continue
            if in_fm:
                in_fm = False
                fm_done = True
                continue
        if in_fm:
            continue
        if stripped.startswith("# "):
            continue
        if any(stripped.startswith(p) for p in extra_skip_prefixes):
            continue
        if not stripped:
            continue
        out.append(line)
    return out


def lazynorth_context(
    lazynorth_root: Path,
    universal_doc: str,
    profile_doc: str,
    universal_limit: int = 20,
    profile_limit: int = 15,
) -> str:
    if not lazynorth_root.is_dir():
        return ""

    sections: list[str] = []

    universal_path = lazynorth_root / universal_doc
    if universal_path.is_file():
        try:
            body = _strip_intro_lines(
                universal_path.read_text(),
                extra_skip_prefixes=("Brújula estratégica",),
            )[:universal_limit]
            if body:
                sections.append("\n".join(body))
        except OSError:
            pass

    if profile_doc:
        profile_path = lazynorth_root / profile_doc
        if profile_path.is_file():
            try:
                body = _strip_intro_lines(
                    profile_path.read_text(),
                    extra_skip_prefixes=("Foco trimestral",),
                )[:profile_limit]
                if body:
                    sections.append("\n".join(body))
            except OSError:
                pass

    return "\n\n".join(sections)


_STALENESS_WINDOW_SECONDS = 300


def _parse_handoff_frontmatter(text: str) -> tuple[dict[str, str], str]:
    """Split a handoff.md into (metadata, body_without_frontmatter).

    Returns an empty metadata dict if the file has no leading `---` block.
    """
    if not text.startswith("---\n"):
        return {}, text
    end = text.find("\n---\n", 4)
    if end == -1:
        return {}, text
    meta_block = text[4:end]
    body = text[end + 5 :]
    meta: dict[str, str] = {}
    for line in meta_block.splitlines():
        if ":" in line:
            key, _, value = line.partition(":")
            meta[key.strip()] = value.strip()
    return meta, body


def _classify_handoff_staleness(
    meta: dict[str, str], latest_session: Path | None
) -> str | None:
    """Return a reason string if the handoff is stale, None if fresh.

    Fresh means: the handoff's session_id matches the latest session JSONL on
    disk AND that JSONL has not grown past `_STALENESS_WINDOW_SECONDS` beyond
    the recorded source_mtime.
    """
    handoff_sid = meta.get("session_id", "")
    if latest_session is None:
        return f"No session JSONL found on disk for handoff {handoff_sid[:8]}."
    latest_sid = latest_session.stem
    if handoff_sid != latest_sid:
        return (
            f"Last written for session {handoff_sid[:8]}. "
            f"Most recent session on disk: {latest_sid[:8]}."
        )
    try:
        source_mtime = float(meta.get("source_mtime", "0") or 0)
    except ValueError:
        source_mtime = 0.0
    try:
        current_mtime = latest_session.stat().st_mtime
    except OSError:
        return None  # can't tell — trust it
    delta = current_mtime - source_mtime
    if delta > _STALENESS_WINDOW_SECONDS:
        return (
            f"Session {handoff_sid[:8]} grew {delta:.0f}s "
            f"past the handoff snapshot (window={_STALENESS_WINDOW_SECONDS}s)."
        )
    return None


def _latest_session_jsonl(sessions_dir: Path) -> Path | None:
    if not sessions_dir.is_dir():
        return None
    jsonl_files = [p for p in sessions_dir.glob("*.jsonl") if p.is_file()]
    if not jsonl_files:
        return None
    return max(jsonl_files, key=lambda f: f.stat().st_mtime)


def handoff_context(memory_dir: Path) -> str:
    parts: list[str] = []

    handoff = memory_dir / "handoff.md"
    if handoff.is_file():
        try:
            raw = handoff.read_text()
        except OSError:
            raw = ""
        if raw:
            meta, body = _parse_handoff_frontmatter(raw)
            body = body.strip()
            if not meta:
                parts.append(
                    "(legacy handoff — no provenance metadata, treat with caution)\n"
                    + body
                )
            else:
                sessions_dir = memory_dir.parent
                latest = _latest_session_jsonl(sessions_dir)
                stale_reason = _classify_handoff_staleness(meta, latest)
                if stale_reason is None:
                    parts.append(body)
                else:
                    parts.append(
                        "⚠️ Handoff may be stale.\n"
                        f"{stale_reason}\n"
                        "Do NOT trust the items below as current. "
                        "Ask the user what's actually pending.\n\n"
                        "--- stale content below ---\n"
                        + body
                    )

    pre_compact = memory_dir / "pre-compact-summary.md"
    if pre_compact.is_file():
        try:
            compact_text = pre_compact.read_text()
            filtered = [
                ln for ln in compact_text.splitlines() if not ln.lstrip().startswith("<!--")
            ]
            body = "\n".join(filtered).strip()
            if body:
                parts.append(f"Pre-compact context:\n{body}")
        except OSError:
            pass

    return "\n\n".join(p for p in parts if p)


def _jsonl_tail_summaries(path: Path, limit: int, include_prevention: bool) -> list[str]:
    if not path.is_file():
        return []
    try:
        lines = path.read_text().strip().splitlines()[-limit:]
    except OSError:
        return []
    out: list[str] = []
    for line in lines:
        try:
            d = json.loads(line)
        except json.JSONDecodeError:
            continue
        summary = d.get("summary", "?")
        if include_prevention:
            prevention = d.get("prevention", "")
            out.append(f"- {summary} → {prevention}" if prevention else f"- {summary}")
        else:
            out.append(f"- {summary}")
    return out


def episodic_context(memory_dir: Path, limit: int = 3) -> str:
    parts: list[str] = []

    decisions = _jsonl_tail_summaries(
        memory_dir / "decisions.jsonl", limit, include_prevention=False
    )
    if decisions:
        parts.append("Recent decisions:\n" + "\n".join(decisions))

    failures = _jsonl_tail_summaries(
        memory_dir / "failures.jsonl", limit, include_prevention=True
    )
    if failures:
        parts.append("Recent failures:\n" + "\n".join(failures))

    return "\n".join(parts)


# --------------------------------------------------------------------------- #
# Composition
# --------------------------------------------------------------------------- #


def _profile_for_config_dir(
    config_dir: str, profiles: dict[str, object]
) -> tuple[str, str]:
    """Returns (profile_name, lazynorth_doc) by matching CLAUDE_CONFIG_DIR
    against each profile's config_dir. Returns ('', '') if no match."""
    if not config_dir:
        return ("", "")
    expanded = str(Path(os.path.expanduser(config_dir)).resolve()) if config_dir else ""
    for name, entry in profiles.items():
        entry_dir = getattr(entry, "config_dir", "") or ""
        if not entry_dir:
            continue
        try:
            if str(Path(os.path.expanduser(entry_dir)).resolve()) == expanded:
                return (name, getattr(entry, "lazynorth_doc", "") or "")
        except OSError:
            continue
    return ("", "")


def _join_sections(*sections: str) -> str:
    return "\n\n".join(s for s in sections if s)


def _compose_banner(
    git_ctx: str, last_session_ctx: str, handoff_ctx: str
) -> str:
    parts: list[str] = []
    branch_match = re.search(r"^Branch:\s*(\S+)", git_ctx, re.MULTILINE)
    if branch_match:
        parts.append(f"on {branch_match.group(1)}")
    if last_session_ctx:
        first_line = last_session_ctx.splitlines()[0]
        parts.append(first_line)
    if handoff_ctx:
        parts.append("has handoff notes")
    if not parts:
        return "Session context loaded (new project)"
    return "Session context loaded: " + " | ".join(parts)


def _truncate_body(
    max_chars: int,
    git_section: str,
    north_section: str,
    session_section: str,
    handoff_section: str,
    episodic_section: str,
) -> str:
    """Drop sections in priority order until body fits: episodic → north →
    handoff. Matches the bash sed-based truncation logic."""
    body = _join_sections(
        git_section, north_section, session_section, handoff_section, episodic_section
    )
    if len(body) <= max_chars:
        return body
    body = _join_sections(git_section, north_section, session_section, handoff_section)
    if len(body) <= max_chars:
        return body
    body = _join_sections(git_section, session_section, handoff_section)
    if len(body) <= max_chars:
        return body
    body = _join_sections(git_section, session_section)
    return body


# --------------------------------------------------------------------------- #
# Entrypoint
# --------------------------------------------------------------------------- #


def main() -> None:
    try:
        json.load(sys.stdin)
    except (json.JSONDecodeError, EOFError, ValueError):
        pass

    claude_dir = Path(os.environ.get("CLAUDE_CONFIG_DIR", Path.home() / ".claude"))
    log_file = claude_dir / "logs" / "hooks.log"
    cwd = Path.cwd()
    _log(log_file, f"fired cwd={cwd}")

    try:
        from lazy_harness.core.config import ConfigError, load_config
        from lazy_harness.core.paths import config_file
    except ImportError:
        return

    cf = config_file()
    cfg = None
    if cf.is_file():
        try:
            cfg = load_config(cf)
        except ConfigError:
            cfg = None

    # Sections
    encoded = "-" + str(cwd).replace("/", "-").lstrip("-")
    memory_dir = claude_dir / "projects" / encoded / "memory"

    git_ctx = git_context(cwd)

    last_session_ctx = ""
    north_ctx = ""
    if cfg is not None:
        knowledge_path = _expand(cfg.knowledge.path)
        sessions_dir = (
            knowledge_path / cfg.knowledge.sessions.subdir if cfg.knowledge.path else Path()
        )
        if (
            cfg.context_inject.enabled
            and cfg.context_inject.last_session_enabled
            and sessions_dir
            and sessions_dir.is_dir()
        ):
            last_session_ctx = last_session_context(sessions_dir, cwd.name)

        if cfg.lazynorth.enabled and cfg.lazynorth.path:
            _, profile_doc = _profile_for_config_dir(
                os.environ.get("CLAUDE_CONFIG_DIR", ""),
                cfg.profiles.items,
            )
            north_ctx = lazynorth_context(
                _expand(cfg.lazynorth.path),
                cfg.lazynorth.universal_doc,
                profile_doc,
            )

    handoff_ctx = handoff_context(memory_dir)
    episodic_ctx = episodic_context(memory_dir)

    # Sections wrapped with markdown headings
    git_section = f"## Git\n{git_ctx}" if git_ctx else ""
    session_section = f"## Last session\n{last_session_ctx}" if last_session_ctx else ""
    handoff_section = (
        f"## Handoff from last session\n{handoff_ctx}" if handoff_ctx else ""
    )
    episodic_section = f"## Recent history\n{episodic_ctx}" if episodic_ctx else ""
    north_section = f"## LazyNorth\n{north_ctx}" if north_ctx else ""

    max_chars = (
        cfg.context_inject.max_body_chars if cfg is not None else 3000
    )
    body = _truncate_body(
        max_chars,
        git_section,
        north_section,
        session_section,
        handoff_section,
        episodic_section,
    )
    if not body:
        body = "New project, no prior context."

    banner = _compose_banner(git_ctx, last_session_ctx, handoff_ctx)

    output = {
        "hookSpecificOutput": {
            "hookEventName": "SessionStart",
            "additionalContext": body,
            "systemMessage": banner,
        }
    }
    print(json.dumps(output))
    _log(log_file, f"injected {len(body)} chars, banner={banner[:80]}")


if __name__ == "__main__":
    main()

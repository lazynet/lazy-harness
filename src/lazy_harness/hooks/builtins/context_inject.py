#!/usr/bin/env python3
"""SessionStart hook: inject project context.

Outputs JSON with hookSpecificOutput for Claude Code.
Collects: git status, handoff notes, episodic memory.
Always exits 0.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path


def _run_git(*args: str) -> str:
    try:
        result = subprocess.run(
            ["git", *args],
            capture_output=True,
            text=True,
            timeout=5,
        )
        return result.stdout.strip()
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return ""


def git_context() -> str:
    try:
        subprocess.run(
            ["git", "rev-parse", "--is-inside-work-tree"],
            capture_output=True,
            check=True,
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        return ""

    parts: list[str] = []
    branch = _run_git("branch", "--show-current")
    parts.append(f"Branch: {branch or 'detached'}")

    last_commit = _run_git("log", "-1", "--format=%h %s")
    if last_commit:
        parts.append(f"Last commit: {last_commit}")

    status_output = _run_git("status", "--short")
    if status_output:
        lines = status_output.strip().splitlines()
        modified = sum(1 for l in lines if not l.startswith("?"))
        untracked = sum(1 for l in lines if l.startswith("?"))
        summary_parts: list[str] = []
        if modified:
            summary_parts.append(f"{modified} modified")
        if untracked:
            summary_parts.append(f"{untracked} untracked")
        if summary_parts:
            parts.append(f"Status: {', '.join(summary_parts)}")
    else:
        parts.append("Status: clean")

    return "\n".join(parts)


def handoff_context() -> str:
    claude_dir = Path(os.environ.get("CLAUDE_CONFIG_DIR", Path.home() / ".claude"))
    cwd = Path.cwd()
    encoded = "-" + str(cwd).replace("/", "-").lstrip("-")
    memory_dir = claude_dir / "projects" / encoded / "memory"

    parts: list[str] = []
    handoff = memory_dir / "handoff.md"
    if handoff.is_file():
        parts.append(handoff.read_text(encoding="utf-8").strip())

    pre_compact = memory_dir / "pre-compact-summary.md"
    if pre_compact.is_file():
        content = pre_compact.read_text(encoding="utf-8").strip()
        lines = [l for l in content.splitlines() if not l.strip().startswith("<!--")]
        if lines:
            parts.append("Pre-compact context:\n" + "\n".join(lines))

    return "\n\n".join(parts)


def episodic_context() -> str:
    claude_dir = Path(os.environ.get("CLAUDE_CONFIG_DIR", Path.home() / ".claude"))
    cwd = Path.cwd()
    encoded = "-" + str(cwd).replace("/", "-").lstrip("-")
    memory_dir = claude_dir / "projects" / encoded / "memory"

    parts: list[str] = []
    for filename, label in [
        ("decisions.jsonl", "Recent decisions"),
        ("failures.jsonl", "Recent failures"),
    ]:
        filepath = memory_dir / filename
        if not filepath.is_file():
            continue
        try:
            lines = filepath.read_text().strip().splitlines()[-3:]
            items: list[str] = []
            for line in lines:
                data = json.loads(line)
                summary = data.get("summary", "?")
                prevention = data.get("prevention", "")
                if prevention:
                    items.append(f"- {summary} → {prevention}")
                else:
                    items.append(f"- {summary}")
            if items:
                parts.append(f"{label}:\n" + "\n".join(items))
        except (json.JSONDecodeError, OSError):
            continue

    return "\n".join(parts)


def main() -> None:
    sections: list[str] = []

    git_ctx = git_context()
    if git_ctx:
        sections.append(f"## Git\n{git_ctx}")

    handoff_ctx = handoff_context()
    if handoff_ctx:
        sections.append(f"## Handoff from last session\n{handoff_ctx}")

    episodic_ctx = episodic_context()
    if episodic_ctx:
        sections.append(f"## Recent history\n{episodic_ctx}")

    body = "\n\n".join(sections) if sections else "New project, no prior context."

    if len(body) > 3000:
        body = body[:2997] + "..."

    branch_line = ""
    for line in (git_ctx or "").splitlines():
        if line.startswith("Branch:"):
            branch_line = line.replace("Branch: ", "on ")
            break
    banner = f"Session context loaded: {branch_line}" if branch_line else "Session context loaded"

    output = {
        "hookSpecificOutput": {
            "hookEventName": "SessionStart",
            "additionalContext": body,
            "systemMessage": banner,
        }
    }
    print(json.dumps(output))


if __name__ == "__main__":
    main()

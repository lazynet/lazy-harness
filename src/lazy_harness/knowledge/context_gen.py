"""Regenerate the dynamic portion of QMD collection contexts.

Reads `~/.config/qmd/index.yml`, preserves user-authored context text, and
updates only the segment after the `<!-- auto -->` delimiter with current
stats (subdir list + .md file count). Never adds or removes collections —
index.yml is the user's source of truth.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

DELIMITER = "<!-- auto -->"
DEFAULT_CONFIG = Path.home() / ".config" / "qmd" / "index.yml"
SKIP_DIRS = {
    ".git",
    ".obsidian",
    ".obsidian.mobile",
    "node_modules",
    "Templates",
    "__pycache__",
    ".claude",
    ".venv",
    "venv",
}
MAX_SHOWN_DIRS = 15


@dataclass
class ContextGenResult:
    updated: list[str]
    skipped: list[str]
    config_path: Path
    dry_run: bool


def _scan_path(path: Path) -> tuple[list[str], int]:
    if not path.exists():
        return [], 0
    subdirs = sorted(
        d.name
        for d in path.iterdir()
        if d.is_dir() and d.name not in SKIP_DIRS and not d.name.startswith(".")
    )
    md_count = len(list(path.rglob("*.md")))
    return subdirs, md_count


def _generate_auto_part(path: Path) -> str:
    subdirs, md_count = _scan_path(path)
    parts = [f"{md_count} archivos .md."]
    if subdirs:
        shown = subdirs[:MAX_SHOWN_DIRS]
        items = ", ".join(shown)
        if len(subdirs) > MAX_SHOWN_DIRS:
            items += f" (+{len(subdirs) - MAX_SHOWN_DIRS} más)"
        parts.append(f"Contiene: {items}.")
    return " ".join(parts)


def _merge_context(existing: str, auto_part: str) -> str:
    if DELIMITER in existing:
        fixed = existing.split(DELIMITER)[0].rstrip()
        return f"{fixed} {DELIMITER} {auto_part}"
    if existing.strip():
        return f"{existing.rstrip()} {DELIMITER} {auto_part}"
    return f"{DELIMITER} {auto_part}"


def _parse_and_update(config_text: str, result: ContextGenResult) -> str:
    """Walk the YAML line-by-line, updating each collection's context in place.

    The file is hand-edited and we must preserve comments and ordering, so a
    generic YAML parser would round-trip poorly. This matches the bash
    implementation it replaces, which iterated indent-based blocks.
    """
    lines = config_text.split("\n")
    out: list[str] = []
    i = 0

    while i < len(lines):
        line = lines[i]
        coll_match = re.match(r"^  (\S+):$", line)
        if not coll_match:
            out.append(line)
            i += 1
            continue

        coll_name = coll_match.group(1)
        out.append(line)
        i += 1

        coll_path: str | None = None
        context_value_idx: int | None = None
        context_indent = "        "

        while i < len(lines):
            curr = lines[i]
            if curr and not curr.startswith("    ") and not curr.startswith("  #"):
                break
            if re.match(r"^  \S", curr) and not curr.startswith("    "):
                break

            path_match = re.match(r"^    path:\s*(.+)$", curr)
            if path_match:
                coll_path = path_match.group(1).strip()

            if re.match(r"^    context:$", curr):
                out.append(curr)
                i += 1
                if i < len(lines) and re.match(r'^      ".*":\s*>', lines[i]):
                    out.append(lines[i])
                    i += 1
                    if i < len(lines) and lines[i].startswith("        "):
                        context_value_idx = len(out)
                        out.append(lines[i])
                        i += 1
                        while (
                            i < len(lines)
                            and lines[i].startswith("        ")
                            and lines[i].strip()
                        ):
                            out.append(lines[i])
                            i += 1
                    continue
                continue

            out.append(curr)
            i += 1

        if coll_path:
            p = Path(os.path.expanduser(coll_path))
            if p.exists():
                auto_part = _generate_auto_part(p)
                if context_value_idx is not None:
                    old_context = out[context_value_idx].strip()
                    new_context = _merge_context(old_context, auto_part)
                    out[context_value_idx] = f"{context_indent}{new_context}"
                    result.updated.append(f"{coll_name}: {new_context}")
                else:
                    new_context = f"{DELIMITER} {auto_part}"
                    out.append("    context:")
                    out.append('      "": >')
                    out.append(f"        {new_context}")
                    out.append("")
                    result.updated.append(f"{coll_name}: NEW {new_context}")
            else:
                result.skipped.append(f"{coll_name}: path not found ({coll_path})")

    return "\n".join(out)


def regenerate(config_path: Path = DEFAULT_CONFIG, *, dry_run: bool = False) -> ContextGenResult:
    result = ContextGenResult(updated=[], skipped=[], config_path=config_path, dry_run=dry_run)
    if not config_path.is_file():
        return result
    original = config_path.read_text()
    updated = _parse_and_update(original, result)
    if not dry_run:
        tmp = config_path.with_suffix(config_path.suffix + ".tmp")
        tmp.write_text(updated)
        os.replace(tmp, config_path)
    return result

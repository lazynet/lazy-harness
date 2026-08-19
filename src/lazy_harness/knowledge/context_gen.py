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


_COLLECTION_RE = re.compile(r"^  (\S+):$")
_PATH_RE = re.compile(r"^    path:\s*(.+)$")
_CONTEXT_RE = re.compile(r"^    context:(.*)$")
# The single entry under `context:` -- a quoted or bare key, then its value.
_ENTRY_RE = re.compile(r"""^      ("[^"]*"|'[^']*'|[^:\s]+):[ \t]*(.*)$""")
# A block scalar header: `|`, `>`, with optional chomping/indent indicators.
_BLOCK_SCALAR_RE = re.compile(r"^[|>][+-]?\d*$|^[|>]\d*[+-]?$")

VALUE_INDENT = "        "


def _in_collection_block(line: str) -> bool:
    """Whether `line` still belongs to the collection block being read."""
    return not line or line.startswith("    ") or line.startswith("  #")


def _unquote(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        return value[1:-1]
    return value


def _read_context_value(block: list[str], entry_idx: int) -> tuple[str, int] | None:
    """Read the context value starting at `entry_idx`.

    Returns the text and the index just past the value, or None if the entry is
    a shape this writer does not know how to rewrite. Every scalar style a
    hand-edited index.yml may use is accepted: plain, single- or double-quoted,
    and the `|` / `>` block scalars, single- or multi-line.
    """
    entry = _ENTRY_RE.match(block[entry_idx])
    if not entry:
        return None
    inline = entry.group(2).strip()

    if not _BLOCK_SCALAR_RE.match(inline):
        # A plain or quoted scalar sits entirely on this line. An empty value
        # would mean a nested structure we do not model, so reject it.
        return (_unquote(inline), entry_idx + 1) if inline else None

    body: list[str] = []
    i = entry_idx + 1
    pending_blanks = 0
    while i < len(block):
        line = block[i]
        if not line.strip():
            # A blank line belongs to the scalar only if indented content follows.
            pending_blanks += 1
            i += 1
            continue
        if not line.startswith(VALUE_INDENT):
            break
        body.extend([""] * pending_blanks)
        pending_blanks = 0
        body.append(line[len(VALUE_INDENT) :])
        i += 1
    return "\n".join(body), i - pending_blanks


def _render_context(key: str, text: str) -> list[str]:
    """Render a context entry as a literal block scalar.

    `|` is used unconditionally: it needs no escaping, so no description can
    produce output that fails to parse, and it matches the shape already
    present in healthy configs.
    """
    lines = ["    context:", f"      {key}: |"]
    lines.extend(f"{VALUE_INDENT}{line}".rstrip() for line in text.split("\n"))
    return lines


def _update_collection(name: str, block: list[str], result: ContextGenResult) -> list[str]:
    """Return `block` with its context entry refreshed, or unchanged on doubt."""
    coll_path: str | None = None
    context_idxs: list[int] = []
    for idx, line in enumerate(block):
        path_match = _PATH_RE.match(line)
        if path_match:
            coll_path = path_match.group(1).strip()
        if _CONTEXT_RE.match(line):
            context_idxs.append(idx)

    if coll_path is None:
        return block

    path = Path(os.path.expanduser(coll_path))
    if not path.exists():
        result.skipped.append(f"{name}: path not found ({coll_path})")
        return block

    # Refuse to touch a collection that is already invalid. Rewriting it would
    # mean picking one of the duplicate values and silently dropping the other.
    if len(context_idxs) > 1:
        result.skipped.append(
            f"{name}: {len(context_idxs)} duplicate context keys -- left untouched, repair by hand"
        )
        return block

    auto_part = _generate_auto_part(path)

    if not context_idxs:
        rendered = _render_context('""', f"{DELIMITER} {auto_part}")
        end = len(block)
        while end > 0 and not block[end - 1].strip():
            end -= 1
        result.updated.append(f"{name}: NEW {DELIMITER} {auto_part}")
        return block[:end] + rendered + block[end:]

    idx = context_idxs[0]
    # `context: {...}` and friends put a value on the key line; only a bare
    # `context:` introduces the nested entry this writer understands.
    if _CONTEXT_RE.match(block[idx]).group(1).strip() or idx + 1 >= len(block):
        result.skipped.append(f"{name}: unrecognised context shape -- left untouched")
        return block

    entry = _ENTRY_RE.match(block[idx + 1])
    parsed = _read_context_value(block, idx + 1)
    if entry is None or parsed is None:
        result.skipped.append(f"{name}: unrecognised context shape -- left untouched")
        return block

    existing, value_end = parsed
    new_context = _merge_context(existing, auto_part)
    result.updated.append(f"{name}: {new_context}")
    return block[:idx] + _render_context(entry.group(1), new_context) + block[value_end:]


def _parse_and_update(config_text: str, result: ContextGenResult) -> str:
    """Walk the YAML collection by collection, updating each context in place.

    The file is hand-edited and we must preserve comments and ordering, so a
    generic YAML parser would round-trip poorly -- and, given PyYAML resolves
    duplicate keys last-wins, would quietly discard hand-written prose from any
    file a previous run had already damaged.
    """
    lines = config_text.split("\n")
    out: list[str] = []
    i = 0

    while i < len(lines):
        coll_match = _COLLECTION_RE.match(lines[i])
        if not coll_match:
            out.append(lines[i])
            i += 1
            continue

        start = i + 1
        end = start
        while end < len(lines) and _in_collection_block(lines[end]):
            end += 1

        out.append(lines[i])
        out.extend(_update_collection(coll_match.group(1), lines[start:end], result))
        i = end

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

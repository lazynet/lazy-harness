"""lh memory decay — mark unreferenced learnings `status: superseded` (ADR-040).

The five-stage pipeline names Decay as "letting unused, unreinforced, or
expired memories fade". Nothing in the harness today logs when a learning is
retrieved — QMD, Engram and the agent's own recall are all read-only
consumers that leave no trail on the file they read — so there is no
citation graph to check a learning against. `origin_session` age is the
honest, deterministic proxy: a learning that has not been reinforced (no
newer learning supersedes it, no operator has touched it) by the time the
horizon closes is the candidate.

This module never deletes a file. It rewrites four frontmatter lines in
place — `status`, `deprecated_by`, `deprecated_on`, `deprecated_reason` —
which are already present as `null` placeholders on every learning
`compound_loop.py` writes. Everything else in the file, including the exact
JSON-flow-style `tags` list, is left byte-identical.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import date
from pathlib import Path

_DECAY_ACTOR = "lh memory decay"


@dataclass(frozen=True)
class DecayCandidate:
    path: Path
    title: str
    origin_session: str
    age_days: int


def _frontmatter_lines(text: str) -> list[str] | None:
    """The lines between the opening and closing `---` markers, or None.

    Line-based, not a YAML parse — `pyyaml` is a dev-only dependency in this
    package, and `collect_existing_learnings` already reads this same file
    shape the same way (`line.startswith("title:")`), so a second parsing
    strategy would be a second way to disagree with the writer.
    """
    if not text.startswith("---\n"):
        return None
    end = text.find("\n---", 4)
    if end == -1:
        return None
    return text[4:end].splitlines()


def _fm_value(lines: list[str], key: str) -> str | None:
    prefix = f"{key}:"
    for line in lines:
        if line.startswith(prefix):
            return line[len(prefix) :].strip().strip('"')
    return None


def _parse_learning(path: Path) -> dict[str, str] | None:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    lines = _frontmatter_lines(text)
    if lines is None:
        return None
    title = _fm_value(lines, "title") or ""
    status = _fm_value(lines, "status") or ""
    origin_session = _fm_value(lines, "origin_session") or ""
    return {"title": title, "status": status, "origin_session": origin_session}


def find_decay_candidates(
    learnings_dir: Path, *, horizon_days: int, today: date
) -> list[DecayCandidate]:
    """Active learnings whose `origin_session` is at least `horizon_days` old.

    Sorted by path for deterministic output. A learning already marked
    anything other than `active` is not re-considered — decay is safe to run
    repeatedly. Anything unparsable (no frontmatter, no `origin_session`, or
    a malformed date) is skipped rather than guessed at.
    """
    if not learnings_dir.is_dir():
        return []

    candidates: list[DecayCandidate] = []
    for path in sorted(learnings_dir.rglob("*.md")):
        data = _parse_learning(path)
        if data is None or data["status"] != "active":
            continue
        origin_session = data["origin_session"]
        if len(origin_session) < len("YYYY-MM-DD"):
            continue
        try:
            origin_date = date.fromisoformat(origin_session[:10])
        except ValueError:
            continue
        age_days = (today - origin_date).days
        if age_days < horizon_days:
            continue
        candidates.append(
            DecayCandidate(
                path=path,
                title=data["title"],
                origin_session=origin_session[:10],
                age_days=age_days,
            )
        )
    return candidates


def _atomic_write(path: Path, content: str) -> None:
    tmp = path.with_name(f".{path.name}.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(content)
    os.replace(tmp, path)


def _rewrite_frontmatter_field(line: str, key: str, value: str) -> str | None:
    if line.startswith(f"{key}:"):
        return f"{key}: {value}"
    return None


def _decayed_text(text: str, *, today: date, reason: str) -> str:
    lines = text.splitlines()
    fm_markers = [i for i, line in enumerate(lines) if line == "---"]
    if len(fm_markers) < 2:
        return text
    start, end = fm_markers[0], fm_markers[1]

    replacements = {
        "status": "superseded",
        "deprecated_by": _DECAY_ACTOR,
        "deprecated_on": today.isoformat(),
        "deprecated_reason": f'"{reason}"',
    }
    for i in range(start + 1, end):
        for key, value in replacements.items():
            rewritten = _rewrite_frontmatter_field(lines[i], key, value)
            if rewritten is not None:
                lines[i] = rewritten
                break

    rebuilt = "\n".join(lines)
    if text.endswith("\n"):
        rebuilt += "\n"
    return rebuilt


def apply_decay(candidates: list[DecayCandidate], *, reason: str, today: date) -> list[Path]:
    """Rewrite `status`/`deprecated_*` in place for each candidate.

    Never deletes: every path handed in still exists, unmoved, after this
    returns. Returns the paths actually rewritten, in the order given.
    """
    written: list[Path] = []
    for candidate in candidates:
        text = candidate.path.read_text(encoding="utf-8")
        new_text = _decayed_text(text, today=today, reason=reason)
        if new_text == text:
            continue
        _atomic_write(candidate.path, new_text)
        written.append(candidate.path)
    return written

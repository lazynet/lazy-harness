"""The set of symlinks a deploy owns, so it can retract its own (ADR-052).

`ensure_symlink` reports an existing link and moves on. That is right for a
link the harness is about to write again and wrong for one it has stopped
generating: under the flat layout every asset was linked at the profile root,
and a segmented deploy that simply stops producing those links would leave each
one behind forever, pointing at a file the agent no longer has any reason to
load.

Deploy therefore records what it linked. On the next run it removes the owned
links it no longer generates and leaves everything else in the config dir
exactly as it found it — this is `WriteOp`'s delete case from ADR-046 applied to
symlinks, and the same reasoning applies: a harness that cannot say "I no longer
produce this" can only ever add.

**The first run has no ledger to read.** Rather than start owning nothing and
strand the entire flat layout, deploy adopts every symlink in the config dir
that resolves under that profile's source directory: those are the harness's by
construction, since nothing else writes links into `profiles/<p>/`. The adoption
walks the config dir once, which is the only run that pays for it.
"""

from __future__ import annotations

import json
from pathlib import Path

LEDGER_RELATIVE = Path(".lazy-harness/links.json")
"""Deliberately outside the agent's own namespace.

A Claude Code config dir is Claude Code's; a file the harness keeps there under
a name the agent may one day claim is a collision waiting to happen.
"""

_VERSION = 1


def read_ledger(config_dir: Path) -> set[Path] | None:
    """The recorded links, or `None` when there is no usable record.

    `None` and `set()` are different answers and the caller acts on the
    difference: `None` triggers adoption, `set()` means a deploy that genuinely
    owns nothing. Anything unparseable is `None` — re-adopting is recoverable,
    while reading junk as "owns nothing" strands every link ever written.
    """
    path = config_dir / LEDGER_RELATIVE
    if not path.is_file():
        return None
    try:
        raw = json.loads(path.read_text())
    except (json.JSONDecodeError, OSError, UnicodeDecodeError):
        return None
    if not isinstance(raw, dict):
        return None
    links = raw.get("links")
    if not isinstance(links, list):
        return None
    return {Path(item) for item in links if isinstance(item, str)}


def write_ledger(config_dir: Path, links: set[Path]) -> None:
    """Record the links this deploy generated, sorted for a readable diff."""
    path = config_dir / LEDGER_RELATIVE
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"version": _VERSION, "links": sorted(link.as_posix() for link in links)}
    path.write_text(json.dumps(payload, indent=2) + "\n")


def _points_into(link: Path, profile_src: Path) -> bool:
    """Whether `link` resolves inside the profile source.

    Resolution is non-strict on purpose: a link whose source was deleted is
    exactly the stale link this module exists to remove, and a strict resolve
    would refuse to classify it.
    """
    try:
        target = link.readlink()
    except OSError:
        return False
    absolute = target if target.is_absolute() else link.parent / target
    try:
        absolute.resolve().relative_to(profile_src.resolve())
    except (ValueError, OSError):
        return False
    return True


def scan_links(config_dir: Path, profile_src: Path) -> set[Path]:
    """Every symlink under `config_dir` that resolves into `profile_src`.

    Symlinked directories are recorded, never descended into — following one
    would walk the profile source and record its contents as if the config dir
    held a link per file.
    """
    found: set[Path] = set()
    if not config_dir.is_dir():
        return found

    stack = [config_dir]
    while stack:
        current = stack.pop()
        try:
            children = sorted(current.iterdir())
        except OSError:
            continue
        for child in children:
            relative = child.relative_to(config_dir)
            if relative.parts[0] == LEDGER_RELATIVE.parts[0]:
                continue
            if child.is_symlink():
                if _points_into(child, profile_src):
                    found.add(relative)
                continue
            if child.is_dir():
                stack.append(child)
    return found


def owned_links(config_dir: Path, profile_src: Path) -> tuple[set[Path], bool]:
    """(the links this deploy owns, whether they were adopted rather than read)."""
    recorded = read_ledger(config_dir)
    if recorded is not None:
        return recorded, False
    return scan_links(config_dir, profile_src), True


def prune_unowned(
    config_dir: Path,
    profile_src: Path,
    *,
    owned: set[Path],
    keep: set[Path],
) -> list[Path]:
    """Remove owned links no longer generated; return what was removed.

    Two things are deliberately left alone. A name the ledger never recorded is
    the user's, whatever it points at. A recorded name that no longer points
    into the profile source has been repointed by hand since — the ledger
    records a name, not a standing claim on it.
    """
    removed: list[Path] = []
    for relative in sorted(owned - keep):
        link = config_dir / relative
        if not link.is_symlink() or not _points_into(link, profile_src):
            continue
        link.unlink()
        removed.append(relative)
    return removed

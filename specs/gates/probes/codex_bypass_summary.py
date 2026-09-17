"""Summarise one `codex exec --json` stream as kinds and key types, never bodies.

`codex-bypass-probe.sh` drives `codex exec --json` once per candidate bypass
level and captures the JSONL stream to a file. This reads one such file back and
prints two things:

*   **The kind inventory** — every event kind the run emitted, with a count and
    the keys each kind carries, one level of nesting deep. This is the discovery
    channel: 0.154.0's stream shape is unmeasured, so anything the two pinned
    signals below do not anticipate still shows up here.
*   **Two signals** — `approval` and `sandbox`, reported as the *kind names* that
    matched. Those are the two questions each level must answer that the marker
    file cannot: did the run ask for approval, and did the sandbox block it. The
    third question — did the command actually run — is ground truth the shell
    half reads off the filesystem, not something a stream is trusted for.

A signal names its kinds rather than returning a boolean because an adapter over
an external binary is held to observed-vs-spec in this repo: `bypass_argv` cites
the vocabulary its verdict was read from, and a bare `True` cites nothing.

**No value is ever printed except a kind name.** The stream carries the model's
reasoning, the shell command it proposed, the workspace path and the prompt; the
questions above need none of them. The output is meant to be pasted into
`specs/designs/codex-evidence.md` §7, which is a public-repo file.

Usage:

    python3 codex_bypass_summary.py <stream.jsonl>
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

# A record carrying neither spelling of the kind. Reported rather than dropped:
# a dropped record is a silent hole in the inventory, and the inventory is the
# whole deliverable.
UNTYPED = "<untyped>"

# A key present in some records of a kind and absent from others. The same
# distinction `copilot_probe_summary.py` marks, for the same reason: an
# unguarded read of an optional key is how a consumer raises on the second run.
OPTIONAL = "?"

# Substring vocabularies, matched against the kind name. Deliberately narrow —
# a signal that fires on anything says nothing, and the negative rows are what
# make the positive ones evidence.
SIGNAL_VOCABULARY: dict[str, tuple[str, ...]] = {
    "approval": ("approval", "approve"),
    "sandbox": ("sandbox",),
}

_MISSING = object()


def json_type(value: object) -> str:
    """The JSON type name of one value. Never the value."""
    if value is None:
        return "null"
    # `bool` before `int` is not cosmetic: `isinstance(True, int)` is true in
    # Python, so the obvious ordering reports every flag as an integer.
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, int):
        return "int"
    if isinstance(value, float):
        return "float"
    if isinstance(value, str):
        return "str"
    if isinstance(value, list):
        inner = sorted({json_type(item) for item in value})
        return f"array<{'|'.join(inner)}>" if inner else "array<>"
    if isinstance(value, dict):
        return "object"
    return type(value).__name__


def event_kind(record: dict) -> str:
    """The kind of one record, under either envelope this binary might emit.

    Codex has shipped both a nested `{"id", "msg": {"type": ...}}` envelope and a
    flat `{"type": ...}` one, and which 0.154.0 emits is exactly the sort of
    thing help text cannot settle. Reading only one spelling would report the
    other run as empty — indistinguishable from the binary refusing to start.
    """
    flat = record.get("type")
    if isinstance(flat, str) and flat:
        return flat
    nested = record.get("msg")
    if isinstance(nested, dict):
        inner = nested.get("type")
        if isinstance(inner, str) and inner:
            return inner
    return UNTYPED


def read_records(path: Path) -> tuple[list[dict], int]:
    """Every JSON object in a stream, plus the count of lines that were not one.

    A run killed by a timeout, or aborted by the CLI on a sandbox denial, leaves
    a truncated last line. That is ordinary input for this probe, never an error.
    """
    records: list[dict] = []
    skipped = 0
    try:
        raw = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return [], 0
    for line in raw.splitlines():
        if not line.strip():
            continue
        try:
            parsed = json.loads(line)
        except (json.JSONDecodeError, ValueError):
            skipped += 1
            continue
        if isinstance(parsed, dict):
            records.append(parsed)
        else:
            skipped += 1
    return records, skipped


def signals(records: list[dict]) -> dict[str, list[str]]:
    """Per signal, the sorted distinct kind names that matched its vocabulary."""
    kinds = {event_kind(record) for record in records}
    matched: dict[str, list[str]] = {}
    for signal, needles in SIGNAL_VOCABULARY.items():
        matched[signal] = sorted(
            kind for kind in kinds if any(needle in kind.lower() for needle in needles)
        )
    return matched


def summarise(records: list[dict], *, depth: int = 2) -> list[str]:
    """`key: type` lines for a set of records, one level of nesting deep.

    Types are unioned across records rather than taken from the first: a key
    that is a string in one event and an object in the next is the finding, and
    a printer that reported whichever came first would hide the contradiction.
    """
    if not records:
        return []
    keys: list[str] = []
    for record in records:
        for key in record:
            if key not in keys:
                keys.append(key)

    lines: list[str] = []
    for key in keys:
        present = [record.get(key, _MISSING) for record in records]
        seen = [value for value in present if value is not _MISSING]
        types = sorted({json_type(value) for value in seen})
        optional = OPTIONAL if len(seen) != len(records) else ""
        lines.append(f"  {key}{optional}: {'|'.join(types)}")
        if depth > 1:
            nested = [value for value in seen if isinstance(value, dict)]
            for nested_line in summarise(nested, depth=depth - 1):
                lines.append(f"  {nested_line}")
    return lines


def report(path: Path) -> str:
    """One stream as a pasteable block: the inventory, then the two signals."""
    records, skipped = read_records(path)
    note = f" ({skipped} unparseable line(s))" if skipped else ""
    if not records:
        return (
            f"no events{note} — the level emitted nothing, or argv was refused "
            f"before the run started (check the captured exit code and stderr)\n"
        )

    grouped: dict[str, list[dict]] = {}
    for record in records:
        grouped.setdefault(event_kind(record), []).append(record)

    out: list[str] = [f"{len(records)} event(s){note}", ""]
    for kind, kind_records in grouped.items():
        out.append(f"{kind}: {len(kind_records)}")
        out.extend(summarise(kind_records))
        out.append("")

    out.append("signals:")
    for signal, kinds in signals(records).items():
        out.append(f"  {signal}: {', '.join(kinds) if kinds else '—'}")
    return "\n".join(out) + "\n"


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(f"usage: {Path(argv[0]).name} <stream.jsonl>", file=sys.stderr)
        return 2
    path = Path(argv[1])
    if not path.is_file():
        print(f"not a file: {path}", file=sys.stderr)
        return 2
    sys.stdout.write(report(path))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))

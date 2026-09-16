"""Summarise a Copilot hook-payload dump as keys and types, never bodies.

`copilot-probe1.sh` points every hook it registers at a sink that appends the
raw payload as one JSON object per line. This reads those sinks back and prints
a schema: per event, per key, the JSON type — and one level of nesting, because
`toolArgs` is where the whole tool-vocabulary question lives.

**No value is ever printed.** A payload carries the model's prompt, a shell
command, a file path and whatever the user was working on; the question the
probe asks is *which keys arrive and in what shape*, and the answer to that
needs no body. The summary is meant to be pasted into
`specs/designs/copilot-evidence.md`, which is a public-repo file.

Usage:

    python3 copilot_probe_summary.py <dir with *.jsonl>

One `<event>.jsonl` per event. An event whose file is missing is reported as
`not fired`, which is a finding rather than an error: the eleven names the
binary accepts are not eleven names one session makes fire.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

# A key present in some records and absent from others gets this suffix. The
# distinction is load-bearing: `parse_hook_input` reading an optional key
# without a guard is exactly how a run with the key absent turns into a
# `TypeError` inside a hook, and a hook that raises is a hook that allows.
OPTIONAL = "?"

_MISSING = object()


def json_type(value: object) -> str:
    """The JSON type name of one value. Never the value."""
    if value is None:
        return "null"
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


def read_records(path: Path) -> tuple[list[dict], int]:
    """Every JSON object in a sink, plus the count of lines that were not one.

    A sink is appended to by a hook that may be killed mid-write, and a probe
    run that ends in a refusal is a normal outcome — so a half-written last
    line is ordinary input here, never an error.
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


def summarise(records: list[dict], *, depth: int = 2) -> list[str]:
    """`key: type` lines for a set of records, one level of nesting deep.

    Types are unioned across records rather than taken from the first, because
    the question a probe answers is what the *contract* is, and a key that is a
    string in one call and an object in the next is the finding.
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


def report(directory: Path) -> str:
    """The whole dump as one pasteable block."""
    sinks = sorted(directory.glob("*.jsonl"))
    if not sinks:
        return f"no sinks under {directory} — no hook fired, or the document never loaded\n"

    out: list[str] = []
    for sink in sinks:
        event = sink.stem
        records, skipped = read_records(sink)
        if not records:
            out.append(f"{event}: not fired (0 records)")
            out.append("")
            continue
        note = f", {skipped} unparseable line(s)" if skipped else ""
        out.append(f"{event}: {len(records)} record(s){note}")
        out.extend(summarise(records))
        out.append("")
    return "\n".join(out) + "\n"


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(f"usage: {Path(argv[0]).name} <dir with *.jsonl>", file=sys.stderr)
        return 2
    directory = Path(argv[1])
    if not directory.is_dir():
        print(f"not a directory: {directory}", file=sys.stderr)
        return 2
    sys.stdout.write(report(directory))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))

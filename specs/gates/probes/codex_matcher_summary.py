"""Summarise one matcher-probe turn as fired counts and tool names, never bodies.

`codex-matcher-probe.sh` installs one `PreToolUse` group per matcher spelling,
each writing the payloads it receives to `<turn dir>/<label>.jsonl`, and drives
two `codex exec` turns. This reads one turn's directory back and prints one row
per label:

    label         matcher                        fired  tool names

**Absent is not empty, and the distinction is the probe's whole finding.** A
label whose sink was never created was never invoked — Codex evaluated the
matcher, it matched nothing, and the group was suppressed *silently*
(`agents/codex.py::_hook_groups` records that silence). A label whose sink
exists with zero records fired and carried nothing. Reporting both as `0` would
answer the probe's question with the ambiguity it was written to remove, so the
first reads `never invoked` and only the second reads a count.

**No value is ever printed except a tool name.** A `PreToolUse` payload carries
the proposed shell command, the patch blob, the prompt's working directory and
absolute paths under `$HOME`; which tool names reached which matcher needs none
of them. The output is meant to be pasted into `specs/designs/codex-evidence.md`,
which is a public-repo file.

Usage:

    python3 codex_matcher_summary.py <turn dir> <label,label,...>
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path

# A payload carrying no readable tool name. Reported rather than dropped: a
# dropped record is a silent hole in a count that is the deliverable, and a
# payload shape with no `tool_name` is itself a finding about this binary.
UNNAMED = "<no tool_name>"

NEVER = "never invoked"


@dataclass(frozen=True)
class LabelRow:
    """One matcher spelling's reading for one turn.

    `fired` is `None` for "the sink was never created", never `0`. The two are
    different observations and the type says so rather than leaving a reader to
    infer it from a count.
    """

    label: str
    fired: int | None
    tool_names: tuple[str, ...]
    unparseable: int


def tool_name(record: dict) -> str | None:
    """The tool name in one payload, under either envelope, or `None`.

    Codex has shipped both a flat `{"tool_name": ...}` payload and one nesting
    the hook fields under `payload`. Reading a single spelling would report a
    fired group as carrying nothing, which is the reading right beside the one
    that means the matcher never matched — the two must not blur.
    """
    flat = record.get("tool_name")
    if isinstance(flat, str) and flat:
        return flat
    nested = record.get("payload")
    if isinstance(nested, dict):
        inner = nested.get("tool_name")
        if isinstance(inner, str) and inner:
            return inner
    return None


def read_sink(path: Path) -> tuple[list[dict], int]:
    """Every JSON object in one sink, plus the count of lines that were not one.

    Several hook processes append to distinct files, but a turn killed by the
    timeout leaves a truncated final line. That is ordinary input here, never an
    error: raising would lose the records that did arrive.
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


def summarise_turn(turn_dir: Path, labels: tuple[str, ...]) -> list[LabelRow]:
    """One row per label, in the order given — which is the hooks.json order.

    Re-sorting would break the correspondence the table exists to show: row N
    is group N of the rendered document, and a reader checks one against the
    other.
    """
    rows: list[LabelRow] = []
    for label in labels:
        path = turn_dir / f"{label}.jsonl"
        if not path.is_file():
            rows.append(LabelRow(label=label, fired=None, tool_names=(), unparseable=0))
            continue
        records, skipped = read_sink(path)
        names = sorted({tool_name(record) or UNNAMED for record in records})
        rows.append(
            LabelRow(
                label=label,
                # `skipped` counts toward `fired`: a truncated line is a payload
                # that arrived, and dropping it would under-report the very
                # group whose handler was still writing when the turn ended.
                fired=len(records) + skipped,
                tool_names=tuple(names),
                unparseable=skipped,
            )
        )
    return rows


def render(rows: list[LabelRow]) -> str:
    """The pasteable table. Tool names are the only values it ever prints."""
    width = max((len(row.label) for row in rows), default=5)
    lines = [f"{'label'.ljust(width)}  fired  tool names"]
    for row in rows:
        if row.fired is None:
            lines.append(f"{row.label.ljust(width)}  {NEVER}")
            continue
        note = f" ({row.unparseable} unparseable)" if row.unparseable else ""
        names = ", ".join(row.tool_names) if row.tool_names else "—"
        lines.append(f"{row.label.ljust(width)}  {row.fired:>5}{note}  {names}")
    return "\n".join(lines) + "\n"


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print(f"usage: {Path(argv[0]).name} <turn dir> <label,label,...>", file=sys.stderr)
        return 2
    labels = tuple(part for part in argv[2].split(",") if part.strip())
    if not labels:
        # An empty table exits 0 and reads as "nothing fired", which is a run
        # that measured nothing wearing the clothes of a run that found nothing.
        print("no labels given — nothing would be measured", file=sys.stderr)
        return 2
    sys.stdout.write(render(summarise_turn(Path(argv[1]), labels)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))

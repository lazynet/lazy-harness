"""lh memory reconcile — schema drift detection over `decisions.jsonl` (ADR-040).

Detection 1 of the Reconcile stage: lines in one project's `decisions.jsonl`
that do not share the field set most lines use. `decisions.jsonl` is
append-only and has been rewritten in place at least twice (`timestamp` ->
`ts`, `decision` -> `summary` with `context`/`project`/`tags` added), so old
lines never catch up. This module only reports the grouping; nothing here
rewrites a line; the real store has no correct value to fill in a `context`
that a 2026-04 line never recorded, and guessing one is exactly the "act
confidently on the wrong fact" failure Reconcile exists to avoid.

Detection 2 (cross-decision contradiction) needs semantic judgement and is an
LLM call — it lives in `cli/memory_cmd.py`, next to the `consolidate` prompt
it mirrors.
"""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class SchemaDriftGroup:
    fields: tuple[str, ...]
    count: int
    example_line_numbers: list[int]


@dataclass(frozen=True)
class SchemaDriftReport:
    path: Path
    total_lines: int
    majority_fields: tuple[str, ...]
    minority_groups: list[SchemaDriftGroup]

    @property
    def has_drift(self) -> bool:
        return bool(self.minority_groups)


def detect_schema_drift(path: Path) -> SchemaDriftReport | None:
    """Group `path`'s JSON lines by field set. None when the file is absent.

    The most common field set is "current"; every other set is drift,
    reported most-common-first. A line that is not valid JSON, or whose JSON
    is not an object, still counts toward `total_lines` — it was appended —
    but contributes no field set: there is nothing to group it by.
    """
    if not path.is_file():
        return None

    field_sets: Counter[tuple[str, ...]] = Counter()
    line_numbers: dict[tuple[str, ...], list[int]] = {}
    total_lines = 0

    for lineno, line in enumerate(path.read_text(errors="replace").splitlines(), start=1):
        if not line.strip():
            continue
        total_lines += 1
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if not isinstance(row, dict):
            continue
        fields = tuple(sorted(row.keys()))
        field_sets[fields] += 1
        line_numbers.setdefault(fields, []).append(lineno)

    if not field_sets:
        return SchemaDriftReport(
            path=path, total_lines=total_lines, majority_fields=(), minority_groups=[]
        )

    majority_fields, _ = field_sets.most_common(1)[0]
    minority_groups = [
        SchemaDriftGroup(fields=fields, count=count, example_line_numbers=line_numbers[fields][:3])
        for fields, count in field_sets.items()
        if fields != majority_fields
    ]
    minority_groups.sort(key=lambda g: -g.count)

    return SchemaDriftReport(
        path=path,
        total_lines=total_lines,
        majority_fields=majority_fields,
        minority_groups=minority_groups,
    )
